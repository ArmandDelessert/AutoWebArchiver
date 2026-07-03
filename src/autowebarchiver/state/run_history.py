from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class RunHistoryStore:
    """Persists one summary entry per run (the numbers otherwise only ever
    shown in the "Run summary" log line, which disappears once CI logs
    expire). This is what a monitoring dashboard reads to show run-over-run
    trends -- feed_stats.json only tracks per-source discovery/outcome
    stats, never the whole-run totals."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._runs: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._runs = []
            return
        try:
            self._runs = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse %s (%s), starting with empty run history", self._path, exc)
            self._runs = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._runs, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def record(self, **fields: int) -> None:
        self._runs.append({"timestamp": _now_iso(), **fields})

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        kept = [r for r in self._runs if _parse_iso(r["timestamp"]) >= cutoff]
        purged = len(self._runs) - len(kept)
        self._runs = kept
        return purged


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
