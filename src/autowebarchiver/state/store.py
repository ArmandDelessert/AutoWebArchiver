from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

logger = logging.getLogger(__name__)

_TRACKING_PARAM_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "rts_source")


def normalize_url(url: str) -> str:
    """Strip tracking query params and the fragment so equivalent URLs dedupe."""
    parsed = urlparse(url)
    kept_params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(k.lower().startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)
    ]
    query = urlencode(kept_params)
    return urlunparse(parsed._replace(query=query, fragment=""))


class SeenStore:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._entries: dict[str, dict] = {}
        # Set by callers throttling save() (see scheduling._save_quietly), not by
        # this class itself -- None means "never saved yet this process".
        self._last_flush_monotonic: float | None = None
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._entries = {}
            return
        try:
            self._entries = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse %s (%s), starting with empty state", self._path, exc)
            self._entries = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def is_known(self, url: str) -> bool:
        """A URL is "known" (won't be re-submitted) unless it failed with a
        transient error and is still awaiting a retry."""
        entry = self._entries.get(normalize_url(url))
        if entry is None:
            return False
        return entry.get("status") != "error_retry"

    def is_archived(self, url: str) -> bool:
        """True if SPN2 confirmed a capture, either just now ("success") or
        already recently enough to skip a new one ("already_archived") --
        stricter than is_known, which also covers pending/error states."""
        entry = self._entries.get(normalize_url(url))
        return entry is not None and entry.get("status") in ("success", "already_archived")

    def status_of(self, url: str) -> str | None:
        """The raw status ("pending"/"success"/"error"/"error_retry"), or None
        if the URL was never seen at all (no submit was ever attempted)."""
        entry = self._entries.get(normalize_url(url))
        return entry.get("status") if entry else None

    def pending_entries(self) -> dict[str, dict]:
        return {
            url: entry for url, entry in self._entries.items() if entry.get("status") == "pending"
        }

    def is_pending_stale(self, url: str, max_age_hours: float) -> bool:
        """True if a "pending" entry has been sitting unresolved for longer
        than max_age_hours. SPN2's own status API only keeps a job's result
        "for a limited time due to system memory limitations" (~1h per their
        docs); once a job has been pending across a cron cycle or two without
        resolving, further polling attempts are unlikely to ever get a real
        answer and just keep re-checking a job SPN2 itself may have forgotten
        about -- this is what lets the caller give up instead of polling the
        same dead job forever."""
        entry = self._entries.get(normalize_url(url))
        if entry is None:
            return False
        age = datetime.now(timezone.utc) - _parse_iso(entry.get("first_seen"))
        return age > timedelta(hours=max_age_hours)

    def mark_pending(self, url: str, job_id: str) -> None:
        key = normalize_url(url)
        existing = self._entries.get(key, {})
        now = _now_iso()
        self._entries[key] = {
            "first_seen": existing.get("first_seen", now),
            "spn2_job_id": job_id,
            "status": "pending",
            "attempts": existing.get("attempts", 0),
            "last_checked": now,
        }

    def mark_resolved(self, url: str, *, status: str, job_id: str | None = None) -> None:
        key = normalize_url(url)
        existing = self._entries.get(key, {})
        self._entries[key] = {
            "first_seen": existing.get("first_seen", _now_iso()),
            "spn2_job_id": job_id or existing.get("spn2_job_id"),
            "status": status,
            "attempts": existing.get("attempts", 0),
            "last_checked": _now_iso(),
        }

    def mark_error(
        self,
        url: str,
        *,
        retryable: bool,
        max_attempts: int,
        job_id: str | None = None,
    ) -> bool:
        """Record a failed capture. Transient failures stay eligible for
        re-submission until ``max_attempts`` is reached, after which they are
        given up on. Returns True if another attempt will be made."""
        key = normalize_url(url)
        existing = self._entries.get(key, {})
        attempts = existing.get("attempts", 0) + 1
        will_retry = retryable and attempts < max_attempts
        self._entries[key] = {
            "first_seen": existing.get("first_seen", _now_iso()),
            "spn2_job_id": job_id or existing.get("spn2_job_id"),
            "status": "error_retry" if will_retry else "error",
            "attempts": attempts,
            "last_checked": _now_iso(),
        }
        return will_retry

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        to_remove = [
            url
            for url, entry in self._entries.items()
            if entry.get("status") != "pending" and _parse_iso(entry.get("first_seen")) < cutoff
        ]
        for url in to_remove:
            del self._entries[url]
        return len(to_remove)

    def __len__(self) -> int:
        return len(self._entries)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
