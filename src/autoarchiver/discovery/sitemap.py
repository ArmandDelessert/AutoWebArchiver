from __future__ import annotations

import logging
import re

import requests
from lxml import etree

from .models import DiscoveredItem

logger = logging.getLogger(__name__)

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_USER_AGENT = "AutoArchiver/0.1 (+https://github.com/)"
_REQUEST_TIMEOUT = 10


def discover_sitemap(
    source_name: str, sitemap_url: str, url_pattern: str | None = None
) -> list[DiscoveredItem]:
    pattern = re.compile(url_pattern) if url_pattern else None
    urls = _fetch_urls(sitemap_url, _is_index_url=True)

    items = []
    for url, lastmod in urls:
        if pattern and not pattern.match(url):
            continue
        items.append(
            DiscoveredItem(url=url, title=None, published_at=lastmod, source=source_name)
        )
    return items


def _fetch_urls(url: str, *, _is_index_url: bool) -> list[tuple[str, str | None]]:
    root = _fetch_xml(url)
    if root is None:
        return []

    tag = etree.QName(root.tag).localname

    if tag == "sitemapindex":
        if not _is_index_url:
            # Avoid recursing more than one level deep.
            return []
        urls: list[tuple[str, str | None]] = []
        for sitemap_el in root.findall("sm:sitemap", _NS):
            loc_el = sitemap_el.find("sm:loc", _NS)
            if loc_el is None or not loc_el.text:
                continue
            urls.extend(_fetch_urls(loc_el.text.strip(), _is_index_url=False))
        return urls

    if tag == "urlset":
        urls = []
        for url_el in root.findall("sm:url", _NS):
            loc_el = url_el.find("sm:loc", _NS)
            if loc_el is None or not loc_el.text:
                continue
            lastmod_el = url_el.find("sm:lastmod", _NS)
            lastmod = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else None
            urls.append((loc_el.text.strip(), lastmod))
        return urls

    logger.warning("Unexpected root element <%s> in sitemap %s", tag, url)
    return []


def _fetch_xml(url: str) -> etree._Element | None:
    try:
        response = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch sitemap %s: %s", url, exc)
        return None

    try:
        return etree.fromstring(response.content)
    except etree.XMLSyntaxError as exc:
        logger.warning("Failed to parse sitemap XML from %s: %s", url, exc)
        return None
