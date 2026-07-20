from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import ConfigError, Source, load_config
from .discovery.models import DiscoveredItem
from .discovery.rss import discover_rss
from .discovery.sitemap import discover_sitemap
from .logging_setup import setup_logging
from .scheduling import (  # noqa: F401 - _save_quietly re-exported for tests
    SourceScheduler,
    _save_quietly,
    archive_new_urls,
    poll_leftovers,
)
from .spn2.client import SPN2Client
from .state.feed_stats import FeedStatsStore
from .state.run_history import RunHistoryStore
from .state.store import SeenStore

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "sources.yaml"
DEFAULT_STATE_PATH = REPO_ROOT / "state" / "seen.json"
DEFAULT_FEED_STATS_PATH = REPO_ROOT / "state" / "feed_stats.json"
DEFAULT_RUN_HISTORY_PATH = REPO_ROOT / "state" / "run_history.json"


class FatalError(Exception):
    """Raised for errors that should abort the whole run with a non-zero exit code."""


def discover_source(source: Source) -> list[DiscoveredItem]:
    if source.type == "rss":
        return discover_rss(source.name, source.url)
    if source.type == "sitemap":
        return discover_sitemap(source.name, source.url, source.url_pattern)
    raise FatalError(f"Unknown source type '{source.type}' for {source.name}")


def run(
    config_path: Path = DEFAULT_CONFIG_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    feed_stats_path: Path = DEFAULT_FEED_STATS_PATH,
    run_history_path: Path = DEFAULT_RUN_HISTORY_PATH,
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
    run_history = RunHistoryStore(run_history_path)
    client = SPN2Client(
        access_key, secret_key, max_captures_per_minute=config.settings.max_captures_per_minute
    )

    totals = {"success": 0, "error": 0, "pending": 0, "already_archived": 0, "error_retry": 0, "error_permanent": 0}

    leftover_counts = poll_leftovers(client, store, config.settings)
    for key, value in leftover_counts.items():
        totals[key] += value

    discovered: list[DiscoveredItem] = []
    for source in config.sources:
        try:
            items = discover_source(source)
            new_count = sum(1 for item in items if not store.is_known(item.url))
            logger.info("Discovered %d item(s) from %s", len(items), source.name)
            stats, dropped_unarchived = feed_stats.record(
                source.name, items, new_count, store, exhaustive=source.exhaustive
            )
            coverage = (
                f", coverage {stats.oldest_published_at}..{stats.newest_published_at}"
                if stats.oldest_published_at and stats.newest_published_at
                else ""
            )
            if stats.dropped_count is None:
                logger.info(
                    "Feed stats for %s: %d new (exhaustive, drop-tracking skipped)%s",
                    source.name,
                    stats.new_count,
                    coverage,
                )
            else:
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

    exhaustive_by_source = {source.name: source.exhaustive for source in config.sources}
    archive_counts, already_archived_by_source, rate_limited_by_source, deferred_count = archive_new_urls(
        client, store, discovered, config.settings, exhaustive_by_source
    )
    for key, value in archive_counts.items():
        totals[key] += value

    # Submission outcomes (including which URLs were already archived, and
    # which hit a 429) are only known now, after archive_new_urls runs --
    # attach them to the history entries feed_stats.record() already appended
    # per source above, so the trend is visible over time in feed_stats.json
    # rather than only in this run's ephemeral CI logs.
    for source_name, count in sorted(already_archived_by_source.items()):
        feed_stats.record_already_archived(source_name, count)
        logger.info('%d URL(s) from %s were "already archived" recently enough (skipped by SPN2)', count, source_name)
    for source_name, count in sorted(rate_limited_by_source.items()):
        feed_stats.record_rate_limited(source_name, count)
        logger.info("%d SPN2 429 (rate-limited) response(s) for %s", count, source_name)

    try:
        feed_stats.purge_older_than(config.settings.state_max_age_days)
        feed_stats.save()
    except OSError as exc:
        logger.error("Could not write feed stats file %s: %s", feed_stats_path, exc)

    purged = store.purge_older_than(config.settings.state_max_age_days)

    try:
        store.save()
    except OSError as exc:
        logger.error("Could not write state file %s: %s", state_path, exc)
        return 1

    run_history.record(
        sources_processed=len(config.sources),
        discovered=len(discovered),
        success=totals["success"],
        error=totals["error"],
        error_retry=totals["error_retry"],
        error_permanent=totals["error_permanent"],
        already_archived=totals["already_archived"],
        pending=totals["pending"],
        rate_limited=client.rate_limited_count,
        deferred=deferred_count,
        purged=purged,
    )
    try:
        run_history.purge_older_than(config.settings.state_max_age_days)
        run_history.save()
    except OSError as exc:
        logger.error("Could not write run history file %s: %s", run_history_path, exc)

    logger.info(
        "Run summary: %d source(s) processed, %d discovered, %d success, %d error "
        "(%d will retry, %d gave up), %d already archived, %d still pending, "
        "%d rate-limited (429), %d state entries purged",
        len(config.sources),
        len(discovered),
        totals["success"],
        totals["error"],
        totals["error_retry"],
        totals["error_permanent"],
        totals["already_archived"],
        totals["pending"],
        client.rate_limited_count,
        purged,
    )
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
