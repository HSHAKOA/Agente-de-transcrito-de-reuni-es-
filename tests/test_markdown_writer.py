from pathlib import Path

from meeting_transcriber.markdown_writer import MarkdownWriter, format_timestamp
from meeting_transcriber.transcriber import Segment


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(65) == "00:01:05"
    assert format_timestamp(3661) == "01:01:01"


def test_incremental_write(tmp_path: Path):
    out = tmp_path / "out.md"
    writer = MarkdownWriter(out, title="Teste", model_size="small", language="pt")

    writer.append_segments([Segment(start=3.2, end=5.0, text="Ola pessoal")])
    writer.append_segments([Segment(start=310.0, end=312.0, text="Segundo bloco")])
    writer.finalize(duration_seconds=320.0)

    content = out.read_text(encoding="utf-8")
    assert "# Teste" in content
    assert "**Modelo Whisper:** small" in content
    assert "**[00:00:03]** Ola pessoal" in content
    assert "**[00:05:10]** Segundo bloco" in content
    assert "Duracao total gravada: 00:05:20" in content


def test_append_empty_segments_is_noop(tmp_path: Path):
    out = tmp_path / "out.md"
    writer = MarkdownWriter(out, title="Teste", model_size="tiny", language=None)
    before = out.read_text(encoding="utf-8")
    writer.append_segments([])
    assert out.read_text(encoding="utf-8") == before
