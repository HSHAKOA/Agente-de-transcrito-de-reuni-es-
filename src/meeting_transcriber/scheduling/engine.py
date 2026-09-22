"""Motor do scheduler: le agendamentos periodicamente e faz as transicoes
automaticas (preflight, inicio, fim gracioso, deteccao de "missed") --
missao, secoes 7-13, 20, 21.

Desenho central: `tick_once()` faz UMA passada por todos os agendamentos
abertos, comparando timestamps ABSOLUTOS (UTC) contra `clock.now()`. Nunca
agenda um `threading.Timer`/`sleep()` calculado com base na duracao ate o
proximo evento -- isso e exatamente o que a missao pede pra evitar (secao
21: mudanca de relogio, horario de verao, suspensao do computador quebram
qualquer timer calculado uma vez so). `tick_once()` e chamado repetidamente
por uma thread de background em producao (`start()`), mas os testes chamam
`tick_once()` diretamente com um `ManualClock`, sem esperar nenhum segundo
de verdade.

Todas as dependencias externas (iniciar/parar gravacao, checar saude de
pasta/dispositivo, saber se ha uma gravacao ativa) sao injetadas como
callables -- o motor inteiro e testavel com dublês, igual ao resto do
projeto (ver `audio/devices.py`, `recorder.py`).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .. import validation as base_validation
from ..audio import devices as audio_devices
from ..audio.models import AudioError, AudioHealthResult
from .clock import Clock
from .models import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_FINISHING,
    STATUS_MISSED,
    STATUS_PREPARING,
    STATUS_RECORDING,
    STATUS_SCHEDULED,
    Schedule,
    ScheduleRun,
    TERMINAL_RUN_STATUSES,
)
from .recurrence import InvalidTimeZone, next_occurrence, to_schedule_zone
from .store import ScheduleStore

logger = logging.getLogger("meeting_transcriber.scheduling")

DEFAULT_TICK_INTERVAL_SECONDS = 20.0
DEFAULT_PREFLIGHT_LEAD_SECONDS = 5 * 60.0
DEFAULT_MISSED_TOLERANCE_SECONDS = 60.0
_MAX_STEPS_PER_TICK = 500  # protecao contra loop infinito em caso de bug; ver `_tick_schedule`


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _now_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="microseconds")


class SchedulerEngine:
    def __init__(
        self,
        store: ScheduleStore,
        clock: Clock,
        *,
        is_recording_active: Callable[[], bool],
        get_active_meeting_dir: Callable[[], Optional[str]],
        get_last_exit_ok: Callable[[], Optional[bool]],
        start_recording: Callable[[dict], "tuple[bool, str]"],
        request_stop: Callable[[], "tuple[bool, str]"],
        sample_rate: int,
        check_folder_health=base_validation.check_folder_health,
        check_device_health=audio_devices.check_device_health,
        tick_interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS,
        preflight_lead_seconds: float = DEFAULT_PREFLIGHT_LEAD_SECONDS,
        missed_tolerance_seconds: float = DEFAULT_MISSED_TOLERANCE_SECONDS,
    ):
        self._store = store
        self._clock = clock
        self._is_recording_active = is_recording_active
        self._get_active_meeting_dir = get_active_meeting_dir
        self._get_last_exit_ok = get_last_exit_ok
        self._start_recording = start_recording
        self._request_stop = request_stop
        self._sample_rate = sample_rate
        self._check_folder_health = check_folder_health
        self._check_device_health = check_device_health
        self._tick_interval = tick_interval_seconds
        self._preflight_lead = timedelta(seconds=preflight_lead_seconds)
        self._missed_tolerance = timedelta(seconds=missed_tolerance_seconds)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- ciclo de vida da thread de background ------------------------------

    def start(self) -> None:
        """Sobe a thread de background e roda um tick imediatamente (missao,
        secao 20: reinicializacao precisa recalcular next_run_at/identificar
        missed/proximas reunioes SEM depender de esperar o primeiro
        intervalo) -- nunca depende de timers criados numa sessao anterior."""
        if self._thread is not None:
            return
        self.tick_once()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="scheduler-engine")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self._tick_interval):
            try:
                self.tick_once()
            except Exception:
                logger.exception("Erro inesperado no loop do scheduler.")

    # -- API publica usada por acoes manuais (webui.py) ---------------------

    def tick_once(self) -> None:
        now = self._clock.now()
        for schedule in self._store.list_all():
            if not schedule.is_open():
                continue
            try:
                self._tick_schedule(schedule, now)
            except InvalidTimeZone as exc:
                self._mark_timezone_unusable(schedule, exc)
            except Exception:
                logger.exception("Erro processando o agendamento %s", schedule.id)

    def start_now(self, schedule_id: str) -> "tuple[bool, str]":
        """Inicia manualmente a proxima ocorrencia deste agendamento, mesmo
        antes do horario previsto (secao 11) ou apos ela ter sido marcada
        'missed' (secao 12). Nunca inicia se a janela ja tiver terminado."""
        schedule = self._store.get(schedule_id)
        if schedule is None:
            return False, "Agendamento nao encontrado."
        if not schedule.is_open():
            return False, "Agendamento cancelado."

        now = self._clock.now()
        if schedule.current_run is None or schedule.current_run.status in TERMINAL_RUN_STATUSES:
            if not self._claim_next_occurrence(schedule, now):
                self._store.save(schedule)
                return False, "Nao ha nenhuma ocorrencia futura para iniciar."

        run = schedule.current_run
        end_at = _parse_iso(run.scheduled_end_at)
        if run.status in (STATUS_RECORDING, STATUS_FINISHING):
            return False, "Esta gravacao ja esta em andamento."
        if now >= end_at:
            self._store.save(schedule)
            return False, (
                f"A janela agendada terminaria as {to_schedule_zone(end_at, schedule.timezone).strftime('%H:%M')}; "
                "nao e mais possivel iniciar esta ocorrencia."
            )
        if self._is_recording_active():
            return False, "Ja existe uma gravacao em andamento (manual ou de outro agendamento)."

        ok, message = self._try_start(schedule, run, now, manual=True)
        self._store.save(schedule)
        return ok, message

    def ignore_missed(self, schedule_id: str) -> "tuple[bool, str]":
        schedule = self._store.get(schedule_id)
        if schedule is None:
            return False, "Agendamento nao encontrado."
        run = schedule.current_run
        if run is None or run.status not in (STATUS_MISSED, STATUS_FAILED):
            return False, "Nao ha uma ocorrencia perdida/com falha pendente para este agendamento."
        schedule.push_history(run)
        schedule.current_run = None
        schedule.status = STATUS_SCHEDULED
        self._store.save(schedule)
        return True, "Ocorrencia perdida descartada."

    # -- maquina de estados interna ------------------------------------------

    def _mark_timezone_unusable(self, schedule: Schedule, exc: InvalidTimeZone) -> None:
        """O nome do fuso e validado no CADASTRO (`scheduling/validation.py`),
        entao chegar aqui significa que o banco de fusos sumiu do ambiente
        DEPOIS: no Windows `zoneinfo` nao tem base propria e depende do pacote
        `tzdata` (requirements.txt). Sem tratar, `next_occurrence` estoura em
        todo tick, o `except Exception` acima engole, e o agendamento fica
        permanentemente inerte sem nenhum sinal na interface -- aconteceu de
        verdade (ver docs/SCHEDULING.md). Registra a causa REAL uma unica vez;
        `is_open()` continua True, entao o agendamento volta a funcionar
        sozinho assim que a dependencia for reinstalada."""
        message = (
            f"Nao foi possivel resolver o fuso “{schedule.timezone}” nesta instalacao. "
            "No Windows o banco de fusos vem do pacote tzdata "
            "(pip install -r requirements.txt). Este agendamento nao vai "
            "disparar enquanto isso nao for corrigido."
        )
        run = schedule.current_run
        if schedule.status == STATUS_FAILED and (run is None or run.error_message == message):
            return  # ja registrado -- nao reescreve o arquivo a cada tick
        if run is not None:
            run.status = STATUS_FAILED
            run.error_message = message
        schedule.status = STATUS_FAILED
        # `next_run_at` ficaria apontando pra um horario que comprovadamente
        # NAO vai disparar -- mentira visivel na tela de Agendamentos. Quando a
        # dependencia voltar, `_claim_next_occurrence` recalcula.
        schedule.next_run_at = None
        self._store.save(schedule)
        logger.error("Agendamento %s: %s (%s)", schedule.id, message, exc)

    def _tick_schedule(self, schedule: Schedule, now: datetime) -> None:
        for _ in range(_MAX_STEPS_PER_TICK):
            if not self._process_schedule_step(schedule, now):
                return
        logger.error("Agendamento %s excedeu o limite de transicoes num unico tick; possivel loop.", schedule.id)

    def _process_schedule_step(self, schedule: Schedule, now: datetime) -> bool:
        """Processa UMA transicao possivel. Devolve True se algo mudou de um
        jeito que pode habilitar OUTRA transicao imediata (ex.: reclamar uma
        ocorrencia atrasada que ja nasce expirada) -- nesse caso
        `_tick_schedule` chama de novo, ainda dentro do mesmo tick. Devolve
        False quando so resta esperar o proximo tick de verdade."""
        if schedule.current_run is None or schedule.current_run.status in TERMINAL_RUN_STATUSES:
            claimed = self._claim_next_occurrence(schedule, now)
            self._store.save(schedule)
            return claimed

        run = schedule.current_run
        start_at = _parse_iso(run.scheduled_start_at)
        end_at = _parse_iso(run.scheduled_end_at)

        if run.status in (STATUS_SCHEDULED, STATUS_PREPARING, STATUS_MISSED, STATUS_FAILED):
            if run.actual_start_at is None and now >= end_at:
                # a janela inteira passou sem nunca ter comecado a gravar --
                # vira historico e libera a proxima ocorrencia. Distingue
                # MISSED (o app nem chegou a tentar -- estava fechado) de
                # FAILED (tentou, mas preflight/inicio real falhou -- ver
                # `_try_start`, que so preenche `error_message` quando ha
                # uma tentativa de verdade): a missao pede uma mensagem
                # clara e um status distinto pra falha de storage/audio,
                # nunca so "perdido" como se o app estivesse fechado.
                run.status = STATUS_FAILED if run.error_message else STATUS_MISSED
                run.error_message = run.error_message or "A janela agendada terminou antes da gravacao comecar."
                schedule.push_history(run)
                schedule.current_run = None
                schedule.status = STATUS_SCHEDULED
                self._store.save(schedule)
                return True

            if run.status not in (STATUS_MISSED, STATUS_FAILED) and now > start_at + self._missed_tolerance:
                run.status = STATUS_FAILED if run.error_message else STATUS_MISSED
                run.error_message = run.error_message or (
                    f"Esta gravacao estava programada para comecar as "
                    f"{to_schedule_zone(start_at, schedule.timezone).strftime('%H:%M')}. "
                    "O aplicativo nao estava disponivel naquele horario."
                )
                schedule.status = run.status
                self._store.save(schedule)
                return False  # fica acionavel (start_now/ignore_missed) ate a janela terminar

            if run.status in (STATUS_MISSED, STATUS_FAILED):
                return False  # nunca reinicia sozinho depois disso -- exige acao do usuario

            if now < start_at:
                if now >= start_at - self._preflight_lead:
                    run.preflight = self._check_readiness(schedule)
                    run.status = STATUS_PREPARING
                    schedule.status = STATUS_PREPARING
                    self._store.save(schedule)
                return False

            # now esta em [start_at, start_at + tolerancia] -- tenta iniciar
            self._try_start(schedule, run, now, manual=False)
            self._store.save(schedule)
            return False

        if run.status == STATUS_RECORDING:
            if now >= end_at and self._is_recording_active():
                self._request_stop()
                run.status = STATUS_FINISHING
                self._store.save(schedule)
                return False
            if not self._is_recording_active():
                self._finalize_run(schedule, run, now, ended_early=(now < end_at))
                return True
            return False

        if run.status == STATUS_FINISHING:
            if not self._is_recording_active():
                self._finalize_run(schedule, run, now, ended_early=False)
                return True
            return False

        return False  # estados terminais ja tratados no topo desta funcao

    def _claim_next_occurrence(self, schedule: Schedule, now: datetime) -> bool:
        search_after = self._last_consumed_start(schedule)
        occ = next_occurrence(schedule, after=search_after)
        if occ is None:
            schedule.next_run_at = None
            if schedule.status not in (STATUS_CANCELLED,):
                schedule.status = STATUS_SCHEDULED
            return False
        schedule.current_run = ScheduleRun(
            occurrence_date=occ.occurrence_date.isoformat(),
            scheduled_start_at=occ.start_at.isoformat(),
            scheduled_end_at=occ.end_at.isoformat(),
            status=STATUS_SCHEDULED,
        )
        schedule.next_run_at = occ.start_at.isoformat()
        schedule.status = STATUS_SCHEDULED
        return True

    @staticmethod
    def _last_consumed_start(schedule: Schedule) -> datetime:
        """Ponto de partida da busca pela proxima ocorrencia: logo depois do
        inicio da ultima ocorrencia ja registrada em `history` (resolvida,
        tenha ela gravado ou nao) -- nunca reprocessa a mesma ocorrencia
        duas vezes (missao, secao 20: "dupla execucao impedida")."""
        if not schedule.history:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        latest = max(_parse_iso(r.scheduled_start_at) for r in schedule.history)
        return latest + timedelta(seconds=1)

    def _try_start(self, schedule: Schedule, run: ScheduleRun, now: datetime, manual: bool) -> "tuple[bool, str]":
        if not manual and self._is_recording_active():
            run.error_message = "Outra gravacao ja estava em andamento no horario programado."
            return False, run.error_message

        readiness = self._check_readiness(schedule)
        run.preflight = readiness
        if not readiness["ok"]:
            run.error_message = readiness["message"]
            return False, readiness["message"]

        ok, message = self._start_recording(self._build_start_opts(schedule))
        if not ok:
            run.error_message = message
            return False, message

        meeting_dir = self._get_active_meeting_dir()
        run.status = STATUS_RECORDING
        run.actual_start_at = _now_iso(now)
        run.meeting_dir = meeting_dir
        run.meeting_id = Path(meeting_dir).name if meeting_dir else None
        run.error_message = None
        run.started_manually_early = manual
        schedule.status = STATUS_RECORDING
        schedule.last_run_at = _now_iso(now)
        return True, "Gravacao iniciada."

    def _finalize_run(self, schedule: Schedule, run: ScheduleRun, now: datetime, ended_early: bool) -> None:
        exit_ok = self._get_last_exit_ok()
        run.actual_end_at = _now_iso(now)
        run.ended_early = ended_early
        if exit_ok is False:
            run.status = STATUS_FAILED
            run.error_message = run.error_message or "O processo de gravacao terminou com um erro (ver log)."
        else:
            run.status = STATUS_COMPLETED
        schedule.push_history(run)
        schedule.current_run = None
        schedule.status = STATUS_SCHEDULED

    def _check_readiness(self, schedule: Schedule) -> dict:
        problems = []
        root = Path(schedule.meetings_root)
        try:
            # mesmo passo que start_transcriber ja faz pro inicio manual --
            # sem isto, um agendamento apontando pra uma pasta ainda nunca
            # usada (ex.: "D:\Reunioes\Faculdade" antes da primeira aula)
            # reprovaria pra sempre no preflight, mesmo sendo perfeitamente
            # possivel cria-la na hora.
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            problems.append(f"Nao foi possivel criar a pasta “{root}”: {exc}")
        else:
            try:
                folder_result = self._check_folder_health(root)
            except OSError as exc:
                # disco removido/rede caida entre o mkdir e a checagem
                problems.append(f"Nao foi possivel checar a pasta “{root}”: {exc}")
            else:
                if not folder_result.ok:
                    problems.append(folder_result.message)
        if schedule.system_audio_enabled:
            problems.extend(self._probe_device("output", "Audio do computador", schedule.system_device_id))
        if schedule.microphone_enabled:
            problems.extend(self._probe_device("input", "Microfone", schedule.microphone_device_id))
        return {"ok": not problems, "message": " ".join(problems) if problems else "READY"}

    def _probe_device(self, kind: str, label: str, device_id: Optional[str]) -> "list[str]":
        """Sonda um dispositivo e devolve os problemas encontrados (lista vazia
        = saudavel). NUNCA propaga excecao, e isso e o ponto: `check_device_health`
        levanta `AudioError` quando o backend de audio nao esta disponivel
        (`soundcard` ausente, driver quebrado). Propagando, o preflight morre no
        meio, `tick_once` engole o erro, NADA e salvo no agendamento e 60 s
        depois a ocorrencia vira "missed" com a mensagem generica de aplicativo
        fechado -- apontando o usuario para a causa errada enquanto a real fica
        so num log de terminal. Transformando em veredito, `_try_start` marca a
        ocorrencia como FAILED com a causa verdadeira (ver a distincao
        MISSED x FAILED em `_process_schedule_step`)."""
        try:
            health: AudioHealthResult = self._check_device_health(kind, device_id, self._sample_rate)
        except AudioError as exc:
            return [f"{label}: {exc.message}"]
        except Exception as exc:  # noqa: BLE001 -- vira veredito, nunca silencio
            logger.exception("Falha inesperada sondando %s no preflight", label)
            return [f"{label}: falha ao checar o dispositivo ({type(exc).__name__}: {exc})."]
        return [] if health.ok else [f"{label}: {health.message}"]

    def _build_start_opts(self, schedule: Schedule) -> dict:
        return {
            "title": schedule.title,
            "model": schedule.transcription_model,
            "device": schedule.device,
            "language": schedule.language,
            "chunk_seconds": schedule.chunk_seconds,
            "keep_audio": True,
            "capture_system": schedule.system_audio_enabled,
            "capture_microphone": schedule.microphone_enabled,
            "system_device_id": schedule.system_device_id,
            "microphone_device_id": schedule.microphone_device_id,
            "meetings_root": schedule.meetings_root,
        }
