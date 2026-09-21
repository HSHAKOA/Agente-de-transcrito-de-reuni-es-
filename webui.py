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
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
SETTINGS_PATH = ROOT / "data" / "settings.json"
SCHEDULES_PATH = ROOT / "data" / "schedules.json"
MEETINGS_DB_PATH = ROOT / "data" / "meetings.db"

# webui.py em si (nao so o subprocesso que ele lanca) agora usa
# meeting_transcriber.validation/session/settings/folder_dialog, entao
# precisa de src/ no sys.path tambem quando rodado direto (fora do .venv
# com editable install).
sys.path.insert(0, str(SRC))

from meeting_transcriber import folder_dialog, settings, validation  # noqa: E402
from meeting_transcriber.audio import devices as audio_devices  # noqa: E402
from meeting_transcriber.audio.models import AudioError  # noqa: E402
from meeting_transcriber.audio_capture import SAMPLE_RATE  # noqa: E402
from meeting_transcriber.scheduling.clock import SystemClock  # noqa: E402
from meeting_transcriber.scheduling.engine import SchedulerEngine  # noqa: E402
from meeting_transcriber.scheduling.service import ScheduleService, ValidationError as ScheduleValidationError  # noqa: E402
from meeting_transcriber.scheduling.store import ScheduleStore  # noqa: E402
from meeting_transcriber.export import CONTENT_TYPES as EXPORT_CONTENT_TYPES  # noqa: E402
from meeting_transcriber.export import EXTENSIONS as EXPORT_EXTENSIONS  # noqa: E402
from meeting_transcriber.export import render as render_export  # noqa: E402
from meeting_transcriber.storage.db import connect as connect_db  # noqa: E402
from meeting_transcriber.storage.import_filesystem import import_all, import_meeting  # noqa: E402
from meeting_transcriber.storage.repository import MeetingRepository  # noqa: E402
from meeting_transcriber.session import (  # noqa: E402
    STATUS_INTERRUPTED,
    MeetingSession,
    find_meeting_dir_across_roots,
    is_pid_running,
    list_sessions,
    mark_interrupted_sessions,
    mark_session_interrupted_if_live,
    new_meeting_id,
)

# Pasta raiz onde TODAS as reunioes sao salvas -- escolhida pelo usuario
# (botao "Escolher pasta" no painel) e lembrada entre execucoes via
# settings.json. So um valor global porque so existe uma gravacao por vez
# (garantido pelo SinglePortServer) -- mudar de pasta com uma gravacao em
# andamento e bloqueado explicitamente (ver _apply_new_meetings_root).
MEETINGS_DIR = settings.get_meetings_root(SETTINGS_PATH)

PORT = 8765
MAX_BODY_BYTES = 1_000_000  # 1 MB — generoso pros campos reais, barra corpo gigante como DoS
_DRAIN_CAP_BYTES = MAX_BODY_BYTES * 4  # teto pra drenar um corpo rejeitado sem nunca ler quantidade ilimitada

# Escalonamento do encerramento gracioso: sinal gracioso -> terminate() -> kill().
# So avanca de estagio se o anterior nao surtir efeito dentro do timeout.
#
# GRACEFUL_TIMEOUT_SECONDS e a janela SEM PROGRESSO (minimo): ao receber o
# sinal, o gravador grava o bloco parcial e ainda transcreve a fila -- e um
# bloco de `chunk_seconds` (300 s) leva bem mais que 30 s no Whisper em CPU.
# Com a janela fixa de 30 s, todo "Parar" de uma gravacao longa estourava o
# prazo e caia em terminate(): os ultimos blocos ficavam sem transcrever
# (observado numa gravacao real de aula: 9 de 11 blocos). Por isso
# `stop_transcriber` amplia a janela para `chunk_seconds` e a reinicia
# enquanto o gravador avanca (ver `_session_progress_token`), com o teto
# absoluto MAX_GRACEFUL_SECONDS.
GRACEFUL_TIMEOUT_SECONDS = 30.0
MAX_GRACEFUL_SECONDS = 1800.0
TERMINATE_TIMEOUT_SECONDS = 5.0

# frequencia do stream SSE do medidor de audio -- dentro da faixa de 5-15
# atualizacoes/s pedida (0.15s ~= 6.7 Hz).
LEVELS_STREAM_INTERVAL_SECONDS = 0.15

# transcricao ao vivo muda bem mais devagar que o nivel de audio (segmentos
# chegam a cada poucos segundos, nunca varias vezes por segundo) -- um
# intervalo mais folgado evita releitura de arquivo sem necessidade.
TRANSCRIPTION_STREAM_INTERVAL_SECONDS = 0.5

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


def _wait_for_graceful_exit(
    proc: subprocess.Popen,
    idle_timeout: float,
    max_total: float,
    progress_fn,
    sleep_fn,
    poll_interval: float,
) -> bool:
    """Espera `proc` sair por conta propria. `idle_timeout` e a janela SEM
    progresso: se `progress_fn()` devolver um token diferente do anterior
    (ex.: mais um bloco transcrito), a janela reinicia -- um gravador que
    avanca nao e um gravador travado. `max_total` e o teto absoluto. Sem
    `progress_fn` (ou se ele falhar), equivale a esperar `idle_timeout`."""

    def _token(fallback):
        if progress_fn is None:
            return fallback
        try:
            return progress_fn()
        except Exception:
            return fallback  # falha ao medir progresso nunca conta como progresso

    last = _token(None)
    elapsed = idle = 0.0
    while elapsed < max_total and idle < idle_timeout:
        if proc.poll() is not None:
            return True
        sleep_fn(poll_interval)
        elapsed += poll_interval
        idle += poll_interval
        current = _token(last)
        if current != last:
            last = current
            idle = 0.0
    return proc.poll() is not None


def shutdown_sequence(
    proc: subprocess.Popen,
    graceful_signal: Optional[int] = None,
    graceful_timeout: float = GRACEFUL_TIMEOUT_SECONDS,
    terminate_timeout: float = TERMINATE_TIMEOUT_SECONDS,
    sleep_fn=time.sleep,
    poll_interval: float = 0.2,
    progress_fn=None,
    max_graceful_seconds: float = MAX_GRACEFUL_SECONDS,
) -> str:
    """Encerra `proc` com escalonamento: sinal gracioso -> terminate() -> kill().

    Antes, "Parar" no painel chamava proc.terminate() direto — no Windows
    isso mata o processo na hora (sem entregar sinal nenhum), descartando o
    bloco de audio que ainda estava no buffer e pulando a finalizacao do
    markdown. Essa funcao so escala pro proximo estagio se o anterior nao
    surtir efeito: `graceful_timeout` e a janela sem progresso (reiniciada
    sempre que `progress_fn` mudar) e `max_graceful_seconds` o teto
    absoluto, dando tempo real pra fila de whisper pendente ser drenada.
    Retorna qual estagio encerrou o processo ("graceful", "terminate" ou
    "kill") — usado em log e em testes.
    """
    graceful_signal = graceful_signal if graceful_signal is not None else _graceful_signal_for_platform()

    try:
        proc.send_signal(graceful_signal)
    except Exception:
        logger.exception("Falha ao enviar sinal de parada graciosa")
    if _wait_for_graceful_exit(proc, graceful_timeout, max_graceful_seconds, progress_fn, sleep_fn, poll_interval):
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
    # True do momento em que /api/stop e aceito ate o subprocesso realmente
    # terminar (_reader_thread detectar o exit) -- correcao pos-auditoria
    # (P1-5): antes disso o botao "Parar" reabilitava na hora (o processo
    # ainda estava vivo terminando o encerramento gracioso, que pode levar
    # ate ~35s), permitindo um duplo clique disparar uma segunda thread de
    # shutdown concorrente no mesmo processo.
    "stopping": False,
    # O que o processo em `proc` esta fazendo: "record" (gravando + transcrevendo
    # uma reuniao nova) ou "resume" (so retranscrevendo os blocos pendentes de
    # uma sessao interrompida, sem gravar audio). As duas ocupam o MESMO slot
    # (`proc`), entao sem isto a UI so saberia dizer "gravando" -- enganoso
    # durante um "Reprocessar". None enquanto nao ha processo.
    "mode": None,
}


def _is_recording_active() -> bool:
    with state_lock:
        return state["proc"] is not None


def _get_active_meeting_dir() -> Optional[str]:
    with state_lock:
        return state["meeting_dir"]


def _get_last_exit_ok() -> Optional[bool]:
    """None = ainda rodando/desconhecido (o engine nunca deveria perguntar
    isso enquanto is_recording_active() ainda for True); True/False so
    depois que o subprocesso realmente terminou -- ver _reader_thread."""
    with state_lock:
        exit_code = state["exit_code"]
    return None if exit_code is None else exit_code == 0


def _scheduler_start_recording(opts: dict) -> "tuple[bool, str]":
    # persist_as_default=False: a configuracao de audio de um agendamento
    # e dele mesmo (Schedule), nunca deveria sobrescrever silenciosamente
    # a preferencia global usada por inicios manuais (ver start_transcriber).
    return start_transcriber(opts, persist_as_default=False)


def _scheduler_request_stop() -> "tuple[bool, str]":
    # MESMA rotina do botao "Parar" manual -- o motor do scheduler nunca
    # tem acesso a proc.kill()/terminate() diretamente, so a este shutdown
    # gracioso (missao, secao 9: "nao criar duas implementacoes diferentes
    # de parada").
    return stop_transcriber()


# Agendamento de gravacoes (Fase C.1): schedules.json fica ao lado de
# settings.json (config do app, fora de qualquer meetings_root -- cada
# agendamento pode apontar pra uma raiz diferente). O motor comeca parado;
# `main()` so chama `.start()` depois que a porta do painel estiver
# garantidamente nossa (mesma ordem de `mark_interrupted_sessions`, pelo
# mesmo motivo: nunca correr pra iniciar/parar nada antes de confirmar que
# somos a unica instancia do painel rodando).
schedule_store = ScheduleStore(SCHEDULES_PATH)
schedule_service = ScheduleService(schedule_store)
schedule_engine = SchedulerEngine(
    schedule_store,
    SystemClock(),
    is_recording_active=_is_recording_active,
    get_active_meeting_dir=_get_active_meeting_dir,
    get_last_exit_ok=_get_last_exit_ok,
    start_recording=_scheduler_start_recording,
    request_stop=_scheduler_request_stop,
    sample_rate=SAMPLE_RATE,
)

# Historico e busca (Fase E): indice SQLite construido a partir das
# pastas de reuniao existentes -- aditivo, nunca no caminho quente de
# gravacao (ver storage/__init__.py). Importar e uma acao EXPLICITA
# (POST /api/meetings/import), nunca automatica no boot -- evita
# trabalho de fundo surpresa toda vez que o painel abre.
meeting_repository = MeetingRepository(connect_db(MEETINGS_DB_PATH))


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
        meeting_dir = state["meeting_dir"]

    # Se o processo morreu sem finalizar a sessao (terminate()/kill() apos o
    # prazo do encerramento gracioso, ou uma queda), `state.json` ficou em
    # "processing"/"recording" -- e `/api/recovery` so lista "interrupted",
    # que ate aqui so era marcado no proximo boot do painel. Marca agora,
    # ANTES de liberar o slot abaixo: enquanto `state["proc"]` ainda esta
    # setado, nenhum /api/start ou /resume consegue tocar nesta reuniao.
    # Uma sessao que terminou direito (completed/interrupted/failed) nao e
    # alterada. Nunca levanta: uma falha aqui so deixa de marcar (o proximo
    # boot ainda pega), nunca impede o slot de ser liberado.
    interrupted_now = None
    if meeting_dir:
        try:
            interrupted_now = mark_session_interrupted_if_live(Path(meeting_dir))
        except OSError:
            logger.warning("Nao foi possivel marcar a sessao %s como interrompida.", meeting_dir, exc_info=True)

    with state_lock:
        state["finished_at"] = time.time()
        state["exit_code"] = exit_code
        state["proc"] = None  # libera pra um novo /api/start poder rodar
        state["stopping"] = False
        state["mode"] = None
    _log(f"[painel] processo encerrado (codigo {exit_code}).")
    if interrupted_now is not None:
        _log(
            "[painel] a reuniao nao terminou de ser transcrita (o processo encerrou antes de finalizar): "
            "o audio esta salvo; use Reprocessar para completar a transcricao."
        )

    # Indexacao automatica no historico (correcao pos-auditoria P1-2): antes
    # disso, a UNICA forma de uma reuniao aparecer no Dashboard/historico/
    # busca era o usuario saber que existe POST /api/meetings/import e
    # chama-lo manualmente -- na pratica o banco ficava sempre vazio.
    # `import_meeting` e idempotente (upsert por id) e nunca toca nenhum
    # arquivo real da reuniao (so LE transcript.md/state.json) -- reimportar
    # a mesma reuniao de novo (ex.: reprocessamento via resume_meeting, que
    # tambem passa por _reader_thread) so atualiza os campos, nunca duplica.
    # Roda mesmo se o processo terminou com erro/interrompido: melhor um
    # registro no historico refletindo o status real do que nenhum registro.
    if meeting_dir:
        result = import_meeting(meeting_repository, Path(meeting_dir))
        if result.ok:
            _log(f"[painel] reuniao indexada no historico ({result.segments_imported} segmento(s)).")
        else:
            # falha na indexacao NUNCA compromete os arquivos reais (audio/
            # transcript.md continuam intactos em disco) -- so registra o
            # erro; o usuario ainda pode rodar "Sincronizar historico"
            # (POST /api/meetings/import) manualmente depois.
            logger.warning("Falha ao indexar automaticamente a reuniao em %s: %s", meeting_dir, result.message)
            _log(f"[painel] aviso: nao foi possivel indexar a reuniao no historico ({result.message}).")


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


def get_settings_info() -> dict:
    """Estado atual das configuracoes de armazenamento: pasta raiz das
    reunioes + espaco livre (quando a pasta existe) -- consultado pela
    pagina ao carregar e periodicamente durante uma gravacao longa (a
    missao pede monitorar espaco, nao so checar uma vez no inicio)."""
    info = {
        "meetings_root": str(MEETINGS_DIR),
        "folder_dialog_available": folder_dialog.is_available(),
        "free_bytes": None,
    }
    if MEETINGS_DIR.exists():
        try:
            info["free_bytes"] = shutil.disk_usage(MEETINGS_DIR).free
        except OSError:
            pass
    return info


def _apply_new_meetings_root(candidate: Path) -> "tuple[bool, str]":
    """Cria a pasta se preciso, roda a checklist de saude (existe, e pasta,
    tem espaco, e gravavel de verdade) e so persiste em settings.json se
    passar em tudo -- nunca troca a raiz "as cegas"."""
    global MEETINGS_DIR

    with state_lock:
        if state["proc"] is not None:
            return False, "Nao e possivel trocar a pasta com uma gravacao em andamento."

        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"Nao foi possivel criar a pasta “{candidate}”: {exc}"

        health = validation.check_folder_health(candidate)
        if not health.ok:
            return False, health.message

        MEETINGS_DIR = candidate
        settings.set_meetings_root(SETTINGS_PATH, candidate)

    return True, "Pasta de reunioes atualizada."


def _validate_and_apply_root(path_value) -> dict:
    try:
        candidate = validation.validate_meetings_root_path(path_value)
    except validation.ValidationError as exc:
        return {"ok": False, "cancelled": False, "message": str(exc), **get_settings_info()}
    ok, message = _apply_new_meetings_root(candidate)
    return {"ok": ok, "cancelled": False, "message": message, **get_settings_info()}


def choose_meetings_folder() -> dict:
    """Abre o seletor nativo de pasta (ver folder_dialog.py) e, se o
    usuario escolher algo, valida e persiste como a nova raiz."""
    initial = str(MEETINGS_DIR) if MEETINGS_DIR.exists() else None
    chosen = folder_dialog.pick_directory(initial_dir=initial)
    if chosen is None:
        return {"ok": False, "cancelled": True, "message": "Nenhuma pasta selecionada.", **get_settings_info()}
    return _validate_and_apply_root(chosen)


def set_meetings_folder_manual(path_value) -> dict:
    """Fallback quando o dialogo nativo nao esta disponivel (ex.: tkinter
    ausente no ambiente): usuario digita o caminho, mesma validacao."""
    return _validate_and_apply_root(path_value)


def open_folder(path_value) -> "tuple[bool, str]":
    """Abre o Explorador de Arquivos (ou equivalente) na pasta indicada.

    `os.startfile` no Windows e uma chamada direta de API do SO -- nao um
    shell, nao interpreta o path como comando. Nos demais SOs usamos
    subprocess.Popen com uma LISTA de argumentos (nunca shell=True nem
    concatenacao de string no comando).

    O path precisa estar dentro de alguma raiz de reunioes JA CONHECIDA
    (`settings.get_known_meeting_roots` -- a mesma lista usada por
    recovery/resume, ver docs/RECOVERY.md), nao so a raiz ATIVA hoje
    (correcao pos-auditoria P2: usuario que trocou de pasta nao conseguia
    mais abrir reunioes antigas). Continua bloqueando qualquer path que
    nao esteja dentro de nenhuma raiz ja usada -- nunca abre um caminho
    arbitrario vindo do cliente.
    """
    if not isinstance(path_value, str) or not path_value.strip():
        return False, "Caminho invalido."
    try:
        path = Path(path_value).resolve()
    except (OSError, RuntimeError):
        return False, "Caminho invalido."

    known_roots = [root.resolve() for root in settings.get_known_meeting_roots(SETTINGS_PATH)]
    if not any(path == root or root in path.parents for root in known_roots):
        return False, "So e possivel abrir pastas dentro de uma raiz de reunioes conhecida."
    if not path.exists():
        return False, "Pasta nao encontrada."

    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - API nativa do SO, nao e shell
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        return False, f"Nao foi possivel abrir a pasta: {exc}"
    return True, "Pasta aberta."


def start_transcriber(opts: dict, persist_as_default: bool = True) -> "tuple[bool, str]":
    """Valida as opcoes vindas do formulario HTML, monta o comando
    `python -m meeting_transcriber ...` e sobe ele como subprocesso.
    Retorna (sucesso, mensagem) pra virar a resposta JSON do /api/start.

    Nenhum campo e confiado sem validacao — ver meeting_transcriber.validation.
    O nome do arquivo de saida nao vem mais do cliente: e sempre
    `transcript.md` dentro da pasta da propria reuniao (que fica dentro da
    raiz configurada) — elimina de vez a superficie de path traversal que
    antes existia no campo "output".

    `opts["meetings_root"]`: opcional -- raiz desta gravacao especifica
    (usado pelo scheduler, secao "Salvar em" de cada agendamento, que pode
    apontar pra uma pasta diferente da raiz global do painel). Omitido:
    usa a raiz global (`MEETINGS_DIR`), igual sempre foi.

    `persist_as_default=False`: nao sobrescreve a preferencia global de
    audio salva em settings.json com a escolha desta gravacao -- usado
    pelo scheduler, cuja configuracao e por AGENDAMENTO, nunca deveria
    silenciosamente virar o padrao da proxima gravacao manual.
    """
    try:
        model = validation.validate_model(opts.get("model") or "small")
        device = validation.validate_device(opts.get("device") or "cpu")
        language = validation.validate_language(opts.get("language") or "pt")
        chunk_seconds = validation.validate_chunk_seconds(opts.get("chunk_seconds", 300))
        title = validation.validate_title(opts.get("title"))
        target_root = (
            validation.validate_meetings_root_path(opts["meetings_root"])
            if opts.get("meetings_root")
            else MEETINGS_DIR
        )
    except validation.ValidationError as exc:
        return False, str(exc)

    keep_audio = bool(opts.get("keep_audio", True))

    # fontes de audio: usa a preferencia salva pra qualquer campo que o
    # cliente nao mandar explicitamente (permite tanto "usa o que ja
    # estava configurado" quanto "troca so pra esta reuniao").
    audio_prefs = settings.get_audio_preferences(SETTINGS_PATH)
    capture_system = bool(opts.get("capture_system", audio_prefs["capture_system"]))
    capture_microphone = bool(opts.get("capture_microphone", audio_prefs["capture_microphone"]))
    system_device_id = opts.get("system_device_id", audio_prefs["system_device_id"])
    microphone_device_id = opts.get("microphone_device_id", audio_prefs["microphone_device_id"])
    for value in (system_device_id, microphone_device_id):
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            return False, "Identificador de dispositivo de audio invalido."

    if not capture_system and not capture_microphone:
        return False, "Selecione pelo menos uma fonte de audio (computador e/ou microfone)."

    with state_lock:
        if state["proc"] is not None:
            return False, "Ja existe uma gravacao em andamento."

        if not (ROOT / ".venv").exists():
            return False, (
                "Ambiente virtual (.venv) nao encontrado. Feche esta janela e "
                "abra o painel atraves do iniciar.bat, que instala tudo "
                "automaticamente antes de abrir o navegador."
            )

        # nunca iniciar silenciosamente numa pasta que nao existe, sem
        # espaco livre suficiente, ou sem permissao de escrita de verdade.
        try:
            target_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"Nao foi possivel criar a pasta de reunioes “{target_root}”: {exc}"
        health = validation.check_folder_health(target_root)
        if not health.ok:
            return False, health.message

        # health check de audio ANTES de subir o subprocesso: da pra dar
        # feedback imediato na UI em vez do usuario ter que abrir o log
        # pra descobrir que o dispositivo escolhido nao existe mais
        # (cli.py faz a MESMA checagem de novo antes de gravar -- e a
        # autoridade final, mas aqui evita a viagem de ida e volta).
        if capture_system:
            audio_health = audio_devices.check_device_health("output", system_device_id, SAMPLE_RATE)
            if not audio_health.ok:
                return False, f"Audio do computador indisponivel: {audio_health.message}"
        if capture_microphone:
            audio_health = audio_devices.check_device_health("input", microphone_device_id, SAMPLE_RATE)
            if not audio_health.ok:
                return False, f"Microfone indisponivel: {audio_health.message}"

        meeting_id = new_meeting_id(title=title)
        meeting_dir = target_root / meeting_id
        output_path = meeting_dir / "transcript.md"
        levels_path = meeting_dir / "levels.json"
        live_transcript_path = meeting_dir / "live_transcript.json"

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
            "--levels-file",
            str(levels_path),
            "--live-transcript-file",
            str(live_transcript_path),
        ]
        if not keep_audio:
            cmd.append("--no-keep-audio")
        if not capture_system:
            cmd.append("--no-capture-system")
        if capture_microphone:
            cmd.append("--capture-microphone")
        if system_device_id:
            cmd.extend(["--system-device", system_device_id])
        if microphone_device_id:
            cmd.extend(["--microphone-device", microphone_device_id])

        proc, error = _launch(cmd)
        if error:
            return False, error

        state["proc"] = proc
        state["mode"] = "record"
        state["output"] = str(output_path)
        state["chunk_seconds"] = chunk_seconds
        state["meeting_dir"] = str(meeting_dir)
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["exit_code"] = None
        state["stopping"] = False
        state["log"].clear()

    # lembra a escolha pra proxima reuniao (mission, secao "Configuracoes":
    # ultimo microfone, ultima saida, capturar sistema/microfone: sim/nao)
    # -- so pra inicio manual; um agendamento tem sua propria configuracao
    # persistida no proprio Schedule, nunca deveria pisar no padrao global.
    if persist_as_default:
        settings.set_audio_preferences(
            SETTINGS_PATH,
            capture_system=capture_system,
            capture_microphone=capture_microphone,
            system_device_id=system_device_id,
            microphone_device_id=microphone_device_id,
        )

    # Comando completo (com paths absolutos do sistema) vai so pro log do
    # SERVIDOR (console/arquivo, nunca exposto por nenhuma API) -- o log em
    # memoria devolvido por /api/status pro navegador leva so uma linha sem
    # detalhe interno (correcao pos-auditoria: evitar vazar caminhos
    # absolutos/argumentos internos pra quem so deveria ver "esta gravando").
    logger.info("Comando do subprocesso de gravacao: %s", cmd)
    _log(f"[painel] gravacao iniciada (meeting_id={meeting_id}).")
    threading.Thread(target=_reader_thread, args=(proc,), daemon=True).start()
    return True, "Gravacao iniciada."


def stop_transcriber() -> "tuple[bool, str]":
    """Pede o encerramento do subprocesso em andamento com shutdown
    gracioso: sinaliza parada (o subprocesso ainda termina de escrever o
    bloco parcial e finalizar o markdown), e so escala para terminate()/
    kill() se ele nao responder dentro do timeout (ver shutdown_sequence).

    Recusa um segundo pedido enquanto o primeiro ainda esta em andamento
    (`state["stopping"]`) -- correcao pos-auditoria (P1-5): antes disso um
    duplo clique no botao "Parar" (facil de acontecer, o encerramento
    gracioso pode levar ate ~35s) disparava uma SEGUNDA thread de
    `shutdown_sequence` concorrente enviando sinais pro mesmo processo.
    """
    with state_lock:
        proc = state["proc"]
        already_stopping = state["stopping"]
        meeting_dir = state["meeting_dir"]
        chunk_seconds = state["chunk_seconds"]
        if proc is not None and not already_stopping:
            state["stopping"] = True
    if proc is None:
        return False, "Nenhuma gravacao em andamento."
    if already_stopping:
        return False, "Ja estamos finalizando esta gravacao, aguarde."

    _log("[painel] parando... aguardando a finalizacao do bloco atual (pode levar ate alguns minutos).")
    threading.Thread(
        target=shutdown_sequence,
        args=(proc,),
        kwargs={
            # a janela sem progresso precisa caber a transcricao de UM bloco
            # (RTF <= 1: se o Whisper nao acompanhasse o tempo real, a fila
            # ja teria crescido durante a propria gravacao)
            "graceful_timeout": max(GRACEFUL_TIMEOUT_SECONDS, float(chunk_seconds or 0)),
            "progress_fn": (lambda: _session_progress_token(meeting_dir)) if meeting_dir else None,
        },
        daemon=True,
    ).start()
    return True, "Parando a gravacao (encerramento gracioso, aguarde)."


def _session_progress_token(meeting_dir: str) -> Optional[tuple]:
    """Muda sempre que o gravador avanca no encerramento: fecha o bloco
    parcial (`chunk_count`), termina de transcrever um bloco
    (`chunks_transcribed`) ou finaliza a sessao (`status`). `None` se
    `state.json` ainda nao existe ou esta ilegivel -- nunca conta como
    progresso."""
    try:
        session_state = json.loads((Path(meeting_dir) / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (session_state.get("status"), session_state.get("chunk_count"), session_state.get("chunks_transcribed"))


def resume_meeting(meeting_id: str) -> "tuple[bool, str]":
    """Sobe `python -m meeting_transcriber --resume <meeting_dir>` para
    reprocessar os blocos pendentes/com falha de uma sessao interrompida.
    Nao grava audio novo, entao pode rodar mesmo sem microfone/loopback.

    A sessao pode estar em QUALQUER raiz ja conhecida (nao so a raiz ativa
    hoje) -- ver find_meeting_dir_across_roots e docs/RECOVERY.md.
    """
    try:
        meeting_id = validation.validate_meeting_id(meeting_id)
    except validation.ValidationError as exc:
        return False, str(exc)

    roots = settings.get_known_meeting_roots(SETTINGS_PATH)
    meeting_dir = find_meeting_dir_across_roots(meeting_id, roots)
    if meeting_dir is None:
        return False, "Sessao nao encontrada."

    # Camada extra de seguranca (nao e adocao de processo -- ver
    # docs/RECOVERY.md): se o PID registrado na sessao ainda parece estar
    # rodando, recusa reprocessar. Isso evita dois processos escrevendo no
    # mesmo state.json/transcript.md ao mesmo tempo caso o processo
    # original nao tenha realmente morrido (ex.: o painel que perdeu
    # contato com ele foi o que reiniciou, nao o gravador em si). PID
    # reciclado pelo SO pode gerar um falso positivo raro (recusa
    # reprocessar sem necessidade) -- falhar fechado aqui e intencional.
    try:
        recorded_pid = MeetingSession.load(meeting_dir).state.get("pid")
    except (json.JSONDecodeError, OSError, KeyError):
        recorded_pid = None
    if recorded_pid and is_pid_running(recorded_pid):
        return False, (
            f"Um processo com PID {recorded_pid} ainda parece estar em execucao para esta "
            "sessao. Para evitar dois processos escrevendo os mesmos arquivos ao mesmo tempo, "
            "verifique o Gerenciador de Tarefas antes de reprocessar."
        )

    with state_lock:
        if state["proc"] is not None:
            return False, "Ja existe uma gravacao/reprocessamento em andamento."

        cmd = [_python_executable(), "-u", "-m", "meeting_transcriber", "--resume", str(meeting_dir)]
        proc, error = _launch(cmd)
        if error:
            return False, error

        state["proc"] = proc
        state["mode"] = "resume"
        state["output"] = None
        state["chunk_seconds"] = None
        state["meeting_dir"] = str(meeting_dir)
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["exit_code"] = None
        state["stopping"] = False
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
            "stopping": state["stopping"],
            "mode": state["mode"] if running else None,
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
    transcricao parcial de cada uma continuam intactos em disco.

    Varre TODAS as raizes ja conhecidas (nao so a raiz ativa hoje) -- se o
    usuario gravou em D:\\Reunioes e depois trocou para E:\\Reunioes, uma
    sessao interrompida deixada em D: continua aparecendo aqui. Nunca varre
    nada fora dessas raizes explicitamente escolhidas alguma vez.
    """
    sessions = []
    for root in settings.get_known_meeting_roots(SETTINGS_PATH):
        if not root.exists():
            continue
        try:
            sessions.extend(s for s in list_sessions(root) if s.get("status") == STATUS_INTERRUPTED)
        except OSError:
            continue
    return {"sessions": sessions}


def get_audio_devices() -> dict:
    """GET /api/audio/devices -- DTOs serializaveis (ver
    audio.models.AudioDevice.to_dict), nunca objetos internos do backend
    de audio. Em caso de falha do proprio motor de audio (ex.: nenhum
    servico de audio disponivel), devolve o erro estruturado em vez de
    deixar a excecao subir (ver audio.models.AudioError.to_dict)."""
    try:
        return audio_devices.list_devices()
    except AudioError as exc:
        return exc.to_dict()


def get_audio_config() -> dict:
    """GET /api/audio/config -- preferencias salvas: ultimo microfone,
    ultima saida, quais fontes capturar por padrao na proxima reuniao."""
    return settings.get_audio_preferences(SETTINGS_PATH)


def set_audio_config(body: dict) -> dict:
    """PUT /api/audio/config -- atualiza so as chaves reconhecidas e
    devolve a configuracao resultante. Nao valida se o dispositivo salvo
    ainda existe (isso so importa na hora de gravar/testar de verdade,
    onde `check_device_health` ja cobre isso com uma mensagem clara)."""
    updates = {}
    if "capture_system" in body:
        updates["capture_system"] = bool(body["capture_system"])
    if "capture_microphone" in body:
        updates["capture_microphone"] = bool(body["capture_microphone"])
    for key in ("system_device_id", "microphone_device_id"):
        if key in body:
            value = body[key]
            updates[key] = str(value) if value else None
    return settings.set_audio_preferences(SETTINGS_PATH, **updates)


def test_audio(body: dict) -> dict:
    """POST /api/audio/test -- testa dispositivo(s) de verdade (abre um
    stream curto, mede o nivel por ~1s, fecha) SEM criar nenhuma reuniao.
    Corpo opcional: {capture_system, capture_microphone, system_device_id,
    microphone_device_id} -- qualquer campo omitido usa a preferencia
    salva atualmente. Sincrono de proposito (a missao permite; um teste de
    ~1-2s por fonte nao justifica um job em background com polling)."""
    with state_lock:
        recording_active = state["proc"] is not None
    if recording_active:
        return {"ok": False, "message": "Nao e possivel testar audio com uma gravacao em andamento."}

    prefs = settings.get_audio_preferences(SETTINGS_PATH)
    capture_system = bool(body.get("capture_system", prefs["capture_system"]))
    capture_microphone = bool(body.get("capture_microphone", prefs["capture_microphone"]))
    system_device_id = body.get("system_device_id", prefs["system_device_id"])
    microphone_device_id = body.get("microphone_device_id", prefs["microphone_device_id"])

    if not capture_system and not capture_microphone:
        return {"ok": False, "message": "Selecione pelo menos uma fonte de audio para testar."}

    results = {}
    ok = True
    if capture_system:
        health = audio_devices.check_device_health("output", system_device_id, SAMPLE_RATE, probe_seconds=1.0)
        results["system"] = health.to_dict()
        ok = ok and health.ok
    if capture_microphone:
        health = audio_devices.check_device_health("input", microphone_device_id, SAMPLE_RATE, probe_seconds=1.0)
        results["microphone"] = health.to_dict()
        ok = ok and health.ok

    return {"ok": ok, "results": results}


def get_audio_levels() -> dict:
    """GET /api/audio/levels -- ultimo snapshot de nivel de audio da
    gravacao ATIVA (se houver), escrito periodicamente pelo subprocesso em
    `<meeting_dir>/levels.json` (ver cli.py:_levels_writer_loop). Devolve
    {} se nao ha gravacao rodando ou o arquivo ainda nao existe/esta no
    meio de uma escrita -- nunca uma excecao por isso.

    Checa `state["proc"] is not None`, nao so `meeting_dir` truthy
    (correcao pos-auditoria): `meeting_dir` continua com o valor da
    ULTIMA sessao mesmo depois dela terminar (get_status ainda usa isso
    pra mostrar informacao da ultima gravacao) -- sem esta checagem extra,
    o medidor de nivel continuava lendo o levels.json residual de uma
    sessao ja encerrada, fazendo o React mostrar audio "ativo" que nao
    existe mais."""
    with state_lock:
        meeting_dir = state["meeting_dir"] if state["proc"] is not None else None
    if not meeting_dir:
        return {}
    levels_path = Path(meeting_dir) / "levels.json"
    try:
        return json.loads(levels_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get_live_transcription() -> dict:
    """GET /api/transcription/live -- ultimo snapshot da transcricao ao
    vivo (segmentos provisorios/definitivos + backlog) da gravacao ATIVA,
    escrito periodicamente pelo subprocesso em
    `<meeting_dir>/live_transcript.json` (ver cli.py:_live_transcript_writer_loop,
    Fase D). Devolve {} se nao ha gravacao rodando, se a transcricao ao
    vivo estiver desativada nesta sessao, ou se o arquivo ainda nao
    existe/esta no meio de uma escrita -- nunca uma excecao por isso.

    Mesma correcao pos-auditoria de `get_audio_levels`: checa
    `state["proc"] is not None`, nao so `meeting_dir` truthy, senao a
    transcricao ao vivo continuaria "aparecendo" depois da gravacao ja ter
    parado."""
    with state_lock:
        meeting_dir = state["meeting_dir"] if state["proc"] is not None else None
    if not meeting_dir:
        return {}
    live_path = Path(meeting_dir) / "live_transcript.json"
    try:
        return json.loads(live_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# -- Agendamento de gravacoes (Fase C.1) ------------------------------------

def _schedule_to_api_dict(schedule, now: datetime) -> dict:
    """Formato de `GET/POST /api/schedules*` -- o dict bruto do Schedule
    mais campos calculados que o cliente precisaria, senao, recalcular
    sozinho (missao, secao 6: contagem regressiva) usando o relogio do
    SERVIDOR, nunca confiando no relogio do navegador."""
    data = schedule.to_dict()
    if schedule.next_run_at:
        next_run = datetime.fromisoformat(schedule.next_run_at)
        data["seconds_until_next_run"] = (next_run - now).total_seconds()
    else:
        data["seconds_until_next_run"] = None
    return data


def get_schedules() -> dict:
    now = datetime.now(timezone.utc)
    return {"schedules": [_schedule_to_api_dict(s, now) for s in schedule_service.list_all()]}


def create_schedule(body: dict) -> "tuple[bool, dict]":
    try:
        schedule = schedule_service.create(body)
    except ScheduleValidationError as exc:
        return False, {"ok": False, "message": str(exc)}
    schedule_engine.tick_once()  # reage imediatamente (ex.: "start now" nem precisa esperar o proximo tick)
    return True, {"ok": True, "schedule": _schedule_to_api_dict(schedule_service.get(schedule.id), datetime.now(timezone.utc))}


def update_schedule(schedule_id: str, body: dict) -> "tuple[bool, dict]":
    try:
        schedule = schedule_service.update(schedule_id, body)
    except ScheduleValidationError as exc:
        return False, {"ok": False, "message": str(exc)}
    return True, {"ok": True, "schedule": _schedule_to_api_dict(schedule, datetime.now(timezone.utc))}


def cancel_schedule(schedule_id: str) -> "tuple[bool, dict]":
    try:
        schedule = schedule_service.cancel(schedule_id)
    except ScheduleValidationError as exc:
        return False, {"ok": False, "message": str(exc)}
    return True, {"ok": True, "schedule": _schedule_to_api_dict(schedule, datetime.now(timezone.utc))}


def start_schedule_now(schedule_id: str) -> "tuple[bool, dict]":
    ok, message = schedule_engine.start_now(schedule_id)
    return ok, {"ok": ok, "message": message}


def ignore_missed_schedule(schedule_id: str) -> "tuple[bool, dict]":
    ok, message = schedule_engine.ignore_missed(schedule_id)
    return ok, {"ok": ok, "message": message}


# -- historico e busca (Fase E) ----------------------------------------

MEETINGS_PAGE_SIZE_DEFAULT = 20
MEETINGS_PAGE_SIZE_MAX = 100


def get_meetings(query_params: dict) -> dict:
    """GET /api/meetings -- lista paginada, com filtro opcional por
    status e busca de texto (`q`). Nunca varre o filesystem na hora: le
    so o indice SQLite (ver `POST /api/meetings/import` pra atualiza-lo)."""
    try:
        limit = min(MEETINGS_PAGE_SIZE_MAX, max(1, int(query_params.get("limit", [MEETINGS_PAGE_SIZE_DEFAULT])[0])))
    except (ValueError, IndexError):
        limit = MEETINGS_PAGE_SIZE_DEFAULT
    try:
        offset = max(0, int(query_params.get("offset", ["0"])[0]))
    except (ValueError, IndexError):
        offset = 0
    status = (query_params.get("status", [None])[0]) or None
    search = (query_params.get("q", [None])[0]) or None

    if search:
        meetings = meeting_repository.search_meetings(search, limit=limit)
        total = len(meetings)
    else:
        meetings = meeting_repository.list_meetings(limit=limit, offset=offset, status=status)
        total = meeting_repository.count_meetings(status=status)
    return {"meetings": meetings, "total": total, "limit": limit, "offset": offset}


def get_meeting_detail(meeting_id: str) -> "tuple[bool, dict]":
    """GET /api/meetings/<id> -- metadados + segmentos de transcricao do
    indice SQLite. 404 (aqui representado como ok=False) se nunca foi
    importada."""
    try:
        meeting_id = validation.validate_meeting_id(meeting_id)
    except validation.ValidationError as exc:
        return False, {"ok": False, "message": str(exc)}
    meeting = meeting_repository.get_meeting(meeting_id)
    if meeting is None:
        return False, {"ok": False, "message": "Reuniao nao encontrada no indice. Rode a importacao primeiro."}
    segments = meeting_repository.list_segments(meeting_id)
    return True, {"ok": True, "meeting": meeting, "segments": segments}


def import_meetings_now() -> dict:
    """POST /api/meetings/import -- varre todas as raizes conhecidas
    (mesmo `settings.get_known_meeting_roots` usado por recovery, ver
    docs/RECOVERY.md) e (re)importa cada reuniao encontrada pro indice
    SQLite. Idempotente: pode ser chamado quantas vezes o usuario quiser."""
    roots = settings.get_known_meeting_roots(SETTINGS_PATH)
    results = import_all(meeting_repository, roots)
    ok_count = sum(1 for r in results if r.ok)
    failed = [{"meeting_id": r.meeting_id, "message": r.message} for r in results if not r.ok]
    return {
        "ok": True,
        "imported": ok_count,
        "failed": failed,
        "total_scanned": len(results),
    }


def delete_meeting(meeting_id: str) -> "tuple[bool, dict]":
    """POST /api/meetings/<id>/delete -- soft delete APENAS no indice
    (marca `deleted_at`); nunca apaga nenhum arquivo real da reuniao
    (missao, secao E.12: exclusao explicita, nunca destrutiva sem
    confirmacao alem desta propria chamada)."""
    try:
        meeting_id = validation.validate_meeting_id(meeting_id)
    except validation.ValidationError as exc:
        return False, {"ok": False, "message": str(exc)}
    removed = meeting_repository.soft_delete_meeting(meeting_id)
    if not removed:
        return False, {"ok": False, "message": "Reuniao nao encontrada (ou ja excluida) no indice."}
    return True, {"ok": True, "message": "Reuniao removida do historico (arquivos originais preservados)."}


def get_meeting_export(meeting_id: str, fmt: str) -> "tuple[bool, str, str, str]":
    """GET /api/meetings/<id>/export?format=... -- devolve
    (ok, content_type_ou_mensagem_de_erro, corpo, extensao_de_arquivo).
    Nunca gera o nome do arquivo a partir de entrada do cliente (so
    `meeting_id`, ja validado, + extensao fixa da tabela `EXTENSIONS`) --
    elimina qualquer superficie de path traversal no download."""
    try:
        meeting_id = validation.validate_meeting_id(meeting_id)
    except validation.ValidationError as exc:
        return False, str(exc), "", ""
    if fmt not in EXPORT_EXTENSIONS:
        return False, f"Formato invalido. Use um de: {', '.join(sorted(EXPORT_EXTENSIONS))}.", "", ""
    meeting = meeting_repository.get_meeting(meeting_id)
    if meeting is None:
        return False, "Reuniao nao encontrada no indice. Rode a importacao primeiro.", "", ""
    segments = meeting_repository.list_segments(meeting_id)
    body = render_export(fmt, meeting, segments)
    return True, EXPORT_CONTENT_TYPES[fmt], body, EXPORT_EXTENSIONS[fmt]


_RESUME_PATH_RE = re.compile(r"^/api/meetings/([^/]+)/resume$")
_MEETING_DELETE_PATH_RE = re.compile(r"^/api/meetings/([^/]+)/delete$")
_MEETING_EXPORT_PATH_RE = re.compile(r"^/api/meetings/([^/]+)/export$")
_MEETING_ITEM_PATH_RE = re.compile(r"^/api/meetings/([^/]+)$")
_SCHEDULE_ITEM_PATH_RE = re.compile(r"^/api/schedules/([^/]+)$")
_SCHEDULE_ACTION_PATH_RE = re.compile(r"^/api/schedules/([^/]+)/(cancel|start-now|ignore-missed)$")

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

# Origens permitidas a mandar requests que MUDAM estado (POST): o proprio
# painel (producao, servido por esta porta) e o dev server do Vite (Fase
# F, `npm run dev`, proxy configurado em frontend/vite.config.ts). Fixo de
# proposito (missao, secao 10: "nao transformar isto num sistema complexo
# de autenticacao web") -- se o Vite subir noutra porta (ex.: 5173 ja
# ocupada), o proxy do dev server ainda funciona porque o NAVEGADOR nunca
# manda Origin:5174 pro backend: o proxy repassa a request como se fosse
# a mesma origem (ver vite.config.ts, changeOrigin:true).
_ALLOWED_ORIGINS = {
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
}

# Diretorio do build de producao do React (Fase F) -- `npm run build` em
# frontend/. Quando existe, e a interface padrao servida por este painel
# (ver Handler.do_GET); quando nao existe (build nunca rodado), cai pro
# painel legado (ROOT/index.html), que sempre funcionou e continua
# funcionando sem exigir Node/npm no computador de quem so quer usar o app.
FRONTEND_DIST = ROOT / "frontend" / "dist"


def _frontend_build_available() -> bool:
    return (FRONTEND_DIST / "index.html").exists()


class Handler(BaseHTTPRequestHandler):
    """Roteador HTTP minimo: serve o painel (React, se o build existir;
    senao o legado index.html) e as rotas da API. Cada request roda numa
    thread propria (heranca de ThreadingHTTPServer), entao /api/status
    continua respondendo rapido mesmo com uma gravacao em andamento no
    subprocesso."""

    def log_message(self, format, *args):  # noqa: A002 - silencia log padrao no console
        pass

    def _valid_host(self) -> bool:
        # Defesa basica contra DNS rebinding / paginas de outros dominios
        # tentando falar com o servidor local: so aceita Host apontando pra
        # este mesmo endereco. O servidor em si so escuta em 127.0.0.1 (ver
        # main()), nunca em 0.0.0.0 — isso aqui e uma camada extra.
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in _ALLOWED_HOSTS

    def _valid_origin(self) -> bool:
        # Defesa contra CSRF local (missao, secao 10): uma pagina maliciosa
        # aberta em outra aba do MESMO navegador poderia, sem isto, mandar
        # `fetch('http://127.0.0.1:8765/api/stop', {method:'POST', ...})` e
        # abortar uma gravacao em andamento -- Host sozinho nao protege
        # disso (o navegador manda Host:127.0.0.1:8765 normalmente, so
        # Origin revela que a pagina que INICIOU o request e outra).
        # Requests SEM Origin (curl, testes automatizados, algumas
        # ferramentas de desenvolvimento) sao permitidas de proposito --
        # documentado, nao um descuido: navegadores sempre mandam Origin em
        # requests cross-origin/fetch; a ausencia dele aqui tipicamente
        # significa "nao veio de um navegador fazendo fetch", nao uma
        # pagina tentando esconder a origem.
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin in _ALLOWED_ORIGINS

    def _serve_frontend_asset(self, path: str) -> bool:
        """Tenta servir `path` como um arquivo estatico do build React
        (frontend/dist/...). Devolve True se serviu (200) ou recusou por
        path traversal (404), False se simplesmente nao existe esse
        arquivo -- nesse caso quem chama decide o fallback (index.html,
        pro roteamento do lado do cliente funcionar em rotas como
        "/agendamentos" que so existem no React, nunca no disco)."""
        dist_root = FRONTEND_DIST.resolve()
        candidate = (FRONTEND_DIST / path.lstrip("/")).resolve()
        if candidate != dist_root and dist_root not in candidate.parents:
            return False  # tentativa de escapar de frontend/dist (ex.: "/../webui.py")
        if not candidate.is_file():
            return False
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self._serve_file(candidate, content_type)
        return True

    def _serve_app(self, path: str) -> None:
        """Serve tudo que nao e /api/*: build de producao do React quando
        existir (arquivo estatico correspondente, ou index.html como
        fallback de SPA -- rotas como "/agendamentos" nao existem como
        arquivo, o proprio React trata a navegacao no cliente), ou o
        painel legado (ROOT/index.html) quando o build nunca foi gerado.
        Nunca serve nada daqui pra dentro de /api/* -- isso e 404, nao um
        fallback de pagina (evita mascarar uma rota de API digitada errada
        como se fosse uma pagina do React)."""
        if path.startswith("/api/"):
            self.send_error(404)
            return
        if _frontend_build_available():
            if path not in ("", "/") and self._serve_frontend_asset(path):
                return
            self._serve_file(FRONTEND_DIST / "index.html", "text/html; charset=utf-8")
            return
        self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")

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
        parsed = urlsplit(self.path)
        path = parsed.path
        query_params = parse_qs(parsed.query)
        try:
            if path == "/api/status":
                self._send_json(get_status())  # consultado pela pagina a cada 1.5s
            elif path == "/api/recovery":
                self._send_json(get_recovery())
            elif path == "/api/settings":
                self._send_json(get_settings_info())
            elif path == "/api/audio/devices":
                self._send_json(get_audio_devices())
            elif path == "/api/audio/config":
                self._send_json(get_audio_config())
            elif path == "/api/audio/levels":
                self._send_json(get_audio_levels())
            elif path == "/api/audio/levels/stream":
                self._serve_levels_stream()
            elif path == "/api/transcription/live":
                self._send_json(get_live_transcription())
            elif path == "/api/transcription/stream":
                self._serve_transcription_stream()
            elif path == "/api/schedules":
                self._send_json(get_schedules())
            elif path == "/api/meetings":
                self._send_json(get_meetings(query_params))
            elif _MEETING_EXPORT_PATH_RE.match(path):
                match = _MEETING_EXPORT_PATH_RE.match(path)
                fmt = (query_params.get("format", [""])[0]) or "markdown"
                self._serve_export(match.group(1), fmt)
            elif _MEETING_ITEM_PATH_RE.match(path):
                match = _MEETING_ITEM_PATH_RE.match(path)
                ok, payload = get_meeting_detail(match.group(1))
                self._send_json(payload, 200 if ok else 404)
            else:
                # nao e nenhuma rota /api/* conhecida: serve o painel
                # (React se o build existir, senao o legado) -- inclui "/"
                # e qualquer rota de navegacao do lado do cliente do React
                # (ex.: se o usuario recarregar a pagina em "/agendamentos").
                self._serve_app(path)
        except Exception:
            logger.exception("Erro tratando GET %s", self.path)
            self._send_json({"ok": False, "message": "Erro interno no painel."}, 500)

    def do_POST(self):  # noqa: N802
        if not self._valid_host():
            self.send_error(400, "Host invalido")
            return
        if not self._valid_origin():
            self.send_error(403, "Origin nao permitida")
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
            if self.path == "/api/choose-folder":
                self._send_json(choose_meetings_folder())
                return
            if self.path == "/api/settings/meetings-root":
                self._send_json(set_meetings_folder_manual(body.get("path")))
                return
            if self.path == "/api/open-folder":
                ok, msg = open_folder(body.get("path"))
                self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
                return
            if self.path == "/api/audio/config":
                # atualizacao de configuracao: POST, nao PUT, pra ficar
                # consistente com o resto desta API (toda mutacao aqui e
                # POST, ex.: /api/settings/meetings-root) -- ver docs/API.md.
                self._send_json(set_audio_config(body))
                return
            if self.path == "/api/audio/test":
                self._send_json(test_audio(body))
                return
            match = _RESUME_PATH_RE.match(self.path)
            if match:
                ok, msg = resume_meeting(match.group(1))
                self._send_json({"ok": ok, "message": msg}, 200 if ok else 409)
                return
            if self.path == "/api/schedules":
                ok, payload = create_schedule(body)
                self._send_json(payload, 200 if ok else 409)
                return
            match = _SCHEDULE_ACTION_PATH_RE.match(self.path)
            if match:
                schedule_id, action = match.group(1), match.group(2)
                handler = {
                    "cancel": lambda: cancel_schedule(schedule_id),
                    "start-now": lambda: start_schedule_now(schedule_id),
                    "ignore-missed": lambda: ignore_missed_schedule(schedule_id),
                }[action]
                ok, payload = handler()
                self._send_json(payload, 200 if ok else 409)
                return
            match = _SCHEDULE_ITEM_PATH_RE.match(self.path)
            if match:
                ok, payload = update_schedule(match.group(1), body)
                self._send_json(payload, 200 if ok else 409)
                return
            if self.path == "/api/meetings/import":
                self._send_json(import_meetings_now())
                return
            match = _MEETING_DELETE_PATH_RE.match(self.path)
            if match:
                ok, payload = delete_meeting(match.group(1))
                self._send_json(payload, 200 if ok else 404)
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

    def _serve_export(self, meeting_id: str, fmt: str) -> None:
        """GET /api/meetings/<id>/export?format=markdown|txt|json|srt|vtt
        -- gera o arquivo na hora (nunca fica salvo em disco) e devolve
        com `Content-Disposition: attachment` pro navegador baixar."""
        ok, content_type_or_error, body, extension = get_meeting_export(meeting_id, fmt)
        if not ok:
            self._send_json({"ok": False, "message": content_type_or_error}, 404)
            return
        data = body.encode("utf-8")
        filename = f"{meeting_id}.{extension}"
        self.send_response(200)
        self.send_header("Content-Type", content_type_or_error)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_levels_stream(self, interval: float = LEVELS_STREAM_INTERVAL_SECONDS) -> None:
        """GET /api/audio/levels/stream -- Server-Sent Events: um evento
        `data: {...}` sempre que o nivel mudar, checado a cada `interval`
        segundos. Escolhido em vez de polling HTTP comum (a missao pede
        5-15 atualizacoes/s pro medidor, bem mais frequente que os 1.5s de
        `/api/status`) e em vez de WebSocket (o fluxo e so backend->
        frontend; SSE cobre isso com `http.server` puro, sem biblioteca
        nova -- ver docs/API.md pra o raciocinio completo).

        Conexao dedicada e de vida longa: termina sozinha quando o cliente
        desconecta (a proxima escrita falha) ou quando o processo do
        painel encerra. `SinglePortServer.daemon_threads = True` garante
        que uma dessas conexoes nunca impede o servidor de encerrar.
        """
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()

            last_payload = None
            while True:
                payload = json.dumps(get_audio_levels())
                if payload != last_payload:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_payload = payload
                time.sleep(interval)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass  # cliente fechou a conexao -- fim normal do stream, nao um erro

    def _serve_transcription_stream(self, interval: float = TRANSCRIPTION_STREAM_INTERVAL_SECONDS) -> None:
        """GET /api/transcription/stream -- Server-Sent Events com o
        snapshot da transcricao ao vivo (Fase D), mesmo raciocinio de
        `_serve_levels_stream` (SSE em vez de WebSocket/polling comum --
        ver docs/API.md)."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()

            last_payload = None
            while True:
                payload = json.dumps(get_live_transcription())
                if payload != last_payload:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_payload = payload
                time.sleep(interval)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass  # cliente fechou a conexao -- fim normal do stream, nao um erro


class SinglePortServer(ThreadingHTTPServer):
    # Por padrao o http.server liga allow_reuse_address=True, que no
    # Windows deixa VARIOS processos ligarem na mesma porta ao mesmo
    # tempo (em vez de dar erro "porta em uso" como no Linux). Isso faz
    # cada request cair num processo diferente/zumbi de forma aleatoria
    # — sintoma classico: "as vezes funciona, as vezes nao", sem padrao.
    # Desligando aqui, o segundo `python webui.py` falha ao subir em vez
    # de virar um zumbi silencioso.
    allow_reuse_address = False
    # Uma conexao de vida longa (o stream SSE do medidor de audio) nunca
    # pode impedir o servidor de encerrar -- threads daemon morrem junto
    # com o processo principal.
    daemon_threads = True


def main() -> None:
    global MEETINGS_DIR
    try:
        MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # A raiz vem de settings.json e pode apontar pra algo que nao existe
        # mais (disco externo desconectado, permissao mudou, projeto movido
        # de maquina) -- cair de volta pro padrao aqui em vez de deixar o
        # painel inteiro travar na inicializacao por causa disso. Nao
        # sobrescreve settings.json sozinho: se o usuario reconectar o
        # disco, a escolha original continua la para escolher de novo.
        logger.warning(
            "Nao foi possivel usar a pasta de reunioes configurada (%s): %s. "
            "Usando o padrao ate uma nova pasta ser escolhida.",
            MEETINGS_DIR, exc,
        )
        MEETINGS_DIR = settings.default_meetings_root()
        try:
            MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # se ate o padrao falhar, start_transcriber vai recusar com uma mensagem clara

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
    # processo anterior que morreu sem finalizar. Varre TODAS as raizes
    # conhecidas, nao so a ativa (ver docs/RECOVERY.md).
    recovered = []
    for root in settings.get_known_meeting_roots(SETTINGS_PATH):
        if not root.exists():
            continue
        try:
            recovered.extend(mark_interrupted_sessions(root))
        except OSError:
            continue
    for entry in recovered:
        logger.warning(
            "Sessao interrompida detectada: %s (%s) — %d/%d blocos transcritos.",
            entry.get("meeting_id"),
            entry.get("title"),
            entry.get("chunks_transcribed", 0),
            entry.get("chunk_count", 0),
        )

    # Motor do scheduler: mesma ordem/raciocinio da deteccao de recuperacao
    # acima -- so sobe depois de garantir que somos a UNICA instancia do
    # painel (senao duas instancias tentariam disparar a mesma ocorrencia
    # agendada ao mesmo tempo). `.start()` ja roda um tick imediato (Fase
    # C.1, secao 20: recalcula next_run_at/identifica "missed" na hora,
    # sem esperar o primeiro intervalo).
    schedule_engine.start()

    print(f"Painel disponivel em {url} (Ctrl+C aqui encerra o servidor, nao a gravacao).")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        schedule_engine.stop()


if __name__ == "__main__":
    main()
