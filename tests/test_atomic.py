"""Escrita atomica tolerante a negacao transitoria do Windows.

Regressao de um incidente observado numa gravacao real de 1h53
(21/09/2026): `os.replace` de `levels.json` -- feito 5x por segundo pelo
gravador enquanto o painel lia o MESMO arquivo para o stream SSE dos
medidores -- falhou dezenas de vezes com `PermissionError [WinError 5]`.
O `open()` do CPython no Windows nao pede `FILE_SHARE_DELETE`, entao basta
alguem ter o destino aberto para a troca ser negada.

Cada falha era engolida por um `except OSError` que despejava um traceback
completo no log; o log do painel (300 linhas) virou quase so isso.

Nada aqui espera tempo real: `sleep` e injetado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meeting_transcriber import atomic


class FlakyReplace:
    """Dublê de `os.replace` que falha as `failures` primeiras chamadas com
    a negacao exata do Windows, e depois funciona."""

    def __init__(self, failures: int, real_replace):
        self.failures = failures
        self.calls = 0
        self._real = real_replace

    def __call__(self, src, dst):
        self.calls += 1
        if self.calls <= self.failures:
            raise PermissionError(5, "Acesso negado")
        return self._real(src, dst)


@pytest.fixture
def sleeps():
    recorded = []
    return recorded, recorded.append


def test_replace_succeeds_without_retrying_when_nothing_holds_the_file(tmp_path: Path, sleeps):
    recorded, sleep = sleeps
    src = tmp_path / "a.tmp"
    src.write_text("conteudo", encoding="utf-8")
    dst = tmp_path / "a.json"

    atomic.replace_with_retry(src, dst, sleep=sleep)

    assert dst.read_text(encoding="utf-8") == "conteudo"
    assert recorded == []  # nao dorme quando nao precisa


def test_replace_retries_through_a_transient_denial(tmp_path: Path, monkeypatch, sleeps):
    """O ponto da correcao: a janela de colisao dura fracoes de
    milissegundo, entao a segunda tentativa passa e a escrita NAO se perde."""
    recorded, sleep = sleeps
    src = tmp_path / "levels.json.tmp-123"
    src.write_text('{"system": 0.4}', encoding="utf-8")
    dst = tmp_path / "levels.json"

    import os as _os

    flaky = FlakyReplace(failures=2, real_replace=_os.replace)
    monkeypatch.setattr(atomic.os, "replace", flaky)

    atomic.replace_with_retry(src, dst, sleep=sleep)

    assert flaky.calls == 3  # 2 negacoes + 1 sucesso
    assert len(recorded) == 2  # dormiu entre as tentativas
    assert json.loads(dst.read_text(encoding="utf-8")) == {"system": 0.4}


def test_replace_gives_up_and_reraises_a_persistent_failure(tmp_path: Path, monkeypatch, sleeps):
    """Retry nao pode mascarar erro de verdade (permissao real, disco
    cheio): esgotadas as tentativas, a excecao original propaga."""
    recorded, sleep = sleeps
    src = tmp_path / "a.tmp"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "a.json"

    import os as _os

    always_fails = FlakyReplace(failures=999, real_replace=_os.replace)
    monkeypatch.setattr(atomic.os, "replace", always_fails)

    with pytest.raises(PermissionError):
        atomic.replace_with_retry(src, dst, attempts=4, sleep=sleep)

    assert always_fails.calls == 4
    assert len(recorded) == 3  # nao dorme depois da ultima tentativa


def test_write_json_survives_a_reader_holding_the_destination(tmp_path: Path, monkeypatch, sleeps):
    """Caminho completo usado por `levels.json`/`state.json`."""
    _, sleep = sleeps
    monkeypatch.setattr(atomic, "DEFAULT_DELAY", 0)
    dst = tmp_path / "levels.json"
    dst.write_text('{"antigo": true}', encoding="utf-8")

    import os as _os

    flaky = FlakyReplace(failures=1, real_replace=_os.replace)
    monkeypatch.setattr(atomic.os, "replace", flaky)

    atomic.write_json(dst, {"system": {"level": 0.2, "active": True}})

    assert json.loads(dst.read_text(encoding="utf-8"))["system"]["active"] is True
    assert flaky.calls == 2
    assert list(tmp_path.glob("*.tmp-*")) == []  # nao deixa lixo pra tras


def test_write_json_keeps_accents_readable(tmp_path: Path):
    """`ensure_ascii=False` importa: transcricao ao vivo em portugues e
    gravada neste arquivo e lida pelo painel."""
    dst = tmp_path / "live.json"

    atomic.write_json(dst, {"texto": "gravação começou às 19h"})

    raw = dst.read_text(encoding="utf-8")
    assert "gravação começou às 19h" in raw


def test_temp_file_name_carries_the_pid(tmp_path: Path, monkeypatch):
    """Painel e gravador escrevem o MESMO destino; se compartilhassem o
    nome do temporario, um sobrescreveria o do outro no meio da escrita."""
    seen = []

    import os as _os
    real_replace = _os.replace

    def capture(src, dst):
        seen.append(Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(atomic.os, "replace", capture)

    atomic.write_text(tmp_path / "state.json", "{}")

    assert seen == [f"state.json.tmp-{_os.getpid()}"]


def test_levels_writer_survives_the_panel_reading_the_same_file(tmp_path: Path, monkeypatch, sleeps):
    """O caso exato do incidente: `webui.py` mantem `levels.json` aberto pro
    stream SSE enquanto `cli.py` o reescreve 5x por segundo. Antes desta
    correcao `_write_levels_snapshot` chamava `os.replace` direto, entao a
    negacao transitoria do Windows propagava, a amostra se perdia e um
    traceback inteiro ia pro log -- cinco vezes por segundo no pior caso.
    Este teste falha no codigo anterior."""
    _, sleep = sleeps
    monkeypatch.setattr(atomic, "DEFAULT_DELAY", 0)

    from meeting_transcriber import cli
    from meeting_transcriber.audio.levels import LevelMeter

    import os as _os

    flaky = FlakyReplace(failures=1, real_replace=_os.replace)
    monkeypatch.setattr(atomic.os, "replace", flaky)

    meter = LevelMeter()
    meter.update("system", 0.42)
    levels_file = tmp_path / "levels.json"

    cli._write_levels_snapshot(meter, levels_file)

    snapshot = json.loads(levels_file.read_text(encoding="utf-8"))
    assert snapshot["system"]["level"] == pytest.approx(0.42)
    assert flaky.calls == 2  # tentou de novo em vez de perder a amostra
