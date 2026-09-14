from pathlib import Path

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
