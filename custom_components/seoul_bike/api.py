"""Public site API with bounded, read-only network recovery.

The original login, payload and parsing implementation lives unchanged in
site_api.py. Keep this module as the stable import path used by the integration.
"""

from __future__ import annotations

from time import time_ns

from yarl import URL

from .const import API_PATH_FAVORITES

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
