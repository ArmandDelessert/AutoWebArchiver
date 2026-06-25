from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from .config import ConfigError, Settings, Source, load_config
from .discovery.models import DiscoveredItem
from .discovery.rss import discover_rss
from .discovery.sitemap import discover_sitemap
from .logging_setup import setup_logging
from .spn2.client import SPN2Client
from .spn2.models import SPN2Result, result_from_status_payload
from .state.store import SeenStore

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "sources.yaml"
DEFAULT_STATE_PATH = REPO_ROOT / "state" / "seen.json"


class FatalError(Exception):
    """Raised for errors that should abort the whole run with a non-zero exit code."""


def discover_source(source: Source) -> list[DiscoveredItem]:
    if source.type == "rss":
        return discover_rss(source.name, source.url)
    if source.type == "sitemap":
        return discover_sitemap(source.name, source.url, source.url_pattern)
    raise FatalError(f"Unknown source type '{source.type}' for {source.name}")


def _poll_jobs(
    client: SPN2Client, store: SeenStore, jobs: dict[str, str], settings: Settings
) -> dict[str, int]:
    """Poll a batch of in-flight jobs (job_id -> url) until each resolves or the
    shared polling deadline is reached. Captures run concurrently server-side, so
    a whole wave resolves in roughly the time of a single capture."""
    counts = {"success": 0, "error": 0, "pending": 0}
    waiting = dict(jobs)
    if not waiting:
        return counts

    deadline = time.monotonic() + settings.poll_timeout_seconds
    while waiting:
        for job_id, url in list(waiting.items()):
            try:
                payload = client.get_status(job_id)
            except Exception as exc:  # noqa: BLE001 - isolate failures; stays pending for next run
                logger.error("Failed to poll job %s for %s: %s", job_id, url, exc)
                counts["pending"] += 1
                del waiting[job_id]
                continue
            result = result_from_status_payload(job_id, url, payload)
            if result is None:
                continue  # still pending
            _record_result(store, result, settings)
            counts[result.status] += 1
            del waiting[job_id]

        if not waiting:
            break
        if time.monotonic() >= deadline:
            for url in waiting.values():
                logger.warning("Job for %s is still pending after polling timeout", url)
                counts["pending"] += 1
            break
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


def _submit_wave(
    client: SPN2Client, store: SeenStore, items: list[DiscoveredItem], settings: Settings
) -> tuple[dict[str, str], int]:
    """Submit a wave of capture requests without waiting for them. Returns the
    in-flight job_id -> url map plus the number of submit failures."""
    in_flight: dict[str, str] = {}
    errors = 0
    for item in items:
        try:
            job_id = client.submit(
                item.url,
                capture_screenshot=settings.capture_screenshot,
                capture_outlinks=settings.capture_outlinks,
                skip_first_archive=settings.skip_first_archive,
                if_not_archived_within=settings.if_not_archived_within,
                js_behavior_timeout=settings.js_behavior_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures per URL
            logger.error("Failed to submit %s for capture: %s", item.url, exc)
            # A submit failure is almost always transient (network/SPN2 hiccup),
            # so keep it eligible for a bounded number of retries.
            store.mark_error(item.url, retryable=True, max_attempts=settings.max_capture_attempts)
            errors += 1
            continue
        store.mark_pending(item.url, job_id)
        in_flight[job_id] = item.url
    return in_flight, errors


def archive_new_urls(
    client: SPN2Client, store: SeenStore, items: list[DiscoveredItem], settings: Settings
) -> dict[str, int]:
    """Archive newly discovered URLs in concurrent waves: submit up to the
    available concurrency, poll that wave to completion, then move on, up to a
    per-run budget."""
    counts = {"success": 0, "error": 0, "pending": 0}
    new_items = [item for item in items if not store.is_known(item.url)]
    logger.info("%d new URL(s) to archive out of %d discovered", len(new_items), len(items))

    try:
        user_status = client.get_user_status()
        available = user_status.get("available", settings.max_concurrent_spn2_jobs)
    except Exception as exc:  # noqa: BLE001 - never let a status check abort the run
        logger.warning("Could not fetch SPN2 user status (%s), assuming default capacity", exc)
        available = settings.max_concurrent_spn2_jobs

    wave_size = max(1, min(settings.max_concurrent_spn2_jobs, available))
    budget = settings.max_captures_per_run
    if len(new_items) > budget:
        logger.info(
            "Limiting this run to %d of %d new URL(s) (per-run budget)", budget, len(new_items)
        )
    queued = new_items[:budget]

    for start in range(0, len(queued), wave_size):
        wave = queued[start : start + wave_size]
        in_flight, submit_errors = _submit_wave(client, store, wave, settings)
        counts["error"] += submit_errors
        wave_counts = _poll_jobs(client, store, in_flight, settings)
        for key, value in wave_counts.items():
            counts[key] += value

    return counts


def _record_result(store: SeenStore, result: SPN2Result, settings: Settings) -> None:
    if result.status == "success":
        store.mark_resolved(result.url, status="success", job_id=result.job_id)
        logger.info("Archived %s -> %s", result.url, result.wayback_url)
    elif result.status == "error":
        will_retry = store.mark_error(
            result.url,
            retryable=result.is_retryable_error,
            max_attempts=settings.max_capture_attempts,
            job_id=result.job_id,
        )
        logger.error(
            "SPN2 error for %s: %s (%s)%s",
            result.url,
            result.message,
            result.status_ext,
            " - will retry next run" if will_retry else " - giving up",
        )
    else:
        # status == "timeout": leave it marked as pending so it gets repolled next run.
        logger.warning("Job for %s is still pending after polling timeout", result.url)


def run(config_path: Path = DEFAULT_CONFIG_PATH, state_path: Path = DEFAULT_STATE_PATH) -> int:
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
            logger.info("Discovered %d item(s) from %s", len(items), source.name)
            discovered.extend(items)
        except Exception as exc:  # noqa: BLE001 - isolate failures per source
            logger.error("Failed to discover items from %s: %s", source.name, exc)

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
