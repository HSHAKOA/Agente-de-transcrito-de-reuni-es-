from __future__ import annotations

from pathlib import Path

import pytest

from meeting_transcriber.scheduling import validation as sv
from meeting_transcriber.scheduling.models import RECURRENCE_CUSTOM_DAYS, RECURRENCE_WEEKLY


def test_validate_title_requires_non_empty():
    with pytest.raises(sv.ValidationError):
        sv.validate_title("   ")


def test_validate_title_strips_and_accepts():
    assert sv.validate_title("  Aula  ") == "Aula"


def test_validate_date_accepts_iso():
    assert sv.validate_date("2026-09-15") == "2026-09-15"


def test_validate_date_rejects_garbage():
    with pytest.raises(sv.ValidationError):
        sv.validate_date("15/09/2026")


def test_validate_time_accepts_hhmm():
    assert sv.validate_time("19:00") == "19:00"
    assert sv.validate_time("00:00") == "00:00"
    assert sv.validate_time("23:59") == "23:59"


def test_validate_time_rejects_invalid():
    for bad in ("24:00", "9:00", "19:60", "abc", ""):
        with pytest.raises(sv.ValidationError):
            sv.validate_time(bad)


def test_validate_timezone_accepts_valid_iana():
    assert sv.validate_timezone("America/Sao_Paulo") == "America/Sao_Paulo"


def test_validate_timezone_rejects_unknown():
    with pytest.raises(sv.ValidationError):
        sv.validate_timezone("Nao/Existe")


def test_validate_duration_end_before_start_same_day_within_cap_still_treated_as_overnight():
    # 19:00 -> 18:00 "no mesmo dia" e sempre interpretado como virada de
    # meia-noite (23h de duracao) -- e rejeitado por estourar o teto de
    # duracao razoavel, nao por uma regra separada de "fim < inicio".
    with pytest.raises(sv.ValidationError):
        sv.validate_duration("2026-09-15", "19:00", "18:00", "America/Sao_Paulo")


def test_validate_duration_allows_overnight_short_window():
    sv.validate_duration("2026-09-15", "23:00", "01:00", "America/Sao_Paulo")  # nao deve lancar


def test_validate_duration_rejects_zero_length():
    with pytest.raises(sv.ValidationError):
        sv.validate_duration("2026-09-15", "19:00", "19:00", "America/Sao_Paulo")


def test_validate_duration_rejects_exceeding_max():
    with pytest.raises(sv.ValidationError):
        sv.validate_duration("2026-09-15", "08:00", "22:00", "America/Sao_Paulo")  # 14h > 12h


def test_validate_duration_accepts_normal_window():
    sv.validate_duration("2026-09-15", "19:00", "20:40", "America/Sao_Paulo")  # nao deve lancar


def test_validate_recurrence_defaults_to_once_when_none():
    rec = sv.validate_recurrence(None)
    assert rec.type == "once"


def test_validate_recurrence_weekly_requires_exactly_one_day():
    with pytest.raises(sv.ValidationError):
        sv.validate_recurrence({"type": RECURRENCE_WEEKLY, "days": [0, 1]})
    rec = sv.validate_recurrence({"type": RECURRENCE_WEEKLY, "days": [0]})
    assert rec.days == [0]


def test_validate_recurrence_custom_days_requires_at_least_one():
    with pytest.raises(sv.ValidationError):
        sv.validate_recurrence({"type": RECURRENCE_CUSTOM_DAYS, "days": []})


def test_validate_recurrence_rejects_unknown_type():
    with pytest.raises(sv.ValidationError):
        sv.validate_recurrence({"type": "nonsense"})


def test_validate_device_id_allows_none():
    assert sv.validate_device_id(None, "Microfone") is None


def test_validate_device_id_rejects_non_string():
    with pytest.raises(sv.ValidationError):
        sv.validate_device_id(123, "Microfone")


def test_validate_meetings_root_resolves_path(tmp_path: Path):
    result = sv.validate_meetings_root(str(tmp_path / "Faculdade"))
    assert result == (tmp_path / "Faculdade").resolve()
