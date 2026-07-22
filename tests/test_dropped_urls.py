import json

from autowebarchiver.state.dropped_urls import DroppedUrlsStore
from autowebarchiver.state.feed_stats import DroppedUrl


def test_record_appends_one_entry_per_dropped_url(tmp_path):
    store = DroppedUrlsStore(tmp_path / "dropped_urls.json")

    store.record(
        "lemonde.fr",
        [
            DroppedUrl(url="https://example.com/a", reason="never_attempted"),
            DroppedUrl(url="https://example.com/b", reason="gave_up"),
        ],
    )

    assert len(store._entries) == 2
    assert store._entries[0]["source"] == "lemonde.fr"
    assert store._entries[0]["url"] == "https://example.com/a"
    assert store._entries[0]["reason"] == "never_attempted"
    assert store._entries[1]["reason"] == "gave_up"
    assert "timestamp" in store._entries[0]


def test_record_with_no_dropped_urls_is_a_no_op(tmp_path):
    store = DroppedUrlsStore(tmp_path / "dropped_urls.json")

    store.record("lemonde.fr", [])

    assert store._entries == []


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "dropped_urls.json"
    store = DroppedUrlsStore(path)
    store.record("s", [DroppedUrl(url="https://example.com/a", reason="gave_up")])
    store.save()

    on_disk = json.loads(path.read_text())
    assert len(on_disk) == 1
    assert on_disk[0]["url"] == "https://example.com/a"

    reloaded = DroppedUrlsStore(path)
    reloaded.record("s", [DroppedUrl(url="https://example.com/b", reason="never_attempted")])
    assert len(reloaded._entries) == 2


def test_purge_older_than_removes_stale_entries(tmp_path):
    store = DroppedUrlsStore(tmp_path / "dropped_urls.json")
    store.record("s", [DroppedUrl(url="https://example.com/old", reason="gave_up")])
    store._entries[0]["timestamp"] = "2000-01-01T00:00:00Z"
    store.record("s", [DroppedUrl(url="https://example.com/new", reason="gave_up")])

    purged = store.purge_older_than(days=90)

    assert purged == 1
    assert len(store._entries) == 1
    assert store._entries[0]["url"] == "https://example.com/new"
