"""Testes do painel local (webui.py): validacao de entrada, hardening HTTP,
e o escalonamento de shutdown gracioso.

Nada aqui sobe um processo real de gravacao (isso exigiria hardware de
audio) nem usa a porta 8765 de verdade (evita qualquer interferencia com uma
sessao real que porventura esteja rodando na maquina de quem roda os
testes) -- subprocess.Popen e substituido por um dublê em memoria, e os
testes HTTP sobem o servidor numa porta efemera (porta 0).
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from pathlib import Path

import pytest

import webui


class FakePopen:
    """Dublê de subprocess.Popen: sem processo de verdade, sem tocar audio.

    Fica "vivo" (poll()/wait() bloqueado, como um processo real ainda
    rodando) ate `finish()` ser chamado -- essencial pros testes de
    concorrencia/estado, senao a thread leitora do webui.py detectaria o
    "processo" como morto quase instantaneamente (stdout vazio) e o estado
    voltaria a "parado" antes do teste conseguir observar "em andamento".
    """

    def __init__(self, cmd, ignore_terminate: bool = False, **kwargs):
        self.args = cmd
        self.returncode = None
        self._done = threading.Event()
        self.signals_received = []
        self.terminated = False
        self.killed = False
        self.ignore_terminate = ignore_terminate  # simula um processo que nao responde a terminate()

    @property
    def stdout(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        self._done.wait()
        raise StopIteration

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._done.wait(timeout)
        if self.returncode is None and self._done.is_set():
            self.returncode = 0
        return self.returncode

    def send_signal(self, sig):
        if self.returncode is None:
            self.signals_received.append(sig)

    def terminate(self):
        self.terminated = True
        if not self.ignore_terminate:
            self.finish(0)

    def kill(self):
        self.killed = True
        self.finish(-9)

    def finish(self, code: int = 0) -> None:
        if self.returncode is None:
            self.returncode = code
        self._done.set()


@pytest.fixture(autouse=True)
def _isolated_webui(tmp_path, monkeypatch):
    """Isola webui.py do disco real e do processo real: ROOT/MEETINGS_DIR
    apontam pra um tmp_path novo a cada teste, subprocess.Popen nunca sobe
    um processo de verdade, e o estado global e resetado."""
    monkeypatch.setattr(webui, "ROOT", tmp_path)
    monkeypatch.setattr(webui, "SETTINGS_PATH", tmp_path / "data" / "settings.json")
    monkeypatch.setattr(webui, "MEETINGS_DIR", tmp_path / "data" / "meetings")
    # recovery/resume agora derivam as raizes conhecidas de settings.json
    # (nao so do valor de MEETINGS_DIR em memoria) -- mantem os dois em
    # sincronia aqui do mesmo jeito que _apply_new_meetings_root faz em
    # producao, senao os testes acabam varrendo a pasta Documentos/Reunioes
    # REAL da maquina em vez do tmp_path isolado.
    webui.settings.set_meetings_root(webui.SETTINGS_PATH, webui.MEETINGS_DIR)
    (tmp_path / ".venv").mkdir()  # start_transcriber exige isso existir

    created_procs = []

    def _fake_popen(cmd, **kwargs):
        proc = FakePopen(cmd, **kwargs)
        created_procs.append(proc)
        return proc

    monkeypatch.setattr(webui.subprocess, "Popen", _fake_popen)

    with webui.state_lock:
        webui.state.update(
            proc=None,
            log=webui.deque(maxlen=1000),
            output=None,
            chunk_seconds=300,
            meeting_dir=None,
            started_at=None,
            finished_at=None,
            exit_code=None,
        )

    yield created_procs

    for proc in created_procs:
        proc.finish(0)  # libera qualquer thread leitora ainda bloqueada em stdout


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# -- start_transcriber: validacao ------------------------------------------

def test_start_transcriber_happy_path(_isolated_webui):
    ok, msg = webui.start_transcriber({"title": "Reuniao de teste", "model": "small", "device": "cpu"})
    assert ok, msg
    assert len(_isolated_webui) == 1
    cmd = _isolated_webui[0].args
    assert "--meeting-dir" in cmd
    output_index = cmd.index("--output") + 1
    output_path = Path(cmd[output_index])
    assert output_path.name == "transcript.md"
    assert webui.MEETINGS_DIR.resolve() in output_path.parents


def test_start_transcriber_creates_meetings_root_when_missing(_isolated_webui, tmp_path):
    webui.MEETINGS_DIR = tmp_path / "nao-existe-ainda" / "Reunioes"
    assert not webui.MEETINGS_DIR.exists()

    ok, msg = webui.start_transcriber({})

    assert ok, msg
    assert webui.MEETINGS_DIR.exists()


def test_start_transcriber_rejects_when_meetings_root_is_a_file(_isolated_webui, tmp_path):
    blocked = tmp_path / "isto-e-um-arquivo"
    blocked.write_text("x", encoding="utf-8")
    webui.MEETINGS_DIR = blocked

    ok, msg = webui.start_transcriber({})

    assert not ok
    assert _isolated_webui == []


def test_start_transcriber_ignores_client_supplied_output_field(_isolated_webui):
    """O campo "output" nao e mais lido: a superficie de path traversal que
    existia nele foi eliminada por construcao (nao so validada) -- o nome
    do arquivo final e sempre transcript.md dentro da pasta da propria
    reuniao, nunca importa o que o cliente mande em "output"."""
    ok, msg = webui.start_transcriber({"output": "../../../windows/win.ini"})

    assert ok, msg
    cmd = _isolated_webui[0].args
    output_index = cmd.index("--output") + 1
    output_path = Path(cmd[output_index])
    assert output_path.name == "transcript.md"
    assert webui.MEETINGS_DIR.resolve() in output_path.parents
    assert "win.ini" not in str(output_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "qualquer_coisa"),
        ("device", "shell"),
        ("chunk_seconds", -1),
        ("chunk_seconds", 999_999_999),
        ("chunk_seconds", "abc"),
        ("title", "x" * 500),
        ("language", "pt; DROP TABLE"),
    ],
)
def test_start_transcriber_rejects_bad_input(_isolated_webui, field, value):
    ok, msg = webui.start_transcriber({field: value})
    assert not ok
    assert msg
    assert _isolated_webui == []  # nenhum subprocesso deve ter sido lancado


def test_start_transcriber_rejects_when_already_running(_isolated_webui):
    ok1, _ = webui.start_transcriber({})
    assert ok1
    ok2, msg2 = webui.start_transcriber({})
    assert not ok2
    assert "andamento" in msg2.lower()
    assert len(_isolated_webui) == 1  # o segundo start nao chegou a subir processo


def test_start_start_concurrent_only_one_wins(_isolated_webui):
    results = []

    def _attempt():
        results.append(webui.start_transcriber({}))

    threads = [threading.Thread(target=_attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    successes = [r for r in results if r[0]]
    assert len(successes) == 1
    assert len(_isolated_webui) == 1


def test_start_transcriber_missing_venv(tmp_path, monkeypatch):
    # sem o fixture autouse criar .venv desta vez -- simula instalacao incompleta
    other = tmp_path / "sem_venv"
    other.mkdir()
    monkeypatch.setattr(webui, "ROOT", other)
    monkeypatch.setattr(webui, "MEETINGS_DIR", other / "data" / "meetings")
    ok, msg = webui.start_transcriber({})
    assert not ok
    assert ".venv" in msg


# -- stop_transcriber / shutdown_sequence -----------------------------------

def test_stop_transcriber_when_nothing_running(_isolated_webui):
    ok, msg = webui.stop_transcriber()
    assert not ok
    assert "nenhuma" in msg.lower()


def test_stop_transcriber_sends_graceful_signal_first(_isolated_webui, monkeypatch):
    webui.start_transcriber({})
    proc = _isolated_webui[0]
    # substitui o escalonamento de verdade por uma versao instantanea, so
    # queremos confirmar QUE ele foi acionado com o processo certo
    calls = []
    monkeypatch.setattr(webui, "shutdown_sequence", lambda p, **kw: calls.append(p))

    ok, msg = webui.stop_transcriber()
    assert ok
    assert _wait_for(lambda: len(calls) == 1)
    assert calls[0] is proc


def test_shutdown_sequence_graceful_success_does_not_escalate():
    proc = FakePopen(["x"])

    def _sleep(_):
        proc.returncode = 0  # processo "morre" logo apos o sinal gracioso

    stage = webui.shutdown_sequence(proc, graceful_signal=99, sleep_fn=_sleep, poll_interval=0.01)

    assert stage == "graceful"
    assert proc.signals_received == [99]
    assert not proc.terminated
    assert not proc.killed


def test_shutdown_sequence_escalates_to_terminate(monkeypatch):
    proc = FakePopen(["x"])
    calls = {"n": 0}

    def _sleep(_):
        calls["n"] += 1
        if proc.terminated:
            proc.returncode = 0  # so morre depois do terminate()

    stage = webui.shutdown_sequence(
        proc, graceful_signal=99, graceful_timeout=0.05, terminate_timeout=1.0, sleep_fn=_sleep, poll_interval=0.01
    )

    assert stage == "terminate"
    assert proc.terminated
    assert not proc.killed


def test_shutdown_sequence_escalates_to_kill_as_last_resort():
    proc = FakePopen(["x"], ignore_terminate=True)  # nunca "morre" sozinho -> forca ate o kill()

    stage = webui.shutdown_sequence(
        proc, graceful_signal=99, graceful_timeout=0.02, terminate_timeout=0.02, sleep_fn=lambda _: None, poll_interval=0.01
    )

    assert stage == "kill"
    assert proc.terminated
    assert proc.killed


def test_stop_stop_concurrent_does_not_crash(_isolated_webui, monkeypatch):
    webui.start_transcriber({})
    monkeypatch.setattr(webui, "shutdown_sequence", lambda p, **kw: "graceful")

    results = []
    threads = [threading.Thread(target=lambda: results.append(webui.stop_transcriber())) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # nenhuma excecao propagada (threads teriam sido interrompidas silenciosamente
    # se .join nao completasse); todas devem ver o processo como "em andamento"
    assert all(ok for ok, _ in results)


# -- resume_meeting -----------------------------------------------------

def test_resume_meeting_rejects_invalid_id(_isolated_webui):
    ok, msg = webui.resume_meeting("../../etc")
    assert not ok
    assert _isolated_webui == []


def test_resume_meeting_rejects_unknown_session(_isolated_webui):
    ok, msg = webui.resume_meeting("20260101-000000-abcdef")
    assert not ok
    assert "nao encontrada" in msg.lower() or "invalida" in msg.lower()


def test_resume_meeting_launches_subprocess_for_known_session(_isolated_webui):
    meeting_dir = webui.MEETINGS_DIR / "20260101-000000-abcdef"
    meeting_dir.mkdir(parents=True)
    (meeting_dir / "state.json").write_text("{}", encoding="utf-8")

    ok, msg = webui.resume_meeting("20260101-000000-abcdef")
    assert ok, msg
    assert len(_isolated_webui) == 1


# -- recovery multi-root (Fase B.1) --------------------------------------

def test_get_recovery_scans_all_known_roots_not_just_active_one(_isolated_webui, tmp_path):
    from meeting_transcriber.session import MeetingSession

    old_root = tmp_path / "RaizAntiga"
    new_root = tmp_path / "RaizNova"

    # simula: usuario gravou em old_root, depois trocou pra new_root
    webui.settings.set_meetings_root(webui.SETTINGS_PATH, old_root)
    stuck_in_old_root = MeetingSession.create(
        base_dir=old_root, title="Deixada pra tras", model="small", language="pt", device="cpu"
    )
    stuck_in_old_root.mark_recording()
    from meeting_transcriber.session import mark_interrupted_sessions

    mark_interrupted_sessions(old_root)

    webui.settings.set_meetings_root(webui.SETTINGS_PATH, new_root)
    webui.MEETINGS_DIR = new_root  # troca a raiz ativa, como start_transcriber/_apply_new_meetings_root fariam

    recovery = webui.get_recovery()
    titles = {s["title"] for s in recovery["sessions"]}
    assert "Deixada pra tras" in titles


def test_resume_meeting_finds_session_left_in_previous_root(_isolated_webui, tmp_path, monkeypatch):
    from meeting_transcriber.session import MeetingSession, mark_interrupted_sessions

    old_root = tmp_path / "RaizAntiga"
    new_root = tmp_path / "RaizNova"

    webui.settings.set_meetings_root(webui.SETTINGS_PATH, old_root)
    session = MeetingSession.create(
        base_dir=old_root, title="Deixada pra tras", model="small", language="pt", device="cpu",
        meeting_id="20260101-000000-ffffff",
    )
    session.mark_recording()  # grava o pid real deste processo de teste
    mark_interrupted_sessions(old_root)

    webui.settings.set_meetings_root(webui.SETTINGS_PATH, new_root)
    webui.MEETINGS_DIR = new_root
    # este teste e sobre achar a sessao em outra raiz, nao sobre a
    # checagem de PID (coberta em testes dedicados abaixo) -- sem isto, o
    # PID real do processo de teste (que esta genuinamente rodando)
    # dispararia a recusa de seguranca.
    monkeypatch.setattr(webui, "is_pid_running", lambda pid: False)

    ok, msg = webui.resume_meeting("20260101-000000-ffffff")
    assert ok, msg
    cmd = _isolated_webui[0].args
    assert str(session.meeting_dir) in cmd


# -- resume PID safety net (Fase B.1: falhar fechado, sem adotar processo) --

def test_resume_meeting_refuses_when_recorded_pid_still_running(_isolated_webui, monkeypatch):
    from meeting_transcriber.session import MeetingSession

    session = MeetingSession.create(
        base_dir=webui.MEETINGS_DIR, title="T", model="small", language="pt", device="cpu",
        meeting_id="20260101-000000-111111",
    )
    session.mark_recording()  # grava um pid de verdade (o deste processo de teste)

    monkeypatch.setattr(webui, "is_pid_running", lambda pid: True)

    ok, msg = webui.resume_meeting("20260101-000000-111111")

    assert not ok
    assert "PID" in msg
    assert _isolated_webui == []  # nenhum subprocesso de reprocessamento foi iniciado


def test_resume_meeting_allows_when_recorded_pid_not_running(_isolated_webui, monkeypatch):
    from meeting_transcriber.session import MeetingSession

    session = MeetingSession.create(
        base_dir=webui.MEETINGS_DIR, title="T", model="small", language="pt", device="cpu",
        meeting_id="20260101-000000-222222",
    )
    session.mark_recording()

    monkeypatch.setattr(webui, "is_pid_running", lambda pid: False)

    ok, msg = webui.resume_meeting("20260101-000000-222222")

    assert ok, msg


def test_resume_meeting_allows_when_pid_liveness_cannot_be_determined(_isolated_webui, monkeypatch):
    """None significa "nao sei dizer" (ex.: plataforma nao suportada) --
    isso NAO pode bloquear o reprocessamento para sempre."""
    from meeting_transcriber.session import MeetingSession

    session = MeetingSession.create(
        base_dir=webui.MEETINGS_DIR, title="T", model="small", language="pt", device="cpu",
        meeting_id="20260101-000000-333333",
    )
    session.mark_recording()

    monkeypatch.setattr(webui, "is_pid_running", lambda pid: None)

    ok, msg = webui.resume_meeting("20260101-000000-333333")

    assert ok, msg
    assert "--resume" in _isolated_webui[0].args


# -- pasta de reunioes (settings, dialogo nativo, abrir pasta) --------------

def test_get_settings_info_reports_current_root(_isolated_webui):
    webui.MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    info = webui.get_settings_info()
    assert info["meetings_root"] == str(webui.MEETINGS_DIR)
    assert info["free_bytes"] is not None
    assert isinstance(info["folder_dialog_available"], bool)


def test_get_settings_info_free_bytes_none_when_root_missing(_isolated_webui):
    info = webui.get_settings_info()
    assert info["free_bytes"] is None


def test_choose_meetings_folder_persists_valid_selection(_isolated_webui, monkeypatch, tmp_path):
    chosen_dir = tmp_path / "Escolhida"
    monkeypatch.setattr(webui.folder_dialog, "pick_directory", lambda initial_dir=None: str(chosen_dir))

    result = webui.choose_meetings_folder()

    assert result["ok"] is True
    assert result["cancelled"] is False
    assert webui.MEETINGS_DIR == chosen_dir.resolve()
    from meeting_transcriber import settings as settings_module

    assert settings_module.get_meetings_root(webui.SETTINGS_PATH) == chosen_dir.resolve()


def test_choose_meetings_folder_reports_cancellation_without_error(_isolated_webui, monkeypatch):
    monkeypatch.setattr(webui.folder_dialog, "pick_directory", lambda initial_dir=None: None)
    previous_root = webui.MEETINGS_DIR

    result = webui.choose_meetings_folder()

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert webui.MEETINGS_DIR == previous_root  # nao mudou nada


def test_choose_meetings_folder_rejects_unhealthy_selection(_isolated_webui, monkeypatch, tmp_path):
    blocked_file = tmp_path / "arquivo-nao-pasta"
    blocked_file.write_text("x", encoding="utf-8")
    # aponta o "dialogo" pro pai do arquivo, mas simula que o usuario de
    # alguma forma escolheu o proprio arquivo (pick_directory devolvendo
    # um caminho que nao e pasta) -- check_folder_health precisa recusar
    monkeypatch.setattr(webui.folder_dialog, "pick_directory", lambda initial_dir=None: str(blocked_file))
    previous_root = webui.MEETINGS_DIR

    result = webui.choose_meetings_folder()

    assert result["ok"] is False
    assert result["cancelled"] is False
    assert webui.MEETINGS_DIR == previous_root


def test_choose_meetings_folder_refuses_while_recording(_isolated_webui, monkeypatch, tmp_path):
    webui.start_transcriber({})
    monkeypatch.setattr(webui.folder_dialog, "pick_directory", lambda initial_dir=None: str(tmp_path / "Outra"))

    result = webui.choose_meetings_folder()

    assert result["ok"] is False
    assert "andamento" in result["message"].lower()


def test_set_meetings_folder_manual_validates_and_persists(_isolated_webui, tmp_path):
    new_root = tmp_path / "Digitada"
    result = webui.set_meetings_folder_manual(str(new_root))
    assert result["ok"] is True
    assert webui.MEETINGS_DIR == new_root.resolve()


def test_set_meetings_folder_manual_rejects_empty_string(_isolated_webui):
    result = webui.set_meetings_folder_manual("")
    assert result["ok"] is False


def test_open_folder_opens_path_within_meetings_root(_isolated_webui, monkeypatch):
    webui.MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    calls = []
    monkeypatch.setattr(webui.os, "startfile", lambda p: calls.append(p), raising=False)
    monkeypatch.setattr(webui.sys, "platform", "win32")

    ok, msg = webui.open_folder(str(webui.MEETINGS_DIR))

    assert ok, msg
    assert calls == [str(webui.MEETINGS_DIR)]


def test_open_folder_rejects_path_outside_meetings_root(_isolated_webui, tmp_path):
    outside = tmp_path.parent  # garantidamente fora de MEETINGS_DIR
    ok, msg = webui.open_folder(str(outside))
    assert not ok


def test_open_folder_rejects_missing_path(_isolated_webui):
    ok, msg = webui.open_folder(str(webui.MEETINGS_DIR / "nao-existe"))
    assert not ok


def test_open_folder_rejects_invalid_input(_isolated_webui):
    for bad in (None, "", 123, []):
        ok, _ = webui.open_folder(bad)
        assert not ok


# -- get_status / get_recovery -----------------------------------------------

def test_get_status_when_idle(_isolated_webui):
    status = webui.get_status()
    assert status["running"] is False


def test_get_recovery_lists_only_interrupted(_isolated_webui):
    from meeting_transcriber.session import MeetingSession

    webui.MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    stuck = MeetingSession.create(base_dir=webui.MEETINGS_DIR, title="Presa", model="small", language="pt", device="cpu")
    stuck.mark_recording()
    done = MeetingSession.create(base_dir=webui.MEETINGS_DIR, title="Ok", model="small", language="pt", device="cpu")
    done.mark_recording()
    done.mark_completed()

    from meeting_transcriber.session import mark_interrupted_sessions

    mark_interrupted_sessions(webui.MEETINGS_DIR)

    recovery = webui.get_recovery()
    titles = {s["title"] for s in recovery["sessions"]}
    assert titles == {"Presa"}


# -- main(): ordem de deteccao de recuperacao --------------------------------

def test_main_does_not_scan_recovery_when_port_already_taken(_isolated_webui, monkeypatch):
    """Regressao: se outra instancia do painel ja estiver rodando (porta
    ocupada -- cenario normal quando ha uma gravacao real em andamento),
    main() NAO pode rodar mark_interrupted_sessions. Rodar antes de saber se
    somos a unica instancia marcaria a sessao alheia, que esta perfeitamente
    ativa, como "interrompida" so por estar em status recording/processing."""
    monkeypatch.setattr(webui.webbrowser, "open", lambda url: None)
    calls = []
    monkeypatch.setattr(webui, "mark_interrupted_sessions", lambda base_dir: calls.append(base_dir) or [])

    class _AlwaysBusyServer:
        def __init__(self, *a, **k):
            raise OSError("port in use (simulado)")

    monkeypatch.setattr(webui, "SinglePortServer", _AlwaysBusyServer)

    webui.main()

    assert calls == []


def test_main_falls_back_to_default_root_when_configured_root_unusable(_isolated_webui, monkeypatch, tmp_path):
    """settings.json pode apontar pra uma pasta que nao existe mais (disco
    externo desconectado, permissao mudou, projeto movido de maquina) --
    main() nao pode travar o painel inteiro por causa disso."""
    unusable = tmp_path / "arquivo-no-lugar-de-pasta"
    unusable.write_text("x", encoding="utf-8")  # mkdir() aqui sempre falha (ja existe como arquivo)
    webui.MEETINGS_DIR = unusable

    fallback = tmp_path / "PadraoDeFallback"
    monkeypatch.setattr(webui.settings, "default_meetings_root", lambda: fallback)
    monkeypatch.setattr(webui.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(webui, "mark_interrupted_sessions", lambda base_dir: [])

    class _FakeServer:
        def __init__(self, *a, **k):
            pass

        def serve_forever(self):
            pass

    monkeypatch.setattr(webui, "SinglePortServer", _FakeServer)

    webui.main()  # nao pode levantar excecao

    assert webui.MEETINGS_DIR == fallback
    assert fallback.exists()


def test_main_scans_recovery_only_after_binding_port(_isolated_webui, monkeypatch):
    monkeypatch.setattr(webui.webbrowser, "open", lambda url: None)
    calls = []
    monkeypatch.setattr(webui, "mark_interrupted_sessions", lambda base_dir: calls.append(base_dir) or [])

    class _FakeServer:
        def __init__(self, *a, **k):
            pass

        def serve_forever(self):
            pass  # nao bloqueia o teste

    monkeypatch.setattr(webui, "SinglePortServer", _FakeServer)

    webui.main()

    assert calls == [webui.MEETINGS_DIR]


# -- HTTP hardening (servidor real numa porta efemera) -----------------------

@pytest.fixture
def live_server(_isolated_webui):
    server = webui.SinglePortServer(("127.0.0.1", 0), webui.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(port, path, body_bytes, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", path, body=body_bytes, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        conn.close()


def test_http_rejects_invalid_json(live_server):
    status, body = _post(live_server, "/api/start", b"{not valid json", {"Content-Length": "15"})
    assert status == 400


def test_http_rejects_non_object_json(live_server):
    payload = json.dumps([1, 2, 3]).encode("utf-8")
    status, body = _post(live_server, "/api/start", payload, {"Content-Length": str(len(payload))})
    assert status == 400


def test_http_rejects_oversized_body(live_server):
    huge = b"x" * (webui.MAX_BODY_BYTES + 1)
    status, _ = _post(live_server, "/api/start", huge, {"Content-Length": str(len(huge))})
    assert status == 413


def test_http_rejects_unknown_route(live_server):
    status, _ = _post(live_server, "/api/does-not-exist", b"{}", {"Content-Length": "2"})
    assert status == 404


def test_http_rejects_bad_host_header(live_server):
    conn = http.client.HTTPConnection("127.0.0.1", live_server, timeout=5)
    try:
        conn.putrequest("GET", "/api/status", skip_host=True)
        conn.putheader("Host", "evil.example.com")
        conn.endheaders()
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 400
    finally:
        conn.close()


def test_http_get_settings_route(live_server):
    conn = http.client.HTTPConnection("127.0.0.1", live_server, timeout=5)
    conn.request("GET", "/api/settings")
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    assert resp.status == 200
    assert "meetings_root" in data


def test_http_settings_meetings_root_route(live_server, tmp_path):
    new_root = tmp_path / "PastaViaHTTP"
    payload = json.dumps({"path": str(new_root)}).encode("utf-8")
    status, body = _post(live_server, "/api/settings/meetings-root", payload, {"Content-Length": str(len(payload))})
    data = json.loads(body)
    assert status == 200
    assert data["ok"] is True
    assert data["meetings_root"] == str(new_root.resolve())


def test_http_choose_folder_route(live_server, monkeypatch, tmp_path):
    chosen = tmp_path / "EscolhidaViaHTTP"
    monkeypatch.setattr(webui.folder_dialog, "pick_directory", lambda initial_dir=None: str(chosen))
    status, body = _post(live_server, "/api/choose-folder", b"{}", {"Content-Length": "2"})
    data = json.loads(body)
    assert status == 200
    assert data["ok"] is True
    assert data["meetings_root"] == str(chosen.resolve())


def test_http_open_folder_route_rejects_outside_root(live_server, tmp_path):
    payload = json.dumps({"path": str(tmp_path.parent)}).encode("utf-8")
    status, body = _post(live_server, "/api/open-folder", payload, {"Content-Length": str(len(payload))})
    data = json.loads(body)
    assert status == 409
    assert data["ok"] is False


def test_http_start_then_status_reports_running(live_server):
    payload = json.dumps({"output": "reuniao.md"}).encode("utf-8")
    status, body = _post(live_server, "/api/start", payload, {"Content-Length": str(len(payload))})
    assert status == 200
    assert json.loads(body)["ok"] is True

    conn = http.client.HTTPConnection("127.0.0.1", live_server, timeout=5)
    conn.request("GET", "/api/status")
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    assert data["running"] is True


def test_http_start_with_malicious_output_field_has_no_effect(live_server):
    """O campo "output" nao existe mais no contrato da API -- um valor de
    path traversal nele e simplesmente ignorado (200 OK, arquivo real fica
    em transcript.md dentro da pasta da reuniao), nao "rejeitado com 400"
    porque nao ha mais nada pra rejeitar: a superficie foi removida."""
    payload = json.dumps({"output": "../../../windows/win.ini"}).encode("utf-8")
    status, body = _post(live_server, "/api/start", payload, {"Content-Length": str(len(payload))})
    data = json.loads(body)
    assert status == 200
    assert data["ok"] is True
