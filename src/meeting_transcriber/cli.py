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
import logging
import os
import queue
import shutil
import signal
import tempfile
import threading
from pathlib import Path
from typing import Optional, Sequence

from .markdown_writer import MarkdownWriter
from .recorder import RecordedChunk, recording_worker
from .session import STATUS_FAILED, MeetingSession
from .transcriber import Transcriber

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

    logger.info("Reprocessando %d bloco(s) pendente(s) de %s...", len(pending), meeting_dir)
    transcriber = Transcriber(model_size=model, device=device, language=language)
    writer = MarkdownWriter.open_existing(transcript_path)

    had_failure = False
    for record in pending:
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

    language = None if args.language.lower() == "auto" else args.language
    keep_audio = not args.no_keep_audio

    # pasta onde os .wav de cada bloco ficam guardados durante a sessao
    if args.work_dir is not None:
        work_dir = args.work_dir
    elif args.meeting_dir is not None:
        work_dir = args.meeting_dir / "chunks"
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="meeting_transcriber_"))
    # so apagamos a pasta inteira no final se foi criada so pra essa execucao
    # (nunca a pasta de uma sessao persistente, que o usuario pode querer consultar depois)
    own_work_dir = args.work_dir is None and args.meeting_dir is None

    session: Optional[MeetingSession] = None
    if args.meeting_dir is not None:
        if (args.meeting_dir / "state.json").exists():
            session = MeetingSession.load(args.meeting_dir)
        else:
            session = MeetingSession.create(
                base_dir=args.meeting_dir.parent,
                title=args.title,
                model=args.model,
                language=args.language,
                device=args.device,
                transcript_path=args.output.resolve(),
                meeting_id=args.meeting_dir.name,
            )

    stop_event = threading.Event()  # sinaliza pra thread de gravacao parar
    chunk_queue: "queue.Queue[Optional[RecordedChunk]]" = queue.Queue()  # blocos prontos, aguardando transcricao

    _register_shutdown_signals(_make_shutdown_handler(stop_event))

    def _on_chunk_recorded(chunk: RecordedChunk) -> None:
        if session is not None:
            session.mark_chunk_recorded(chunk.index, chunk.path, chunk.start_offset_seconds, chunk.duration_seconds)

    # a gravacao roda em thread separada da transcricao (ver recorder.py):
    # gravar nunca espera transcrever, e vice-versa.
    recorder_thread = threading.Thread(
        target=recording_worker,
        args=(work_dir, args.chunk_seconds, stop_event, chunk_queue),
        kwargs={"on_chunk_recorded": _on_chunk_recorded},
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

    logger.info("Gravando audio do sistema. Pressione Ctrl+C para parar e finalizar a transcricao.")
    if session is not None:
        session.mark_recording()
    recorder_thread.start()

    total_duration = 0.0
    try:
        # loop principal: consome blocos gravados da fila, transcreve e
        # anexa ao markdown, um por um, ate a gravacao sinalizar fim (None).
        while True:
            chunk = chunk_queue.get()  # bloqueia ate ter um bloco pronto (ou None = acabou)
            if chunk is None:
                break
            logger.info("Transcrevendo bloco %d (%.1fs)...", chunk.index, chunk.duration_seconds)
            try:
                segments = transcriber.transcribe_file(chunk.path, offset_seconds=chunk.start_offset_seconds)
                writer.append_segments(segments)  # escreve no .md JA, nao espera a sessao acabar
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
        recorder_thread.join(timeout=5)
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
