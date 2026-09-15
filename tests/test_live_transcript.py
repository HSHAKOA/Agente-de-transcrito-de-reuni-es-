from __future__ import annotations

from meeting_transcriber.live.segments import STATE_COMMITTED, STATE_PROVISIONAL, LiveSegment
from meeting_transcriber.live.transcript import LiveTranscript


def _prov(start, end, text, source="mixed"):
    return LiveSegment(start, end, text, STATE_PROVISIONAL, source)


def _comm(start, end, text, source="mixed"):
    return LiveSegment(start, end, text, STATE_COMMITTED, source)


def test_add_provisional_appears_in_snapshot():
    t = LiveTranscript()
    t.add_provisional(_prov(0, 8, "ola mundo"))
    snap = t.snapshot()
    assert len(snap["segments"]) == 1
    assert snap["segments"][0]["text"] == "ola mundo"
    assert snap["segments"][0]["state"] == "provisional"


def test_segments_sorted_by_start():
    t = LiveTranscript()
    t.add_provisional(_prov(8, 16, "segundo"))
    t.add_provisional(_prov(0, 8, "primeiro"))
    snap = t.snapshot()
    assert [s["text"] for s in snap["segments"]] == ["primeiro", "segundo"]


def test_reprocessed_window_replaces_previous_provisional_at_same_start():
    t = LiveTranscript()
    t.add_provisional(_prov(0, 8, "texto errado"))
    t.add_provisional(_prov(0, 8, "texto corrigido"))
    snap = t.snapshot()
    assert len(snap["segments"]) == 1
    assert snap["segments"][0]["text"] == "texto corrigido"


def test_commit_range_replaces_overlapping_provisional_segments():
    t = LiveTranscript()
    t.add_provisional(_prov(0, 8, "provisorio um"))
    t.add_provisional(_prov(8, 16, "provisorio dois"))
    t.commit_range(0, 16, [_comm(0, 7.5, "Definitivo um."), _comm(7.5, 16, "Definitivo dois.")])

    snap = t.snapshot()
    texts = [s["text"] for s in snap["segments"]]
    states = {s["state"] for s in snap["segments"]}
    assert texts == ["Definitivo um.", "Definitivo dois."]
    assert states == {"committed"}


def test_commit_range_never_touches_segments_outside_its_range():
    t = LiveTranscript()
    t.add_provisional(_prov(0, 8, "dentro"))
    t.add_provisional(_prov(20, 28, "fora"))
    t.commit_range(0, 8, [_comm(0, 8, "Dentro definitivo.")])

    snap = t.snapshot()
    by_text = {s["text"]: s["state"] for s in snap["segments"]}
    assert by_text["Dentro definitivo."] == "committed"
    assert by_text["fora"] == "provisional"


def test_committed_segments_never_overwritten_by_a_later_commit_of_different_range():
    t = LiveTranscript()
    t.commit_range(0, 8, [_comm(0, 8, "primeiro chunk")])
    t.commit_range(8, 16, [_comm(8, 16, "segundo chunk")])
    snap = t.snapshot()
    assert [s["text"] for s in snap["segments"]] == ["primeiro chunk", "segundo chunk"]


def test_backlog_classifies_live_when_caught_up():
    t = LiveTranscript()
    t.set_recorded_seconds(60)
    t.commit_range(0, 60, [_comm(0, 60, "tudo transcrito")])
    backlog = t.backlog()
    assert backlog["status"] == "LIVE"
    assert backlog["pending_seconds"] == 0.0


def test_backlog_classifies_processing_when_moderately_behind():
    t = LiveTranscript()
    t.set_recorded_seconds(70)
    t.commit_range(0, 60, [_comm(0, 60, "x")])
    backlog = t.backlog()
    assert backlog["status"] == "PROCESSING"
    assert backlog["pending_seconds"] == 10.0


def test_backlog_classifies_behind_when_far_behind():
    t = LiveTranscript()
    t.set_recorded_seconds(200)
    t.commit_range(0, 60, [_comm(0, 60, "x")])
    backlog = t.backlog()
    assert backlog["status"] == "BEHIND"


def test_snapshot_reports_average_latency():
    t = LiveTranscript()
    t.record_latency(1.0)
    t.record_latency(3.0)
    snap = t.snapshot()
    assert snap["avg_latency_seconds"] == 2.0


def test_snapshot_latency_none_when_no_data():
    t = LiveTranscript()
    assert t.snapshot()["avg_latency_seconds"] is None


def test_model_load_seconds_reported():
    t = LiveTranscript()
    t.set_model_load_seconds(4.2)
    assert t.snapshot()["model_load_seconds"] == 4.2


def test_concurrent_writes_do_not_corrupt_segment_list():
    import threading

    t = LiveTranscript()

    def _writer(offset):
        for i in range(50):
            t.add_provisional(_prov(offset + i, offset + i + 1, f"seg-{offset}-{i}"))

    threads = [threading.Thread(target=_writer, args=(base,)) for base in (0, 1000, 2000, 3000)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    snap = t.snapshot()
    assert len(snap["segments"]) == 200
    starts = [s["start_seconds"] for s in snap["segments"]]
    assert starts == sorted(starts)
