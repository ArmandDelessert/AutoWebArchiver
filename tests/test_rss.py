import responses

from autowebarchiver.discovery.rss import discover_rss


@responses.activate
def test_discover_rss_extracts_items(fixtures_dir):
    body = (fixtures_dir / "sample_rss.xml").read_bytes()
    responses.add(responses.GET, "https://example.com/feed.xml", body=body, status=200)

    items = discover_rss("sample-source", "https://example.com/feed.xml")

    assert len(items) == 2
    assert items[0].url == "https://example.com/articles/first"
    assert items[0].title == "First article"
    assert items[0].source == "sample-source"
    assert items[0].published_at == "2024-01-01T10:00:00Z"


@responses.activate
def test_discover_rss_handles_malformed_feed_without_raising(fixtures_dir):
    body = (fixtures_dir / "sample_malformed_rss.xml").read_bytes()
    responses.add(responses.GET, "https://example.com/feed.xml", body=body, status=200)

    items = discover_rss("broken-source", "https://example.com/feed.xml")

    # feedparser should still salvage what it can, or return an empty list,
    # but must never raise.
    assert isinstance(items, list)


@responses.activate
def test_discover_rss_handles_fetch_failure_gracefully():
    responses.add(responses.GET, "https://example.com/feed.xml", status=500)

    items = discover_rss("sample-source", "https://example.com/feed.xml")

    assert items == []
