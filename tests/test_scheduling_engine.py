"""Testes do motor do scheduler -- tudo com `ManualClock` (nunca espera
segundo real nenhum) e dublês para iniciar/parar gravacao e checar saude
de pasta/dispositivo, seguindo o mesmo padrao de dublês do resto do
projeto (ver audio/devices.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from meeting_transcriber.audio.models import AudioError, AudioErrorCode, AudioHealthResult
from meeting_transcriber.scheduling.clock import ManualClock
from meeting_transcriber.scheduling.engine import SchedulerEngine
from meeting_transcriber.scheduling.models import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_FINISHING,
    STATUS_MISSED,
    STATUS_PREPARING,
    STATUS_RECORDING,
    STATUS_SCHEDULED,
    Recurrence,
    RECURRENCE_DAILY,
    Schedule,
)
from meeting_transcriber.scheduling.store import ScheduleStore
from meeting_transcriber.validation import FolderHealth


class FakeBackend:
    """Dublê do lado "producao real" que o engine chama pra ligar/desligar
    gravacao. `request_stop()` NAO desliga sozinho -- so `finish()` (chamado
    pelo teste) simula o subprocesso realmente terminando, permitindo
    observar o estado intermediario FINISHING (missao, secao 9: nunca pula
    direto pra "completed" sem passar pelo shutdown gracioso)."""

    def __init__(self):
        self.active = False
        self.meeting_dir = None
        self.last_exit_ok = True
        self.start_calls = []
        self.stop_calls = 0
        self.fail_start_message = None
        self._seq = 0

    def is_recording_active(self):
        return self.active

    def get_active_meeting_dir(self):
        return self.meeting_dir

    def get_last_exit_ok(self):
        return self.last_exit_ok

    def start_recording(self, opts):
        self.start_calls.append(opts)
        if self.fail_start_message:
            return False, self.fail_start_message
        self._seq += 1
        self.active = True
        self.meeting_dir = str(Path(opts["meetings_root"]) / f"meeting_{self._seq}")
        return True, "Gravacao iniciada."

    def request_stop(self):
        self.stop_calls += 1
        return True, "Parando..."

    def finish(self, exit_ok=True):
        self.active = False
        self.meeting_dir = None
        self.last_exit_ok = exit_ok


def _ok_folder_health(path):
    return FolderHealth(True, "OK", free_bytes=10**9)


def _failing_folder_health(path):
    return FolderHealth(False, f"A pasta “{path}” nao existe.")


def _ok_device_health(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
    return AudioHealthResult(ok=True, code=None, message="OK", device_id=device_id, level=0.1)


def _failing_device_health(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
    return AudioHealthResult(ok=False, code="AUDIO_DEVICE_NOT_FOUND", message="Microfone USB nao encontrado.")


def _schedule(tmp_path: Path, **overrides) -> Schedule:
    defaults = dict(
        id="sch_1",
        title="Aula de Calculo",
        scheduled_date="2026-09-15",
        start_time="19:00",
        end_time="20:40",
        timezone="America/Sao_Paulo",
        meetings_root=str(tmp_path / "Faculdade"),
        system_audio_enabled=True,
        microphone_enabled=False,
        recurrence=Recurrence(),
    )
    defaults.update(overrides)
    return Schedule(**defaults)


START_UTC = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)  # 19:00 America/Sao_Paulo
END_UTC = datetime(2026, 9, 15, 23, 40, tzinfo=timezone.utc)  # 20:40 America/Sao_Paulo


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


def _make_engine(tmp_path: Path, clock: ManualClock, backend: FakeBackend, **kwargs) -> SchedulerEngine:
    store = ScheduleStore(tmp_path / "schedules.json")
    return SchedulerEngine(
        store,
        clock,
        is_recording_active=backend.is_recording_active,
        get_active_meeting_dir=backend.get_active_meeting_dir,
        get_last_exit_ok=backend.get_last_exit_ok,
        start_recording=backend.start_recording,
        request_stop=backend.request_stop,
        sample_rate=16000,
        check_folder_health=kwargs.pop("check_folder_health", _ok_folder_health),
        check_device_health=kwargs.pop("check_device_health", _ok_device_health),
        **kwargs,
    )


# -- start automatico / stop automatico -------------------------------------

def test_automatic_start_at_scheduled_time(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC - timedelta(minutes=10))
    engine = _make_engine(tmp_path, clock, backend)
    schedule = _schedule(tmp_path)
    engine._store.save(schedule)

    engine.tick_once()
    assert backend.start_calls == []  # ainda nao chegou a hora

    clock.set(START_UTC)
    engine.tick_once()

    assert len(backend.start_calls) == 1
    assert backend.start_calls[0]["title"] == "Aula de Calculo"
    assert backend.start_calls[0]["meetings_root"] == str(tmp_path / "Faculdade")
    loaded = engine._store.get("sch_1")
    assert loaded.status == STATUS_RECORDING
    assert loaded.current_run.status == STATUS_RECORDING
    assert loaded.current_run.meeting_id == "meeting_1"


def test_automatic_stop_uses_graceful_request_never_kill(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    assert backend.active is True

    clock.set(END_UTC)
    engine.tick_once()

    assert backend.stop_calls == 1
    assert backend.active is True  # ainda "gravando" ate o backend confirmar o fim (shutdown gracioso, nao kill)
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.status == STATUS_FINISHING

    backend.finish(exit_ok=True)
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    assert loaded.current_run is None
    assert loaded.history[-1].status == STATUS_COMPLETED
    assert loaded.history[-1].ended_early is False


def test_recurring_schedule_returns_to_scheduled_after_completion(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path, recurrence=Recurrence(type=RECURRENCE_DAILY)))
    engine.tick_once()
    clock.set(END_UTC)
    engine.tick_once()
    backend.finish()
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    assert loaded.status == STATUS_SCHEDULED
    assert loaded.current_run is not None
    assert loaded.current_run.occurrence_date == "2026-09-16"


def test_double_execution_is_prevented_for_same_occurrence(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    assert len(backend.start_calls) == 1

    # varios ticks a mais, ainda dentro da janela de gravacao -- nunca tenta
    # comecar de novo a MESMA ocorrencia so porque ainda esta "scheduled"
    # aparentemente (na pratica ja esta RECORDING, entao nem caberia, mas
    # este teste garante que nenhum caminho de codigo tenta de novo).
    for _ in range(5):
        clock.advance(seconds=30)
        engine.tick_once()
    assert len(backend.start_calls) == 1


# -- preflight -----------------------------------------------------------

def test_preflight_runs_within_lead_window_and_marks_preparing(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC - timedelta(minutes=4))
    engine = _make_engine(tmp_path, clock, backend, preflight_lead_seconds=5 * 60)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    assert loaded.status == STATUS_PREPARING
    assert loaded.current_run.preflight["ok"] is True


def test_preflight_reports_device_failure_without_blocking_status_change(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC - timedelta(minutes=4))
    engine = _make_engine(tmp_path, clock, backend, check_device_health=_failing_device_health)
    engine._store.save(_schedule(tmp_path, microphone_enabled=True, microphone_device_id="mic-x"))
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    assert loaded.current_run.preflight["ok"] is False
    assert "Microfone USB" in loaded.current_run.preflight["message"]


# -- falha de storage / dispositivo bloqueando o inicio -----------------

def test_missing_folder_blocks_start_and_eventually_fails(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(
        tmp_path, clock, backend, check_folder_health=_failing_folder_health, missed_tolerance_seconds=60
    )
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    assert backend.start_calls == []
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.status == STATUS_SCHEDULED  # ainda tentando, dentro da tolerancia
    assert loaded.current_run.error_message

    clock.advance(seconds=61)
    engine.tick_once()
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.status == STATUS_FAILED
    assert loaded.status == STATUS_FAILED


def test_device_disappearing_blocks_start_with_clear_error(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend, check_device_health=_failing_device_health)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()

    assert backend.start_calls == []
    loaded = engine._store.get("sch_1")
    assert "nao encontrado" in loaded.current_run.error_message


def test_device_reconnecting_within_tolerance_still_starts(tmp_path: Path, backend: FakeBackend):
    calls = {"n": 0}

    def _flaky_device_health(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return AudioHealthResult(ok=False, code="AUDIO_DEVICE_NOT_FOUND", message="Indisponivel.")
        return AudioHealthResult(ok=True, code=None, message="OK", device_id=device_id)

    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend, check_device_health=_flaky_device_health)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    assert backend.start_calls == []

    clock.advance(seconds=20)
    engine.tick_once()
    assert len(backend.start_calls) == 1
    assert engine._store.get("sch_1").current_run.status == STATUS_RECORDING


# -- missed ---------------------------------------------------------------

def test_missed_when_app_opens_late(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC + timedelta(minutes=17))
    engine = _make_engine(tmp_path, clock, backend, missed_tolerance_seconds=60)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()

    assert backend.start_calls == []
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.status == STATUS_MISSED
    assert loaded.status == STATUS_MISSED
    assert "19:00" in loaded.current_run.error_message


def test_missed_within_tolerance_still_starts(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC + timedelta(seconds=30))
    engine = _make_engine(tmp_path, clock, backend, missed_tolerance_seconds=60)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()

    assert len(backend.start_calls) == 1
    assert engine._store.get("sch_1").current_run.status == STATUS_RECORDING


def test_start_now_resolves_missed(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC + timedelta(minutes=17))
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    assert engine._store.get("sch_1").current_run.status == STATUS_MISSED

    ok, message = engine.start_now("sch_1")
    assert ok is True
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.status == STATUS_RECORDING
    assert loaded.current_run.started_manually_early is True


def test_start_now_refuses_after_window_fully_passed(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(END_UTC + timedelta(minutes=1))
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()  # "once" ja passou inteiro -- resolvido pro historico como missed, sem ocorrencia futura

    ok, message = engine.start_now("sch_1")
    assert ok is False
    loaded = engine._store.get("sch_1")
    assert loaded.history[-1].status == STATUS_MISSED
    assert backend.start_calls == []


def test_start_now_refuses_when_current_run_window_already_elapsed(tmp_path: Path, backend: FakeBackend):
    """Corrida estreita: `current_run` ainda nao foi resolvido pro historico
    (o proximo tick ainda nao rodou), mas o relogio ja passou do fim da
    janela -- `start_now` precisa recusar sozinho, sem depender de um tick
    ter acontecido antes."""
    from meeting_transcriber.scheduling.models import ScheduleRun

    clock = ManualClock(END_UTC + timedelta(minutes=1))
    engine = _make_engine(tmp_path, clock, backend)
    schedule = _schedule(tmp_path)
    schedule.current_run = ScheduleRun(
        occurrence_date="2026-09-15",
        scheduled_start_at=START_UTC.isoformat(),
        scheduled_end_at=END_UTC.isoformat(),
        status=STATUS_SCHEDULED,
    )
    engine._store.save(schedule)

    ok, message = engine.start_now("sch_1")
    assert ok is False
    assert "nao e mais possivel" in message.lower()
    assert backend.start_calls == []


# Mensagens que citam um horario usam o fuso do AGENDAMENTO, nunca o do
# computador que roda o app. Duas zonas com offsets diferentes (-3 e +9)
# garantem que o teste nunca passa por coincidencia com o fuso da maquina
# onde roda -- o CI roda em UTC, o desenvolvimento em America/Sao_Paulo, e
# esta regressao so foi pega justamente por essa diferenca.
_ZONE_CASES = [
    (
        "America/Sao_Paulo",
        datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc),  # 19:00 local
        datetime(2026, 9, 15, 23, 40, tzinfo=timezone.utc),  # 20:40 local
    ),
    (
        "Asia/Tokyo",
        datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),  # 19:00 local
        datetime(2026, 9, 15, 11, 40, tzinfo=timezone.utc),  # 20:40 local
    ),
]


@pytest.mark.parametrize("tz_name,start_utc,end_utc", _ZONE_CASES)
def test_missed_message_uses_schedule_timezone_not_host_timezone(
    tmp_path: Path, backend: FakeBackend, tz_name, start_utc, end_utc
):
    clock = ManualClock(start_utc + timedelta(minutes=17))
    engine = _make_engine(tmp_path, clock, backend, missed_tolerance_seconds=60)
    engine._store.save(_schedule(tmp_path, timezone=tz_name))
    engine.tick_once()

    message = engine._store.get("sch_1").current_run.error_message
    assert "19:00" in message


@pytest.mark.parametrize("tz_name,start_utc,end_utc", _ZONE_CASES)
def test_start_now_elapsed_window_message_uses_schedule_timezone(
    tmp_path: Path, backend: FakeBackend, tz_name, start_utc, end_utc
):
    from meeting_transcriber.scheduling.models import ScheduleRun

    clock = ManualClock(end_utc + timedelta(minutes=1))
    engine = _make_engine(tmp_path, clock, backend)
    schedule = _schedule(tmp_path, timezone=tz_name)
    schedule.current_run = ScheduleRun(
        occurrence_date="2026-09-15",
        scheduled_start_at=start_utc.isoformat(),
        scheduled_end_at=end_utc.isoformat(),
        status=STATUS_SCHEDULED,
    )
    engine._store.save(schedule)

    ok, message = engine.start_now("sch_1")
    assert ok is False
    assert "20:40" in message


def test_ignore_missed_advances_recurring_schedule(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC + timedelta(minutes=17))
    engine = _make_engine(tmp_path, clock, backend, missed_tolerance_seconds=60)
    engine._store.save(_schedule(tmp_path, recurrence=Recurrence(type=RECURRENCE_DAILY)))
    engine.tick_once()
    assert engine._store.get("sch_1").current_run.status == STATUS_MISSED

    ok, _ = engine.ignore_missed("sch_1")
    assert ok is True
    engine.tick_once()
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.occurrence_date == "2026-09-16"


def test_ignore_missed_refuses_when_nothing_missed(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC - timedelta(hours=1))
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    ok, _ = engine.ignore_missed("sch_1")
    assert ok is False


# -- iniciar/parar manualmente -------------------------------------------

def test_start_now_before_scheduled_time(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC - timedelta(minutes=8))
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))

    ok, message = engine.start_now("sch_1")
    assert ok is True
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.status == STATUS_RECORDING
    assert loaded.current_run.started_manually_early is True

    # o disparo automatico nao pode tentar de novo quando bater 19:00
    clock.set(START_UTC)
    engine.tick_once()
    assert len(backend.start_calls) == 1


def test_manual_stop_before_end_marks_ended_early(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    assert backend.active is True

    # usuario clica "Parar" manualmente, bem antes do end_at -- simulado
    # aqui como o backend simplesmente terminando por conta propria (o
    # engine so tem visibilidade via is_recording_active/get_last_exit_ok,
    # igual teria no motor rodando de verdade dentro do webui.py).
    clock.advance(minutes=10)
    backend.finish(exit_ok=True)
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    assert backend.stop_calls == 0  # o engine NAO foi quem pediu a parada
    assert loaded.history[-1].ended_early is True
    assert loaded.history[-1].status == STATUS_COMPLETED


def test_early_stop_does_not_restart_within_original_window(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()
    clock.advance(minutes=10)
    backend.finish(exit_ok=True)
    engine.tick_once()
    assert len(backend.start_calls) == 1

    # ainda dentro do horario original (19:00-20:40) -- uma reuniao "once"
    # ja completada nao pode comecar de novo so porque ainda estamos na
    # mesma janela de tempo.
    clock.advance(minutes=20)
    engine.tick_once()
    assert len(backend.start_calls) == 1


def test_crash_marks_failed_not_completed(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()

    clock.advance(minutes=5)
    backend.finish(exit_ok=False)
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    assert loaded.history[-1].status == STATUS_FAILED
    assert loaded.history[-1].ended_early is True


# -- concorrencia: uma sessao ativa por aplicacao -------------------------

def test_does_not_start_when_another_recording_already_active(tmp_path: Path, backend: FakeBackend):
    backend.active = True  # alguem ja gravando manualmente, fora do scheduler
    backend.meeting_dir = str(tmp_path / "outra")

    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend, missed_tolerance_seconds=60)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()

    assert backend.start_calls == []
    loaded = engine._store.get("sch_1")
    assert "andamento" in loaded.current_run.error_message

    clock.advance(seconds=61)
    engine.tick_once()
    loaded = engine._store.get("sch_1")
    assert loaded.current_run.status == STATUS_FAILED


# -- restart do backend / relogio mudando -------------------------------

def test_restart_recomputes_state_from_persisted_store(tmp_path: Path, backend: FakeBackend):
    clock = ManualClock(START_UTC - timedelta(minutes=10))
    engine1 = _make_engine(tmp_path, clock, backend)
    engine1._store.save(_schedule(tmp_path))
    engine1.tick_once()

    # "reinicia o backend": uma NOVA instancia do engine, mesmo store em
    # disco, sem nenhum estado em memoria herdado da instancia anterior.
    clock2 = ManualClock(START_UTC)
    engine2 = SchedulerEngine(
        ScheduleStore(tmp_path / "schedules.json"),
        clock2,
        is_recording_active=backend.is_recording_active,
        get_active_meeting_dir=backend.get_active_meeting_dir,
        get_last_exit_ok=backend.get_last_exit_ok,
        start_recording=backend.start_recording,
        request_stop=backend.request_stop,
        sample_rate=16000,
        check_folder_health=_ok_folder_health,
        check_device_health=_ok_device_health,
    )
    engine2.tick_once()
    assert len(backend.start_calls) == 1
    assert engine2._store.get("sch_1").current_run.status == STATUS_RECORDING


def test_clock_jump_forward_does_not_crash_and_resolves_missed(tmp_path: Path, backend: FakeBackend):
    """Simula o computador voltando de suspensao/hibernacao: o relogio salta
    horas de uma vez (nunca um sleep() que soma segundos reais)."""
    clock = ManualClock(START_UTC - timedelta(minutes=1))
    engine = _make_engine(tmp_path, clock, backend, missed_tolerance_seconds=60)
    engine._store.save(_schedule(tmp_path))
    engine.tick_once()

    clock.advance(hours=5)  # salto abrupto -- nada de sleep incremental
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    assert loaded.history[-1].status == STATUS_MISSED
    assert backend.start_calls == []


# -- o preflight nunca pode derrubar o tick ---------------------------------
#
# Regressao de um incidente real (21/09/2026): o painel subiu num interpretador
# sem `soundcard`, `check_device_health` passou a levantar AudioError, o
# preflight morreu no meio, `tick_once` engoliu a excecao (nada foi salvo no
# agendamento) e 60 s depois a aula virou "missed" com a mensagem generica
# "O aplicativo nao estava disponivel naquele horario" -- falso: o app estava
# aberto e tentando. A causa real so existia num log de terminal.


def _raising_device_health(exc):
    def _probe(kind, device_id, samplerate, probe_seconds=0.3, backend=None):
        raise exc

    return _probe


def test_audio_backend_error_at_preflight_fails_with_the_real_cause(tmp_path: Path, backend: FakeBackend):
    """AudioError na sonda vira veredito de preflight, nao excecao solta."""
    clock = ManualClock(START_UTC)
    engine = _make_engine(
        tmp_path,
        clock,
        backend,
        missed_tolerance_seconds=60,
        check_device_health=_raising_device_health(
            AudioError(AudioErrorCode.BACKEND_UNAVAILABLE, "O motor de audio nao esta disponivel neste momento.")
        ),
    )
    engine._store.save(_schedule(tmp_path))

    engine.tick_once()  # horario de inicio: tenta iniciar e reprova no preflight
    run = engine._store.get("sch_1").current_run
    assert backend.start_calls == []  # nunca grava com o backend quebrado
    assert "O motor de audio nao esta disponivel" in (run.error_message or "")

    clock.advance(seconds=120)  # passa da tolerancia de "missed"
    engine.tick_once()

    loaded = engine._store.get("sch_1")
    run = loaded.current_run or loaded.history[-1]
    # o ponto da regressao: FAILED com a causa verdadeira, nunca MISSED
    assert run.status == STATUS_FAILED
    assert "O motor de audio nao esta disponivel" in run.error_message
    assert "nao estava disponivel naquele horario" not in run.error_message


def test_unexpected_probe_crash_becomes_preflight_problem(tmp_path: Path, backend: FakeBackend):
    """Qualquer excecao da sonda (driver, bug de terceiro) vira veredito."""
    clock = ManualClock(START_UTC)
    engine = _make_engine(
        tmp_path,
        clock,
        backend,
        check_device_health=_raising_device_health(RuntimeError("driver explodiu")),
    )
    engine._store.save(_schedule(tmp_path))

    engine.tick_once()

    run = engine._store.get("sch_1").current_run
    assert backend.start_calls == []
    assert "Audio do computador" in run.error_message
    assert "driver explodiu" in run.error_message


def test_folder_check_oserror_becomes_preflight_problem(tmp_path: Path, backend: FakeBackend):
    """Disco removido entre o mkdir e a checagem nao derruba o tick."""

    def _exploding_folder_health(path):
        raise OSError("dispositivo nao esta pronto")

    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend, check_folder_health=_exploding_folder_health)
    engine._store.save(_schedule(tmp_path))

    engine.tick_once()

    run = engine._store.get("sch_1").current_run
    assert backend.start_calls == []
    assert "dispositivo nao esta pronto" in run.error_message


# -- banco de fusos ausente (tzdata) ----------------------------------------


def test_missing_timezone_database_marks_schedule_failed_with_real_cause(
    tmp_path: Path, backend: FakeBackend
):
    """Mesmo incidente, segundo sintoma: sem `tzdata` o `next_occurrence`
    estoura em TODO tick e o agendamento fica permanentemente inerte, sem
    nenhum sinal na interface. Um nome de fuso que nao resolve reproduz
    exatamente o que o `zoneinfo` faz quando a base de fusos nao existe."""
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path, timezone="Zona/Inexistente"))

    engine.tick_once()  # nao pode propagar excecao

    loaded = engine._store.get("sch_1")
    assert loaded.status == STATUS_FAILED
    assert loaded.next_run_at is None  # nunca prometer um horario que nao vai disparar
    assert backend.start_calls == []


def test_missing_timezone_database_is_recorded_only_once(tmp_path: Path, backend: FakeBackend):
    """Nao reescreve schedules.json a cada tick (20 s) enquanto a dependencia
    estiver faltando -- o erro e persistente, o registro e uma vez so."""
    clock = ManualClock(START_UTC)
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path, timezone="Zona/Inexistente"))

    saves = []
    original_save = engine._store.save

    def _counting_save(schedule):
        saves.append(schedule.id)
        return original_save(schedule)

    engine._store.save = _counting_save

    engine.tick_once()
    first = len(saves)
    engine.tick_once()
    engine.tick_once()

    assert first == 1
    assert len(saves) == 1  # ticks seguintes nao regravam nada


def test_schedule_recovers_when_the_timezone_database_comes_back(tmp_path: Path, backend: FakeBackend):
    """`is_open()` so exclui `cancelled`, entao reinstalar a dependencia faz o
    agendamento voltar sozinho -- sem exigir recadastro."""
    clock = ManualClock(START_UTC - timedelta(minutes=10))
    engine = _make_engine(tmp_path, clock, backend)
    engine._store.save(_schedule(tmp_path, timezone="Zona/Inexistente"))
    engine.tick_once()
    assert engine._store.get("sch_1").status == STATUS_FAILED

    repaired = engine._store.get("sch_1")
    repaired.timezone = "America/Sao_Paulo"  # dependencia reinstalada
    engine._store.save(repaired)

    engine.tick_once()
    clock.set(START_UTC)
    engine.tick_once()

    assert len(backend.start_calls) == 1
    assert engine._store.get("sch_1").current_run.status == STATUS_RECORDING
