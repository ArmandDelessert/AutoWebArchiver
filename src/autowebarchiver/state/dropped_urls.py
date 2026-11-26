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
        self,
        is_archived: Callable[[str], bool | None],
        *,
        delay_seconds: float = 0.0,
        max_seconds: float | None = None,
    ) -> int:
        """Re-check entries against Internet Archive and drop the ones
        confirmed archived since they were recorded -- the point of this
        list is "still needs attention", and an entry archived by someone
        else in the meantime (IA's own crawler, a manual save) no longer
        does. is_archived(url) returning None (check failed) leaves the
        entry in place: better to keep re-checking next run than to drop it
        on a flaky network call. delay_seconds is only meaningful with a
        real, non-instant checker -- see main.py's use of wayback.is_archived,
        a public unauthenticated endpoint best not hammered in a tight loop.

        max_seconds bounds the whole pass: this list grows into the
        thousands, at about a second per check, and re-checking all of it
        every run once pushed runs past the CI job timeout. Entries are
        taken never-checked first, then longest-unchecked (each one tried is
        stamped with last_checked), so successive runs cover the whole list.
        The list keeps its original order. Returns the number removed."""
        deadline = None if max_seconds is None else time.monotonic() + max_seconds
        queue = sorted(self._entries, key=lambda e: e.get("last_checked", ""))
        archived: set[int] = set()
        checked = 0
        for entry in queue:
            if deadline is not None and time.monotonic() >= deadline:
                break
            if checked:
                time.sleep(delay_seconds)
            checked += 1
            entry["last_checked"] = _now_iso()
            if is_archived(entry["url"]):
                archived.add(id(entry))
        if queue:
            logger.info(
                "Re-checked %d of %d URL(s) in the dropped-URL log against Internet Archive",
                checked,
                len(queue),
            )
        self._entries = [e for e in self._entries if id(e) not in archived]
        return len(archived)

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
