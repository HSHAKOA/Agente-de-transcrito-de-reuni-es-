from pathlib import Path

import pytest

from meeting_transcriber.validation import (
    ValidationError,
    check_folder_health,
    validate_chunk_seconds,
    validate_device,
    validate_language,
    validate_meeting_id,
    validate_meetings_root_path,
    validate_model,
    validate_output_filename,
    validate_title,
)


# -- model / device -----------------------------------------------------

@pytest.mark.parametrize("value", ["tiny", "base", "small", "medium", "large-v3"])
def test_validate_model_accepts_allowlist(value):
    assert validate_model(value) == value


@pytest.mark.parametrize("value", ["qualquer_coisa", "", None, 123, "tiny;rm -rf", ["small"]])
def test_validate_model_rejects_anything_else(value):
    with pytest.raises(ValidationError):
        validate_model(value)


@pytest.mark.parametrize("value", ["cpu", "cuda"])
def test_validate_device_accepts_allowlist(value):
    assert validate_device(value) == value


@pytest.mark.parametrize("value", ["shell", "gpu", "", None, 1, "cpu && echo hi"])
def test_validate_device_rejects_anything_else(value):
    with pytest.raises(ValidationError):
        validate_device(value)


# -- language -------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [("pt", "pt"), ("EN", "en"), ("auto", "auto"), (" pt ", "pt")])
def test_validate_language_accepts_valid_codes(value, expected):
    assert validate_language(value) == expected


@pytest.mark.parametrize("value", ["", "1", "pt-br-xx-yy", None, 5, "pt; DROP TABLE"])
def test_validate_language_rejects_invalid(value):
    with pytest.raises(ValidationError):
        validate_language(value)


# -- chunk_seconds ----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [(300, 300), ("300", 300), (5, 5), (1800, 1800), (30.0, 30)])
def test_validate_chunk_seconds_accepts_valid_range(value, expected):
    assert validate_chunk_seconds(value) == expected


@pytest.mark.parametrize(
    "value",
    [-1, 0, 4, 1801, 999_999_999, "abc", None, [], {}, True, False, 30.5],
)
def test_validate_chunk_seconds_rejects_invalid(value):
    with pytest.raises(ValidationError):
        validate_chunk_seconds(value)


# -- title ------------------------------------------------------------------

def test_validate_title_uses_default_when_missing():
    assert validate_title(None) == "Transcricao de reuniao"
    assert validate_title("") == "Transcricao de reuniao"
    assert validate_title("   ") == "Transcricao de reuniao"


def test_validate_title_strips_and_accepts_normal_text():
    assert validate_title("  Reuniao de Sexta  ") == "Reuniao de Sexta"


def test_validate_title_rejects_huge_title():
    with pytest.raises(ValidationError):
        validate_title("x" * 500)


def test_validate_title_rejects_non_string():
    with pytest.raises(ValidationError):
        validate_title(12345)


# -- output filename (path traversal) ---------------------------------------

def test_validate_output_filename_accepts_plain_name(tmp_path: Path):
    result = validate_output_filename("reuniao.md", tmp_path)
    assert result == (tmp_path.resolve() / "reuniao.md")


def test_validate_output_filename_appends_md_extension(tmp_path: Path):
    result = validate_output_filename("reuniao", tmp_path)
    assert result.name == "reuniao.md"


def test_validate_output_filename_uses_default_when_missing(tmp_path: Path):
    result = validate_output_filename(None, tmp_path)
    assert result.name == "transcricao.md"


@pytest.mark.parametrize(
    "malicious",
    [
        "../../arquivo.md",
        "..\\..\\arquivo.md",
        "../etc/passwd",
        "..",
        ".",
        "/etc/passwd",
        "C:\\Windows\\teste.md",
        "sub/dir.md",
        "sub\\dir.md",
        ".hidden.md",
    ],
)
def test_validate_output_filename_rejects_path_traversal(tmp_path: Path, malicious):
    with pytest.raises(ValidationError):
        validate_output_filename(malicious, tmp_path)


def test_validate_output_filename_rejects_huge_name(tmp_path: Path):
    with pytest.raises(ValidationError):
        validate_output_filename("x" * 500 + ".md", tmp_path)


def test_validate_output_filename_rejects_non_string(tmp_path: Path):
    with pytest.raises(ValidationError):
        validate_output_filename(12345, tmp_path)


@pytest.mark.parametrize("reserved", ["CON.md", "con", "NUL.md", "COM1.md", "lpt1"])
def test_validate_output_filename_rejects_windows_reserved_names(tmp_path: Path, reserved):
    with pytest.raises(ValidationError):
        validate_output_filename(reserved, tmp_path)


def test_validate_output_filename_result_always_confined_to_base_dir(tmp_path: Path):
    result = validate_output_filename("qualquer.md", tmp_path)
    assert result.parent == tmp_path.resolve()


# -- meeting id ---------------------------------------------------------

def test_validate_meeting_id_accepts_generated_format():
    assert validate_meeting_id("20260914-153000-ab12ef") == "20260914-153000-ab12ef"


@pytest.mark.parametrize("value", ["../etc", "..\\etc", "a/b", "a b", "", None, "x" * 200])
def test_validate_meeting_id_rejects_invalid(value):
    with pytest.raises(ValidationError):
        validate_meeting_id(value)


# -- meetings root path (pasta escolhida pelo usuario) -----------------------

def test_validate_meetings_root_path_resolves_and_expands(tmp_path: Path):
    result = validate_meetings_root_path(str(tmp_path))
    assert result == tmp_path.resolve()


@pytest.mark.parametrize("value", ["", "   ", None, 123, [], {}])
def test_validate_meetings_root_path_rejects_empty_or_wrong_type(value):
    with pytest.raises(ValidationError):
        validate_meetings_root_path(value)


def test_validate_meetings_root_path_does_not_require_existing_folder(tmp_path: Path):
    # validacao pura so confere o formato do caminho -- existir/ser gravavel
    # e responsabilidade de check_folder_health (que de fato toca o disco)
    candidate = tmp_path / "ainda-nao-existe"
    result = validate_meetings_root_path(str(candidate))
    assert result == candidate.resolve()


# -- check_folder_health ------------------------------------------------

def test_check_folder_health_ok_for_healthy_writable_folder(tmp_path: Path):
    health = check_folder_health(tmp_path)
    assert health.ok is True
    assert health.free_bytes is not None and health.free_bytes > 0


def test_check_folder_health_rejects_missing_folder(tmp_path: Path):
    health = check_folder_health(tmp_path / "nao-existe")
    assert health.ok is False
    assert "nao existe" in health.message.lower() or "não existe" in health.message.lower()


def test_check_folder_health_rejects_path_that_is_a_file(tmp_path: Path):
    file_path = tmp_path / "arquivo.txt"
    file_path.write_text("x", encoding="utf-8")
    health = check_folder_health(file_path)
    assert health.ok is False


def test_check_folder_health_rejects_low_disk_space(tmp_path: Path, monkeypatch):
    import shutil as shutil_module

    fake_usage = shutil_module.disk_usage(tmp_path)._replace(free=1024)  # 1 KB, bem abaixo do minimo
    monkeypatch.setattr("meeting_transcriber.validation.shutil.disk_usage", lambda p: fake_usage)

    health = check_folder_health(tmp_path)
    assert health.ok is False
    assert health.free_bytes == 1024


def test_check_folder_health_rejects_when_write_probe_fails(tmp_path: Path):
    def _boom(path):
        raise OSError("permissao negada (simulado)")

    health = check_folder_health(tmp_path, write_probe=_boom)
    assert health.ok is False
    assert health.free_bytes is not None  # ja tinha passado da checagem de espaco


def test_check_folder_health_leaves_no_probe_file_behind(tmp_path: Path):
    check_folder_health(tmp_path)
    assert list(tmp_path.iterdir()) == []
