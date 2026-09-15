from __future__ import annotations

from meeting_transcriber import whisper_config as wc


def test_all_presets_map_to_known_model_names():
    for preset, model in wc.WHISPER_PRESETS.items():
        assert model  # nunca vazio
    assert set(wc.WHISPER_PRESETS) == {"FAST", "BALANCED", "ACCURATE", "MAXIMUM"}


def test_resolve_model_size_accepts_preset_case_insensitive():
    assert wc.resolve_model_size("fast") == wc.WHISPER_PRESETS["FAST"]
    assert wc.resolve_model_size("BALANCED") == wc.WHISPER_PRESETS["BALANCED"]


def test_resolve_model_size_passes_through_direct_model_name():
    assert wc.resolve_model_size("small") == "small"  # nao e um preset, mas ja e um nome valido


def test_resolve_model_size_defaults_when_none():
    assert wc.resolve_model_size(None) == wc.WHISPER_PRESETS[wc.DEFAULT_PRESET]


def test_resolve_model_size_defaults_when_empty_string():
    assert wc.resolve_model_size("") == wc.WHISPER_PRESETS[wc.DEFAULT_PRESET]


def test_is_cuda_available_never_raises_when_ctranslate2_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "ctranslate2":
            raise ImportError("simulado: nao instalado")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert wc.is_cuda_available() is False


def test_is_cuda_available_never_raises_on_unexpected_error(monkeypatch):
    import sys
    import types

    fake_module = types.ModuleType("ctranslate2")

    def _boom():
        raise RuntimeError("driver quebrado (simulado)")

    fake_module.get_cuda_device_count = _boom
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_module)
    assert wc.is_cuda_available() is False


def test_resolve_device_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    monkeypatch.setattr(wc, "is_cuda_available", lambda: False)
    assert wc.resolve_device("cuda") == "cpu"


def test_resolve_device_keeps_cuda_when_available(monkeypatch):
    monkeypatch.setattr(wc, "is_cuda_available", lambda: True)
    assert wc.resolve_device("cuda") == "cuda"


def test_resolve_device_never_touches_cpu_request():
    assert wc.resolve_device("cpu") == "cpu"


def test_live_preset_is_faster_than_default_preset():
    live_model = wc.WHISPER_PRESETS[wc.DEFAULT_LIVE_PRESET]
    default_model = wc.WHISPER_PRESETS[wc.DEFAULT_PRESET]
    # "tiny" (o preset ao vivo padrao) precisa vir antes de "small" (o
    # preset padrao geral) numa ordem crescente de custo -- checagem
    # simples por indice na propria tabela de tamanhos conhecidos do
    # Whisper, sem inventar uma metrica de velocidade de verdade aqui.
    order = ["tiny", "base", "small", "medium", "large-v3"]
    assert order.index(live_model) < order.index(default_model)
