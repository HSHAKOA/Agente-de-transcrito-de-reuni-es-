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
    monkeypatch.setattr(webui, "MEETINGS_DIR", tmp_path / "data" / "meetings")
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
    ok, msg = webui.start_transcriber({"output": "reuniao.md", "model": "small", "device": "cpu"})
    assert ok, msg
    assert len(_isolated_webui) == 1
    cmd = _isolated_webui[0].args
    assert "--meeting-dir" in cmd
    assert str(webui.ROOT / "reuniao.md") in cmd


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "qualquer_coisa"),
        ("device", "shell"),
        ("chunk_seconds", -1),
        ("chunk_seconds", 999_999_999),
        ("chunk_seconds", "abc"),
        ("title", "x" * 500),
        ("output", "../../arquivo.md"),
        ("output", "..\\..\\arquivo.md"),
        ("output", "C:\\Windows\\teste.md"),
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
    assert "--resume" in _isolated_webui[0].args


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


def test_http_start_with_malicious_output_returns_400_family(live_server):
    payload = json.dumps({"output": "../../../windows/win.ini"}).encode("utf-8")
    status, body = _post(live_server, "/api/start", payload, {"Content-Length": str(len(payload))})
    data = json.loads(body)
    assert data["ok"] is False
    assert status == 409  # start_transcriber trata validacao como falha de negocio, nao erro de protocolo
