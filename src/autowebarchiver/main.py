from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import ConfigError, Settings, Source, load_config
from .discovery.models import DiscoveredItem
from .discovery.rss import discover_rss
from .discovery.sitemap import discover_sitemap
from .logging_setup import setup_logging
from .spn2.client import SPN2Client
from .spn2.models import SPN2Result
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


def repoll_pending(client: SPN2Client, store: SeenStore, settings: Settings) -> dict[str, int]:
    counts = {"success": 0, "error": 0, "pending": 0}
    for url, entry in list(store.pending_entries().items()):
        job_id = entry.get("spn2_job_id")
        if not job_id:
            continue
        try:
            result = client.poll_until_resolved(
                job_id, url, interval=settings.poll_interval_seconds, timeout=settings.poll_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures; stays pending for next run
            logger.error("Failed to poll pending job for %s: %s", url, exc)
            counts["pending"] += 1
            continue
        _record_result(store, result, settings)
        counts[result.status if result.status in counts else "pending"] += 1
    return counts


def submit_new_urls(
    client: SPN2Client, store: SeenStore, items: list[DiscoveredItem], settings: Settings
) -> dict[str, int]:
    counts = {"success": 0, "error": 0, "pending": 0}
    new_items = [item for item in items if not store.is_known(item.url)]
    logger.info("%d new URL(s) to archive out of %d discovered", len(new_items), len(items))

    try:
        user_status = client.get_user_status()
        available = user_status.get("available", settings.max_concurrent_spn2_jobs)
    except Exception as exc:  # noqa: BLE001 - never let a status check abort the run
        logger.warning("Could not fetch SPN2 user status (%s), assuming default capacity", exc)
        available = settings.max_concurrent_spn2_jobs

    batch_size = max(1, min(settings.max_concurrent_spn2_jobs, available))
    if len(new_items) > batch_size:
        logger.info(
            "Limiting this run to %d of %d new URL(s) based on available SPN2 capacity",
            batch_size,
            len(new_items),
        )
    new_items = new_items[:batch_size]

    for item in new_items:
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
            store.mark_error(
                item.url, retryable=True, max_attempts=settings.max_capture_attempts
            )
            counts["error"] += 1
            continue

        store.mark_pending(item.url, job_id)
        try:
            result = client.poll_until_resolved(
                job_id,
                item.url,
                interval=settings.poll_interval_seconds,
                timeout=settings.poll_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures; stays pending for next run
            logger.error("Failed to poll capture job for %s: %s", item.url, exc)
            counts["pending"] += 1
            continue
        _record_result(store, result, settings)
        counts[result.status if result.status in counts else "pending"] += 1

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

    repoll_counts = repoll_pending(client, store, config.settings)
    for key, value in repoll_counts.items():
        totals[key] += value

    discovered: list[DiscoveredItem] = []
    for source in config.sources:
        try:
            items = discover_source(source)
            logger.info("Discovered %d item(s) from %s", len(items), source.name)
            discovered.extend(items)
        except Exception as exc:  # noqa: BLE001 - isolate failures per source
            logger.error("Failed to discover items from %s: %s", source.name, exc)

    submit_counts = submit_new_urls(client, store, discovered, config.settings)
    for key, value in submit_counts.items():
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
