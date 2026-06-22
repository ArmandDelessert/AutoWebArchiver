from autoarchiver.discovery.rss import discover_rss


def test_discover_rss_extracts_items(fixtures_dir):
    feed_path = (fixtures_dir / "sample_rss.xml").as_uri()
    items = discover_rss("sample-source", feed_path)

    assert len(items) == 2
    assert items[0].url == "https://example.com/articles/first"
    assert items[0].title == "First article"
    assert items[0].source == "sample-source"
    assert items[0].published_at == "2024-01-01T10:00:00Z"


def test_discover_rss_handles_malformed_feed_without_raising(fixtures_dir):
    feed_path = (fixtures_dir / "sample_malformed_rss.xml").as_uri()
    items = discover_rss("broken-source", feed_path)

    # feedparser should still salvage what it can, or return an empty list,
    # but must never raise.
    assert isinstance(items, list)
