"""Painel local (HTML) para controlar o meeting_transcriber com um botao.

Sobe um servidor HTTP so com a biblioteca padrao (sem Flask/FastAPI, sem
dependencia extra) em http://127.0.0.1:8765, serve o index.html e expoe uma
API minima (/api/start, /api/stop, /api/status) que liga/desliga o processo
`python -m meeting_transcriber` como subprocesso e guarda o log em memoria
para a pagina exibir ao vivo.

Uso: python webui.py   (ou clique duplo em iniciar.bat, que ja prepara o
ambiente virtual antes de chamar isto aqui).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PORT = 8765


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

# Estado global do painel, compartilhado entre as threads que atendem
# requests HTTP e a thread que le a saida do subprocesso. state_lock
# protege todo acesso porque varias threads mexem nele ao mesmo tempo.
state_lock = threading.Lock()
state = {
    "proc": None,  # subprocess.Popen do "python -m meeting_transcriber" em andamento, ou None se parado
    "log": deque(maxlen=1000),  # ultimas linhas de log (stdout+stderr do subprocesso), pra pagina mostrar ao vivo
    "output": None,  # caminho do .md que a sessao atual/ultima esta escrevendo
    "chunk_seconds": 300,  # usado so pra calcular a barra de progresso do bloco atual
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


def start_transcriber(opts: dict) -> tuple[bool, str]:
    """Monta o comando `python -m meeting_transcriber ...` a partir das
    opcoes vindas do formulario HTML e sobe ele como subprocesso.
    Retorna (sucesso, mensagem) pra virar a resposta JSON do /api/start.
    """
    with state_lock:
        if state["proc"] is not None:
            return False, "Ja existe uma gravacao em andamento."

        output = opts.get("output") or "transcricao.md"
        chunk_seconds = int(opts.get("chunk_seconds") or 300)
        cmd = [
            _python_executable(),
            "-u",
            "-m",
            "meeting_transcriber",
            "--output",
            output,
            "--title",
            opts.get("title") or "Transcricao de reuniao",
            "--model",
            opts.get("model") or "small",
            "--device",
            opts.get("device") or "cpu",
            "--language",
            opts.get("language") or "pt",
            "--chunk-seconds",
            str(chunk_seconds),
        ]
        if not opts.get("keep_audio", True):
            cmd.append("--no-keep-audio")

        if not (ROOT / ".venv").exists():
            return False, (
                "Ambiente virtual (.venv) nao encontrado. Feche esta janela e "
                "abra o painel atraves do iniciar.bat, que instala tudo "
                "automaticamente antes de abrir o navegador."
            )

        env = {**__import__("os").environ, "PYTHONPATH": str(SRC), "PYTHONUNBUFFERED": "1"}
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

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
            return False, f"Nao consegui iniciar o processo: {exc}"

        state["proc"] = proc
        state["output"] = output
        state["chunk_seconds"] = chunk_seconds
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["exit_code"] = None
        state["log"].clear()

    _log(f"[painel] iniciado: {' '.join(cmd)}")
    threading.Thread(target=_reader_thread, args=(proc,), daemon=True).start()
    return True, "Gravacao iniciada."


def stop_transcriber() -> tuple[bool, str]:
    """Encerra o subprocesso em andamento.

    terminate() no Windows mata na hora (sem rodar o handler de Ctrl+C do
    cli.py), entao o bloco que estava sendo gravado nesse instante e
    perdido — igual ao comportamento documentado pra uma queda inesperada.
    Tudo que ja foi transcrito antes disso ja esta salvo no .md.
    """
    with state_lock:
        proc = state["proc"]
    if proc is None:
        return False, "Nenhuma gravacao em andamento."

    _log("[painel] parando... aguarde a finalizacao do bloco atual.")
    try:
        proc.terminate()
    except Exception:
        pass

    # rede de seguranca: se por algum motivo terminate() nao surtir efeito,
    # forca depois de 8s (kill nao pode falhar/travar).
    def _force_kill_later():
        time.sleep(8)
        if proc.poll() is None:
            proc.kill()

    threading.Thread(target=_force_kill_later, daemon=True).start()
    return True, "Parando a gravacao."


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
            "started_at": started_at,
            "finished_at": state["finished_at"],
            "exit_code": state["exit_code"],
            "log": list(state["log"])[-300:],
        }

    # bloco atual: aproximado por relogio de parede, o processo grava em
    # blocos continuos de chunk_seconds desde o inicio da sessao.
    if running and started_at:
        elapsed = time.time() - started_at
        payload["block_elapsed"] = elapsed % chunk_seconds
        payload["block_index"] = int(elapsed // chunk_seconds)

    if output:
        output_path = (ROOT / output).resolve()
        payload["output_path"] = str(output_path)
        if output_path.exists():
            stat = output_path.stat()
            payload["output_exists"] = True
            payload["output_saved_at"] = stat.st_mtime
            payload["output_size"] = stat.st_size
        else:
            payload["output_exists"] = False

    return payload


class Handler(BaseHTTPRequestHandler):
    """Roteador HTTP minimo: serve o index.html e as 3 rotas da API.
    Cada request roda numa thread propria (heranca de ThreadingHTTPServer),
    entao /api/status continua respondendo rapido mesmo com uma gravacao
    em andamento no subprocesso."""

    def log_message(self, format, *args):  # noqa: A002 - silencia log padrao no console
        pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")  # sempre le do disco, sem cache
        elif self.path == "/api/status":
            self._send_json(get_status())  # consultado pela pagina a cada 1.5s
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        if self.path == "/api/start":
            # body = {output, title, model, device, language, chunk_seconds, keep_audio}
            ok, msg = start_transcriber(body)
            self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        elif self.path == "/api/stop":
            ok, msg = stop_transcriber()
            self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
        else:
            self.send_error(404)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
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
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = SinglePortServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Painel ja esta rodando em {url}. Abrindo o navegador nele em vez de subir outro.")
        webbrowser.open(url)
        return

    print(f"Painel disponivel em {url} (Ctrl+C aqui encerra o servidor, nao a gravacao).")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
