from __future__ import annotations

import logging
import time

import feedparser
import requests

from .models import USER_AGENT, DiscoveredItem

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10


def discover_rss(source_name: str, feed_url: str) -> list[DiscoveredItem]:
    try:
        response = requests.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch RSS feed %s for %s: %s", feed_url, source_name, exc)
        return []

    feed = feedparser.parse(response.content)

    if feed.bozo:
        logger.warning(
            "Feed for %s is malformed (%s), attempting to use partial results",
            source_name,
            getattr(feed, "bozo_exception", "unknown reason"),
        )

    items: list[DiscoveredItem] = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link:
            continue
        published_at = _to_iso8601(entry.get("published_parsed") or entry.get("updated_parsed"))
        items.append(
            DiscoveredItem(
                url=link,
                title=entry.get("title"),
                published_at=published_at,
                source=source_name,
            )
        )
    return items


def _to_iso8601(parsed_time: time.struct_time | None) -> str | None:
    if parsed_time is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", parsed_time)
