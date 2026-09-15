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
