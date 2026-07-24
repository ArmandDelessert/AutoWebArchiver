from datetime import UTC, datetime, timedelta

import responses

from autowebarchiver.wayback import is_archived


def _snapshot(timestamp):
    return {
        "url": "https://example.com/a",
        "archived_snapshots": {
            "closest": {
                "status": "200",
                "available": True,
                "url": "http://web.archive.org/web/2026/https://example.com/a",
                "timestamp": timestamp,
            }
        },
    }


@responses.activate
def test_is_archived_true_when_snapshot_is_old_enough():
    old = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d%H%M%S")
    responses.add(responses.GET, "https://archive.org/wayback/available", json=_snapshot(old), status=200)

    assert is_archived("https://example.com/a") is True


@responses.activate
def test_is_archived_false_when_snapshot_is_too_fresh():
    # Confirmed for real: a snapshot minutes old can be reported "available"
    # by this endpoint before its content is actually retrievable.
    fresh = (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y%m%d%H%M%S")
    responses.add(responses.GET, "https://archive.org/wayback/available", json=_snapshot(fresh), status=200)

    assert is_archived("https://example.com/a") is False


@responses.activate
def test_is_archived_respects_custom_min_age_hours():
    age = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y%m%d%H%M%S")
    responses.add(responses.GET, "https://archive.org/wayback/available", json=_snapshot(age), status=200)

    assert is_archived("https://example.com/a", min_age_hours=2) is False
    responses.reset()
    responses.add(responses.GET, "https://archive.org/wayback/available", json=_snapshot(age), status=200)
    assert is_archived("https://example.com/a", min_age_hours=0.5) is True


@responses.activate
def test_is_archived_true_when_timestamp_missing():
    body = {
        "url": "https://example.com/a",
        "archived_snapshots": {"closest": {"status": "200", "available": True, "url": "x"}},
    }
    responses.add(responses.GET, "https://archive.org/wayback/available", json=body, status=200)

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
