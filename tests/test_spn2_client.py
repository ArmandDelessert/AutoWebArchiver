import responses

from autoarchiver.spn2.client import SPN2Client


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
def test_submit_retries_after_429(monkeypatch):
    monkeypatch.setattr("autoarchiver.spn2.client.time.sleep", lambda *_: None)
    monkeypatch.setattr("autoarchiver.spn2.client.random.uniform", lambda *_: 0)

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
    monkeypatch.setattr("autoarchiver.spn2.client.time.sleep", lambda *_: None)
    responses.add(
        responses.GET,
        "https://web.archive.org/save/status/job-1",
        json={"status": "pending", "job_id": "job-1", "resources": []},
        status=200,
    )

    client = make_client()
    result = client.poll_until_resolved("job-1", "https://example.com/", interval=1, timeout=0)

    assert result.status == "timeout"


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
