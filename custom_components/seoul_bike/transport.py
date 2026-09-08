"""Bounded retries for read-only requests to the legacy Seoul Bike site."""

from __future__ import annotations

import asyncio
import errno
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .const import (
    API_PATH_MOVE_ROUTE,
    API_PATH_STATION_REALTIME_ALL,
    API_PATH_VOUCHER_INFO,
)

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 10.0
RETRY_DELAYS = (0.5, 1.0)
MAX_RETRY_AFTER_SECONDS = 5.0
_READ_ONLY_POST_PATHS = frozenset(
    (API_PATH_MOVE_ROUTE, API_PATH_STATION_REALTIME_ALL, API_PATH_VOUCHER_INFO)
)
_RETRYABLE_STATUSES = frozenset((500, 502, 503, 504))
_RETRYABLE_ERRNOS = frozenset(
    (errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE, errno.ETIMEDOUT,
     errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH)
)


def _is_transient(error: Exception) -> bool:
    """Never retry authentication, invalid content, or TLS validation failures."""
    if isinstance(error, (aiohttp.ClientSSLError, aiohttp.ServerFingerprintMismatch)):
        return False
    if isinstance(error, aiohttp.ClientResponseError):
        return error.status in _RETRYABLE_STATUSES
    if isinstance(error, (TimeoutError, aiohttp.ClientConnectionError, aiohttp.ClientPayloadError)):
        return True
    return isinstance(error, OSError) and error.errno in _RETRYABLE_ERRNOS


def _retry_delay(error: Exception, default: float) -> float | None:
    """Respect Retry-After; defer long/invalid waits to HA's next poll."""
    if not isinstance(error, aiohttp.ClientResponseError) or not error.headers:
        return default
    raw = error.headers.get("Retry-After")
    if raw is None:
        return default
    try:
        value = str(raw).strip()
        if value.isdigit():
            seconds = float(value)
        else:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
    if seconds > MAX_RETRY_AFTER_SECONDS:
        return None
    return max(default, seconds)


def site_request(method: str):
    """Wrap one existing site method without changing its parsing or payloads.

    GETs and the three explicitly allowlisted query POSTs may be retried.
    Login and any future/unrecognised POST remain single-attempt operations.
    Cancellation is deliberately not caught (CancelledError is BaseException).
    """
    def decorate(func):
        @wraps(func)
        async def request(self, *args: Any, **kwargs: Any):
            path = args[0] if args else kwargs.get("path", kwargs.get("url", ""))
            can_retry = method == "GET" or (
                method == "POST" and path in _READ_ONLY_POST_PATHS
            )
            attempts = len(RETRY_DELAYS) + 1 if can_retry else 1
            endpoint = urlsplit(path).path
            url = f"{self.BASE}{endpoint}" if endpoint.startswith("/") else endpoint
            for attempt in range(1, attempts + 1):
                # Do not let an earlier success on the same URL mask this failure.
                self.last_meta = None
                self.last_error = None
                try:
                    async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                        result = await func(self, *args, **kwargs)
                except Exception as error:
                    transient = _is_transient(error)
                    if isinstance(error, aiohttp.ClientResponseError):
                        self._record_meta(method, url, error.status, f"http_{error.status}")
                    elif transient or not self.last_meta:
                        # Never log request headers, cookies, POST bodies, or raw URLs.
                        code = type(error).__name__
                        if isinstance(error, OSError) and error.errno is not None:
                            code = f"{code}:errno_{error.errno}"
                        self._record_meta(method, url, None, code)
                    self.last_meta["attempts"] = attempt
                    if not transient or attempt == attempts:
                        raise
                    delay = _retry_delay(error, RETRY_DELAYS[attempt - 1])
                    if delay is None:
                        raise
                    _LOGGER.debug(
                        "Transient %s failure for %s %s (attempt %s/%s); retry in %.1fs",
                        type(error).__name__, method, endpoint, attempt, attempts, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    if self.last_meta is not None:
                        self.last_meta["attempts"] = attempt
                    return result
        return request
    return decorate
