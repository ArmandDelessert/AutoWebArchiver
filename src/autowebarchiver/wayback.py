from __future__ import annotations

import logging
from datetime import UTC, datetime

import requests

logger = logging.getLogger(__name__)

_AVAILABILITY_URL = "https://archive.org/wayback/available"


def is_archived(url: str, *, timeout: int = 10, min_age_hours: float = 3.0) -> bool | None:
    """Best-effort check via the public Wayback availability API (the same
    one the dashboard's "Vérifier sur Internet Archive" button uses -- fast,
    ~0.5s, but known to be unreliable in both directions: it can report a
    real capture as missing (lagging the authoritative CDX index by up to
    its own ~6h cache window), and -- confirmed directly, on a URL captured
    minutes earlier -- it can also report "available" for a snapshot whose
    content isn't actually retrievable yet (IA's own index and storage
    aren't immediately consistent right after a capture). Returns None
    (rather than False) on any failure, so callers can tell "confirmed not
    archived" apart from "couldn't check right now" and treat the latter as
    inconclusive rather than a negative.

    A "closest" snapshot younger than min_age_hours is treated the same as
    no snapshot at all: too fresh to trust as settled, so callers (notably
    DroppedUrlsStore.purge_confirmed_archived) don't silently drop an entry
    that still needs attention. It'll simply be re-checked next run, once
    it's had time to actually become retrievable."""
    try:
        response = requests.get(_AVAILABILITY_URL, params={"url": url}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not check Wayback availability for %s: %s", url, exc)
        return None
    closest = data.get("archived_snapshots", {}).get("closest")
    if not closest or not closest.get("available"):
        return False
    timestamp = closest.get("timestamp")
    if timestamp:
        try:
            captured_at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            captured_at = None
        if captured_at is not None:
            age_hours = (datetime.now(UTC) - captured_at).total_seconds() / 3600
            if age_hours < min_age_hours:
                return False
    return True
