import pytest
import responses

from autowebarchiver.spn2.client import AlreadyArchivedError, SPN2Client


def make_client(**kwargs):
    return SPN2Client("access", "secret", max_captures_per_minute=100, **kwargs)


@responses.activate
def test_submit_returns_job_id():
    responses.add(
        responses.POST,
        "https://web.archive.org/save",
        json={"url": "https://example.com/", "job_id": "job-1"},
        status=200,
    )

    client = make_client()
    job_id = client.submit("https://example.com/")

    assert job_id == "job-1"


@responses.activate
def test_submit_raises_already_archived_when_no_job_id():
    responses.add(
        responses.POST,
        "https://web.archive.org/save",
        json={
            "url": "https://example.com/",
            "job_id": None,
            "message": "The same snapshot had been made 4 hours, 45 minutes ago. "
            "You can make new capture of this URL after 168 hours.",
        },
        status=200,
    )

    client = make_client()
    with pytest.raises(AlreadyArchivedError, match="same snapshot"):
        client.submit("https://example.com/")


@responses.activate
def test_submit_retries_after_429(monkeypatch):
    monkeypatch.setattr("autowebarchiver.spn2.client.time.sleep", lambda *_: None)
    monkeypatch.setattr("autowebarchiver.spn2.client.random.uniform", lambda *_: 0)

    responses.add(responses.POST, "https://web.archive.org/save", status=429)
    responses.add(
        responses.POST,
        "https://web.archive.org/save",
        json={"url": "https://example.com/", "job_id": "job-2"},
        status=200,
    )

    client = make_client()
    job_id = client.submit("https://example.com/")

    assert job_id == "job-2"
    assert len(responses.calls) == 2
    assert client.rate_limited_count == 1  # only the 429 counts, not the eventual success


@responses.activate
def test_already_archived_does_not_consume_local_rate_budget():
    responses.add(
        responses.POST,
        "https://web.archive.org/save",
        json={"url": "https://example.com/a", "job_id": None, "message": "same snapshot"},
        status=200,
    )
    responses.add(
        responses.POST,
        "https://web.archive.org/save",
        json={"url": "https://example.com/b", "job_id": None, "message": "same snapshot"},
        status=200,
    )

    client = SPN2Client("access", "secret", max_captures_per_minute=1)
    with pytest.raises(AlreadyArchivedError):
        client.submit("https://example.com/a")
    # A real per-minute cap of 1 would normally force a wait for a 2nd
    # submission -- but since the 1st was a dedup skip (no real capture
    # work), it must not count against the budget.
    assert client.next_submit_wait_seconds() == 0.0
    with pytest.raises(AlreadyArchivedError):
        client.submit("https://example.com/b")


@responses.activate
def test_real_capture_consumes_local_rate_budget():
    responses.add(
        responses.POST,
        "https://web.archive.org/save",
        json={"url": "https://example.com/a", "job_id": "job-1"},
        status=200,
    )

    client = SPN2Client("access", "secret", max_captures_per_minute=1)
    client.submit("https://example.com/a")

    assert client.next_submit_wait_seconds() > 0


@responses.activate
def test_poll_until_resolved_returns_success():
    responses.add(
        responses.GET,
        "https://web.archive.org/save/status/job-1",
        json={
            "status": "success",
            "job_id": "job-1",
            "original_url": "https://example.com/",
            "timestamp": "20240101000000",
        },
        status=200,
    )

    client = make_client()
    result = client.poll_until_resolved("job-1", "https://example.com/", interval=0, timeout=5)

    assert result.status == "success"
    assert result.wayback_url == "https://web.archive.org/web/20240101000000/https://example.com/"


@responses.activate
def test_poll_until_resolved_returns_error():
    responses.add(
        responses.GET,
        "https://web.archive.org/save/status/job-1",
        json={
            "status": "error",
            "job_id": "job-1",
            "status_ext": "error:not-found",
            "message": "Target URL not found",
        },
        status=200,
    )

    client = make_client()
    result = client.poll_until_resolved("job-1", "https://example.com/", interval=0, timeout=5)

    assert result.status == "error"
    assert result.status_ext == "error:not-found"
    assert result.is_retryable_error is False


@responses.activate
def test_poll_until_resolved_times_out(monkeypatch):
    monkeypatch.setattr("autowebarchiver.spn2.client.time.sleep", lambda *_: None)
    responses.add(
        responses.GET,
        "https://web.archive.org/save/status/job-1",
        json={"status": "pending", "job_id": "job-1", "resources": []},
        status=200,
    )

    client = make_client()
    result = client.poll_until_resolved("job-1", "https://example.com/", interval=1, timeout=0)

    assert result.status == "timeout"


def test_next_submit_wait_seconds_tracks_rolling_window(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("autowebarchiver.spn2.client.time.monotonic", lambda: clock["t"])

    client = SPN2Client("access", "secret", max_captures_per_minute=2)

    # Empty window: a slot is free.
    assert client.next_submit_wait_seconds() == 0.0

    # Fill the window to capacity.
    client._submit_timestamps.append(1000.0)
    client._submit_timestamps.append(1000.0)
    wait = client.next_submit_wait_seconds()
    assert 59.9 < wait <= 60.2  # must wait ~until the oldest leaves the 60s window

    # Once the window has passed, both timestamps are pruned and a slot frees.
    clock["t"] = 1061.0
    assert client.next_submit_wait_seconds() == 0.0


@responses.activate
def test_get_user_status():
    responses.add(
        responses.GET,
        "https://web.archive.org/save/status/user",
        json={"available": 5, "processing": 2},
        status=200,
    )

    client = make_client()
    status = client.get_user_status()

    assert status == {"available": 5, "processing": 2}
