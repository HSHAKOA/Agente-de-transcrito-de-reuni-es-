"""Ponto de entrada de linha de comando.

Arquitetura: uma thread dedicada (`recording_worker`) grava o audio do
sistema em blocos continuos e os coloca numa fila; a thread principal
consome a fila, transcreve cada bloco com faster-whisper e vai anexando o
resultado ao .md. As duas etapas rodam em paralelo, entao a gravacao nunca
para para esperar a transcricao terminar — essencial para reunioes longas.

Quando `--meeting-dir` e passado (o painel local sempre passa), o progresso
tambem e espelhado em `state.json`/`metadata.json` dentro dessa pasta (ver
`session.py`), o que permite detectar e recuperar uma sessao interrompida na
proxima inicializacao do app.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import shutil
import signal
import tempfile
import threading
from pathlib import Path
from typing import Optional, Sequence

from .audio.devices import check_device_health
from .audio.dual_capture import dual_recording_worker
from .audio.levels import LevelMeter, compute_rms, normalize_level
from .audio.loopback import make_loopback_mic_factory
from .audio.microphone import make_microphone_factory
from .audio_capture import SAMPLE_RATE
from .live.pipeline import LiveTranscriptionPipeline
from .live.segments import STATE_COMMITTED, LiveSegment
from .live.transcript import LiveTranscript
from .live.whisper_adapter import load_live_model, make_transcribe_window_fn
from .markdown_writer import MarkdownWriter
from .recorder import RecordedChunk, recording_worker
from .session import STATUS_FAILED, MeetingSession
from .transcriber import Transcriber
from .whisper_config import DEFAULT_LIVE_PRESET

logger = logging.getLogger("meeting_transcriber")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grava o audio de saida do sistema (loopback) e transcreve para Markdown."
    )
    parser.add_argument("-o", "--output", type=Path, default=Path("transcricao.md"), help="Arquivo .md de saida")
    parser.add_argument("--title", default="Transcricao de reuniao", help="Titulo no topo do markdown")
    parser.add_argument("--model", default="small", help="Tamanho do modelo Whisper (tiny/base/small/medium/large-v3)")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Dispositivo de inferencia")
    parser.add_argument(
        "--language", default="pt", help="Codigo do idioma (ex: pt, en) ou 'auto' para deteccao automatica"
    )
    parser.add_argument(
        "--chunk-seconds", type=int, default=300, help="Duracao alvo (em segundos) de cada bloco de gravacao/transcricao"
    )
    parser.add_argument(
        "--no-keep-audio",
        action="store_true",
        help="Apaga o .wav de cada bloco logo apos transcrever (por padrao os blocos ficam salvos, "
        "como rede de seguranca para reprocessar em caso de falha)",
    )
    parser.add_argument(
        "--work-dir", type=Path, default=None, help="Diretorio para os blocos de audio temporarios (padrao: pasta temporaria do sistema, ou <meeting-dir>/chunks se --meeting-dir for usado)"
    )
    parser.add_argument(
        "--meeting-dir",
        type=Path,
        default=None,
        help="Pasta de sessao persistente (ex.: data/meetings/<id>) onde metadata.json/state.json sao "
        "mantidos para permitir detectar e recuperar a sessao caso o processo seja interrompido. "
        "Se omitido, o comportamento e o mesmo de antes (sem estado persistente).",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        metavar="MEETING_DIR",
        help="Nao grava audio novo: so reprocessa os blocos pendentes/com falha de uma sessao "
        "existente em MEETING_DIR e finaliza. Usado para recuperar uma sessao interrompida.",
    )
    parser.add_argument(
        "--capture-system",
        dest="capture_system",
        action="store_true",
        default=True,
        help="Captura o audio de saida do sistema via loopback (padrao: ligado, comportamento original)",
    )
    parser.add_argument(
        "--no-capture-system",
        dest="capture_system",
        action="store_false",
        help="Desativa a captura do audio do sistema (use com --capture-microphone para gravar so o microfone)",
    )
    parser.add_argument(
        "--capture-microphone",
        dest="capture_microphone",
        action="store_true",
        default=False,
        help="Ativa a captura do microfone. Combinado com --capture-system (o padrao), grava as duas "
        "fontes simultaneamente e mixa; sozinho, grava so o microfone.",
    )
    parser.add_argument(
        "--system-device",
        default=None,
        metavar="DEVICE_ID",
        help="ID do dispositivo de saida para loopback (padrao: dispositivo de saida padrao do sistema)",
    )
    parser.add_argument(
        "--microphone-device",
        default=None,
        metavar="DEVICE_ID",
        help="ID do microfone de entrada (padrao: microfone padrao do sistema)",
    )
    parser.add_argument(
        "--levels-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Arquivo onde escrever, periodicamente e de forma atomica, um snapshot JSON do nivel de "
        "audio de cada fonte (usado pelo medidor de audio do painel). Apagado ao final da sessao.",
    )
    parser.add_argument(
        "--live-transcription",
        dest="live_transcription",
        action="store_true",
        default=True,
        help="Ativa a previa de transcricao quase em tempo real, alem da transcricao duravel por "
        "bloco (padrao: ligado).",
    )
    parser.add_argument(
        "--no-live-transcription",
        dest="live_transcription",
        action="store_false",
        help="Desativa a previa ao vivo (a transcricao duravel por bloco continua normalmente).",
    )
    parser.add_argument(
        "--live-preset",
        default=DEFAULT_LIVE_PRESET,
        metavar="PRESET",
        help="Preset do modelo Whisper usado SO pela previa ao vivo (FAST/BALANCED/ACCURATE/MAXIMUM, "
        "ou um nome de modelo direto). Padrao: mais rapido que o modelo da transcricao duravel, ja "
        "que precisa terminar bem antes da proxima janela chegar.",
    )
    parser.add_argument(
        "--live-transcript-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Arquivo onde escrever, periodicamente e de forma atomica, um snapshot JSON da "
        "transcricao ao vivo (segmentos provisorios/definitivos + backlog). Apagado ao final da sessao.",
    )
    return parser.parse_args(argv)


def _make_shutdown_handler(stop_event: threading.Event, force_exit=os._exit):
    """Fabrica o handler de sinal de parada graciosa.

    Isolado numa funcao pura (em vez de uma closure direta dentro de `run`)
    para poder testar a logica de "1o sinal para, 2o sinal forca saida" sem
    de fato registrar um signal handler nem matar o processo de teste —
    o teste injeta um `force_exit` falso e verifica se foi chamado.
    """

    def handler(signum, frame):  # noqa: ARG001
        if stop_event.is_set():
            logger.warning("Forcando encerramento imediato (sem finalizar a transcricao pendente).")
            force_exit(1)
            return
        logger.info(
            "Parando a gravacao... aguardando a transcricao dos blocos pendentes "
            "(sinal de parada de novo para forcar o encerramento)."
        )
        stop_event.set()

    return handler


def _register_shutdown_signals(handler) -> None:
    """Registra o handler gracioso para SIGINT (Ctrl+C em qualquer SO) e,
    no Windows, tambem para SIGBREAK — que e o sinal que o Python recebe
    quando alguem manda CTRL_BREAK_EVENT para o processo (e o mecanismo que
    o painel usa para pedir parada graciosa sem matar o processo na hora;
    ver webui.py:shutdown_sequence). Sem isso, so o Ctrl+C no terminal
    conseguia disparar o shutdown gracioso — o botao "Parar" do painel nunca
    tinha como chegar ate aqui.
    """
    signal.signal(signal.SIGINT, handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handler)


def _write_levels_snapshot(level_meter: LevelMeter, levels_file: Path) -> None:
    """Escrita atomica (mesmo padrao de session.py/settings.py): grava num
    arquivo temporario e substitui com `os.replace`. levels.json e lido com
    muito mais frequencia que state.json (varias vezes por segundo pelo
    stream do painel), entao nunca pode aparecer pela metade pro leitor."""
    tmp_path = levels_file.with_name(levels_file.name + f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(level_meter.snapshot()), encoding="utf-8")
    os.replace(tmp_path, levels_file)


def _levels_writer_loop(
    level_meter: LevelMeter, levels_file: Path, stop_event: threading.Event, interval: float = 0.2
) -> None:
    """Roda numa thread dedicada, escrevendo o snapshot mais recente do
    `level_meter` em `levels_file` a cada `interval` segundos ate
    `stop_event` ser sinalizado. `webui.py` streama o conteudo desse
    arquivo via SSE -- ver docs/API.md.
    """
    levels_file.parent.mkdir(parents=True, exist_ok=True)
    while not stop_event.wait(interval):
        try:
            _write_levels_snapshot(level_meter, levels_file)
        except OSError:
            logger.exception("Falha ao escrever %s", levels_file)
    try:
        _write_levels_snapshot(level_meter, levels_file)  # ultima escrita, com o estado final
    except OSError:
        pass


def _write_live_transcript_snapshot(live_transcript: LiveTranscript, live_transcript_file: Path) -> None:
    """Mesmo padrao de `_write_levels_snapshot` -- escrita atomica, arquivo
    lido com frequencia (SSE do painel), nunca pode aparecer pela metade."""
    tmp_path = live_transcript_file.with_name(live_transcript_file.name + f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(live_transcript.snapshot(), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, live_transcript_file)


def _live_transcript_writer_loop(
    live_transcript: LiveTranscript, live_transcript_file: Path, stop_event: threading.Event, interval: float = 0.5
) -> None:
    live_transcript_file.parent.mkdir(parents=True, exist_ok=True)
    while not stop_event.wait(interval):
        try:
            _write_live_transcript_snapshot(live_transcript, live_transcript_file)
        except OSError:
            logger.exception("Falha ao escrever %s", live_transcript_file)
    try:
        _write_live_transcript_snapshot(live_transcript, live_transcript_file)
    except OSError:
        pass


def run_resume(meeting_dir: Path) -> int:
    """Modo de recuperacao: nao grava audio nenhum, so reprocessa os blocos
    de uma sessao existente que ainda nao foram transcritos com sucesso
    (novos ou que falharam antes), anexando ao .md que ja existia.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not (meeting_dir / "state.json").exists():
        logger.error("Sessao nao encontrada em %s (state.json ausente).", meeting_dir)
        return 1

    session = MeetingSession.load(meeting_dir)
    metadata = session.metadata
    model = metadata.get("model", "small")
    device = metadata.get("device", "cpu")
    language = metadata.get("language")
    language = None if (language or "").lower() == "auto" else language

    transcript_path_str = metadata.get("transcript_path")
    if not transcript_path_str:
        logger.error("Sessao %s nao tem transcript_path registrado em metadata.json.", meeting_dir)
        return 1
    transcript_path = Path(transcript_path_str)
    if not transcript_path.exists():
        logger.error("Arquivo de transcricao %s nao existe mais.", transcript_path)
        return 1

    pending = session.pending_chunks()
    if not pending:
        logger.info("Nenhum bloco pendente para reprocessar em %s.", meeting_dir)
        session.mark_completed()
        return 0

    # mesmo handler grato usado na gravacao: sem isso, um sinal de parada
    # (Ctrl+C, ou o botao "Parar" do painel mandando CTRL_BREAK_EVENT/SIGINT)
    # chegando durante um --resume cairia no comportamento padrao do Python
    # (KeyboardInterrupt/encerramento abrupto) no meio de uma chamada
    # bloqueante do Whisper, em vez de parar de forma limpa entre um bloco e
    # outro. O bloco em andamento nesse instante so seria perdido da mesma
    # forma (fica pendente pra proxima tentativa); nenhum ja transcrito e afetado.
    stop_event = threading.Event()
    _register_shutdown_signals(_make_shutdown_handler(stop_event))

    logger.info("Reprocessando %d bloco(s) pendente(s) de %s...", len(pending), meeting_dir)
    transcriber = Transcriber(model_size=model, device=device, language=language)
    writer = MarkdownWriter.open_existing(transcript_path)

    had_failure = False
    for record in pending:
        if stop_event.is_set():
            logger.warning(
                "Reprocessamento interrompido pelo usuario; %d bloco(s) restante(s) continuam pendentes.",
                len(pending) - pending.index(record),
            )
            break
        chunk_path = meeting_dir / record.path
        if not chunk_path.exists():
            logger.error("Audio do bloco %d nao encontrado em %s; nao ha o que reprocessar.", record.index, chunk_path)
            session.mark_chunk_failed(record.index, "arquivo de audio ausente")
            had_failure = True
            continue
        try:
            segments = transcriber.transcribe_file(chunk_path, offset_seconds=record.start_offset_seconds)
            writer.append_segments(segments)
            session.mark_chunk_transcribed(record.index, record.start_offset_seconds + record.duration_seconds)
        except Exception as exc:  # um bloco com falha nao pode interromper o reprocessamento dos demais
            logger.exception("Falha ao reprocessar o bloco %d", record.index)
            writer.append_error_note(record.start_offset_seconds, chunk_path, exc)
            session.mark_chunk_failed(record.index, str(exc))
            had_failure = True

    session.mark_completed()  # rebaixa sozinho para "interrupted" se ainda sobrou algum chunk falho
    logger.info("Reprocessamento concluido (%s).", "com pendencias" if had_failure else "completo")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.resume is not None:
        return run_resume(args.resume)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.capture_system and not args.capture_microphone:
        # nunca comecar uma sessao sem nenhuma fonte de audio -- a
        # prioridade maxima da missao e "nunca deixar o usuario achar que
        # esta gravando quando nao ha audio nenhum sendo capturado".
        logger.error(
            "Nenhuma fonte de audio habilitada (--capture-system/--capture-microphone) -- nada para gravar."
        )
        return 1
    dual_mode = args.capture_system and args.capture_microphone
    # rotulo de fonte usado pelos segmentos DEFINITIVOS da transcricao ao
    # vivo -- "mixed" bate com o que dual_capture.mix_chunks ja produz de
    # verdade pro chunk duravel; os PROVISORIOS em modo dual usam
    # "system"/"microphone" separados (ver _on_raw_block_dual).
    live_source_label = "mixed" if dual_mode else ("microphone" if args.capture_microphone else "system")

    language = None if args.language.lower() == "auto" else args.language
    keep_audio = not args.no_keep_audio

    # Health check ANTES de criar qualquer arquivo (missao, secao "Health
    # check antes de gravar"): resolve e testa cada dispositivo habilitado
    # de verdade (abre um stream curto, le alguns frames, fecha) -- nunca
    # inicia a sessao silenciosamente se o dispositivo escolhido nao existe
    # ou nao abre.
    system_device_id = system_device_name = None
    microphone_device_id = microphone_device_name = None
    if args.capture_system:
        health = check_device_health("output", args.system_device, SAMPLE_RATE)
        if not health.ok:
            logger.error("Audio do sistema indisponivel (%s): %s", health.code, health.message)
            return 1
        system_device_id, system_device_name = health.device_id, health.device_name
    if args.capture_microphone:
        health = check_device_health("input", args.microphone_device, SAMPLE_RATE)
        if not health.ok:
            logger.error("Microfone indisponivel (%s): %s", health.code, health.message)
            return 1
        microphone_device_id, microphone_device_name = health.device_id, health.device_name

    # pasta onde os .wav de cada bloco ficam guardados durante a sessao --
    # "audio/" (com subpastas system/microphone/mixed) quando as duas
    # fontes estao ativas, "chunks/" (layout original, uma fonte so) caso
    # contrario -- nunca muda o layout de quem so usa o caminho de sempre.
    if args.work_dir is not None:
        work_dir = args.work_dir
    elif args.meeting_dir is not None:
        work_dir = args.meeting_dir / ("audio" if dual_mode else "chunks")
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="meeting_transcriber_"))
    # so apagamos a pasta inteira no final se foi criada so pra essa execucao
    # (nunca a pasta de uma sessao persistente, que o usuario pode querer consultar depois)
    own_work_dir = args.work_dir is None and args.meeting_dir is None

    session: Optional[MeetingSession] = None
    if args.meeting_dir is not None:
        state_path = args.meeting_dir / "state.json"
        if state_path.exists():
            existing = MeetingSession.load(args.meeting_dir)
            if existing.state.get("chunks"):
                # recording_worker sempre comeca a numerar em chunk_00000.wav;
                # gravar de novo aqui sobrescreveria silenciosamente audio de
                # uma sessao anterior que ja tem blocos registrados. --resume
                # existe exatamente pra continuar uma sessao existente sem
                # gravar nada novo -- gravar de novo exige uma pasta nova.
                logger.error(
                    "Pasta de sessao %s ja tem audio gravado (%d bloco(s)); gravar aqui de novo "
                    "sobrescreveria esse audio. Use --resume %s para reprocessar, ou aponte "
                    "--meeting-dir para uma pasta nova.",
                    args.meeting_dir,
                    len(existing.state["chunks"]),
                    args.meeting_dir,
                )
                return 1
            session = existing  # sessao "created" mas que nunca chegou a gravar nada -- seguro reusar
        else:
            session = MeetingSession.create(
                base_dir=args.meeting_dir.parent,
                title=args.title,
                model=args.model,
                language=args.language,
                device=args.device,
                transcript_path=args.output.resolve(),
                meeting_id=args.meeting_dir.name,
                system_audio_enabled=args.capture_system,
                system_device_id=system_device_id,
                system_device_name=system_device_name,
                microphone_enabled=args.capture_microphone,
                microphone_device_id=microphone_device_id,
                microphone_device_name=microphone_device_name,
                audio_sample_rate=SAMPLE_RATE,
                audio_backend="soundcard",
            )

    stop_event = threading.Event()  # sinaliza pra thread de gravacao parar
    chunk_queue: "queue.Queue[Optional[RecordedChunk]]" = queue.Queue()  # blocos prontos, aguardando transcricao

    _register_shutdown_signals(_make_shutdown_handler(stop_event))

    level_meter = LevelMeter()

    # Transcricao ao vivo (Fase D): opcional e independente da transcricao
    # duravel por chunk (inalterada, ver loop principal mais abaixo) -- se
    # falhar ao carregar o modelo ao vivo, so desativa a previa, nunca a
    # gravacao/transcricao de verdade.
    live_transcript = LiveTranscript()
    live_pipeline: Optional[LiveTranscriptionPipeline] = None
    if args.live_transcription:
        try:
            live_model, live_language, load_seconds = load_live_model(args.live_preset, args.device, language)
            live_transcript.set_model_load_seconds(load_seconds)
            live_pipeline = LiveTranscriptionPipeline(
                live_transcript, make_transcribe_window_fn(live_model, live_language), SAMPLE_RATE,
            )
            live_pipeline.start()
        except Exception:
            logger.exception(
                "Falha ao iniciar a transcricao ao vivo -- desativada nesta sessao "
                "(a gravacao e a transcricao duravel continuam normalmente)."
            )
            live_pipeline = None

    def _on_single_chunk_recorded(chunk: RecordedChunk) -> None:
        if session is not None:
            session.mark_chunk_recorded(chunk.index, chunk.path, chunk.start_offset_seconds, chunk.duration_seconds)
        live_transcript.set_recorded_seconds(chunk.start_offset_seconds + chunk.duration_seconds)

    def _on_dual_chunk_recorded(source: str, chunk: RecordedChunk) -> None:
        # so o chunk MIXADO conta pro progresso da sessao -- e o que
        # efetivamente entra na fila de transcricao; os brutos
        # "system"/"microphone" sao so artefatos intermediarios em disco.
        if source == "mixed":
            if session is not None:
                session.mark_chunk_recorded(chunk.index, chunk.path, chunk.start_offset_seconds, chunk.duration_seconds)
            live_transcript.set_recorded_seconds(chunk.start_offset_seconds + chunk.duration_seconds)

    # a gravacao roda em thread separada da transcricao (ver recorder.py):
    # gravar nunca espera transcrever, e vice-versa.
    def _on_raw_block_dual(source: str, block) -> None:
        # sem stream "mixed" em tempo real (a mixagem so acontece por
        # chunk duravel) -- a previa ao vivo em modo dual mostra
        # "system"/"microphone" como fontes SEPARADAS (ver docstring de
        # dual_recording_worker e docs/LIVE_TRANSCRIPTION.md).
        if live_pipeline is not None:
            live_pipeline.on_block(source, block)

    def _on_block_single(source: str, block) -> None:
        level_meter.update(source, normalize_level(compute_rms(block)))
        if live_pipeline is not None:
            live_pipeline.on_block(source, block)

    if dual_mode:
        recorder_thread = threading.Thread(
            target=dual_recording_worker,
            args=(work_dir, args.chunk_seconds, stop_event, chunk_queue),
            kwargs=dict(
                system_mic_factory=make_loopback_mic_factory(args.system_device),
                microphone_mic_factory=make_microphone_factory(args.microphone_device),
                samplerate=SAMPLE_RATE,
                on_chunk_recorded=_on_dual_chunk_recorded,
                on_level=level_meter.update,
                on_raw_block=_on_raw_block_dual,
            ),
            daemon=True,
        )
    elif args.capture_microphone:
        recorder_thread = threading.Thread(
            target=recording_worker,
            args=(work_dir, args.chunk_seconds, stop_event, chunk_queue),
            kwargs=dict(
                mic_factory=make_microphone_factory(args.microphone_device),
                on_chunk_recorded=_on_single_chunk_recorded,
                on_block=lambda block: _on_block_single("microphone", block),
            ),
            daemon=True,
        )
    else:
        # caminho original (so sistema, dispositivo padrao): preserva
        # `mic_factory` no valor padrao de `recording_worker`
        # (`get_loopback_microphone`) quando nenhum dispositivo especifico
        # foi pedido, em vez de trocar por uma resolucao equivalente porem
        # nao identica -- zero risco de mudar o comportamento ja testado.
        recorder_kwargs = dict(
            on_chunk_recorded=_on_single_chunk_recorded,
            on_block=lambda block: _on_block_single("system", block),
        )
        if args.system_device is not None:
            recorder_kwargs["mic_factory"] = make_loopback_mic_factory(args.system_device)
        recorder_thread = threading.Thread(
            target=recording_worker,
            args=(work_dir, args.chunk_seconds, stop_event, chunk_queue),
            kwargs=recorder_kwargs,
            daemon=True,
        )

    writer = MarkdownWriter(args.output, args.title, args.model, language)  # ja cria o .md com cabecalho

    try:
        transcriber = Transcriber(model_size=args.model, device=args.device, language=language)  # carrega o Whisper
    except Exception as exc:
        # Falha ao carregar o modelo (ex.: --device cuda sem GPU/driver
        # compativel) acontecia antes de qualquer try/finally existir,
        # deixando o .md com cabecalho mas sem rodape e sem sinalizar a
        # sessao como falha. Agora finaliza o markdown e marca a sessao.
        logger.exception("Falha ao carregar o modelo Whisper '%s' (device=%s).", args.model, args.device)
        writer.finalize(0.0)
        if session is not None:
            session.mark_failed(f"Falha ao carregar o modelo Whisper: {exc}")
        return 1

    levels_writer_stop = threading.Event()
    levels_writer_thread: Optional[threading.Thread] = None
    if args.levels_file is not None:
        levels_writer_thread = threading.Thread(
            target=_levels_writer_loop,
            args=(level_meter, args.levels_file, levels_writer_stop),
            daemon=True,
        )
        levels_writer_thread.start()

    live_transcript_writer_stop = threading.Event()
    live_transcript_writer_thread: Optional[threading.Thread] = None
    if args.live_transcript_file is not None:
        live_transcript_writer_thread = threading.Thread(
            target=_live_transcript_writer_loop,
            args=(live_transcript, args.live_transcript_file, live_transcript_writer_stop),
            daemon=True,
        )
        live_transcript_writer_thread.start()

    logger.info(
        "Gravando (sistema=%s, microfone=%s). Pressione Ctrl+C para parar e finalizar a transcricao.",
        args.capture_system,
        args.capture_microphone,
    )
    if session is not None:
        session.mark_recording()
    recorder_thread.start()

    total_duration = 0.0
    try:
        # loop principal: consome blocos gravados da fila, transcreve e
        # anexa ao markdown, um por um, ate a gravacao sinalizar fim (None).
        #
        # `chunk_queue.get()` sem timeout ficaria bloqueado ate o PROXIMO
        # item chegar -- e no Windows, o interpretador so processa um sinal
        # pendente (Ctrl+C, ou CTRL_BREAK_EVENT vindo do painel) quando a
        # thread PRINCIPAL retorna pra avaliar bytecode Python. Com
        # chunk_seconds grande (ate 1800s), a thread principal podia ficar
        # parada nesse get() por ate 30 minutos antes de sequer ter a chance
        # de notar que alguem pediu pra parar -- confirmado na pratica
        # durante esta fase (um teste real com hardware, usando sinal real,
        # so terminou apos o chunk_seconds inteiro, nao em segundos como
        # esperado). Um timeout curto aqui garante que a thread principal
        # volta a rodar bytecode Python periodicamente, dando ao
        # interpretador a chance de processar o sinal pendente sem afetar o
        # comportamento normal (nada muda quando ha itens disponiveis).
        while True:
            try:
                chunk = chunk_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk is None:
                break
            logger.info("Transcrevendo bloco %d (%.1fs)...", chunk.index, chunk.duration_seconds)
            try:
                segments = transcriber.transcribe_file(chunk.path, offset_seconds=chunk.start_offset_seconds)
                writer.append_segments(segments)  # escreve no .md JA, nao espera a sessao acabar
                # a transcricao DURAVEL deste chunk e a fonte de verdade --
                # substitui qualquer previa provisoria dessa faixa de tempo
                # (Fase D: "committed" sempre vence "provisional").
                live_transcript.commit_range(
                    chunk.start_offset_seconds,
                    chunk.start_offset_seconds + chunk.duration_seconds,
                    [
                        LiveSegment(s.start, s.end, s.text, STATE_COMMITTED, live_source_label)
                        for s in segments
                    ],
                )
            except Exception as exc:  # um bloco com falha nao pode derrubar a sessao inteira
                logger.exception("Falha ao transcrever o bloco %d", chunk.index)
                writer.append_error_note(chunk.start_offset_seconds, chunk.path, exc)
                if session is not None:
                    session.mark_chunk_failed(chunk.index, str(exc))
                continue  # mantem o .wav desse bloco mesmo com --no-keep-audio, para retentativa manual
            total_duration = chunk.start_offset_seconds + chunk.duration_seconds
            if session is not None:
                session.mark_chunk_transcribed(chunk.index, total_duration)
            if not keep_audio:
                chunk.path.unlink(missing_ok=True)  # apaga o .wav so depois de transcrever com sucesso
    except Exception as exc:
        logger.exception("Erro inesperado no loop de transcricao.")
        if session is not None:
            session.mark_failed(str(exc))
        raise
    finally:
        # roda mesmo se o loop acima quebrar por excecao: garante que o
        # markdown fecha corretamente e a pasta temporaria e limpa.
        writer.finalize(total_duration)
        # dual_recording_worker junta suas DUAS threads internas (ate
        # _THREAD_JOIN_TIMEOUT_SECONDS cada) depois de emitir o sentinel --
        # o join externo aqui precisa cobrir esse tempo, senao arriscamos
        # seguir pra limpeza/rmtree enquanto as threads de captura ainda
        # estao terminando.
        recorder_thread.join(timeout=25 if dual_mode else 5)
        if live_pipeline is not None:
            # emite a ultima janela parcial de cada fonte antes de parar --
            # nunca perde os ultimos segundos so por nao terem fechado uma
            # janela inteira (Fase D: "shutdown com transcricao pendente").
            for source in (["system", "microphone"] if dual_mode else [live_source_label]):
                live_pipeline.flush(source)
            live_pipeline.stop(timeout=10.0)
        if live_transcript_writer_thread is not None:
            live_transcript_writer_stop.set()
            live_transcript_writer_thread.join(timeout=2)
            args.live_transcript_file.unlink(missing_ok=True)
        if levels_writer_thread is not None:
            levels_writer_stop.set()
            levels_writer_thread.join(timeout=2)
            args.levels_file.unlink(missing_ok=True)
        if own_work_dir and keep_audio:
            logger.info("Blocos de audio preservados em %s", work_dir)
        elif own_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        logger.info("Transcricao salva em %s", args.output)
        if session is not None and session.state.get("status") != STATUS_FAILED:
            session.mark_completed()

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    return run(args)
