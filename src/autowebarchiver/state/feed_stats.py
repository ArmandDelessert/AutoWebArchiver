from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..discovery.models import DiscoveredItem
from .store import SeenStore, normalize_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedRunStats:
    timestamp: str
    item_count: int
    new_count: int
    # None means "not tracked this run" (exhaustive sources -- see record()),
    # not "confirmed zero drops".
    dropped_count: int | None
    dropped_unarchived_count: int | None
    oldest_published_at: str | None
    newest_published_at: str | None


@dataclass(frozen=True)
class DroppedUrl:
    url: str
    # Why it never got archived before falling out of the feed:
    # "never_attempted" - no submit was ever made for it (starved of capacity)
    # "gave_up" - submitted, retried, and permanently failed (e.g. blocked/403)
    # "still_retrying" - was mid-retry (error_retry) when it fell out
    # "still_pending" - a capture job was in flight when it fell out
    reason: str


class FeedStatsStore:
    """Tracks, per source, how a feed/sitemap's content changes run over run:
    its size, how many items are genuinely new, and -- the key signal -- how
    many items disappeared from the feed without ever being successfully
    archived. That last number is the real, measured indicator of whether a
    feed's retention window is wide enough for our capture throughput; it
    replaces guessing at each site's undocumented retention policy."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._sources: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._sources = {}
            return
        try:
            self._sources = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse %s (%s), starting with empty stats", self._path, exc)
            self._sources = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._sources, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def record(
        self,
        source_name: str,
        items: list[DiscoveredItem],
        new_count: int,
        seen_store: SeenStore,
        exhaustive: bool = False,
    ) -> tuple[FeedRunStats, list[DroppedUrl]]:
        """Compare this run's discovered items against the previous run's for the
        same source, compute stats, and persist the new snapshot in memory
        (call save() to write it to disk). Returns the stats plus the list of
        dropped-but-never-archived URLs with their failure reason, for logging
        only -- not persisted, to keep feed_stats.json from growing unbounded.

        For exhaustive sources, drop-tracking is skipped entirely: dropped_count
        and dropped_unarchived_count come back None, and the previous full URL
        list isn't stored. That metric exists to catch items about to roll off
        a rotating/size-limited feed -- not meaningful for a full-site sitemap,
        where nothing is at risk the same way (see SourceScheduler's exhaustive
        tier). Storing last_urls for these anyway is what made feed_stats.json
        balloon past seen.json's own size once large sitemaps were added: a
        12,000+ item sitemap means a 12,000-URL list rewritten whole every run,
        for a signal that was never actionable there in the first place."""
        if exhaustive:
            published = [item.published_at for item in items if item.published_at]
            stats = FeedRunStats(
                timestamp=_now_iso(),
                item_count=len(items),
                new_count=new_count,
                dropped_count=None,
                dropped_unarchived_count=None,
                oldest_published_at=min(published) if published else None,
                newest_published_at=max(published) if published else None,
            )
            history = self._sources.get(source_name, {}).get("history", [])
            history.append(stats.__dict__)
            self._sources[source_name] = {"last_urls": [], "history": history}
            return stats, []

        current_urls = {normalize_url(item.url) for item in items}
        previous = self._sources.get(source_name, {})
        previous_urls = set(previous.get("last_urls", []))

        dropped = previous_urls - current_urls
        dropped_unarchived = [
            DroppedUrl(url=url, reason=_drop_reason(seen_store.status_of(url)))
            for url in dropped
            if not seen_store.is_archived(url)
        ]

        published = [item.published_at for item in items if item.published_at]
        stats = FeedRunStats(
            timestamp=_now_iso(),
            item_count=len(items),
            new_count=new_count,
            dropped_count=len(dropped),
            dropped_unarchived_count=len(dropped_unarchived),
            oldest_published_at=min(published) if published else None,
            newest_published_at=max(published) if published else None,
        )

        history = previous.get("history", [])
        history.append(stats.__dict__)
        self._sources[source_name] = {
            "last_urls": sorted(current_urls),
            "history": history,
        }
        return stats, dropped_unarchived

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        purged = 0
        for source in self._sources.values():
            kept = [h for h in source["history"] if _parse_iso(h["timestamp"]) >= cutoff]
            purged += len(source["history"]) - len(kept)
            source["history"] = kept
        return purged


def _drop_reason(status: str | None) -> str:
    return {
        None: "never_attempted",
        "error": "gave_up",
        "error_retry": "still_retrying",
        "pending": "still_pending",
    }.get(status, status or "never_attempted")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
