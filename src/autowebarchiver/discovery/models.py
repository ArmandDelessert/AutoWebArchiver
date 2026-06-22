from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveredItem:
    url: str
    title: str | None
    published_at: str | None
    source: str
