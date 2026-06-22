import responses

from autowebarchiver.discovery.sitemap import discover_sitemap


@responses.activate
def test_discover_sitemap_extracts_urls(fixtures_dir):
    body = (fixtures_dir / "sample_sitemap.xml").read_bytes()
    responses.add(responses.GET, "https://example.com/sitemap.xml", body=body, status=200)

    items = discover_sitemap("sample-source", "https://example.com/sitemap.xml")

    assert len(items) == 3
    urls = [item.url for item in items]
    assert "https://example.com/news/article-1.html" in urls
    assert items[0].published_at == "2024-01-01T10:00:00Z"


@responses.activate
def test_discover_sitemap_applies_url_pattern(fixtures_dir):
    body = (fixtures_dir / "sample_sitemap.xml").read_bytes()
    responses.add(responses.GET, "https://example.com/sitemap.xml", body=body, status=200)

    items = discover_sitemap(
        "sample-source", "https://example.com/sitemap.xml", url_pattern=r".*\.html$"
    )

    assert len(items) == 2
    assert all(item.url.endswith(".html") for item in items)


@responses.activate
def test_discover_sitemap_follows_sitemap_index(fixtures_dir):
    index_body = (fixtures_dir / "sample_sitemap_index.xml").read_bytes()
    child_body = (fixtures_dir / "sample_sitemap.xml").read_bytes()
    responses.add(responses.GET, "https://example.com/sitemap.xml", body=index_body, status=200)
    responses.add(
        responses.GET, "https://example.com/sitemap-child.xml", body=child_body, status=200
    )

    items = discover_sitemap("sample-source", "https://example.com/sitemap.xml")

    assert len(items) == 3


@responses.activate
def test_discover_sitemap_handles_http_error_gracefully():
    responses.add(responses.GET, "https://example.com/sitemap.xml", status=500)

    items = discover_sitemap("sample-source", "https://example.com/sitemap.xml")

    assert items == []
