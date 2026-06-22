import json

from autowebarchiver.state.store import SeenStore, normalize_url


def test_normalize_url_strips_tracking_params():
    url = "https://example.com/article?utm_source=twitter&id=42#section"
    assert normalize_url(url) == "https://example.com/article?id=42"


def test_seen_store_roundtrip(tmp_path):
    state_path = tmp_path / "seen.json"
    store = SeenStore(state_path)

    assert not store.is_known("https://example.com/a")

    store.mark_pending("https://example.com/a", "job-1")
    assert store.is_known("https://example.com/a")
    assert len(store.pending_entries()) == 1

    store.mark_resolved("https://example.com/a", status="success", job_id="job-1")
    assert len(store.pending_entries()) == 0

    store.save()

    reloaded = SeenStore(state_path)
    assert reloaded.is_known("https://example.com/a")

    on_disk = json.loads(state_path.read_text())
    assert on_disk["https://example.com/a"]["status"] == "success"


def test_seen_store_dedup_via_normalized_url(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    store.mark_resolved("https://example.com/a?utm_source=foo", status="success")

    assert store.is_known("https://example.com/a?utm_source=bar")


def test_purge_older_than_removes_stale_entries(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    store.mark_resolved("https://example.com/old", status="success")
    store._entries["https://example.com/old"]["first_seen"] = "2000-01-01T00:00:00Z"

    store.mark_resolved("https://example.com/recent", status="success")

    purged = store.purge_older_than(days=90)

    assert purged == 1
    assert not store.is_known("https://example.com/old")
    assert store.is_known("https://example.com/recent")


def test_purge_keeps_pending_entries_regardless_of_age(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    store.mark_pending("https://example.com/in-flight", "job-1")
    store._entries["https://example.com/in-flight"]["first_seen"] = "2000-01-01T00:00:00Z"

    purged = store.purge_older_than(days=90)

    assert purged == 0
    assert store.is_known("https://example.com/in-flight")
