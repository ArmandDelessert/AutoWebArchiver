from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_SOURCE_TYPES = {"rss", "sitemap"}

# SPN2 duration format: an integer optionally followed by a unit.
# Note: 'm' is minutes and 'M' is months (case matters). No unit => seconds.
_DURATION_RE = re.compile(r"^\d+[smhdwMy]?$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Source:
    name: str
    type: str
    url: str
    url_pattern: str | None = None


@dataclass(frozen=True)
class Settings:
    if_not_archived_within: str = "1h"
    capture_outlinks: bool = False
    capture_screenshot: bool = False
    skip_first_archive: bool = True
    js_behavior_timeout: int = 0
    max_captures_per_minute: int = 7
    max_concurrent_spn2_jobs: int = 10
    max_captures_per_run: int = 60
    max_run_seconds: int = 600
    max_capture_attempts: int = 3
    poll_interval_seconds: int = 15
    poll_timeout_seconds: int = 180
    state_max_age_days: int = 90


@dataclass(frozen=True)
class Config:
    sources: list[Source]
    settings: Settings


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict) or "sources" not in raw:
        raise ConfigError(f"Config must be a mapping with a 'sources' key: {path}")

    sources = []
    seen_names: set[str] = set()
    for i, entry in enumerate(raw["sources"]):
        if not isinstance(entry, dict):
            raise ConfigError(f"sources[{i}] must be a mapping")
        missing = {"name", "type", "url"} - entry.keys()
        if missing:
            raise ConfigError(f"sources[{i}] missing required field(s): {missing}")
        if entry["type"] not in VALID_SOURCE_TYPES:
            raise ConfigError(
                f"sources[{i}] has invalid type '{entry['type']}', must be one of {VALID_SOURCE_TYPES}"
            )
        name = entry["name"]
        if name in seen_names:
            raise ConfigError(f"sources[{i}] has duplicate name '{name}'; names must be unique")
        seen_names.add(name)
        sources.append(
            Source(
                name=name,
                type=entry["type"],
                url=entry["url"],
                url_pattern=entry.get("url_pattern"),
            )
        )

    if not sources:
        raise ConfigError(f"No sources defined in {path}")

    try:
        settings = Settings(**raw.get("settings", {}))
    except TypeError as exc:
        raise ConfigError(f"Invalid settings in {path}: {exc}") from exc

    if not _DURATION_RE.match(settings.if_not_archived_within):
        raise ConfigError(
            f"Invalid if_not_archived_within '{settings.if_not_archived_within}': expected a "
            "number optionally followed by a unit s/m/h/d/w/M/y (e.g. '12h', '5d', '1M'). "
            "Note: 'm' = minutes, 'M' = months."
        )

    return Config(sources=sources, settings=settings)
