"""Captura do audio de saida do sistema (loopback).

Usa a biblioteca `soundcard`, que sabe abrir o dispositivo de saida padrao
em modo de gravacao (loopback):

- Windows: loopback nativo via WASAPI.
- Linux (PulseAudio/PipeWire): fonte "monitor" do dispositivo de saida padrao.
- macOS: o CoreAudio nao tem loopback nativo. E necessario instalar um
  dispositivo de audio virtual (ex.: BlackHole) e selecioná-lo como saida
  padrao antes de rodar este programa. Veja o README.md.
"""

from __future__ import annotations

SAMPLE_RATE = 16_000  # taxa de amostragem esperada pelo Whisper


def get_loopback_microphone() -> "sc.Microphone":  # noqa: F821 - sc importado sob demanda abaixo
    """Retorna um `Microphone` que grava o que esta saindo pelo dispositivo
    de audio padrao do sistema (o que voce ouve pelas caixas/fone).

    O import de `soundcard` fica dentro da funcao (em vez do topo do
    modulo) porque a biblioteca tenta carregar a lib nativa de audio do SO
    (libpulse no Linux, WASAPI no Windows) assim que e importada — isso
    falha em ambientes sem placa de som/servidor de audio (ex.: containers
    de CI). Adiando o import, o resto do pacote continua importavel e
    testavel nesses ambientes; so quebra aqui, na hora de gravar de fato.
    """
    import soundcard as sc

    speaker = sc.default_speaker()
    try:
        return sc.get_microphone(id=speaker.name, include_loopback=True)
    except Exception as exc:  # depende de SO/driver, dificil restringir o tipo
        raise RuntimeError(
            "Nao foi possivel abrir a captura de audio do sistema (loopback) "
            f"para o dispositivo de saida '{speaker.name}'. Veja o README.md "
            "para os requisitos do seu sistema operacional (no macOS e "
            "necessario instalar o BlackHole e seleciona-lo como saida)."
        ) from exc
