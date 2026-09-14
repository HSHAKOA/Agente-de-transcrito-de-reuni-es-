from pathlib import Path

import pytest

from meeting_transcriber.validation import (
    ValidationError,
    validate_chunk_seconds,
    validate_device,
    validate_language,
    validate_meeting_id,
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
