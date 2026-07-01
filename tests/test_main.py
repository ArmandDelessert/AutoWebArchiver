import autowebarchiver.main as main
from autowebarchiver.config import Settings
from autowebarchiver.discovery.models import DiscoveredItem
from autowebarchiver.spn2.client import AlreadyArchivedError
from autowebarchiver.state.store import SeenStore


class FakeClient:
    """Records the order of submit/status calls so tests can assert that a whole
    wave is submitted before it is polled (i.e. captures run concurrently)."""

    def __init__(self, status_by_url, available=10, already_archived_urls=()):
        self._status_by_url = status_by_url
        self.available = available
        self._already_archived_urls = set(already_archived_urls)
        self.calls = []  # ordered log of ("submit" | "status", url)
        self._job_url = {}
        self._n = 0

    def get_user_status(self):
        return {"available": self.available}

    def next_submit_wait_seconds(self):
        return 0.0

    def submit(self, url, **kwargs):
        self.calls.append(("submit", url))
        if url in self._already_archived_urls:
            raise AlreadyArchivedError("The same snapshot had been made 1 hour ago.")
        self._n += 1
        job_id = f"job-{self._n}"
        self._job_url[job_id] = url
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

    counts, _ = main.archive_new_urls(client, store, items, _settings(max_concurrent_spn2_jobs=10))

    assert counts["success"] == 3
    # One wave of 3: all submits happen before any status poll (decoupled).
    assert _kinds(client) == ["submit", "submit", "submit", "status", "status", "status"]
    assert all(store.is_known(it.url) for it in items)


def test_archive_processes_in_waves_bounded_by_concurrency(tmp_path):
    items = _items(5)
    client = FakeClient({it.url: _success(it.url) for it in items}, available=2)
    store = SeenStore(tmp_path / "seen.json")

    main.archive_new_urls(client, store, items, _settings(max_concurrent_spn2_jobs=2))

    # wave_size = min(2, available=2) -> waves of 2, 2, 1.
    assert _kinds(client)[:2] == ["submit", "submit"]
    # The first wave must be polled before the third URL is ever submitted.
    third_submit_idx = [i for i, (k, _) in enumerate(client.calls) if k == "submit"][2]
    assert any(k == "status" for k, _ in client.calls[:third_submit_idx])


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
    settings = _settings(max_concurrent_spn2_jobs=10, max_capture_attempts=3)

    counts, _ = main.archive_new_urls(client, store, [item], settings)
    assert counts["error"] == 1
    assert not store.is_known(item.url)  # transient -> eligible for retry

    # A subsequent run re-submits the same URL.
    main.archive_new_urls(client, store, [item], settings)
    assert len([c for c in client.calls if c[0] == "submit"]) == 2


def test_already_archived_is_not_counted_as_an_error(tmp_path):
    item = _items(1)[0]  # source="s"
    client = FakeClient({}, available=10, already_archived_urls={item.url})
    store = SeenStore(tmp_path / "seen.json")
    settings = _settings(max_concurrent_spn2_jobs=10)

    counts, already_archived_by_source = main.archive_new_urls(client, store, [item], settings)

    assert counts == {"success": 0, "error": 0, "pending": 0, "already_archived": 1}
    assert already_archived_by_source == {"s": 1}
    assert store.is_known(item.url)
    assert store.is_archived(item.url)
    # No status polling should ever happen -- there was no job to poll.
    assert not any(kind == "status" for kind, _ in client.calls)

    # A subsequent run does not re-submit it.
    main.archive_new_urls(client, store, [item], settings)
    assert len([c for c in client.calls if c[0] == "submit"]) == 1


def test_scheduler_orders_oldest_first_within_a_source():
    items = [
        DiscoveredItem(url="newest", title=None, published_at="2026-06-03T00:00:00Z", source="a"),
        DiscoveredItem(url="undated", title=None, published_at=None, source="a"),
        DiscoveredItem(url="oldest", title=None, published_at="2026-06-01T00:00:00Z", source="a"),
    ]

    scheduler = main.SourceScheduler(items)
    order = [scheduler.pop_next({}, min_reserved=1).url for _ in range(3)]

    # Oldest published date first; undated items (unknown urgency) come last.
    assert order == ["oldest", "newest", "undated"]


def test_scheduler_guarantees_minimum_slots_for_minority_source():
    items = [DiscoveredItem(url=f"a{i}", title=None, published_at=None, source="a") for i in range(9)]
    items.append(DiscoveredItem(url="b0", title=None, published_at=None, source="b"))
    scheduler = main.SourceScheduler(items)

    # Even though "a" has 9x the volume and already fills 9 of 10 concurrent
    # slots, "b" still has an item and 0 in-flight slots (< min_reserved=1):
    # the next pick must go to "b", not pile more onto the dominant source.
    picked = scheduler.pop_next({"a": 9, "b": 0}, min_reserved=1)
    assert picked.source == "b"


def test_scheduler_falls_back_to_proportional_once_minimum_is_met():
    items = [DiscoveredItem(url=f"a{i}", title=None, published_at=None, source="a") for i in range(8)]
    items += [DiscoveredItem(url=f"b{i}", title=None, published_at=None, source="b") for i in range(2)]
    scheduler = main.SourceScheduler(items)

    # Both sources are always reported as already meeting the reserved
    # minimum, so every pick goes through the proportional branch: "b"'s 2
    # items should land interleaved across the run (not clumped at either
    # end), roughly in proportion to its 20% share of the 10 items -- not
    # starved-prioritized, but not starved-out either. The exact tie-break
    # order is an implementation detail (see the rotation regression test
    # below), so only the interleaving property is asserted here.
    in_flight = {"a": 1, "b": 1}
    picks = [scheduler.pop_next(in_flight, min_reserved=1).source for _ in range(10)]

    assert picks.count("b") == 2
    assert picks[0] == "a"  # "a" starts furthest behind proportionally (tied at 0, first in order)
    assert picks[-1] != "b"  # "b"'s 2 picks should not both land at the very end (clumped)


def test_scheduler_rotates_ties_instead_of_starving_last_source():
    # Regression test for the bug found in production: when several sources
    # are simultaneously starved (or tied) on every pick -- which happens
    # whenever the real concurrent-capture capacity is lower than the number
    # of active sources -- pop_next used to always resolve the tie in favor
    # of whichever source was listed earliest in sources.yaml, permanently
    # starving the last-listed source (apreslabiere.fr, purely because of its
    # position in the file, not anything about that site) for as long as any
    # earlier source still had items.
    items = []
    for name in ["a", "b", "c", "d"]:
        items += [
            DiscoveredItem(url=f"{name}{i}", title=None, published_at=None, source=name) for i in range(50)
        ]
    scheduler = main.SourceScheduler(items)

    # Every call sees all sources with 0 in-flight, as if real concurrency
    # never lets more than one source's slot persist between decisions --
    # the worst case for a fixed tie-break order.
    picks = [scheduler.pop_next({}, min_reserved=1).source for _ in range(8)]

    from collections import Counter

    counts = Counter(picks)
    assert set(counts) == {"a", "b", "c", "d"}
    assert counts["d"] >= 2  # "d" is last in config order -- the one that used to starve


def test_scheduler_demotes_exhaustive_sources_behind_urgent_ones():
    # "huge" has way more items (and thus a much lower emitted/total ratio),
    # but it's flagged exhaustive: it must not crowd out "urgent" beyond the
    # guaranteed floor, even though pure proportional fairness would favor it.
    items = [DiscoveredItem(url=f"h{i}", title=None, published_at=None, source="huge") for i in range(100)]
    items += [DiscoveredItem(url=f"u{i}", title=None, published_at=None, source="urgent") for i in range(5)]
    scheduler = main.SourceScheduler(items, exhaustive={"huge": True, "urgent": False})

    # Past the initial floor (both already have 1 in flight), every further
    # pick should still go to "urgent" while it has items left -- "huge" is
    # excluded from the proportional pool entirely, not just deprioritized.
    in_flight = {"huge": 1, "urgent": 1}
    picks = [scheduler.pop_next(in_flight, min_reserved=1).source for _ in range(4)]

    assert picks == ["urgent", "urgent", "urgent", "urgent"]


def test_scheduler_uses_exhaustive_source_once_urgent_is_drained():
    items = [DiscoveredItem(url=f"h{i}", title=None, published_at=None, source="huge") for i in range(3)]
    items.append(DiscoveredItem(url="u0", title=None, published_at=None, source="urgent"))
    scheduler = main.SourceScheduler(items, exhaustive={"huge": True, "urgent": False})

    in_flight = {"huge": 1, "urgent": 1}
    scheduler.pop_next(in_flight, min_reserved=1)  # drains "urgent"'s only item

    # No urgent items left at all: spare capacity goes to the exhaustive
    # source rather than sitting idle.
    picked = scheduler.pop_next(in_flight, min_reserved=1)
    assert picked.source == "huge"


def test_archive_submits_normalized_url(tmp_path):
    raw = "https://www.rts.ch/article-1.html?rts_source=rss_t"
    clean = "https://www.rts.ch/article-1.html"
    item = DiscoveredItem(url=raw, title=None, published_at=None, source="rts.ch")
    client = FakeClient({clean: _success(clean)}, available=10)
    store = SeenStore(tmp_path / "seen.json")

    counts, _ = main.archive_new_urls(client, store, [item], _settings(max_concurrent_spn2_jobs=10))

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

    counts, _ = main.archive_new_urls(client, store, items, _settings(max_concurrent_spn2_jobs=10))

    assert counts["success"] == 1
    assert len([c for c in client.calls if c[0] == "submit"]) == 1


def test_archive_defers_everything_when_run_budget_is_zero(tmp_path):
    items = _items(3)
    client = FakeClient({it.url: _success(it.url) for it in items}, available=10)
    store = SeenStore(tmp_path / "seen.json")

    counts, _ = main.archive_new_urls(
        client, store, items, _settings(max_concurrent_spn2_jobs=10, max_run_seconds=0)
    )

    # Time budget spent before submitting anything: nothing captured, nothing
    # marked known, so every URL is retried on the next run.
    assert counts == {"success": 0, "error": 0, "pending": 0, "already_archived": 0}
    assert not any(kind == "submit" for kind, _ in client.calls)
    assert all(not store.is_known(it.url) for it in items)


def test_save_quietly_throttles_writes(tmp_path, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("autowebarchiver.main.time.monotonic", lambda: clock["t"])
    store = SeenStore(tmp_path / "seen.json")
    save_calls = []
    monkeypatch.setattr(store, "save", lambda: save_calls.append(clock["t"]))

    main._save_quietly(store, min_interval_seconds=20)
    main._save_quietly(store, min_interval_seconds=20)  # too soon, skipped
    assert save_calls == [1000.0]

    clock["t"] = 1015.0
    main._save_quietly(store, min_interval_seconds=20)  # still too soon
    assert save_calls == [1000.0]

    clock["t"] = 1021.0
    main._save_quietly(store, min_interval_seconds=20)  # interval elapsed
    assert save_calls == [1000.0, 1021.0]

    # min_interval_seconds=0 (the default, e.g. a final unconditional flush)
    # always writes regardless of how recently the last one happened.
    main._save_quietly(store)
    assert save_calls == [1000.0, 1021.0, 1021.0]


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
