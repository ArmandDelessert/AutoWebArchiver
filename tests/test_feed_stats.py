import json

from autowebarchiver.discovery.models import DiscoveredItem
from autowebarchiver.state.feed_stats import FeedStatsStore
from autowebarchiver.state.store import SeenStore


def _item(url, published_at=None):
    return DiscoveredItem(url=url, title=None, published_at=published_at, source="s")


def test_first_run_has_no_drops():
    stats_store = FeedStatsStore("unused.json")  # not saved in this test
    seen = SeenStore("unused-seen.json")
    items = [_item("https://e.com/a"), _item("https://e.com/b")]

    stats, dropped = stats_store.record("rts.ch", items, new_count=2, seen_store=seen)

    assert stats.item_count == 2
    assert stats.new_count == 2
    assert stats.dropped_count == 0
    assert stats.dropped_unarchived_count == 0
    assert dropped == []


def test_dropped_unarchived_is_flagged(tmp_path):
    stats_store = FeedStatsStore(tmp_path / "feed_stats.json")
    seen = SeenStore(tmp_path / "seen.json")

    # Run 1: two items seen, only one ever gets archived.
    stats_store.record("rts.ch", [_item("https://e.com/a"), _item("https://e.com/b")], 2, seen)
    seen.mark_resolved("https://e.com/a", status="success")

    # Run 2: "b" fell out of the feed without ever being archived; "a" did too,
    # but it doesn't count since it was successfully captured.
    stats, dropped = stats_store.record("rts.ch", [_item("https://e.com/c")], 1, seen)

    assert stats.dropped_count == 2
    assert stats.dropped_unarchived_count == 1
    assert len(dropped) == 1
    assert dropped[0].url == "https://e.com/b"
    assert dropped[0].reason == "never_attempted"


def test_published_at_coverage_tracks_min_max():
    stats_store = FeedStatsStore("unused.json")
    seen = SeenStore("unused-seen.json")
    items = [
        _item("https://e.com/a", published_at="2026-06-25T10:00:00Z"),
        _item("https://e.com/b", published_at="2026-06-25T08:00:00Z"),
        _item("https://e.com/c", published_at=None),
    ]

    stats, _ = stats_store.record("letemps.ch", items, new_count=3, seen_store=seen)

    assert stats.oldest_published_at == "2026-06-25T08:00:00Z"
    assert stats.newest_published_at == "2026-06-25T10:00:00Z"


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "feed_stats.json"
    stats_store = FeedStatsStore(path)
    seen = SeenStore(tmp_path / "seen.json")
    stats_store.record("rts.ch", [_item("https://e.com/a")], 1, seen)
    stats_store.save()

    on_disk = json.loads(path.read_text())
    assert on_disk["rts.ch"]["last_urls"] == ["https://e.com/a"]
    assert len(on_disk["rts.ch"]["history"]) == 1

    reloaded = FeedStatsStore(path)
    stats, _ = reloaded.record("rts.ch", [_item("https://e.com/a")], 0, seen)
    assert stats.dropped_count == 0  # "a" is still present, not dropped


def test_dropped_reason_breakdown(tmp_path):
    stats_store = FeedStatsStore(tmp_path / "feed_stats.json")
    seen = SeenStore(tmp_path / "seen.json")

    seen.mark_error("https://e.com/gave-up", retryable=False, max_attempts=3)
    seen.mark_error("https://e.com/retrying", retryable=True, max_attempts=3)
    seen.mark_pending("https://e.com/in-flight", "job-1")
    # "https://e.com/never-tried" has no entry at all in seen_store.

    stats_store.record(
        "rts.ch",
        [
            _item("https://e.com/gave-up"),
            _item("https://e.com/retrying"),
            _item("https://e.com/in-flight"),
            _item("https://e.com/never-tried"),
        ],
        new_count=1,
        seen_store=seen,
    )
    _, dropped = stats_store.record("rts.ch", [], new_count=0, seen_store=seen)

    reasons = {d.url: d.reason for d in dropped}
    assert reasons["https://e.com/gave-up"] == "gave_up"
    assert reasons["https://e.com/retrying"] == "still_retrying"
    assert reasons["https://e.com/in-flight"] == "still_pending"
    assert reasons["https://e.com/never-tried"] == "never_attempted"


def test_record_already_archived_attaches_to_latest_history_entry(tmp_path):
    path = tmp_path / "feed_stats.json"
    stats_store = FeedStatsStore(path)
    seen = SeenStore(tmp_path / "seen.json")

    stats_store.record("rts.ch", [_item("https://e.com/a")], new_count=1, seen_store=seen)
    stats_store.record_already_archived("rts.ch", 3)
    stats_store.save()

    on_disk = json.loads(path.read_text())
    assert on_disk["rts.ch"]["history"][-1]["already_archived_count"] == 3


def test_record_already_archived_is_noop_for_unknown_source(tmp_path):
    stats_store = FeedStatsStore(tmp_path / "feed_stats.json")
    # Must not raise even though "unknown.ch" was never record()-ed.
    stats_store.record_already_archived("unknown.ch", 5)


def test_record_rate_limited_attaches_to_latest_history_entry(tmp_path):
    path = tmp_path / "feed_stats.json"
    stats_store = FeedStatsStore(path)
    seen = SeenStore(tmp_path / "seen.json")

    stats_store.record("rts.ch", [_item("https://e.com/a")], new_count=1, seen_store=seen)
    stats_store.record_rate_limited("rts.ch", 7)
    stats_store.save()

    on_disk = json.loads(path.read_text())
    assert on_disk["rts.ch"]["history"][-1]["rate_limited_count"] == 7


def test_record_rate_limited_is_noop_for_unknown_source(tmp_path):
    stats_store = FeedStatsStore(tmp_path / "feed_stats.json")
    stats_store.record_rate_limited("unknown.ch", 2)


def test_exhaustive_source_skips_drop_tracking_and_last_urls(tmp_path):
    path = tmp_path / "feed_stats.json"
    stats_store = FeedStatsStore(path)
    seen = SeenStore(tmp_path / "seen.json")
    items = [_item(f"https://big.example/{i}") for i in range(5000)]

    stats, dropped = stats_store.record("big-sitemap", items, new_count=5000, seen_store=seen, exhaustive=True)
    stats_store.save()

    assert stats.dropped_count is None
    assert stats.dropped_unarchived_count is None
    assert dropped == []

    # The whole point: no 5000-URL list persisted to disk for an exhaustive
    # source, which is what made feed_stats.json balloon in practice.
    on_disk = json.loads(path.read_text())
    assert on_disk["big-sitemap"]["last_urls"] == []

    # A later run doesn't spuriously report drops either (nothing was stored
    # to diff against).
    stats2, dropped2 = stats_store.record(
        "big-sitemap", items[:100], new_count=0, seen_store=seen, exhaustive=True
    )
    assert stats2.dropped_count is None
    assert dropped2 == []


def test_purge_older_than_removes_stale_history(tmp_path):
    stats_store = FeedStatsStore(tmp_path / "feed_stats.json")
    seen = SeenStore(tmp_path / "seen.json")
    stats_store.record("rts.ch", [_item("https://e.com/a")], 1, seen)
    stats_store._sources["rts.ch"]["history"][0]["timestamp"] = "2000-01-01T00:00:00Z"
    stats_store.record("rts.ch", [_item("https://e.com/b")], 1, seen)

    purged = stats_store.purge_older_than(days=90)

    assert purged == 1
    assert len(stats_store._sources["rts.ch"]["history"]) == 1
