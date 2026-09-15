"""Configuracao centralizada do Whisper (Fase D, secao D.9): presets em
vez do usuario ter que saber o nome exato de cada tamanho de modelo, e
deteccao segura de CUDA -- pedir `--device cuda` numa maquina sem GPU
NVIDIA/driver compativel nunca pode travar a inicializacao com um erro
opaco do CTranslate2; cai para CPU com um aviso claro no log.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Preset -> tamanho de modelo Whisper. Mapeamento deliberadamente simples
# (so o nome do modelo) -- nao um sistema de configuracao generico, so o
# suficiente pro usuario escolher "rapido" vs "preciso" sem decorar nomes
# de modelo.
WHISPER_PRESETS = {
    "FAST": "tiny",
    "BALANCED": "small",
    "ACCURATE": "medium",
    "MAXIMUM": "large-v3",
}

DEFAULT_PRESET = "BALANCED"

# A transcricao AO VIVO (Fase D) roda num orcamento de tempo bem mais
# apertado que a transcricao DURAVEL (precisa terminar bem antes da
# proxima janela chegar) -- por isso usa um preset mais rapido por
# padrao, independente do preset escolhido pra transcricao final.
DEFAULT_LIVE_PRESET = "FAST"


def resolve_model_size(preset_or_model: Optional[str]) -> str:
    """Aceita tanto um preset (`"BALANCED"`, case-insensitive) quanto um
    nome de modelo Whisper direto (`"small"`) -- assim quem ja usava
    `--model small` continua funcionando sem mudanca nenhuma."""
    if not preset_or_model:
        return WHISPER_PRESETS[DEFAULT_PRESET]
    upper = preset_or_model.upper()
    if upper in WHISPER_PRESETS:
        return WHISPER_PRESETS[upper]
    return preset_or_model  # ja e um nome de modelo Whisper valido (validado depois por validation.py)


def is_cuda_available() -> bool:
    """Nunca lanca excecao -- qualquer falha ao perguntar pro CTranslate2
    (biblioteca ausente, driver quebrado, etc.) e tratada como "sem CUDA
    disponivel", nunca como erro fatal."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def resolve_device(requested_device: str) -> str:
    """Se `requested_device == "cuda"` mas nao ha CUDA disponivel de
    verdade, cai pra CPU com um aviso -- nunca deixa a tentativa de
    carregar o modelo explodir com um erro criptico do CTranslate2 no
    meio da inicializacao (missao, secao D.9: "nao permitir CUDA
    inexistente causar crash opaco")."""
    if requested_device == "cuda" and not is_cuda_available():
        logger.warning(
            "Device 'cuda' foi pedido mas nenhuma GPU CUDA compativel foi detectada -- usando 'cpu' no lugar."
        )
        return "cpu"
    return requested_device
