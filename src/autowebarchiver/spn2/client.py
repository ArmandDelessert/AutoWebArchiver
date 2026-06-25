from __future__ import annotations

import logging
import random
import time
from collections import deque

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .models import SPN2Result, result_from_status_payload

logger = logging.getLogger(__name__)

_CAPTURE_URL = "https://web.archive.org/save"
_STATUS_URL = "https://web.archive.org/save/status/{job_id}"
_USER_STATUS_URL = "https://web.archive.org/save/status/user"
_SYSTEM_STATUS_URL = "https://web.archive.org/save/status/system"


class SPN2Error(Exception):
    """Raised for non-retryable failures while talking to the SPN2 API."""


class SPN2Client:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        *,
        session: requests.Session | None = None,
        max_captures_per_minute: int = 7,
        request_timeout: int = 30,
    ) -> None:
        self._session = session or requests.Session()
        self._auth_header = f"LOW {access_key}:{secret_key}"
        self._max_captures_per_minute = max_captures_per_minute
        self._request_timeout = request_timeout
        self._submit_timestamps: deque[float] = deque()

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Authorization": self._auth_header}

    _WINDOW = 60.0

    def _prune_timestamps(self, now: float) -> None:
        while self._submit_timestamps and now - self._submit_timestamps[0] > self._WINDOW:
            self._submit_timestamps.popleft()

    def next_submit_wait_seconds(self) -> float:
        """Return how long (in seconds) until a submission would respect
        max_captures_per_minute. 0.0 means a slot is free right now. This is a
        pure check based on a local rolling window of submit timestamps -- it
        records nothing and never blocks."""
        now = time.monotonic()
        self._prune_timestamps(now)
        if len(self._submit_timestamps) < self._max_captures_per_minute:
            return 0.0
        return max(0.0, self._WINDOW - (now - self._submit_timestamps[0]) + 0.1)

    def _throttle(self) -> None:
        """Block until submitting would not exceed max_captures_per_minute, then
        record the submission. Callers that pre-check next_submit_wait_seconds()
        (e.g. the sliding-window loop) will find this is a no-op wait."""
        wait = self.next_submit_wait_seconds()
        if wait > 0:
            logger.debug("Throttling SPN2 submissions, sleeping %.1fs", wait)
            time.sleep(wait)
        self._submit_timestamps.append(time.monotonic())

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def submit(
        self,
        url: str,
        *,
        capture_all: bool = False,
        capture_outlinks: bool = False,
        capture_screenshot: bool = False,
        skip_first_archive: bool = True,
        if_not_archived_within: str | None = None,
        js_behavior_timeout: int | None = None,
        force_get: bool = False,
    ) -> str:
        """Submit a capture request and return the job_id."""
        self._throttle()

        data = {"url": url}
        if capture_all:
            data["capture_all"] = "1"
        if capture_outlinks:
            data["capture_outlinks"] = "1"
        if capture_screenshot:
            data["capture_screenshot"] = "1"
        if skip_first_archive:
            data["skip_first_archive"] = "1"
        if force_get:
            data["force_get"] = "1"
        if if_not_archived_within:
            data["if_not_archived_within"] = if_not_archived_within
        if js_behavior_timeout is not None:
            data["js_behavior_timeout"] = str(js_behavior_timeout)

        response = self._session.post(
            _CAPTURE_URL, headers=self._headers(), data=data, timeout=self._request_timeout
        )

        if response.status_code == 429:
            logger.warning('SPN2 returned 429 for "%s", backing off', url)
            time.sleep(random.uniform(10, 20))
            response.raise_for_status()

        response.raise_for_status()
        payload = response.json()
        job_id = payload.get("job_id")
        if not job_id:
            raise SPN2Error(f"SPN2 capture request for {url} did not return a job_id: {payload}")
        return job_id

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def get_status(self, job_id: str) -> dict:
        response = self._session.get(
            _STATUS_URL.format(job_id=job_id), headers=self._headers(), timeout=self._request_timeout
        )
        response.raise_for_status()
        return response.json()

    def poll_until_resolved(
        self, job_id: str, url: str, *, interval: int = 15, timeout: int = 180
    ) -> SPN2Result:
        """Poll a capture job until it resolves to success/error, or timeout."""
        deadline = time.monotonic() + timeout
        while True:
            payload = self.get_status(job_id)
            result = result_from_status_payload(job_id, url, payload)
            if result is not None:
                return result

            if time.monotonic() >= deadline:
                logger.warning("Timed out waiting for SPN2 job %s (%s)", job_id, url)
                return SPN2Result(job_id=job_id, url=url, status="timeout")

            time.sleep(interval)

    def submit_and_poll(self, url: str, *, interval: int = 15, timeout: int = 180, **submit_kwargs) -> SPN2Result:
        job_id = self.submit(url, **submit_kwargs)
        return self.poll_until_resolved(job_id, url, interval=interval, timeout=timeout)

    def get_user_status(self) -> dict:
        """Returns {"available": N, "processing": N} for the authenticated account."""
        response = self._session.get(
            _USER_STATUS_URL,
            headers=self._headers(),
            params={"_t": random.randint(0, 10_000_000)},
            timeout=self._request_timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_system_status(self) -> dict:
        response = self._session.get(_SYSTEM_STATUS_URL, timeout=self._request_timeout)
        response.raise_for_status()
        return response.json()
