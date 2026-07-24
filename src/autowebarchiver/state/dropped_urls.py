from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .feed_stats import DroppedUrl

logger = logging.getLogger(__name__)


class DroppedUrlsStore:
    """Persists the actual URLs that fell out of a rotating feed/sitemap
    without ever being archived (FeedStatsStore.record()'s dropped_unarchived
    return value) -- a real, permanent loss, otherwise only ever visible in a
    single run's CI logs before they expire. Kept in its own small file
    rather than inside feed_stats.json: that file explicitly avoids storing
    per-run URL lists to stay small (see FeedStatsStore.record()'s
    docstring), but that concern was about every discovered item, run over
    run -- these entries only exist for the rare, actionable case where an
    item was truly lost, so growth here stays proportional to real problems,
    not to feed size."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._entries = []
            return
        try:
            self._entries = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse %s (%s), starting with empty dropped-URL log", self._path, exc)
            self._entries = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def record(self, source_name: str, dropped: list[DroppedUrl], github_run_id: str | None = None) -> None:
        now = _now_iso()
        for item in dropped:
            self._entries.append(
                {
                    "timestamp": now,
                    "source": source_name,
                    "url": item.url,
                    "reason": item.reason,
                    "github_run_id": github_run_id,
                }
            )

    def purge_confirmed_archived(
        self, is_archived: Callable[[str], bool | None], *, delay_seconds: float = 0.0
    ) -> int:
        """Re-check every entry against Internet Archive and drop the ones
        confirmed archived since they were recorded -- the point of this
        list is "still needs attention", and an entry archived by someone
        else in the meantime (IA's own crawler, a manual save) no longer
        does. is_archived(url) returning None (check failed) leaves the
        entry in place: better to keep re-checking next run than to drop it
        on a flaky network call. delay_seconds is only meaningful with a
        real, non-instant checker -- see main.py's use of wayback.is_archived,
        a public unauthenticated endpoint best not hammered in a tight loop."""
        kept = []
        removed = 0
        for i, entry in enumerate(self._entries):
            if i:
                time.sleep(delay_seconds)
            if is_archived(entry["url"]):
                removed += 1
            else:
                kept.append(entry)
        self._entries = kept
        return removed

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        kept = [e for e in self._entries if _parse_iso(e["timestamp"]) >= cutoff]
        purged = len(self._entries) - len(kept)
        self._entries = kept
        return purged


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
