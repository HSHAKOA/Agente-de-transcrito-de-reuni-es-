from __future__ import annotations

import json

import pytest

from meeting_transcriber.export import EXPORTERS, render
from meeting_transcriber.export._timecodes import format_timecode


def _meeting(**overrides) -> dict:
    data = dict(
        id="m1", title="Reuniao Projeto ERP", status="completed",
        started_at="2026-09-15T19:00:00+00:00", finished_at="2026-09-15T20:00:00+00:00",
        duration_seconds=3661.0, language="pt", model="small",
    )
    data.update(overrides)
    return data


def _segments():
    return [
        {"sequence": 0, "start_seconds": 0.0, "end_seconds": 5.0, "text": "Ola a todos.", "speaker_label": "Você"},
        {"sequence": 1, "start_seconds": 5.0, "end_seconds": 10.0, "text": "Vamos comecar.", "speaker_label": None},
    ]


# -- timecode ---------------------------------------------------------------

def test_format_timecode_srt_style():
    assert format_timecode(3661.5, ",") == "01:01:01,500"


def test_format_timecode_vtt_style():
    assert format_timecode(0.0, ".") == "00:00:00.000"


def test_format_timecode_never_negative():
    assert format_timecode(-5.0, ",") == "00:00:00,000"


# -- txt ----------------------------------------------------------------

def test_txt_includes_title_and_speaker_labels():
    text = render("txt", _meeting(), _segments())
    assert "Reuniao Projeto ERP" in text
    assert "Você: Ola a todos." in text
    assert "Vamos comecar." in text  # sem label, sem prefixo


# -- json -----------------------------------------------------------------

def test_json_is_valid_and_round_trips():
    text = render("json", _meeting(), _segments())
    data = json.loads(text)
    assert data["meeting"]["id"] == "m1"
    assert len(data["segments"]) == 2
    assert data["segments"][0]["text"] == "Ola a todos."


def test_json_never_includes_raw_python_repr():
    text = render("json", _meeting(), [])
    assert "None" not in text or json.loads(text)  # deve ser JSON valido (null, nao "None")


# -- markdown ---------------------------------------------------------------

def test_markdown_includes_metadata_and_transcript():
    text = render("markdown", _meeting(), _segments())
    assert "# Reuniao Projeto ERP" in text
    assert "## Metadados" in text
    assert "## Transcricao" in text
    assert "**[00:00:00]**" in text
    assert "**Você**" in text


def test_markdown_never_includes_empty_summary_sections():
    text = render("markdown", _meeting(), _segments())
    assert "## Resumo" not in text
    assert "## Decisões" not in text
    assert "## Tarefas" not in text


def test_markdown_handles_no_segments():
    text = render("markdown", _meeting(), [])
    assert "Nenhum segmento" in text


# -- srt --------------------------------------------------------------------

def test_srt_format_is_well_formed():
    text = render("srt", _meeting(), _segments())
    blocks = text.strip().split("\n\n")
    assert len(blocks) == 2
    first_lines = blocks[0].splitlines()
    assert first_lines[0] == "1"
    assert first_lines[1] == "00:00:00,000 --> 00:00:05,000"
    assert "Ola a todos." in first_lines[2]


def test_srt_sequential_numbering():
    text = render("srt", _meeting(), _segments())
    assert text.strip().startswith("1\n")
    assert "\n2\n" in text


def test_srt_zero_duration_segment_gets_minimum_duration():
    segments = [{"sequence": 0, "start_seconds": 5.0, "end_seconds": 5.0, "text": "x", "speaker_label": None}]
    text = render("srt", _meeting(), segments)
    assert "00:00:05,000 --> 00:00:05,500" in text


# -- vtt ----------------------------------------------------------------

def test_vtt_starts_with_header():
    text = render("vtt", _meeting(), _segments())
    assert text.startswith("WEBVTT\n")


def test_vtt_uses_dot_separator_not_comma():
    text = render("vtt", _meeting(), _segments())
    assert "00:00:00.000 --> 00:00:05.000" in text
    assert "," not in text.split("\n\n")[1] if len(text.split("\n\n")) > 1 else True


def test_vtt_includes_all_segments():
    text = render("vtt", _meeting(), _segments())
    assert "Ola a todos." in text
    assert "Vamos comecar." in text


# -- render() dispatch --------------------------------------------------

def test_render_rejects_unknown_format():
    with pytest.raises(ValueError):
        render("docx", _meeting(), _segments())


def test_all_registered_exporters_handle_empty_segments():
    for fmt in EXPORTERS:
        result = render(fmt, _meeting(), [])
        assert isinstance(result, str)


def test_all_registered_exporters_handle_missing_optional_metadata():
    minimal_meeting = {"id": "m1", "title": None, "status": "completed"}
    for fmt in EXPORTERS:
        result = render(fmt, minimal_meeting, _segments())
        assert isinstance(result, str)
        assert len(result) > 0
