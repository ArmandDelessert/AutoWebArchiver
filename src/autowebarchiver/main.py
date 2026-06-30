from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from pathlib import Path

from dotenv import load_dotenv

from .config import ConfigError, Settings, Source, load_config
from .discovery.models import DiscoveredItem
from .discovery.rss import discover_rss
from .discovery.sitemap import discover_sitemap
from .logging_setup import setup_logging
from .spn2.client import SPN2Client
from .spn2.models import SPN2Result, result_from_status_payload
from .state.feed_stats import FeedStatsStore
from .state.store import SeenStore, normalize_url

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "sources.yaml"
DEFAULT_STATE_PATH = REPO_ROOT / "state" / "seen.json"
DEFAULT_FEED_STATS_PATH = REPO_ROOT / "state" / "feed_stats.json"


class FatalError(Exception):
    """Raised for errors that should abort the whole run with a non-zero exit code."""


def discover_source(source: Source) -> list[DiscoveredItem]:
    if source.type == "rss":
        return discover_rss(source.name, source.url)
    if source.type == "sitemap":
        return discover_sitemap(source.name, source.url, source.url_pattern)
    raise FatalError(f"Unknown source type '{source.type}' for {source.name}")


def _poll_once(
    client: SPN2Client,
    store: SeenStore,
    in_flight: dict[str, tuple[str, float]],
    settings: Settings,
    counts: dict[str, int],
) -> None:
    """Poll every in-flight job (job_id -> (url, deadline)) exactly once. Resolved
    jobs are recorded and removed; jobs past their per-job deadline are left
    pending for the next run. Mutates in_flight and counts in place."""
    now = time.monotonic()
    for job_id, (url, deadline) in list(in_flight.items()):
        try:
            payload = client.get_status(job_id)
        except Exception as exc:  # noqa: BLE001 - isolate failures; stays pending for next run
            logger.error('Failed to poll job %s for "%s": %s', job_id, url, exc)
            counts["pending"] += 1
            del in_flight[job_id]
            continue
        result = result_from_status_payload(job_id, url, payload)
        if result is not None:
            _record_result(store, result, settings)
            counts[result.status] += 1
            del in_flight[job_id]
        elif now >= deadline:
            logger.warning('Job for "%s" is still pending after polling timeout', url)
            counts["pending"] += 1
            del in_flight[job_id]


def _poll_jobs(
    client: SPN2Client, store: SeenStore, jobs: dict[str, str], settings: Settings
) -> dict[str, int]:
    """Poll a fixed set of jobs (job_id -> url) until each resolves or times out."""
    counts = {"success": 0, "error": 0, "pending": 0}
    deadline = time.monotonic() + settings.poll_timeout_seconds
    in_flight = {job_id: (url, deadline) for job_id, url in jobs.items()}
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


def _submit(client: SPN2Client, store: SeenStore, url: str, settings: Settings) -> str | None:
    """Submit a single capture request for an already-normalized URL. Returns its
    job_id, or None if the submit failed (the URL is then marked for a bounded
    retry)."""
    try:
        job_id = client.submit(
            url,
            capture_screenshot=settings.capture_screenshot,
            capture_outlinks=settings.capture_outlinks,
            skip_first_archive=settings.skip_first_archive,
            if_not_archived_within=settings.if_not_archived_within,
            js_behavior_timeout=settings.js_behavior_timeout,
        )
    except Exception as exc:  # noqa: BLE001 - isolate failures per URL
        logger.error('Failed to submit "%s" for capture: %s', url, exc)
        # A submit failure is almost always transient (network/SPN2 hiccup),
        # so keep it eligible for a bounded number of retries.
        store.mark_error(url, retryable=True, max_attempts=settings.max_capture_attempts)
        _save_quietly(store)
        return None
    store.mark_pending(url, job_id)
    _save_quietly(store)
    return job_id


def _save_quietly(store: SeenStore) -> None:
    """Persist state immediately after every mutation. If the process is killed
    externally (e.g. a canceled CI job) mid-run, this bounds the data loss to the
    single in-flight HTTP call instead of the whole run, since nothing was
    previously durable until the final save() at the end of run()."""
    try:
        store.save()
    except OSError as exc:
        logger.error("Could not write state file: %s", exc)


def _interleave_by_source(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    """Round-robin items across their source so consecutive captures hit
    different hosts. This keeps per-host concurrency low and avoids SPN2's
    same-host throttling (429) and target-site anti-bot blocks (403/502) that
    occur when many captures target one host at once."""
    buckets: dict[str, deque[DiscoveredItem]] = {}
    order: list[str] = []
    for item in items:
        if item.source not in buckets:
            buckets[item.source] = deque()
            order.append(item.source)
        buckets[item.source].append(item)

    result: list[DiscoveredItem] = []
    while len(result) < len(items):
        for source in order:
            if buckets[source]:
                result.append(buckets[source].popleft())
    return result


def archive_new_urls(
    client: SPN2Client, store: SeenStore, items: list[DiscoveredItem], settings: Settings
) -> dict[str, int]:
    """Archive newly discovered URLs with a single-threaded sliding window: keep
    up to `concurrency` captures in flight, submitting a new one as soon as a slot
    frees and the per-minute rate allows, until the time budget runs out.
    Submitting and polling are both quick HTTP calls, so one thread interleaves
    them -- no threads or asyncio needed (the throughput ceiling is SPN2's 7
    submissions/min, not our local concurrency). URLs are submitted round-robin
    across sources to spread load over hosts."""
    counts = {"success": 0, "error": 0, "pending": 0}

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
    queued = deque(_interleave_by_source(new_items))
    in_flight: dict[str, tuple[str, float]] = {}
    run_deadline = time.monotonic() + settings.max_run_seconds

    while True:
        now = time.monotonic()
        accepting = now < run_deadline  # stop submitting once the time budget is spent

        # Fill free concurrency slots while the per-minute rate allows.
        while (
            accepting
            and queued
            and len(in_flight) < concurrency
            and client.next_submit_wait_seconds() == 0
        ):
            url = normalize_url(queued.popleft().url)
            job_id = _submit(client, store, url, settings)
            if job_id is None:
                counts["error"] += 1
                continue
            in_flight[job_id] = (url, time.monotonic() + settings.poll_timeout_seconds)

        _poll_once(client, store, in_flight, settings, counts)

        # Done once nothing is in flight and we won't submit anything more.
        if not in_flight and (not accepting or not queued):
            break

        # Sleep until the next thing can happen: a poll cycle for in-flight jobs,
        # or the next free rate slot if we still have URLs waiting to be submitted.
        waits = []
        if in_flight:
            waits.append(settings.poll_interval_seconds)
        if accepting and queued and len(in_flight) < concurrency:
            waits.append(client.next_submit_wait_seconds())
        if not waits:
            break
        time.sleep(min(waits))

    if queued:
        logger.warning(
            "Stopped after the %ds run budget; %d URL(s) deferred to the next run",
            settings.max_run_seconds,
            len(queued),
        )

    return counts


def _record_result(store: SeenStore, result: SPN2Result, settings: Settings) -> None:
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
        return
    _save_quietly(store)


def run(
    config_path: Path = DEFAULT_CONFIG_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    feed_stats_path: Path = DEFAULT_FEED_STATS_PATH,
) -> int:
    setup_logging()
    load_dotenv()

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    access_key = os.environ.get("ARCHIVE_ORG_ACCESS_KEY")
    secret_key = os.environ.get("ARCHIVE_ORG_SECRET_KEY")
    if not access_key or not secret_key:
        logger.error(
            "Missing ARCHIVE_ORG_ACCESS_KEY/ARCHIVE_ORG_SECRET_KEY environment variables"
        )
        return 1

    store = SeenStore(state_path)
    feed_stats = FeedStatsStore(feed_stats_path)
    client = SPN2Client(
        access_key, secret_key, max_captures_per_minute=config.settings.max_captures_per_minute
    )

    totals = {"success": 0, "error": 0, "pending": 0}

    leftover_counts = poll_leftovers(client, store, config.settings)
    for key, value in leftover_counts.items():
        totals[key] += value

    discovered: list[DiscoveredItem] = []
    for source in config.sources:
        try:
            items = discover_source(source)
            new_count = sum(1 for item in items if not store.is_known(item.url))
            logger.info("Discovered %d item(s) from %s", len(items), source.name)
            stats, dropped_unarchived = feed_stats.record(source.name, items, new_count, store)
            coverage = (
                f", coverage {stats.oldest_published_at}..{stats.newest_published_at}"
                if stats.oldest_published_at and stats.newest_published_at
                else ""
            )
            logger.info(
                "Feed stats for %s: %d new, %d dropped (%d never archived)%s",
                source.name,
                stats.new_count,
                stats.dropped_count,
                stats.dropped_unarchived_count,
                coverage,
            )
            if dropped_unarchived:
                reason_counts: dict[str, int] = {}
                for dropped in dropped_unarchived:
                    reason_counts[dropped.reason] = reason_counts.get(dropped.reason, 0) + 1
                logger.warning(
                    "%d URL(s) from %s fell out of the feed before being archived (%s)",
                    len(dropped_unarchived),
                    source.name,
                    ", ".join(f"{count} {reason}" for reason, count in sorted(reason_counts.items())),
                )
                for dropped in dropped_unarchived[:10]:
                    logger.warning('  - [%s] "%s"', dropped.reason, dropped.url)
            discovered.extend(items)
        except Exception as exc:  # noqa: BLE001 - isolate failures per source
            logger.error("Failed to discover items from %s: %s", source.name, exc)

    try:
        feed_stats.purge_older_than(config.settings.state_max_age_days)
        feed_stats.save()
    except OSError as exc:
        logger.error("Could not write feed stats file %s: %s", feed_stats_path, exc)

    archive_counts = archive_new_urls(client, store, discovered, config.settings)
    for key, value in archive_counts.items():
        totals[key] += value

    purged = store.purge_older_than(config.settings.state_max_age_days)

    try:
        store.save()
    except OSError as exc:
        logger.error("Could not write state file %s: %s", state_path, exc)
        return 1

    logger.info(
        "Run summary: %d source(s) processed, %d discovered, %d success, %d error, "
        "%d still pending, %d state entries purged",
        len(config.sources),
        len(discovered),
        totals["success"],
        totals["error"],
        totals["pending"],
        purged,
    )
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
