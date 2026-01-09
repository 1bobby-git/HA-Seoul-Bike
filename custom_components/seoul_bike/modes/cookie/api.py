from __future__ import annotations

import aiohttp


def _normalize_cookie(raw: str) -> str:
    v = (raw or "").strip().strip('"').strip("'")
    low = v.lower()
    if low.startswith("cookie "):
        v = v[7:].strip()
    low = v.lower()
    if low.startswith("cookie:"):
        v = v[7:].strip()
    return v


class SeoulPublicBikeSiteApi:
    BASE = "https://www.bikeseoul.com"

    def __init__(self, session: aiohttp.ClientSession, cookie: str) -> None:
        self._session = session
        self._cookie = _normalize_cookie(cookie)

        # 일반적인 모바일 UA (고정)
        self._ua = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        )

    def set_cookie(self, cookie: str) -> None:
        self._cookie = _normalize_cookie(cookie)

    def _headers(self, referer_path: str | None = None) -> dict[str, str]:
        h = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
            "Connection": "keep-alive",
        }
        if self._cookie:
            h["Cookie"] = self._cookie
        if referer_path:
            h["Referer"] = f"{self.BASE}{referer_path}"
        return h

    async def _get_text(self, path: str, params: dict | None = None, referer_path: str | None = None) -> str:
        url = f"{self.BASE}{path}"
        async with self._session.get(url, params=params, headers=self._headers(referer_path), allow_redirects=True) as resp:
            resp.raise_for_status()
            return await resp.text(errors="ignore")

    async def fetch_use_history_html(self) -> str:
        return await self._get_text("/app/mybike/getMemberUseHistory.do", referer_path="/app/mybike/getMemberUseHistory.do")

    async def fetch_left_page_html(self) -> str:
        return await self._get_text("/myLeftPage.do", referer_path="/myLeftPage.do")

    async def fetch_favorites_html(self) -> str:
        return await self._get_text("/app/mybike/favoriteStation.do", referer_path="/app/mybike/favoriteStation.do")

    async def fetch_station_realtime_html(self, station_id: str | None, station_no: str | None) -> str:
        """
        즐겨찾기 대여소 수량 파싱용.
        사이트 구현이 케이스별로 달라서, 가능한 범위에서 가장 보수적으로 시도한다.
        """
        tries: list[tuple[dict | None, str | None]] = []

        if station_id:
            tries.append(({"stationId": station_id}, "/app/mybike/favoriteStation.do"))
        if station_no:
            tries.append(({"stationNo": station_no}, "/app/mybike/favoriteStation.do"))
        if station_id and station_no:
            tries.append(({"stationId": station_id, "stationNo": station_no}, "/app/mybike/favoriteStation.do"))

        # 마지막 fallback: 파라미터 없이
        tries.append((None, "/app/mybike/favoriteStation.do"))

        last_exc: Exception | None = None
        for params, ref in tries:
            try:
                return await self._get_text("/app/station/moveStationRealtimeStatus.do", params=params, referer_path=ref)
            except Exception as e:
                last_exc = e

        raise last_exc if last_exc else RuntimeError("대여소 실시간 페이지 요청 실패")
