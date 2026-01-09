from __future__ import annotations

import logging
import re
from datetime import timedelta, datetime
from typing import Any
from html import unescape

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SeoulPublicBikeSiteApi
from .const import CONF_COOKIE, DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL_S = 60


def _strip_tags(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return unescape(s).replace("\xa0", " ").strip()


def _to_float(text: str) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _extract_div_by_class(html: str, class_name: str) -> str | None:
    pattern = (
        r'<div[^>]*class=["\'][^"\']*\b'
        + re.escape(class_name)
        + r'\b[^"\']*["\'][^>]*>(.*?)</div>'
    )
    m = re.search(pattern, html or "", flags=re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def _extract_kcal_box(html: str) -> dict[str, str]:
    block = _extract_div_by_class(html, "kcal_box")
    if not block:
        return {}

    pairs = re.findall(
        r'alt="([^"]+)"[^>]*>.*?<p>\s*([^<]+?)\s*</p>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )

    out: dict[str, str] = {}
    for k, v in pairs:
        key = (k or "").strip()
        val = (v or "").strip()
        if key and val:
            out[key] = val
    return out


def _extract_payment_history(html: str) -> list[dict[str, Any]]:
    block = _extract_div_by_class(html, "payment_box")
    if not block:
        return []

    table_m = re.search(r"<table[^>]*>(.*?)</table>", block, flags=re.DOTALL | re.IGNORECASE)
    if not table_m:
        return []

    table_html = table_m.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE)

    out: list[dict[str, Any]] = []
    for r in rows:
        if re.search(r"<\s*th\b", r, flags=re.IGNORECASE):
            continue

        tds = re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.DOTALL | re.IGNORECASE)
        if len(tds) < 5:
            continue

        cells = [_strip_tags(x) for x in tds]
        bike = cells[0]
        rent_dt = cells[1]
        rent_station = cells[2]
        return_dt = cells[3]
        return_station = cells[4]

        hist_id = cells[5] if len(cells) > 5 else None
        dist_km = _to_float(cells[6]) if len(cells) > 6 else None

        out.append(
            {
                "bike": bike,
                "rent_datetime": rent_dt,
                "rent_station": rent_station,
                "return_datetime": return_dt,
                "return_station": return_station,
                "history_id": hist_id,
                "distance_km": dist_km,
            }
        )

    return out


def _looks_like_login(html: str) -> bool:
    t = (html or "").lower()
    return ("로그인" in t and "비밀번호" in t) or ("/login" in t and "password" in t)


def _parse_ticket_expiry(left_html: str) -> datetime | None:
    if not left_html:
        return None

    tz = dt_util.DEFAULT_TIME_ZONE

    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})\s+(\d{1,2}):(\d{2})", left_html)
    if m:
        y, mo, d, hh, mm = map(int, m.groups())
        dt_local = datetime(y, mo, d, hh, mm, tzinfo=tz)
        return dt_util.as_utc(dt_local)

    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", left_html)
    if m:
        y, mo, d = map(int, m.groups())
        dt_local = datetime(y, mo, d, 0, 0, tzinfo=tz)
        return dt_util.as_utc(dt_local)

    return None


def _extract_favorites_with_counts(fav_html: str) -> list[dict[str, Any]]:
    """
    favoriteStation.do 마크업에서:
    - moveRentalStation('ST-xxxx', '대여소명')
    - <div class="bike">일반 / 새싹<p>12 / 0</p></div>
    를 같은 <li> 안에서 함께 파싱한다.
    """
    if not fav_html:
        return []

    lis = re.findall(r"<li\b[^>]*>(.*?)</li>", fav_html, flags=re.DOTALL | re.IGNORECASE)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for li in lis:
        m = re.search(
            r"moveRentalStation\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)",
            li,
            flags=re.IGNORECASE,
        )
        if not m:
            continue

        station_id = (m.group(1) or "").strip()
        station_name = (m.group(2) or "").strip()
        if not station_id or not station_name:
            continue

        key = (station_id, station_name)
        if key in seen:
            continue
        seen.add(key)

        # counts: <div class="bike"> ... <p>12 / 0</p>
        cm = re.search(
            r'<div[^>]*class=["\'][^"\']*\bbike\b[^"\']*["\'][^>]*>.*?<p>\s*(\d+)\s*/\s*(\d+)\s*</p>',
            li,
            flags=re.DOTALL | re.IGNORECASE,
        )
        normal = int(cm.group(1)) if cm else None
        sprout = int(cm.group(2)) if cm else None

        m_no = re.match(r"^\s*(\d+)\.", station_name)
        station_no = m_no.group(1) if m_no else ""

        out.append(
            {
                "station_id": station_id,
                "station_name": station_name,
                "station_no": station_no,
                "normal": normal,
                "sprout": sprout,
            }
        )

    return out


class SeoulPublicBikeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        raw_cookie = entry.options.get(CONF_COOKIE) or entry.data.get(CONF_COOKIE) or ""
        self._api = SeoulPublicBikeSiteApi(async_get_clientsession(hass), raw_cookie)

        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_S),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            raw_cookie = self.entry.options.get(CONF_COOKIE) or self.entry.data.get(CONF_COOKIE) or ""
            self._api.set_cookie(raw_cookie)

            use_html = await self._api.fetch_use_history_html()
            if _looks_like_login(use_html):
                return {
                    "error": "로그인 페이지로 응답됨(쿠키 만료/권한/세션 제한 가능)",
                    "updated_at": datetime.now().isoformat(),
                    "kcal": {},
                    "history": [],
                    "last": {},
                    "ticket_expiry": None,
                    "favorites": [],
                    "favorite_status": {},
                }

            kcal = _extract_kcal_box(use_html)
            history = _extract_payment_history(use_html)
            last = history[0] if history else {}

            left_html = await self._api.fetch_left_page_html()
            ticket_expiry = None if _looks_like_login(left_html) else _parse_ticket_expiry(left_html)

            fav_html = await self._api.fetch_favorites_html()
            favorites = [] if _looks_like_login(fav_html) else _extract_favorites_with_counts(fav_html)

            # ✅ 즐겨찾기 값은 favoriteStation.do 마크업의 p(일반/새싹)로 확정
            favorite_status: dict[str, Any] = {}
            for f in favorites:
                sid = f.get("station_id") or ""
                favorite_status[sid] = {
                    "station_id": sid,
                    "station_name": f.get("station_name"),
                    "station_no": f.get("station_no"),
                    "normal": f.get("normal"),
                    "sprout": f.get("sprout"),
                }

            return {
                "error": None,
                "updated_at": datetime.now().isoformat(),
                "kcal": kcal,
                "history": history,
                "last": last,
                "ticket_expiry": ticket_expiry.isoformat() if ticket_expiry else None,
                "favorites": favorites,          # counts 포함
                "favorite_status": favorite_status,
            }

        except Exception as err:
            raise UpdateFailed(f"업데이트 실패: {err}") from err
