"""Public site API with bounded, read-only network recovery.

The original login, payload and parsing implementation lives unchanged in
site_api.py. Keep this module as the stable import path used by the integration.
"""

from __future__ import annotations

from time import time_ns
from typing import Any
from urllib.parse import urlsplit

from yarl import URL

from .const import API_PATH_FAVORITES, API_PATH_LOGIN

from .site_api import (
    SeoulPublicBikeSiteApi as _SiteApi,
    _normalize_cookie,
    _strip_tags,
)
from .transport import site_request

# Retain the helpers historically imported from this module.
__all__ = ["SeoulPublicBikeSiteApi", "_normalize_cookie", "_strip_tags"]


class SeoulPublicBikeSiteApi(_SiteApi):
    """Preserve site behavior while recovering from transient connection loss."""

    # Final address of the last request that got a response. site_api's error
    # path overwrites last_meta with the requested URL, which hides a redirect
    # to the sign-in page.
    last_response_url: str | None = None

    def _record_meta(
        self,
        method: str,
        url: str,
        status: int | None,
        error: str | None = None,
    ) -> None:
        super()._record_meta(method, url, status, error)
        if status is not None:
            self.last_response_url = url

    def rent_status_redirected_to_login(self) -> bool:
        """Return true when the last rent status request ended on /login.do."""
        return urlsplit(str(self.last_response_url or "")).path.endswith(API_PATH_LOGIN)

    async def fetch_rent_status(self) -> dict[str, Any]:
        self.last_response_url = None
        return await super().fetch_rent_status()

    async def login(self, username: str, password: str) -> str:
        try:
            return await super().login(username, password)
        except ValueError as err:
            # The check after the login POST lands on the sign-in page when the
            # site rejected the password. Report a rejection, never a temporary
            # error that would send the same password again on every poll.
            if str(err) == "non_json_response" and self.rent_status_redirected_to_login():
                raise ValueError("login_failed") from err
            raise

    def _headers(self, referer_path: str | None = None) -> dict[str, str]:
        headers = super()._headers(referer_path)
        # This legacy server may close idle keep-alive connections between polls.
        # Do not retain this response's socket, or alter HA's shared connector.
        headers["Connection"] = "close"
        headers["Cache-Control"] = "no-cache, no-store, max-age=0"
        headers["Pragma"] = "no-cache"
        return headers

    async def fetch_favorites_html(self) -> str:
        """Read a fresh account snapshot, not a cached favorite page."""
        return await self._get_text(
            API_PATH_FAVORITES,
            params={"_": str(time_ns())},
            referer_path=API_PATH_FAVORITES,
        )

    def _cookie_header_from_session(self) -> str:
        """Read this session's cookies; aiohttp 4 accepts only yarl.URL here."""
        try:
            cookies = self._session.cookie_jar.filter_cookies(URL(self.BASE))
        except Exception:
            cookies = {}
        parts: list[str] = []
        for name, morsel in cookies.items():
            value = getattr(morsel, "value", None)
            if value is None:
                continue
            parts.append(f"{name}={value}")
        return "; ".join(parts)

    _get_text = site_request("GET")(_SiteApi._get_text)
    _get_json = site_request("GET")(_SiteApi._get_json)
    _get_text_url = site_request("GET")(_SiteApi._get_text_url)
    _post_text = site_request("POST")(_SiteApi._post_text)
    _post_json = site_request("POST")(_SiteApi._post_json)
