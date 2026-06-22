from __future__ import annotations

from dataclasses import dataclass

# status_ext values that are permanent failures: retrying will not help.
# Anything not in this set is treated as transient and eligible for retry.
NON_RETRYABLE_STATUS_EXT = {
    "error:bad-request",
    "error:blocked",
    "error:blocked-client-ip",
    "error:blocked-url",
    "error:filesize-limit",
    "error:ftp-access-denied",
    "error:invalid-url-syntax",
    "error:invalid-host-resolution",
    "error:method-not-allowed",
    "error:no-access",
    "error:not-found",
    "error:not-implemented",
    "error:too-many-daily-captures",
    "error:unauthorized",
    "error:max-daily-bandwidth",
    "error:max-daily-bandwidth-from-ip",
    "error:max-daily-bandwidth-host",
}


@dataclass(frozen=True)
class SPN2Result:
    job_id: str
    url: str
    status: str  # "success" | "error" | "timeout"
    original_url: str | None = None
    timestamp: str | None = None
    duration_sec: float | None = None
    status_ext: str | None = None
    message: str | None = None

    @property
    def is_retryable_error(self) -> bool:
        if self.status != "error":
            return False
        return self.status_ext not in NON_RETRYABLE_STATUS_EXT

    @property
    def wayback_url(self) -> str | None:
        if self.status != "success" or not self.timestamp or not self.original_url:
            return None
        return f"https://web.archive.org/web/{self.timestamp}/{self.original_url}"
