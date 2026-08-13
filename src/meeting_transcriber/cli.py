"""Ponto de entrada de linha de comando.

Arquitetura: uma thread dedicada (`recording_worker`) grava o audio do
sistema em blocos continuos e os coloca numa fila; a thread principal
consome a fila, transcreve cada bloco com faster-whisper e vai anexando o
resultado ao .md. As duas etapas rodam em paralelo, entao a gravacao nunca
para para esperar a transcricao terminar — essencial para reunioes longas.
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
        "--work-dir", type=Path, default=None, help="Diretorio para os blocos de audio temporarios (padrao: pasta temporaria do sistema)"
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    language = None if args.language.lower() == "auto" else args.language
    keep_audio = not args.no_keep_audio

    # pasta onde os .wav de cada bloco ficam guardados durante a sessao
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="meeting_transcriber_"))
    own_work_dir = args.work_dir is None  # so apagamos a pasta se fomos nos que a criamos

    stop_event = threading.Event()  # sinaliza pra thread de gravacao parar
    chunk_queue: "queue.Queue[Optional[RecordedChunk]]" = queue.Queue()  # blocos prontos, aguardando transcricao

    def handle_sigint(signum, frame):  # noqa: ARG001
        # 1o Ctrl+C: para a gravacao mas deixa terminar de transcrever o que
        # ja foi gravado (graceful shutdown). 2o Ctrl+C: desiste na hora.
        if stop_event.is_set():
            logger.warning("Forcando encerramento imediato (sem finalizar a transcricao pendente).")
            os._exit(1)
        logger.info(
            "Parando a gravacao... aguardando a transcricao dos blocos pendentes "
            "(pressione Ctrl+C de novo para forcar o encerramento)."
        )
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    # a gravacao roda em thread separada da transcricao (ver recorder.py):
    # gravar nunca espera transcrever, e vice-versa.
    recorder_thread = threading.Thread(
        target=recording_worker,
        args=(work_dir, args.chunk_seconds, stop_event, chunk_queue),
        daemon=True,
    )

    writer = MarkdownWriter(args.output, args.title, args.model, language)  # ja cria o .md com cabecalho
    transcriber = Transcriber(model_size=args.model, device=args.device, language=language)  # carrega o Whisper

    logger.info("Gravando audio do sistema. Pressione Ctrl+C para parar e finalizar a transcricao.")
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
                continue  # mantem o .wav desse bloco mesmo com --no-keep-audio, para retentativa manual
            total_duration = chunk.start_offset_seconds + chunk.duration_seconds
            if not keep_audio:
                chunk.path.unlink(missing_ok=True)  # apaga o .wav so depois de transcrever com sucesso
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

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    return run(args)
