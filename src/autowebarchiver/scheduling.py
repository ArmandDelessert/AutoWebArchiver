from __future__ import annotations

import logging
import time
from collections import deque

from .config import Settings
from .discovery.models import DiscoveredItem
from .spn2.client import AlreadyArchivedError, SPN2Client
from .spn2.models import SPN2Result, result_from_status_payload
from .state.store import SeenStore, normalize_url

logger = logging.getLogger(__name__)


def _urgency_key(item: DiscoveredItem) -> tuple[bool, str]:
    """Sort key putting the oldest-dated items first. Items closest to falling
    out of a rotating feed/sitemap (lowest publish/lastmod date) are the most
    urgent to capture before they're lost; items with no date are treated as
    least urgent (sorted last) since we can't tell how close they are to
    expiring. Applying this uniformly (rather than only to feeds known to be
    size-limited) is harmless for exhaustive sitemaps too -- order barely
    matters there, and processing their oldest content first is in fact what
    we want, never silently skipping old articles in favor of newer ones."""
    return (item.published_at is None, item.published_at or "")


class SourceScheduler:
    """Picks which item to submit next across multiple sources, applying three
    rules in order: (1) within a source, the most urgent (oldest-dated) item
    goes first; (2) any source with items left is guaranteed at least
    `min_reserved` of the concurrent in-flight slots once one frees up, even
    if another source represents the bulk of the queue -- this floor applies
    to every source, including exhaustive ones, so a large historical backlog
    still makes steady progress every run, just never dominates; (3) beyond
    that floor, slots are filled in proportion to each source's remaining
    share, but the proportional pool is restricted to non-exhaustive sources
    while any of them still have items -- exhaustive sources (sitemaps/feeds
    listing a site's entire history, where nothing is ever at risk of being
    lost) only compete for spare capacity once every time-sensitive source is
    satisfied for this slot-fill, so a huge historical sitemap can't crowd out
    urgent captures just because it has the largest raw item count.

    Tie-breaks (multiple sources simultaneously starved, or tied on
    emitted/total ratio) rotate through sources round-robin rather than
    always favoring whichever source happens to be listed first in
    sources.yaml. Without this, if the real concurrent-capture capacity ever
    falls below the number of active sources, sources placed early in the
    config permanently win every tie and the last-listed source can be
    starved out completely, for as long as any earlier source still has
    items -- this actually happened to whichever source ended up last once
    4 large sitemaps were added, and isn't specific to that source's site,
    just its position in the file."""

    def __init__(self, items: list[DiscoveredItem], exhaustive: dict[str, bool] | None = None):
        self._exhaustive = exhaustive or {}
        self._queues: dict[str, deque[DiscoveredItem]] = {}
        self._total: dict[str, int] = {}
        self._emitted: dict[str, int] = {}
        for item in items:
            if item.source not in self._queues:
                self._queues[item.source] = deque()
                self._total[item.source] = 0
                self._emitted[item.source] = 0
            self._queues[item.source].append(item)
            self._total[item.source] += 1
        for source, queue in self._queues.items():
            self._queues[source] = deque(sorted(queue, key=_urgency_key))
        self._order: list[str] = list(self._queues.keys())
        self._rotate_from = 0  # index into _order; advances past whichever source we last picked

    def __len__(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def _rotated(self, candidates: set[str]) -> list[str]:
        """`candidates` reordered to start just after the last pick, so a set
        of tied sources cycles through fairly across repeated calls instead
        of always resolving to the same (earliest-configured) member."""
        return [s for s in self._order[self._rotate_from :] + self._order[: self._rotate_from] if s in candidates]

    def pop_next(self, in_flight_count_by_source: dict[str, int], min_reserved: int) -> DiscoveredItem | None:
        active = {source for source, queue in self._queues.items() if queue}
        if not active:
            return None

        starved = {s for s in active if in_flight_count_by_source.get(s, 0) < min_reserved}
        if starved:
            source = self._rotated(starved)[0]
        else:
            urgent = {s for s in active if not self._exhaustive.get(s, False)}
            pool = urgent or active  # fall back to exhaustive sources if nothing urgent remains
            # min() breaks ties by picking the first candidate in the input
            # order, so feeding it the rotated order makes ties round-robin
            # instead of always favoring the same source.
            source = min(self._rotated(pool), key=lambda s: self._emitted[s] / self._total[s])

        self._rotate_from = (self._order.index(source) + 1) % len(self._order)
        self._emitted[source] += 1
        return self._queues[source].popleft()


def _save_quietly(store: SeenStore, min_interval_seconds: float = 0.0) -> None:
    """Persist state, but skip the write if the last one happened less than
    `min_interval_seconds` ago. Bounds worst-case data loss (if the process is
    killed externally, e.g. a canceled CI job) to roughly that interval instead
    of the whole run, while avoiding a full-file JSON rewrite after every
    single mutation -- with thousands of tracked URLs now, writing on every
    submit/resolve made the file rewrite itself a real, growing cost. Pass
    min_interval_seconds=0 (the default) to always write, e.g. for a final,
    unconditional flush."""
    now = time.monotonic()
    last_flush = store._last_flush_monotonic
    if last_flush is not None and now - last_flush < min_interval_seconds:
        return
    try:
        store.save()
    except OSError as exc:
        logger.error("Could not write state file: %s", exc)
    else:
        store._last_flush_monotonic = now


def _record_result(store: SeenStore, result: SPN2Result, settings: Settings) -> bool | None:
    """Returns whether the job will be retried next run, or None when that
    question doesn't apply (status other than "error")."""
    will_retry = None
    if result.status == "success":
        store.mark_resolved(result.url, status="success", job_id=result.job_id)
        logger.info('Archived "%s" -> "%s"', result.url, result.wayback_url)
    elif result.status == "error":
        will_retry = store.mark_error(
            result.url,
            retryable=result.is_retryable_error,
            max_attempts=settings.max_capture_attempts,
            job_id=result.job_id,
        )
        logger.error(
            'SPN2 error for "%s": %s (%s)%s',
            result.url,
            result.message,
            result.status_ext,
            " - will retry next run" if will_retry else " - giving up",
        )
    else:
        # status == "timeout": leave it marked as pending so it gets repolled next run.
        logger.warning("Job for %s is still pending after polling timeout", result.url)
        return will_retry
    _save_quietly(store, settings.state_save_interval_seconds)
    return will_retry


def _submit(
    client: SPN2Client, store: SeenStore, url: str, settings: Settings
) -> tuple[str | None, str, bool | None]:
    """Submit a single capture request for an already-normalized URL. Returns
    (job_id, outcome, will_retry). job_id is only set when outcome == "submitted"
    (a capture job was created and needs polling). Otherwise there's nothing to
    poll: "already_archived" means SPN2 already had a recent-enough capture
    (not an error), "error" means the submit genuinely failed (marked for a
    bounded retry). will_retry is only meaningful when outcome == "error"."""
    try:
        job_id = client.submit(
            url,
            capture_screenshot=settings.capture_screenshot,
            capture_outlinks=settings.capture_outlinks,
            skip_first_archive=settings.skip_first_archive,
            if_not_archived_within=settings.if_not_archived_within,
            js_behavior_timeout=settings.js_behavior_timeout,
        )
    except AlreadyArchivedError as exc:
        logger.info('"%s" is already archived recently enough, skipping (%s)', url, exc)
        store.mark_resolved(url, status="already_archived")
        _save_quietly(store, settings.state_save_interval_seconds)
        return None, "already_archived", None
    except Exception as exc:  # noqa: BLE001 - isolate failures per URL
        logger.error('Failed to submit "%s" for capture: %s', url, exc)
        # A submit failure is almost always transient (network/SPN2 hiccup),
        # so keep it eligible for a bounded number of retries.
        will_retry = store.mark_error(url, retryable=True, max_attempts=settings.max_capture_attempts)
        _save_quietly(store, settings.state_save_interval_seconds)
        return None, "error", will_retry
    store.mark_pending(url, job_id)
    _save_quietly(store, settings.state_save_interval_seconds)
    return job_id, "submitted", None


def _poll_once(
    client: SPN2Client,
    store: SeenStore,
    in_flight: dict[str, tuple[str, str, float]],
    settings: Settings,
    counts: dict[str, int],
) -> None:
    """Poll every in-flight job (job_id -> (url, source, deadline)) exactly once.
    Resolved jobs are recorded and removed; jobs past their per-job deadline are
    left pending for the next run, UNLESS the entry has been pending for longer
    than settings.pending_job_max_age_hours -- SPN2 only keeps job status "for
    a limited time", so a job that old is unlikely to ever resolve and is given
    up on (retried like any other transient failure) instead of being polled
    forever. Mutates in_flight and counts in place."""
    now = time.monotonic()
    for job_id, (url, _source, deadline) in list(in_flight.items()):
        try:
            payload = client.get_status(job_id)
        except Exception as exc:  # noqa: BLE001 - isolate failures; stays pending for next run
            logger.error('Failed to poll job %s for "%s": %s', job_id, url, exc)
            counts["pending"] += 1
            del in_flight[job_id]
            continue
        result = result_from_status_payload(job_id, url, payload)
        if result is not None:
            will_retry = _record_result(store, result, settings)
            counts[result.status] += 1
            if result.status == "error":
                counts["error_retry" if will_retry else "error_permanent"] += 1
            del in_flight[job_id]
        elif now >= deadline:
            if store.is_pending_stale(url, settings.pending_job_max_age_hours):
                will_retry = store.mark_error(url, retryable=True, max_attempts=settings.max_capture_attempts)
                logger.warning(
                    'Giving up polling "%s": still pending after %.0fh (SPN2 likely no longer has its status)%s',
                    url,
                    settings.pending_job_max_age_hours,
                    " - will retry next run" if will_retry else " - giving up for good",
                )
                _save_quietly(store, settings.state_save_interval_seconds)
                counts["error"] += 1
                counts["error_retry" if will_retry else "error_permanent"] += 1
            else:
                logger.warning('Job for "%s" is still pending after polling timeout', url)
                counts["pending"] += 1
            del in_flight[job_id]


def _poll_jobs(
    client: SPN2Client, store: SeenStore, jobs: dict[str, str], settings: Settings
) -> dict[str, int]:
    """Poll a fixed set of jobs (job_id -> url) until each resolves or times out."""
    counts = {"success": 0, "error": 0, "pending": 0, "already_archived": 0, "error_retry": 0, "error_permanent": 0}
    deadline = time.monotonic() + settings.poll_timeout_seconds
    # No per-source scheduling happens here, so the source slot is unused ("").
    in_flight = {job_id: (url, "", deadline) for job_id, url in jobs.items()}
    while in_flight:
        _poll_once(client, store, in_flight, settings, counts)
        if in_flight:
            time.sleep(settings.poll_interval_seconds)
    return counts


def poll_leftovers(client: SPN2Client, store: SeenStore, settings: Settings) -> dict[str, int]:
    """Resolve jobs left pending by a previous run."""
    jobs = {
        entry["spn2_job_id"]: url
        for url, entry in store.pending_entries().items()
        if entry.get("spn2_job_id")
    }
    return _poll_jobs(client, store, jobs, settings)


def archive_new_urls(
    client: SPN2Client,
    store: SeenStore,
    items: list[DiscoveredItem],
    settings: Settings,
    exhaustive: dict[str, bool] | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], int]:
    """Archive newly discovered URLs with a single-threaded sliding window: keep
    up to `concurrency` captures in flight, submitting a new one as soon as a slot
    frees and the per-minute rate allows, until the time budget runs out.
    Submitting and polling are both quick HTTP calls, so one thread interleaves
    them -- no threads or asyncio needed (the throughput ceiling is SPN2's 7
    submissions/min, not our local concurrency). Which item gets the next slot
    is decided by SourceScheduler -- see its docstring for the scheduling rules.

    Returns (counts, already_archived_by_source, rate_limited_by_source,
    deferred_count): the aggregate outcome counts, per-source breakdowns of
    the "already_archived" outcome and of 429 (rate-limited) responses, and
    how many URLs were left unsubmitted when the time budget ran out."""
    counts = {"success": 0, "error": 0, "pending": 0, "already_archived": 0, "error_retry": 0, "error_permanent": 0}
    already_archived_by_source: dict[str, int] = {}
    rate_limited_by_source: dict[str, int] = {}

    # Normalize and de-duplicate (a URL can appear under several feeds, or with
    # different tracking params that normalize to the same canonical URL).
    new_items: list[DiscoveredItem] = []
    seen_normalized: set[str] = set()
    for item in items:
        normalized = normalize_url(item.url)
        if normalized in seen_normalized or store.is_known(item.url):
            continue
        seen_normalized.add(normalized)
        new_items.append(item)
    logger.info("%d new URL(s) to archive out of %d discovered", len(new_items), len(items))

    try:
        user_status = client.get_user_status()
        available = user_status.get("available", settings.max_concurrent_spn2_jobs)
    except Exception as exc:  # noqa: BLE001 - never let a status check abort the run
        logger.warning("Could not fetch SPN2 user status (%s), assuming default capacity", exc)
        available = settings.max_concurrent_spn2_jobs

    concurrency = max(1, min(settings.max_concurrent_spn2_jobs, available))
    logger.info(
        "Using %d concurrent slot(s) (SPN2 reports %d available, cap is %d) across %d source(s)",
        concurrency,
        available,
        settings.max_concurrent_spn2_jobs,
        len({item.source for item in new_items}),
    )
    scheduler = SourceScheduler(new_items, exhaustive)
    in_flight: dict[str, tuple[str, str, float]] = {}
    run_deadline = time.monotonic() + settings.max_run_seconds

    while True:
        now = time.monotonic()
        accepting = now < run_deadline  # stop submitting once the time budget is spent

        in_flight_count_by_source: dict[str, int] = {}
        for _url, source, _deadline in in_flight.values():
            in_flight_count_by_source[source] = in_flight_count_by_source.get(source, 0) + 1

        # Fill free concurrency slots while the per-minute rate allows.
        while (
            accepting
            and len(scheduler)
            and len(in_flight) < concurrency
            and client.next_submit_wait_seconds() == 0
        ):
            next_item: DiscoveredItem | None = scheduler.pop_next(
                in_flight_count_by_source, settings.min_concurrent_slots_per_source
            )
            if next_item is None:
                break
            item = next_item
            url = normalize_url(item.url)
            rate_limited_before = client.rate_limited_count
            job_id, outcome, will_retry = _submit(client, store, url, settings)
            rate_limited_delta = client.rate_limited_count - rate_limited_before
            if rate_limited_delta:
                rate_limited_by_source[item.source] = (
                    rate_limited_by_source.get(item.source, 0) + rate_limited_delta
                )
            if outcome != "submitted":
                counts[outcome] += 1
                if outcome == "already_archived":
                    already_archived_by_source[item.source] = already_archived_by_source.get(item.source, 0) + 1
                elif outcome == "error":
                    counts["error_retry" if will_retry else "error_permanent"] += 1
                continue
            assert job_id is not None  # guaranteed by _submit when outcome == "submitted"
            in_flight[job_id] = (url, item.source, time.monotonic() + settings.poll_timeout_seconds)
            in_flight_count_by_source[item.source] = in_flight_count_by_source.get(item.source, 0) + 1

        _poll_once(client, store, in_flight, settings, counts)

        # Done once nothing is in flight and we won't submit anything more.
        if not in_flight and (not accepting or not len(scheduler)):
            break

        # Sleep until the next thing can happen: a poll cycle for in-flight jobs,
        # or the next free rate slot if we still have URLs waiting to be submitted.
        waits: list[float] = []
        if in_flight:
            waits.append(settings.poll_interval_seconds)
        if accepting and len(scheduler) and len(in_flight) < concurrency:
            waits.append(client.next_submit_wait_seconds())
        if not waits:
            break
        time.sleep(min(waits))

    deferred_count = len(scheduler)
    if deferred_count:
        logger.warning(
            "Stopped after the %ds run budget; %d URL(s) deferred to the next run",
            settings.max_run_seconds,
            deferred_count,
        )

    return counts, already_archived_by_source, rate_limited_by_source, deferred_count
