import autowebarchiver.main as main
from autowebarchiver.config import Settings
from autowebarchiver.discovery.models import DiscoveredItem
from autowebarchiver.state.store import SeenStore


class FakeClient:
    """Records the order of submit/status calls so tests can assert that a whole
    wave is submitted before it is polled (i.e. captures run concurrently)."""

    def __init__(self, status_by_url, available=10):
        self._status_by_url = status_by_url
        self.available = available
        self.calls = []  # ordered log of ("submit" | "status", url)
        self._job_url = {}
        self._n = 0

    def get_user_status(self):
        return {"available": self.available}

    def next_submit_wait_seconds(self):
        return 0.0

    def submit(self, url, **kwargs):
        self._n += 1
        job_id = f"job-{self._n}"
        self._job_url[job_id] = url
        self.calls.append(("submit", url))
        return job_id

    def get_status(self, job_id):
        url = self._job_url[job_id]
        self.calls.append(("status", url))
        return self._status_by_url[url]


def _items(n):
    return [
        DiscoveredItem(url=f"https://e.com/{i}", title=None, published_at=None, source="s")
        for i in range(n)
    ]


def _success(url):
    return {
        "status": "success",
        "job_id": "x",
        "original_url": url,
        "timestamp": "20240101000000",
    }


def _settings(**over):
    return Settings(poll_interval_seconds=0, poll_timeout_seconds=5, **over)


def _kinds(client):
    return [kind for kind, _ in client.calls]


def test_archive_submits_whole_wave_before_polling(tmp_path):
    items = _items(3)
    client = FakeClient({it.url: _success(it.url) for it in items}, available=10)
    store = SeenStore(tmp_path / "seen.json")

    counts = main.archive_new_urls(
        client, store, items, _settings(max_concurrent_spn2_jobs=10, max_captures_per_run=60)
    )

    assert counts["success"] == 3
    # One wave of 3: all submits happen before any status poll (decoupled).
    assert _kinds(client) == ["submit", "submit", "submit", "status", "status", "status"]
    assert all(store.is_known(it.url) for it in items)


def test_archive_processes_in_waves_bounded_by_concurrency(tmp_path):
    items = _items(5)
    client = FakeClient({it.url: _success(it.url) for it in items}, available=2)
    store = SeenStore(tmp_path / "seen.json")

    main.archive_new_urls(
        client, store, items, _settings(max_concurrent_spn2_jobs=2, max_captures_per_run=60)
    )

    # wave_size = min(2, available=2) -> waves of 2, 2, 1.
    assert _kinds(client)[:2] == ["submit", "submit"]
    # The first wave must be polled before the third URL is ever submitted.
    third_submit_idx = [i for i, (k, _) in enumerate(client.calls) if k == "submit"][2]
    assert any(k == "status" for k, _ in client.calls[:third_submit_idx])


def test_archive_respects_per_run_budget(tmp_path):
    items = _items(5)
    client = FakeClient({it.url: _success(it.url) for it in items}, available=10)
    store = SeenStore(tmp_path / "seen.json")

    counts = main.archive_new_urls(
        client, store, items, _settings(max_concurrent_spn2_jobs=10, max_captures_per_run=2)
    )

    assert counts["success"] == 2
    assert len([c for c in client.calls if c[0] == "submit"]) == 2


def test_retryable_error_is_resubmitted_on_next_run(tmp_path):
    item = _items(1)[0]
    bad_gateway = {
        "status": "error",
        "job_id": "x",
        "status_ext": "error:bad-gateway",
        "message": "Bad Gateway",
    }
    client = FakeClient({item.url: bad_gateway}, available=10)
    store = SeenStore(tmp_path / "seen.json")
    settings = _settings(max_concurrent_spn2_jobs=10, max_captures_per_run=60, max_capture_attempts=3)

    counts = main.archive_new_urls(client, store, [item], settings)
    assert counts["error"] == 1
    assert not store.is_known(item.url)  # transient -> eligible for retry

    # A subsequent run re-submits the same URL.
    main.archive_new_urls(client, store, [item], settings)
    assert len([c for c in client.calls if c[0] == "submit"]) == 2


def test_interleave_by_source_round_robins():
    items = [
        DiscoveredItem(url="a0", title=None, published_at=None, source="a"),
        DiscoveredItem(url="a1", title=None, published_at=None, source="a"),
        DiscoveredItem(url="a2", title=None, published_at=None, source="a"),
        DiscoveredItem(url="b0", title=None, published_at=None, source="b"),
        DiscoveredItem(url="b1", title=None, published_at=None, source="b"),
    ]

    result = main._interleave_by_source(items)

    assert [it.source for it in result] == ["a", "b", "a", "b", "a"]
    assert [it.url for it in result] == ["a0", "b0", "a1", "b1", "a2"]


def test_archive_submits_normalized_url(tmp_path):
    raw = "https://www.rts.ch/article-1.html?rts_source=rss_t"
    clean = "https://www.rts.ch/article-1.html"
    item = DiscoveredItem(url=raw, title=None, published_at=None, source="rts.ch")
    client = FakeClient({clean: _success(clean)}, available=10)
    store = SeenStore(tmp_path / "seen.json")

    counts = main.archive_new_urls(
        client, store, [item], _settings(max_concurrent_spn2_jobs=10, max_captures_per_run=60)
    )

    assert counts["success"] == 1
    # The tracking param is stripped before submission, so the capture is clean.
    assert [url for kind, url in client.calls if kind == "submit"] == [clean]
    assert store.is_known(raw)


def test_archive_dedupes_urls_differing_only_by_tracking_param(tmp_path):
    items = [
        DiscoveredItem(url="https://e.com/a?rts_source=rss_t", title=None, published_at=None, source="s"),
        DiscoveredItem(url="https://e.com/a", title=None, published_at=None, source="s"),
    ]
    client = FakeClient({"https://e.com/a": _success("https://e.com/a")}, available=10)
    store = SeenStore(tmp_path / "seen.json")

    counts = main.archive_new_urls(
        client, store, items, _settings(max_concurrent_spn2_jobs=10, max_captures_per_run=60)
    )

    assert counts["success"] == 1
    assert len([c for c in client.calls if c[0] == "submit"]) == 1


def test_poll_leftovers_resolves_previous_run_pending(tmp_path):
    item = _items(1)[0]
    client = FakeClient({item.url: _success(item.url)}, available=10)
    store = SeenStore(tmp_path / "seen.json")
    store.mark_pending(item.url, "job-1")
    client._job_url["job-1"] = item.url  # simulate the job from a previous run

    counts = main.poll_leftovers(client, store, _settings())

    assert counts["success"] == 1
    assert store.is_known(item.url)
    assert len(store.pending_entries()) == 0
