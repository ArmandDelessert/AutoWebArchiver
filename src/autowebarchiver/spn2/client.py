from __future__ import annotations

import logging
import random
import time
from collections import deque

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)

_CAPTURE_URL = "https://web.archive.org/save"
_STATUS_URL = "https://web.archive.org/save/status/{job_id}"
_USER_STATUS_URL = "https://web.archive.org/save/status/user"
_SYSTEM_STATUS_URL = "https://web.archive.org/save/status/system"


class SPN2Error(Exception):
    """Raised for non-retryable failures while talking to the SPN2 API."""


class AlreadyArchivedError(SPN2Error):
    """Raised when SPN2 skips the capture because a capture recent enough to
    satisfy if_not_archived_within already exists. Not a failure: the URL is
    already archived, just not by this request, so callers should treat it as
    a resolved outcome rather than an error to retry."""


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
        self.rate_limited_count = 0  # total 429s seen from /save across this client's lifetime

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
        """Block until submitting would not exceed max_captures_per_minute.
        Does NOT record the attempt -- callers record it themselves (via
        _record_submit) only once the outcome is known, so requests SPN2
        answers without doing real capture work (if_not_archived_within
        dedup skips) don't consume a slot of our local budget. Callers that
        pre-check next_submit_wait_seconds() (e.g. the sliding-window loop)
        will find this is a no-op wait."""
        wait = self.next_submit_wait_seconds()
        if wait > 0:
            logger.debug("Throttling SPN2 submissions, sleeping %.1fs", wait)
            time.sleep(wait)

    def _record_submit(self) -> None:
        """Record that a submission actually happened, for rate-limiting
        purposes. Called only when SPN2 did real capture work (a job_id came
        back) -- not for dedup skips (AlreadyArchivedError), which cost SPN2
        a cheap index lookup rather than the crawler capacity the 7/min cap
        is meant to protect."""
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
            # A real rate-limit rejection: this attempt genuinely counted
            # against SPN2's budget, so record it too (on top of the
            # server-mandated backoff) -- self-correcting our own pacing to
            # be more conservative rather than immediately retrying as if
            # nothing happened.
            self._record_submit()
            self.rate_limited_count += 1
            logger.warning('SPN2 returned 429 for "%s", backing off', url)
            time.sleep(random.uniform(10, 20))
            response.raise_for_status()

        response.raise_for_status()
        payload = response.json()
        job_id = payload.get("job_id")
        if not job_id:
            # SPN2 returns 200 with no job_id specifically when
            # if_not_archived_within is already satisfied by an existing
            # capture -- it's telling us no new capture was needed, not that
            # the request failed. This didn't consume any real crawler
            # capacity, so it doesn't count against our local submit budget
            # either (see _record_submit).
            message = payload.get("message") or f"No job_id returned for {url}: {payload}"
            raise AlreadyArchivedError(message)
        self._record_submit()
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
