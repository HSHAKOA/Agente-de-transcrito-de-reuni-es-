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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import webui
from meeting_transcriber.audio.models import AudioHealthResult


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

    # start_transcriber/test_audio agora testam o(s) dispositivo(s) de
    # audio de verdade antes de prosseguir -- sem isto, cada teste bateria
    # no backend de audio REAL desta maquina. Devolve "saudavel" por
    # padrao; testes especificos de falha de dispositivo sobrescrevem isto.
    def _fake_health(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
        return AudioHealthResult(
            ok=True, code=None, message="OK", device_id=device_id or f"default-{kind}",
            device_name=f"Dispositivo {kind} de teste", level=0.1,
        )

    monkeypatch.setattr(webui.audio_devices, "check_device_health", _fake_health)

    # Fase C.1: schedule_store/service/engine sao construidos uma unica vez
    # na importacao do modulo, apontando pro schedules.json REAL do
    # projeto -- sem isolar aqui, os testes de agendamento vazariam pro
    # disco de verdade (mesmo raciocinio de SETTINGS_PATH/MEETINGS_DIR
    # acima). O engine reaproveita os MESMOS callables `webui._is_recording_
    # active`/etc, que ja leem `webui.state`/`state_lock` dinamicamente --
    # so a persistencia (`ScheduleStore`) e a instancia do engine em si
    # precisam ser trocadas por uma nova, presa ao tmp_path.
    from meeting_transcriber.scheduling.engine import SchedulerEngine
    from meeting_transcriber.scheduling.service import ScheduleService
    from meeting_transcriber.scheduling.store import ScheduleStore

    monkeypatch.setattr(webui, "SCHEDULES_PATH", tmp_path / "data" / "schedules.json")
    test_schedule_store = ScheduleStore(webui.SCHEDULES_PATH)
    monkeypatch.setattr(webui, "schedule_store", test_schedule_store)
    monkeypatch.setattr(webui, "schedule_service", ScheduleService(test_schedule_store))
    monkeypatch.setattr(
        webui,
        "schedule_engine",
        SchedulerEngine(
            test_schedule_store,
            webui.SystemClock(),
            is_recording_active=webui._is_recording_active,
            get_active_meeting_dir=webui._get_active_meeting_dir,
            get_last_exit_ok=webui._get_last_exit_ok,
            start_recording=webui._scheduler_start_recording,
            request_stop=webui._scheduler_request_stop,
            sample_rate=webui.SAMPLE_RATE,
        ),
    )

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


# -- audio (Fase C) ------------------------------------------------------

def test_get_audio_devices_returns_serializable_dtos(_isolated_webui, monkeypatch):
    def _fake_list_devices(backend=None):
        return {
            "inputs": [{"id": "mic-1", "name": "Microfone Falso", "is_default": True}],
            "outputs": [{"id": "spk-1", "name": "Alto-falantes Falsos", "is_default": True, "loopback_supported": True}],
        }

    monkeypatch.setattr(webui.audio_devices, "list_devices", _fake_list_devices)
    result = webui.get_audio_devices()
    assert result["inputs"][0]["id"] == "mic-1"
    assert result["outputs"][0]["loopback_supported"] is True


def test_get_audio_devices_returns_structured_error_on_backend_failure(_isolated_webui, monkeypatch):
    from meeting_transcriber.audio.models import AudioError, AudioErrorCode

    def _boom(backend=None):
        raise AudioError(AudioErrorCode.BACKEND_UNAVAILABLE, "Motor de audio indisponivel.")

    monkeypatch.setattr(webui.audio_devices, "list_devices", _boom)
    result = webui.get_audio_devices()
    assert result["error"]["code"] == AudioErrorCode.BACKEND_UNAVAILABLE


def test_get_audio_config_defaults(_isolated_webui):
    config = webui.get_audio_config()
    assert config == {
        "capture_system": True,
        "capture_microphone": False,
        "system_device_id": None,
        "microphone_device_id": None,
    }


def test_set_audio_config_updates_only_given_fields(_isolated_webui):
    webui.set_audio_config({"capture_microphone": True, "microphone_device_id": "mic-1"})
    config = webui.get_audio_config()
    assert config["capture_microphone"] is True
    assert config["microphone_device_id"] == "mic-1"
    assert config["capture_system"] is True  # nao mexido, continua o padrao


def test_set_audio_config_clears_device_id_with_empty_string(_isolated_webui):
    webui.set_audio_config({"system_device_id": "spk-1"})
    webui.set_audio_config({"system_device_id": ""})
    assert webui.get_audio_config()["system_device_id"] is None


def test_test_audio_refuses_when_no_source_selected(_isolated_webui):
    result = webui.test_audio({"capture_system": False, "capture_microphone": False})
    assert result["ok"] is False


def test_test_audio_refuses_during_active_recording(_isolated_webui):
    webui.start_transcriber({})
    result = webui.test_audio({})
    assert result["ok"] is False
    assert "andamento" in result["message"].lower()


def test_test_audio_returns_results_per_source(_isolated_webui, monkeypatch):
    def _fake_health(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
        return AudioHealthResult(ok=True, code=None, message="OK", device_id=f"{kind}-id", level=0.4)

    monkeypatch.setattr(webui.audio_devices, "check_device_health", _fake_health)
    result = webui.test_audio({"capture_system": True, "capture_microphone": True})
    assert result["ok"] is True
    assert result["results"]["system"]["device_id"] == "output-id"
    assert result["results"]["microphone"]["device_id"] == "input-id"


def test_test_audio_reports_failure_for_unhealthy_device(_isolated_webui, monkeypatch):
    from meeting_transcriber.audio.models import AudioErrorCode

    def _fake_health(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
        return AudioHealthResult(ok=False, code=AudioErrorCode.DEVICE_NOT_FOUND, message="Nao encontrado")

    monkeypatch.setattr(webui.audio_devices, "check_device_health", _fake_health)
    result = webui.test_audio({"capture_system": True, "capture_microphone": False})
    assert result["ok"] is False
    assert result["results"]["system"]["code"] == AudioErrorCode.DEVICE_NOT_FOUND


def test_get_audio_levels_empty_when_not_recording(_isolated_webui):
    assert webui.get_audio_levels() == {}


def test_get_audio_levels_reads_current_meeting_levels_file(_isolated_webui, tmp_path):
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    (meeting_dir / "levels.json").write_text('{"system": {"level": 0.5}}', encoding="utf-8")
    with webui.state_lock:
        webui.state["meeting_dir"] = str(meeting_dir)
    assert webui.get_audio_levels() == {"system": {"level": 0.5}}


def test_get_audio_levels_tolerates_missing_or_malformed_file(_isolated_webui, tmp_path):
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    with webui.state_lock:
        webui.state["meeting_dir"] = str(meeting_dir)
    assert webui.get_audio_levels() == {}  # arquivo nao existe ainda -- nao e erro

    (meeting_dir / "levels.json").write_text("{ nao e json valido", encoding="utf-8")
    assert webui.get_audio_levels() == {}  # escrita atomica no meio -- tambem nao e erro


# -- start_transcriber: fontes de audio -----------------------------------

def test_start_transcriber_rejects_when_no_audio_source_selected(_isolated_webui):
    ok, msg = webui.start_transcriber({"capture_system": False, "capture_microphone": False})
    assert not ok
    assert _isolated_webui == []


def test_start_transcriber_rejects_when_system_health_check_fails(_isolated_webui, monkeypatch):
    from meeting_transcriber.audio.models import AudioErrorCode

    def _unhealthy(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
        return AudioHealthResult(ok=False, code=AudioErrorCode.DEVICE_NOT_FOUND, message="Sumiu")

    monkeypatch.setattr(webui.audio_devices, "check_device_health", _unhealthy)
    ok, msg = webui.start_transcriber({})
    assert not ok
    assert "Sumiu" in msg
    assert _isolated_webui == []


def test_start_transcriber_passes_capture_flags_to_subprocess(_isolated_webui):
    ok, msg = webui.start_transcriber({"capture_system": True, "capture_microphone": True, "microphone_device_id": "mic-9"})
    assert ok, msg
    cmd = _isolated_webui[0].args
    assert "--capture-microphone" in cmd
    assert "--microphone-device" in cmd
    assert "mic-9" in cmd
    assert "--no-capture-system" not in cmd


def test_start_transcriber_passes_no_capture_system_when_disabled(_isolated_webui):
    ok, msg = webui.start_transcriber({"capture_system": False, "capture_microphone": True})
    assert ok, msg
    cmd = _isolated_webui[0].args
    assert "--no-capture-system" in cmd


def test_start_transcriber_persists_audio_preferences(_isolated_webui):
    webui.start_transcriber({"capture_microphone": True, "microphone_device_id": "mic-7"})
    config = webui.get_audio_config()
    assert config["capture_microphone"] is True
    assert config["microphone_device_id"] == "mic-7"


def test_start_transcriber_rejects_oversized_device_id(_isolated_webui):
    ok, msg = webui.start_transcriber({"system_device_id": "x" * 500})
    assert not ok
    assert _isolated_webui == []


def test_start_transcriber_passes_levels_file(_isolated_webui):
    ok, msg = webui.start_transcriber({})
    assert ok, msg
    cmd = _isolated_webui[0].args
    assert "--levels-file" in cmd
    idx = cmd.index("--levels-file")
    assert cmd[idx + 1].endswith("levels.json")


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


# -- agendamento de gravacoes (Fase C.1) -------------------------------------

def _schedule_body(tmp_path, **overrides) -> dict:
    body = dict(
        title="Aula de Calculo",
        scheduled_date=(datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat(),  # perto o
        # suficiente pra cair dentro do horizonte de deteccao de conflito, longe o suficiente pra nunca virar
        # "missed" por acidente entre a criacao do agendamento e o teste rodar
        start_time="19:00",
        end_time="20:40",
        timezone="America/Sao_Paulo",
        meetings_root=str(tmp_path / "Faculdade"),
        system_audio_enabled=True,
        microphone_enabled=False,
    )
    body.update(overrides)
    return body


def test_create_schedule_via_api(_isolated_webui, tmp_path):
    ok, payload = webui.create_schedule(_schedule_body(tmp_path))
    assert ok is True
    assert payload["schedule"]["title"] == "Aula de Calculo"
    assert payload["schedule"]["status"] == "scheduled"


def test_create_schedule_rejects_invalid_body(_isolated_webui, tmp_path):
    ok, payload = webui.create_schedule(_schedule_body(tmp_path, start_time="19:00", end_time="19:00"))
    assert ok is False
    assert payload["ok"] is False


def test_create_schedule_detects_conflict(_isolated_webui, tmp_path):
    webui.create_schedule(_schedule_body(tmp_path, title="A", start_time="19:00", end_time="20:00"))
    ok, payload = webui.create_schedule(_schedule_body(tmp_path, title="B", start_time="19:30", end_time="21:00"))
    assert ok is False
    assert "A" in payload["message"]


def test_get_schedules_lists_created_and_includes_countdown(_isolated_webui, tmp_path):
    webui.create_schedule(_schedule_body(tmp_path))
    result = webui.get_schedules()
    assert len(result["schedules"]) == 1
    entry = result["schedules"][0]
    assert entry["seconds_until_next_run"] is not None
    assert entry["seconds_until_next_run"] > 0


def test_update_schedule_via_api(_isolated_webui, tmp_path):
    ok, payload = webui.create_schedule(_schedule_body(tmp_path))
    schedule_id = payload["schedule"]["id"]
    ok, payload = webui.update_schedule(schedule_id, _schedule_body(tmp_path, title="Novo Titulo"))
    assert ok is True
    assert payload["schedule"]["title"] == "Novo Titulo"


def test_update_unknown_schedule_returns_error(_isolated_webui, tmp_path):
    ok, payload = webui.update_schedule("nao-existe", _schedule_body(tmp_path))
    assert ok is False


def test_cancel_schedule_via_api(_isolated_webui, tmp_path):
    ok, payload = webui.create_schedule(_schedule_body(tmp_path))
    schedule_id = payload["schedule"]["id"]
    ok, payload = webui.cancel_schedule(schedule_id)
    assert ok is True
    assert payload["schedule"]["status"] == "cancelled"


def test_start_schedule_now_via_api(_isolated_webui, tmp_path):
    ok, payload = webui.create_schedule(_schedule_body(tmp_path))
    schedule_id = payload["schedule"]["id"]
    ok, payload = webui.start_schedule_now(schedule_id)
    assert ok is True

    status = webui.get_status()
    assert status["running"] is True


def test_start_schedule_now_refuses_when_manual_recording_active(_isolated_webui, tmp_path):
    webui.start_transcriber({})
    ok, payload = webui.create_schedule(_schedule_body(tmp_path))
    schedule_id = payload["schedule"]["id"]
    ok, payload = webui.start_schedule_now(schedule_id)
    assert ok is False


def test_ignore_missed_schedule_via_api_when_nothing_missed(_isolated_webui, tmp_path):
    ok, payload = webui.create_schedule(_schedule_body(tmp_path))
    schedule_id = payload["schedule"]["id"]
    ok, payload = webui.ignore_missed_schedule(schedule_id)
    assert ok is False


def test_scheduled_recording_uses_its_own_meetings_root_not_the_global_one(_isolated_webui, tmp_path):
    """O agendamento aponta pra uma pasta DIFERENTE da raiz global do
    painel -- start_transcriber precisa respeitar isso, nao gravar na
    MEETINGS_DIR de sempre."""
    schedule_root = tmp_path / "OutraRaizDiferente"
    ok, payload = webui.create_schedule(_schedule_body(tmp_path, meetings_root=str(schedule_root)))
    schedule_id = payload["schedule"]["id"]
    webui.start_schedule_now(schedule_id)

    status = webui.get_status()
    assert status["meeting_dir"].startswith(str(schedule_root))
    assert not status["meeting_dir"].startswith(str(webui.MEETINGS_DIR))


def test_scheduled_start_does_not_overwrite_global_audio_preference(_isolated_webui, tmp_path):
    webui.settings.set_audio_preferences(webui.SETTINGS_PATH, capture_microphone=False)
    ok, payload = webui.create_schedule(_schedule_body(tmp_path, microphone_enabled=True))
    webui.start_schedule_now(payload["schedule"]["id"])

    prefs = webui.settings.get_audio_preferences(webui.SETTINGS_PATH)
    assert prefs["capture_microphone"] is False  # nao foi contaminado pela config do agendamento


def test_schedule_engine_tick_starts_automatically(_isolated_webui, tmp_path, monkeypatch):
    from meeting_transcriber.scheduling.clock import ManualClock

    ok, payload = webui.create_schedule(_schedule_body(tmp_path))
    schedule = webui.schedule_service.get(payload["schedule"]["id"])
    start_at = datetime.fromisoformat(schedule.current_run.scheduled_start_at)

    clock = ManualClock(start_at)
    monkeypatch.setattr(webui.schedule_engine, "_clock", clock)
    webui.schedule_engine.tick_once()

    status = webui.get_status()
    assert status["running"] is True
    loaded = webui.schedule_service.get(schedule.id)
    assert loaded.current_run.status == "recording"
