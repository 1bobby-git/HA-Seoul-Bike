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

    # site_api's error path overwrites last_meta with the requested URL, which
    # hides a redirect to the sign-in page, so these flags follow the final
    # address of each response instead.
    _tracking_rent_status = False
    _rent_status_saw_login_page = False
    _login_post_landed_on_login_page = False

    def _record_meta(
        self,
        method: str,
        url: str,
        status: int | None,
        error: str | None = None,
    ) -> None:
        super()._record_meta(method, url, status, error)
        if status is None:
            return
        on_login_page = urlsplit(str(url)).path.endswith(API_PATH_LOGIN)
        if method == "POST":
            self._login_post_landed_on_login_page = on_login_page
        elif self._tracking_rent_status and on_login_page:
            self._rent_status_saw_login_page = True

    def rent_status_redirected_to_login(self) -> bool:
        """Return true when the last rent status check reached /login.do.

        Either rent status path counts, whatever the other path answered.
        """
        return self._rent_status_saw_login_page

    async def fetch_rent_status(self) -> dict[str, Any]:
        self._rent_status_saw_login_page = False
        self._tracking_rent_status = True
        try:
            return await super().fetch_rent_status()
        finally:
            self._tracking_rent_status = False

    async def login(self, username: str, password: str) -> str:
        self._login_post_landed_on_login_page = False
        self._rent_status_saw_login_page = False
        try:
            return await super().login(username, password)
        except Exception as err:
            # The site sent the login form back and the check after it lands on
            # the sign-in page: the password was rejected. Report a rejection,
            # never a temporary error that would send the same password again
            # on every poll. An accepted login whose check is redirected stays
            # a temporary error.
            if self._login_post_landed_on_login_page and self._rent_status_saw_login_page:
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
