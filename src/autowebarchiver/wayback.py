from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_AVAILABILITY_URL = "https://archive.org/wayback/available"


def is_archived(url: str, *, timeout: int = 10) -> bool | None:
    """Best-effort check via the public Wayback availability API (the same
    one the dashboard's "Vérifier sur Internet Archive" button uses -- fast,
    ~0.5s, but known to lag behind the authoritative CDX index by up to its
    own ~6h cache window). Returns None (rather than False) on any failure,
    so callers can tell "confirmed not archived" apart from "couldn't check
    right now" and treat the latter as inconclusive rather than a negative."""
    try:
        response = requests.get(_AVAILABILITY_URL, params={"url": url}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not check Wayback availability for %s: %s", url, exc)
        return None
    closest = data.get("archived_snapshots", {}).get("closest")
    return bool(closest and closest.get("available"))
