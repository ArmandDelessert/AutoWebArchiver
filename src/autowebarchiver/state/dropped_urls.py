from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
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

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        kept = [e for e in self._entries if _parse_iso(e["timestamp"]) >= cutoff]
        purged = len(self._entries) - len(kept)
        self._entries = kept
        return purged


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
