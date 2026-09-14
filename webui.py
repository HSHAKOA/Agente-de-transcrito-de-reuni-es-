"""Painel local (HTML) para controlar o meeting_transcriber com um botao.

Sobe um servidor HTTP so com a biblioteca padrao (sem Flask/FastAPI, sem
dependencia extra) em http://127.0.0.1:8765, serve o index.html e expoe uma
API minima (/api/start, /api/stop, /api/status, /api/recovery,
/api/meetings/<id>/resume) que liga/desliga o processo
`python -m meeting_transcriber` como subprocesso e guarda o log em memoria
para a pagina exibir ao vivo.

O servidor so escuta em 127.0.0.1 (nunca 0.0.0.0) e valida todo campo vindo
do navegador antes de repassar para o subprocesso — ver `meeting_transcriber
.validation`. Isso importa mesmo rodando "so localmente": qualquer aba aberta
no mesmo navegador pode, em tese, tentar falar com esse endereco.

Uso: python webui.py   (ou clique duplo em iniciar.bat, que ja prepara o
ambiente virtual antes de chamar isto aqui).
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
MEETINGS_DIR = ROOT / "data" / "meetings"

# webui.py em si (nao so o subprocesso que ele lanca) agora usa
# meeting_transcriber.validation/session, entao precisa de src/ no
# sys.path tambem quando rodado direto (fora do .venv com editable install).
sys.path.insert(0, str(SRC))

from meeting_transcriber import validation  # noqa: E402
from meeting_transcriber.session import (  # noqa: E402
    STATUS_INTERRUPTED,
    list_sessions,
    mark_interrupted_sessions,
    new_meeting_id,
)

PORT = 8765
MAX_BODY_BYTES = 1_000_000  # 1 MB — generoso pros campos reais, barra corpo gigante como DoS
_DRAIN_CAP_BYTES = MAX_BODY_BYTES * 4  # teto pra drenar um corpo rejeitado sem nunca ler quantidade ilimitada

# Escalonamento do encerramento gracioso: sinal gracioso -> terminate() -> kill().
# So avanca de estagio se o anterior nao surtir efeito dentro do timeout.
GRACEFUL_TIMEOUT_SECONDS = 30.0
TERMINATE_TIMEOUT_SECONDS = 5.0

logger = logging.getLogger("meeting_transcriber.webui")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _python_executable() -> str:
    """Python do .venv do projeto, se existir; senao, o mesmo que roda este script.

    Nao basta usar sys.executable direto: se alguem abrir webui.py sem passar
    pelo iniciar.bat (ex.: clicando duas vezes no .py), o Windows roda com o
    Python global, que nao tem faster-whisper/soundcard instalados — so o
    .venv tem. Procurar o .venv explicitamente evita esse erro silencioso.
    """
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        ROOT / ".venv" / "bin" / "python",  # Linux/macOS
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _graceful_signal_for_platform() -> int:
    """No Windows, so CTRL_BREAK_EVENT pode ser enviado para outro processo
    (CTRL_C_EVENT e desabilitado para processos criados com
    CREATE_NEW_PROCESS_GROUP — exatamente a flag usada ao lancar o
    subprocesso, ver `start_transcriber`). cli.py registra um handler pra
    SIGBREAK (o sinal que o Python expoe pra CTRL_BREAK_EVENT) que faz a
    mesma coisa que o Ctrl+C no terminal: para a gravacao e deixa a fila de
    transcricao pendente terminar antes de sair.
    """
    if sys.platform == "win32":
        return signal.CTRL_BREAK_EVENT
    return signal.SIGINT


def _wait_until_dead(proc: subprocess.Popen, timeout: float, sleep_fn, poll_interval: float) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if proc.poll() is not None:
            return True
        sleep_fn(poll_interval)
        elapsed += poll_interval
    return proc.poll() is not None


def shutdown_sequence(
    proc: subprocess.Popen,
    graceful_signal: Optional[int] = None,
    graceful_timeout: float = GRACEFUL_TIMEOUT_SECONDS,
    terminate_timeout: float = TERMINATE_TIMEOUT_SECONDS,
    sleep_fn=time.sleep,
    poll_interval: float = 0.2,
) -> str:
    """Encerra `proc` com escalonamento: sinal gracioso -> terminate() -> kill().

    Antes, "Parar" no painel chamava proc.terminate() direto — no Windows
    isso mata o processo na hora (sem entregar sinal nenhum), descartando o
    bloco de audio que ainda estava no buffer e pulando a finalizacao do
    markdown. Essa funcao so escala pro proximo estagio se o anterior nao
    surtir efeito dentro do timeout, dando tempo real pra fila de whisper
    pendente ser drenada. Retorna qual estagio encerrou o processo
    ("graceful", "terminate" ou "kill") — usado em log e em testes.
    """
    graceful_signal = graceful_signal if graceful_signal is not None else _graceful_signal_for_platform()

    try:
        proc.send_signal(graceful_signal)
    except Exception:
        logger.exception("Falha ao enviar sinal de parada graciosa")
    if _wait_until_dead(proc, graceful_timeout, sleep_fn, poll_interval):
        return "graceful"

    logger.warning("Processo nao parou graciosamente em %.0fs; usando terminate().", graceful_timeout)
    try:
        proc.terminate()
    except Exception:
        pass
    if _wait_until_dead(proc, terminate_timeout, sleep_fn, poll_interval):
        return "terminate"

    logger.warning("Processo nao respondeu a terminate(); usando kill() como ultimo recurso.")
    try:
        proc.kill()
    except Exception:
        pass
    _wait_until_dead(proc, terminate_timeout, sleep_fn, poll_interval)
    return "kill"


# Estado global do painel, compartilhado entre as threads que atendem
# requests HTTP e a thread que le a saida do subprocesso. state_lock
# protege todo acesso porque varias threads mexem nele ao mesmo tempo.
state_lock = threading.Lock()
state = {
    "proc": None,  # subprocess.Popen do "python -m meeting_transcriber" em andamento, ou None se parado
    "log": deque(maxlen=1000),  # ultimas linhas de log (stdout+stderr do subprocesso), pra pagina mostrar ao vivo
    "output": None,  # caminho do .md que a sessao atual/ultima esta escrevendo
    "chunk_seconds": 300,  # usado so pra calcular a barra de progresso do bloco atual
    "meeting_dir": None,
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
}


def _log(line: str) -> None:
    """Adiciona uma linha ao log em memoria (thread-safe)."""
    with state_lock:
        state["log"].append(line.rstrip("\n"))


def _reader_thread(proc: subprocess.Popen) -> None:
    """Roda em background: le a saida do subprocesso linha a linha e vai
    guardando no log, ate o processo terminar (naturalmente ou por termos
    chamado stop_transcriber). So aqui descobrimos que o processo morreu.
    """
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        _log(raw_line)
    exit_code = proc.wait()
    with state_lock:
        state["finished_at"] = time.time()
        state["exit_code"] = exit_code
        state["proc"] = None  # libera pra um novo /api/start poder rodar
    _log(f"[painel] processo encerrado (codigo {exit_code}).")


def _launch(cmd: list[str]) -> "tuple[subprocess.Popen, Optional[str]]":
    """Sobe `cmd` como subprocesso com o ambiente/flags corretos.
    `creationflags=CREATE_NEW_PROCESS_GROUP` no Windows e o que permite
    mandar CTRL_BREAK_EVENT depois (ver `_graceful_signal_for_platform`)."""
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONUNBUFFERED": "1"}
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        return None, f"Nao consegui iniciar o processo: {exc}"
    return proc, None


def start_transcriber(opts: dict) -> "tuple[bool, str]":
    """Valida as opcoes vindas do formulario HTML, monta o comando
    `python -m meeting_transcriber ...` e sobe ele como subprocesso.
    Retorna (sucesso, mensagem) pra virar a resposta JSON do /api/start.

    Nenhum campo e confiado sem validacao — ver meeting_transcriber.validation.
    Isso inclui o nome do arquivo de saida: so um nome simples e aceito,
    nunca um caminho (barra a escrita de arquivo arbitraria/path traversal).
    """
    try:
        model = validation.validate_model(opts.get("model") or "small")
        device = validation.validate_device(opts.get("device") or "cpu")
        language = validation.validate_language(opts.get("language") or "pt")
        chunk_seconds = validation.validate_chunk_seconds(opts.get("chunk_seconds", 300))
        title = validation.validate_title(opts.get("title"))
        output_path = validation.validate_output_filename(opts.get("output"), ROOT)
    except validation.ValidationError as exc:
        return False, str(exc)

    keep_audio = bool(opts.get("keep_audio", True))

    with state_lock:
        if state["proc"] is not None:
            return False, "Ja existe uma gravacao em andamento."

        if not (ROOT / ".venv").exists():
            return False, (
                "Ambiente virtual (.venv) nao encontrado. Feche esta janela e "
                "abra o painel atraves do iniciar.bat, que instala tudo "
                "automaticamente antes de abrir o navegador."
            )

        meeting_id = new_meeting_id()
        meeting_dir = MEETINGS_DIR / meeting_id

        cmd = [
            _python_executable(),
            "-u",
            "-m",
            "meeting_transcriber",
            "--output",
            str(output_path),
            "--title",
            title,
            "--model",
            model,
            "--device",
            device,
            "--language",
            language,
            "--chunk-seconds",
            str(chunk_seconds),
            "--meeting-dir",
            str(meeting_dir),
        ]
        if not keep_audio:
            cmd.append("--no-keep-audio")

        proc, error = _launch(cmd)
        if error:
            return False, error

        state["proc"] = proc
        state["output"] = str(output_path)
        state["chunk_seconds"] = chunk_seconds
        state["meeting_dir"] = str(meeting_dir)
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["exit_code"] = None
        state["log"].clear()

    _log(f"[painel] iniciado: {' '.join(cmd)}")
    threading.Thread(target=_reader_thread, args=(proc,), daemon=True).start()
    return True, "Gravacao iniciada."


def stop_transcriber() -> "tuple[bool, str]":
    """Pede o encerramento do subprocesso em andamento com shutdown
    gracioso: sinaliza parada (o subprocesso ainda termina de escrever o
    bloco parcial e finalizar o markdown), e so escala para terminate()/
    kill() se ele nao responder dentro do timeout (ver shutdown_sequence).
    """
    with state_lock:
        proc = state["proc"]
    if proc is None:
        return False, "Nenhuma gravacao em andamento."

    _log("[painel] parando... aguardando a finalizacao do bloco atual (pode levar ate alguns minutos).")
    threading.Thread(target=shutdown_sequence, args=(proc,), daemon=True).start()
    return True, "Parando a gravacao (encerramento gracioso, aguarde)."


def resume_meeting(meeting_id: str) -> "tuple[bool, str]":
    """Sobe `python -m meeting_transcriber --resume <meeting_dir>` para
    reprocessar os blocos pendentes/com falha de uma sessao interrompida.
    Nao grava audio novo, entao pode rodar mesmo sem microfone/loopback."""
    try:
        meeting_id = validation.validate_meeting_id(meeting_id)
    except validation.ValidationError as exc:
        return False, str(exc)

    meetings_resolved = MEETINGS_DIR.resolve()
    meeting_dir = (meetings_resolved / meeting_id).resolve()
    if meeting_dir.parent != meetings_resolved:
        return False, "Sessao invalida."
    if not (meeting_dir / "state.json").exists():
        return False, "Sessao nao encontrada."

    with state_lock:
        if state["proc"] is not None:
            return False, "Ja existe uma gravacao/reprocessamento em andamento."

        cmd = [_python_executable(), "-u", "-m", "meeting_transcriber", "--resume", str(meeting_dir)]
        proc, error = _launch(cmd)
        if error:
            return False, error

        state["proc"] = proc
        state["output"] = None
        state["chunk_seconds"] = None
        state["meeting_dir"] = str(meeting_dir)
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["exit_code"] = None
        state["log"].clear()

    _log(f"[painel] reprocessando sessao interrompida {meeting_id}...")
    threading.Thread(target=_reader_thread, args=(proc,), daemon=True).start()
    return True, "Reprocessamento iniciado."


def get_status() -> dict:
    """Monta o JSON que a pagina consulta a cada 1.5s (polling) pra
    atualizar status, barra de progresso, log e indicador de "salvo"."""
    with state_lock:
        running = state["proc"] is not None
        output = state["output"]
        chunk_seconds = state["chunk_seconds"]
        started_at = state["started_at"]
        payload = {
            "running": running,
            "output": output,
            "chunk_seconds": chunk_seconds,
            "meeting_dir": state["meeting_dir"],
            "started_at": started_at,
            "finished_at": state["finished_at"],
            "exit_code": state["exit_code"],
            "log": list(state["log"])[-300:],
        }

    # bloco atual: aproximado por relogio de parede, o processo grava em
    # blocos continuos de chunk_seconds desde o inicio da sessao.
    if running and started_at and chunk_seconds:
        elapsed = time.time() - started_at
        payload["block_elapsed"] = elapsed % chunk_seconds
        payload["block_index"] = int(elapsed // chunk_seconds)

    if output:
        output_path = Path(output)
        payload["output_path"] = str(output_path)
        if output_path.exists():
            stat = output_path.stat()
            payload["output_exists"] = True
            payload["output_saved_at"] = stat.st_mtime
            payload["output_size"] = stat.st_size
        else:
            payload["output_exists"] = False

    return payload


def get_recovery() -> dict:
    """Sessoes que ficaram travadas em recording/processing e foram
    marcadas como interrompidas na inicializacao do painel (ver `main`) —
    ou seja, reunioes cujo processo morreu sem finalizar. O audio e a
    transcricao parcial de cada uma continuam intactos em disco."""
    sessions = [s for s in list_sessions(MEETINGS_DIR) if s.get("status") == STATUS_INTERRUPTED]
    return {"sessions": sessions}


_RESUME_PATH_RE = re.compile(r"^/api/meetings/([^/]+)/resume$")

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


class Handler(BaseHTTPRequestHandler):
    """Roteador HTTP minimo: serve o index.html e as rotas da API.
    Cada request roda numa thread propria (heranca de ThreadingHTTPServer),
    entao /api/status continua respondendo rapido mesmo com uma gravacao
    em andamento no subprocesso."""

    def log_message(self, format, *args):  # noqa: A002 - silencia log padrao no console
        pass

    def _valid_host(self) -> bool:
        # Defesa basica contra DNS rebinding / paginas de outros dominios
        # tentando falar com o servidor local: so aceita Host apontando pra
        # este mesmo endereco. O servidor em si so escuta em 127.0.0.1 (ver
        # main()), nunca em 0.0.0.0 — isso aqui e uma camada extra.
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in _ALLOWED_HOSTS

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if not self._valid_host():
            self.send_error(400, "Host invalido")
            return
        try:
            if self.path == "/" or self.path == "/index.html":
                self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")  # sempre le do disco, sem cache
            elif self.path == "/api/status":
                self._send_json(get_status())  # consultado pela pagina a cada 1.5s
            elif self.path == "/api/recovery":
                self._send_json(get_recovery())
            else:
                self.send_error(404)
        except Exception:
            logger.exception("Erro tratando GET %s", self.path)
            self._send_json({"ok": False, "message": "Erro interno no painel."}, 500)

    def do_POST(self):  # noqa: N802
        if not self._valid_host():
            self.send_error(400, "Host invalido")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send_json({"ok": False, "message": "Content-Length invalido."}, 400)
            return
        if length < 0:
            self._send_json({"ok": False, "message": "Content-Length invalido."}, 400)
            return
        if length > MAX_BODY_BYTES:
            # drena (e descarta) o corpo antes de responder, ate um teto
            # seguro -- nunca mais que _DRAIN_CAP_BYTES, mesmo que o
            # Content-Length declarado minta e seja muito maior. Sem isso,
            # bytes nao lidos ficam pendurados no socket e o SO pode
            # resetar a conexao abruptamente ao inves de entregar esta
            # resposta 413 de forma limpa pro cliente.
            remaining = min(length, _DRAIN_CAP_BYTES)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            self._send_json({"ok": False, "message": "Corpo da requisicao muito grande."}, 413)
            return

        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json({"ok": False, "message": "JSON invalido."}, 400)
            return
        if not isinstance(body, dict):
            self._send_json({"ok": False, "message": "Corpo da requisicao precisa ser um objeto JSON."}, 400)
            return

        try:
            if self.path == "/api/start":
                # body = {output, title, model, device, language, chunk_seconds, keep_audio}
                ok, msg = start_transcriber(body)
                self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
                return
            if self.path == "/api/stop":
                ok, msg = stop_transcriber()
                self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
                return
            match = _RESUME_PATH_RE.match(self.path)
            if match:
                ok, msg = resume_meeting(match.group(1))
                self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
                return
            self.send_error(404)
        except Exception:
            logger.exception("Erro tratando POST %s", self.path)
            self._send_json({"ok": False, "message": "Erro interno no painel."}, 500)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


class SinglePortServer(ThreadingHTTPServer):
    # Por padrao o http.server liga allow_reuse_address=True, que no
    # Windows deixa VARIOS processos ligarem na mesma porta ao mesmo
    # tempo (em vez de dar erro "porta em uso" como no Linux). Isso faz
    # cada request cair num processo diferente/zumbi de forma aleatoria
    # — sintoma classico: "as vezes funciona, as vezes nao", sem padrao.
    # Desligando aqui, o segundo `python webui.py` falha ao subir em vez
    # de virar um zumbi silencioso.
    allow_reuse_address = False


def main() -> None:
    MEETINGS_DIR.mkdir(parents=True, exist_ok=True)

    url = f"http://127.0.0.1:{PORT}"
    try:
        # 127.0.0.1 explicito e proposital: o painel nunca deve ser exposto
        # em 0.0.0.0/rede por padrao.
        server = SinglePortServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # Ja existe um painel rodando (porta ocupada) -- CRUCIAL rodar a
        # deteccao de recuperacao so DEPOIS de confirmar que somos a unica
        # instancia. Se rodasse antes desta checagem, subir um segundo
        # `webui.py` enquanto o primeiro tem uma gravacao de verdade em
        # andamento marcaria essa sessao ativa como "interrupted" so por
        # estar em status "recording" -- que e exatamente o estado normal
        # de uma sessao que nao tem nada de errado.
        print(f"Painel ja esta rodando em {url}. Abrindo o navegador nele em vez de subir outro.")
        webbrowser.open(url)
        return

    # Deteccao de recuperacao: so roda aqui, com a porta garantidamente
    # nossa -- ou seja, nenhum outro processo deste painel pode estar com
    # uma sessao de verdade em andamento neste exato momento. Qualquer
    # reuniao ainda travada em recording/processing so pode ser sobra de um
    # processo anterior que morreu sem finalizar.
    recovered = mark_interrupted_sessions(MEETINGS_DIR)
    for entry in recovered:
        logger.warning(
            "Sessao interrompida detectada: %s (%s) — %d/%d blocos transcritos.",
            entry.get("meeting_id"),
            entry.get("title"),
            entry.get("chunks_transcribed", 0),
            entry.get("chunk_count", 0),
        )

    print(f"Painel disponivel em {url} (Ctrl+C aqui encerra o servidor, nao a gravacao).")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
