"""Orquestracao de captura SIMULTANEA (audio do sistema + microfone).

Cada fonte roda na sua PROPRIA thread, reaproveitando
`recorder.recording_worker` (a mesma logica de particionamento em blocos,
flush do buffer parcial no stop, sentinela de fim -- ja testada e em uso
pelo caminho de fonte unica, que continua existindo sem nenhuma mudanca de
comportamento). Uma terceira thread ("mixer") pareia os chunks das duas
fontes por indice e produz um chunk MIXADO por par, pronto pra
transcrever -- e essa fila mixada que `cli.py` consome, exatamente como ja
consome a fila de fonte unica hoje.

## Estrategia de sincronizacao (documentada de proposito)

As duas fontes comecam a gravar quase no mesmo instante (as duas threads
sao iniciadas em sequencia, uma logo apos a outra) e usam o MESMO
`chunk_seconds`/`samplerate`, entao o chunk de indice N de cada fonte
cobre aproximadamente a mesma janela da gravacao. Isto NAO e sincronizacao
amostra-a-amostra: pequenas diferencas de agendamento entre as duas
threads podem fazer uma fonte fechar um chunk uma fracao de segundo antes/
depois da outra. `mixer.mix_samples`/`pad_to_length` absorvem essa
diferenca de TAMANHO completando com silencio -- irrelevante numa escala
de fracoes de segundo por chunk de dezenas de segundos a minutos.

O que isto NAO resolve, documentado como limitacao explicita desta fase:
drift de clock acumulado numa gravacao muito longa (horas) entre dois
dispositivos de audio com clocks fisicos diferentes. Cada fonte grava
exatamente `chunk_seconds` contando amostras (nao relogio de parede), entao
um clock de hardware um pouco mais rapido/lento acumula alguns
milissegundos de diferenca por chunk -- ao longo de horas isso pode chegar
a segundos de desalinhamento entre as duas fontes. Corrigir isso de verdade
exigiria resampling adaptativo com um relogio compartilhado; fica pra uma
fase futura, so se a pratica mostrar que o drift do `soundcard`/WASAPI e
perceptivel numa reuniao real (nao ha evidencia disso ainda).

## Eco/duplicacao (limitacao conhecida, nao resolvida nesta fase)

O microfone pode captar fisicamente o som saindo pelas caixas -- nesse
caso o audio mixado tera o mesmo trecho de fala "duas vezes" (uma vinda do
loopback do sistema, outra do microfone captando o ambiente). Cancelamento
de eco (AEC) fica fora de escopo aqui; a mitigacao pratica e recomendar
fones de ouvido ao usuario quando as duas fontes estao ativas.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Callable, Optional

from ..recorder import RecordedChunk, recording_worker
from .levels import compute_rms, normalize_level
from .mixer import mix_chunks

logger = logging.getLogger(__name__)

# tempo maximo de espera por uma thread de captura terminar de verdade
# depois do stop_event ser sinalizado -- generoso o bastante pra flush do
# ultimo bloco parcial, mas nao trava o encerramento indefinidamente se
# algo travar no dispositivo.
_THREAD_JOIN_TIMEOUT_SECONDS = 10.0


def dual_recording_worker(
    session_dir: Path,
    chunk_seconds: int,
    stop_event: threading.Event,
    out_queue: "queue.Queue[Optional[RecordedChunk]]",
    system_mic_factory: Callable[[], object],
    microphone_mic_factory: Callable[[], object],
    samplerate: int,
    on_chunk_recorded: Optional[Callable[[str, RecordedChunk], None]] = None,
    on_level: Optional[Callable[[str, float], None]] = None,
    on_raw_block: Optional[Callable[[str, "object"], None]] = None,
) -> None:
    """Grava sistema + microfone simultaneamente e poe chunks MIXADOS em
    `out_queue` -- a mesma interface que `recording_worker` ja expoe pro
    caminho de fonte unica, entao `cli.py` consome os dois casos sem
    precisar saber qual esta em uso.

    `on_chunk_recorded(source, chunk)` e chamado para cada chunk BRUTO
    ("system"/"microphone") assim que gravado, ALEM do chunk mixado ir pra
    `out_queue` -- quem chama decide se quer rastrear os brutos e/ou so o
    mixado (ver `cli.py`, que usa isso pra manter `chunks_recorded` da
    sessao contando os blocos brutos das duas fontes).

    `on_raw_block(source, block)` e chamado com o bloco de audio CRU
    (~0.5s) de cada fonte assim que lido -- usado pela transcricao ao vivo
    (Fase D), que precisa do audio antes dele virar nivel/chunk. Nao ha
    hoje um fluxo "mixado" em tempo real (a mixagem so acontece por
    CHUNK, ao fechar um bloco duravel) -- por isso a previa ao vivo em
    modo dual mostra "system"/"microphone" como fontes SEPARADAS, nunca
    uma "mixed" em tempo real (documentado em docs/LIVE_TRANSCRIPTION.md).
    """
    system_dir = session_dir / "system"
    microphone_dir = session_dir / "microphone"
    mixed_dir = session_dir / "mixed"

    system_queue: "queue.Queue[Optional[RecordedChunk]]" = queue.Queue()
    microphone_queue: "queue.Queue[Optional[RecordedChunk]]" = queue.Queue()

    def _on_system_chunk(chunk: RecordedChunk) -> None:
        if on_chunk_recorded is not None:
            on_chunk_recorded("system", chunk)

    def _on_microphone_chunk(chunk: RecordedChunk) -> None:
        if on_chunk_recorded is not None:
            on_chunk_recorded("microphone", chunk)

    def _on_system_block(block) -> None:
        if on_level is not None:
            on_level("system", normalize_level(compute_rms(block)))
        if on_raw_block is not None:
            on_raw_block("system", block)

    def _on_microphone_block(block) -> None:
        if on_level is not None:
            on_level("microphone", normalize_level(compute_rms(block)))
        if on_raw_block is not None:
            on_raw_block("microphone", block)

    system_thread = threading.Thread(
        target=recording_worker,
        args=(system_dir, chunk_seconds, stop_event, system_queue),
        kwargs=dict(
            samplerate=samplerate,
            mic_factory=system_mic_factory,
            on_chunk_recorded=_on_system_chunk,
            on_block=_on_system_block,
        ),
        daemon=True,
        name="audio-capture-system",
    )
    microphone_thread = threading.Thread(
        target=recording_worker,
        args=(microphone_dir, chunk_seconds, stop_event, microphone_queue),
        kwargs=dict(
            samplerate=samplerate,
            mic_factory=microphone_mic_factory,
            on_chunk_recorded=_on_microphone_chunk,
            on_block=_on_microphone_block,
        ),
        daemon=True,
        name="audio-capture-microphone",
    )

    system_thread.start()
    microphone_thread.start()

    try:
        _mix_loop(system_queue, microphone_queue, mixed_dir, samplerate, out_queue, on_chunk_recorded)
    finally:
        # garante que as duas threads de captura realmente pararam antes
        # de devolver o controle, mesmo se o mixer sair mais cedo por
        # excecao -- nunca deixa threads de captura orfas rodando.
        stop_event.set()
        system_thread.join(timeout=_THREAD_JOIN_TIMEOUT_SECONDS)
        microphone_thread.join(timeout=_THREAD_JOIN_TIMEOUT_SECONDS)
        if system_thread.is_alive() or microphone_thread.is_alive():
            logger.error(
                "Thread(s) de captura nao terminaram dentro do timeout (system=%s vivo, microphone=%s vivo).",
                system_thread.is_alive(),
                microphone_thread.is_alive(),
            )


def _mix_loop(
    system_queue: "queue.Queue[Optional[RecordedChunk]]",
    microphone_queue: "queue.Queue[Optional[RecordedChunk]]",
    mixed_dir: Path,
    samplerate: int,
    out_queue: "queue.Queue[Optional[RecordedChunk]]",
    on_chunk_recorded: Optional[Callable[[str, RecordedChunk], None]] = None,
) -> None:
    """Pareia chunks das duas filas por ordem de chegada (indice) e produz
    um chunk mixado por par. Se uma fonte termina (sentinela None) antes
    da outra, ela passa a ser tratada como silencio para os chunks
    restantes da outra -- nunca fica esperando um chunk que nao vai mais
    chegar (o que travaria o encerramento gracioso pra sempre).

    Chama `on_chunk_recorded("mixed", chunk)` para cada chunk mixado
    produzido -- e esse evento (nao os brutos "system"/"microphone") que
    `cli.py` usa pra rastrear o progresso da sessao, ja que e o chunk
    MIXADO que efetivamente entra na fila de transcricao.
    """
    system_alive = True
    microphone_alive = True
    index = 0

    try:
        while system_alive or microphone_alive:
            system_chunk = system_queue.get() if system_alive else None
            if system_chunk is None and system_alive:
                system_alive = False

            microphone_chunk = microphone_queue.get() if microphone_alive else None
            if microphone_chunk is None and microphone_alive:
                microphone_alive = False

            if system_chunk is None and microphone_chunk is None:
                break

            try:
                mixed = mix_chunks(system_chunk, microphone_chunk, mixed_dir, index, samplerate)
            except Exception:
                logger.exception("Falha ao mixar o chunk %d; pulando esse par.", index)
                index += 1
                continue

            index += 1
            if on_chunk_recorded is not None:
                try:
                    on_chunk_recorded("mixed", mixed)
                except Exception:
                    logger.exception("Falha ao notificar chunk mixado %d", mixed.index)
            out_queue.put(mixed)
    finally:
        out_queue.put(None)
