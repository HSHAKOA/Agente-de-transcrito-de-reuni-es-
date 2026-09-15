import os
from pathlib import Path

import pytest

from meeting_transcriber import settings


def test_load_returns_empty_dict_when_missing(tmp_path: Path):
    assert settings.load(tmp_path / "settings.json") == {}


def test_load_returns_empty_dict_for_corrupted_json(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("{ nao e json valido", encoding="utf-8")
    assert settings.load(path) == {}


def test_load_returns_empty_dict_for_non_object_json(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert settings.load(path) == {}


def test_save_then_load_round_trips(tmp_path: Path):
    path = tmp_path / "nested" / "settings.json"
    settings.save(path, {"meetings_root": "D:\\Reunioes", "model": "small"})
    assert settings.load(path) == {"meetings_root": "D:\\Reunioes", "model": "small"}


def test_save_is_atomic_no_leftover_tmp_files(tmp_path: Path):
    path = tmp_path / "settings.json"
    settings.save(path, {"a": 1})
    settings.save(path, {"a": 2})
    leftovers = list(tmp_path.glob("*.tmp-*"))
    assert leftovers == []


def test_save_retries_transient_replace_failure(tmp_path: Path, monkeypatch):
    """os.replace() pode falhar transitoriamente no Windows (antivirus/
    indexador segurando um handle no destino por uma fracao de segundo) --
    observado na pratica; save() deve absorver algumas falhas passageiras
    em vez de propagar na primeira tentativa."""
    path = tmp_path / "settings.json"
    real_replace = os.replace
    calls = {"n": 0}

    def _flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("acesso negado (simulado)")
        return real_replace(src, dst)

    monkeypatch.setattr(settings.os, "replace", _flaky_replace)
    settings.save(path, {"a": 1})

    assert calls["n"] == 3
    assert settings.load(path) == {"a": 1}


def test_save_gives_up_after_exhausting_retries(tmp_path: Path, monkeypatch):
    path = tmp_path / "settings.json"

    def _always_fails(src, dst):
        raise PermissionError("acesso negado (simulado, permanente)")

    monkeypatch.setattr(settings.os, "replace", _always_fails)

    with pytest.raises(PermissionError):
        settings.save(path, {"a": 1})


def test_get_meetings_root_uses_default_when_unset(tmp_path: Path):
    root = settings.get_meetings_root(tmp_path / "settings.json")
    assert root == settings.default_meetings_root()


def test_set_then_get_meetings_root(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    new_root = tmp_path / "MinhasReunioes"
    settings.set_meetings_root(settings_path, new_root)
    assert settings.get_meetings_root(settings_path) == new_root


def test_set_meetings_root_preserves_other_keys(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings.save(settings_path, {"model": "medium"})
    settings.set_meetings_root(settings_path, tmp_path / "X")
    data = settings.load(settings_path)
    assert data["model"] == "medium"
    assert data["meetings_root"] == str(tmp_path / "X")


def test_default_meetings_root_is_under_documents():
    root = settings.default_meetings_root()
    assert root.name == "Reunioes"
    assert root.parent.name == "Documents"


# -- raizes conhecidas (recovery multi-root) ---------------------------

def test_known_roots_includes_default_when_nothing_set(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    roots = settings.get_known_meeting_roots(settings_path)
    assert roots == [settings.default_meetings_root()]


def test_set_meetings_root_registers_it_as_known(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    root_a = tmp_path / "A"
    settings.set_meetings_root(settings_path, root_a)
    assert settings.get_known_meeting_roots(settings_path) == [root_a.resolve()]


def test_switching_roots_keeps_previous_ones_known(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    root_a = tmp_path / "A"
    root_b = tmp_path / "B"
    settings.set_meetings_root(settings_path, root_a)
    settings.set_meetings_root(settings_path, root_b)

    known = settings.get_known_meeting_roots(settings_path)
    assert root_a.resolve() in known
    assert root_b.resolve() in known
    assert settings.get_meetings_root(settings_path) == root_b.resolve()


def test_known_roots_are_deduplicated(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    root_a = tmp_path / "A"
    settings.set_meetings_root(settings_path, root_a)
    settings.set_meetings_root(settings_path, root_a)  # mesma raiz de novo
    settings.set_meetings_root(settings_path, root_a / ".")  # mesma raiz, grafia diferente

    known = settings.get_known_meeting_roots(settings_path)
    assert known.count(root_a.resolve()) == 1


def test_known_roots_survive_a_root_that_no_longer_exists(tmp_path: Path):
    """Uma raiz num disco desconectado nao pode quebrar a leitura da lista
    -- get_known_meeting_roots so normaliza texto, nunca toca o disco."""
    settings_path = tmp_path / "settings.json"
    missing_drive_root = "Z:\\NuncaExistiu\\Reunioes"
    settings.set_meetings_root(settings_path, tmp_path / "Real")
    data = settings.load(settings_path)
    data["known_meeting_roots"].append(missing_drive_root)
    settings.save(settings_path, data)

    roots = settings.get_known_meeting_roots(settings_path)
    assert len(roots) == 2  # nao lanca excecao, so devolve as duas normalizadas


def test_forget_meeting_root_removes_from_known_list(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    root_a = tmp_path / "A"
    root_b = tmp_path / "B"
    settings.set_meetings_root(settings_path, root_a)
    settings.set_meetings_root(settings_path, root_b)

    removed = settings.forget_meeting_root(settings_path, root_a)

    assert removed is True
    assert root_a.resolve() not in settings.get_known_meeting_roots(settings_path)


def test_forget_meeting_root_refuses_to_remove_active_root(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    root_a = tmp_path / "A"
    settings.set_meetings_root(settings_path, root_a)

    removed = settings.forget_meeting_root(settings_path, root_a)

    assert removed is False
    assert root_a.resolve() in settings.get_known_meeting_roots(settings_path)


def test_forget_meeting_root_returns_false_when_not_known(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings.set_meetings_root(settings_path, tmp_path / "A")
    assert settings.forget_meeting_root(settings_path, tmp_path / "NuncaFoiUsada") is False


# -- preferencias de audio -----------------------------------------------

def test_get_audio_preferences_defaults_when_unset(tmp_path: Path):
    prefs = settings.get_audio_preferences(tmp_path / "settings.json")
    assert prefs == {
        "capture_system": True,
        "capture_microphone": False,
        "system_device_id": None,
        "microphone_device_id": None,
    }


def test_set_audio_preferences_partial_update_preserves_others(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings.set_audio_preferences(settings_path, capture_microphone=True, microphone_device_id="mic-1")
    settings.set_audio_preferences(settings_path, system_device_id="spk-2")

    prefs = settings.get_audio_preferences(settings_path)
    assert prefs["capture_microphone"] is True
    assert prefs["microphone_device_id"] == "mic-1"
    assert prefs["system_device_id"] == "spk-2"
    assert prefs["capture_system"] is True  # nao tocado, continua o padrao


def test_set_audio_preferences_ignores_unknown_keys(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings.set_audio_preferences(settings_path, nonsense_key="qualquer coisa")
    prefs = settings.get_audio_preferences(settings_path)
    assert "nonsense_key" not in prefs


def test_audio_preferences_persist_across_reads(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings.set_audio_preferences(settings_path, capture_system=False, capture_microphone=True)
    reloaded = settings.get_audio_preferences(settings_path)
    assert reloaded["capture_system"] is False
    assert reloaded["capture_microphone"] is True


def test_audio_preferences_coexist_with_meetings_root(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings.set_meetings_root(settings_path, tmp_path / "Raiz")
    settings.set_audio_preferences(settings_path, capture_microphone=True)

    assert settings.get_meetings_root(settings_path) == (tmp_path / "Raiz").resolve()
    assert settings.get_audio_preferences(settings_path)["capture_microphone"] is True
