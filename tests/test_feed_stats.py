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

    stats = stats_store.record("rts.ch", items, new_count=2, seen_store=seen)

    assert stats.item_count == 2
    assert stats.new_count == 2
    assert stats.dropped_count == 0
    assert stats.dropped_unarchived_count == 0


def test_dropped_unarchived_is_flagged(tmp_path):
    stats_store = FeedStatsStore(tmp_path / "feed_stats.json")
    seen = SeenStore(tmp_path / "seen.json")

    # Run 1: two items seen, only one ever gets archived.
    stats_store.record("rts.ch", [_item("https://e.com/a"), _item("https://e.com/b")], 2, seen)
    seen.mark_resolved("https://e.com/a", status="success")

    # Run 2: "b" fell out of the feed without ever being archived; "a" did too,
    # but it doesn't count since it was successfully captured.
    stats = stats_store.record("rts.ch", [_item("https://e.com/c")], 1, seen)

    assert stats.dropped_count == 2
    assert stats.dropped_unarchived_count == 1


def test_published_at_coverage_tracks_min_max():
    stats_store = FeedStatsStore("unused.json")
    seen = SeenStore("unused-seen.json")
    items = [
        _item("https://e.com/a", published_at="2026-06-25T10:00:00Z"),
        _item("https://e.com/b", published_at="2026-06-25T08:00:00Z"),
        _item("https://e.com/c", published_at=None),
    ]

    stats = stats_store.record("letemps.ch", items, new_count=3, seen_store=seen)

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
    stats = reloaded.record("rts.ch", [_item("https://e.com/a")], 0, seen)
    assert stats.dropped_count == 0  # "a" is still present, not dropped


def test_purge_older_than_removes_stale_history(tmp_path):
    stats_store = FeedStatsStore(tmp_path / "feed_stats.json")
    seen = SeenStore(tmp_path / "seen.json")
    stats_store.record("rts.ch", [_item("https://e.com/a")], 1, seen)
    stats_store._sources["rts.ch"]["history"][0]["timestamp"] = "2000-01-01T00:00:00Z"
    stats_store.record("rts.ch", [_item("https://e.com/b")], 1, seen)

    purged = stats_store.purge_older_than(days=90)

    assert purged == 1
    assert len(stats_store._sources["rts.ch"]["history"]) == 1
