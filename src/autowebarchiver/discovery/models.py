from __future__ import annotations

from dataclasses import dataclass

USER_AGENT = "AutoWebArchiver/0.1 (+https://github.com/ArmandDelessert/AutoWebArchiver)"


@dataclass(frozen=True)
class DiscoveredItem:
    url: str
    title: str | None
    published_at: str | None
    source: str
