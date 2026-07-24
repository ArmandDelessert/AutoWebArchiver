import responses

from autowebarchiver.wayback import is_archived


@responses.activate
def test_is_archived_true_when_closest_snapshot_available():
    responses.add(
        responses.GET,
        "https://archive.org/wayback/available",
        json={
            "url": "https://example.com/a",
            "archived_snapshots": {
                "closest": {"status": "200", "available": True, "url": "http://web.archive.org/web/2026/https://example.com/a", "timestamp": "20260101000000"}
            },
        },
        status=200,
    )

    assert is_archived("https://example.com/a") is True


@responses.activate
def test_is_archived_false_when_no_snapshot():
    responses.add(
        responses.GET,
        "https://archive.org/wayback/available",
        json={"url": "https://example.com/a", "archived_snapshots": {}},
        status=200,
    )

    assert is_archived("https://example.com/a") is False


@responses.activate
def test_is_archived_none_on_http_error():
    responses.add(responses.GET, "https://archive.org/wayback/available", status=500)

    assert is_archived("https://example.com/a") is None


@responses.activate
def test_is_archived_none_on_malformed_json():
    responses.add(
        responses.GET,
        "https://archive.org/wayback/available",
        body="not json",
        status=200,
    )

    assert is_archived("https://example.com/a") is None
