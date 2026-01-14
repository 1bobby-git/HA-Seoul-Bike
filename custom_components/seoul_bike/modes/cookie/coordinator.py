# custom_components/seoul_bike/modes/cookie/coordinator.py

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta, datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any
from html import unescape
from html.parser import HTMLParser

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SeoulPublicBikeSiteApi
from .const import (
    CONF_COOKIE,
    CONF_COOKIE_PASSWORD,
    CONF_COOKIE_UPDATE_INTERVAL,
    CONF_COOKIE_USERNAME,
    CONF_LOCATION_ENTITY,
    CONF_MAX_RESULTS,
    CONF_MIN_BIKES,
    CONF_RADIUS_M,
    CONF_STATION_IDS,
    CONF_USE_HISTORY_WEEK,
    CONF_USE_HISTORY_MONTH,
    DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_MIN_BIKES,
    DEFAULT_RADIUS_M,
    DEFAULT_USE_HISTORY_WEEK,
    DEFAULT_USE_HISTORY_MONTH,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL_S = 60
_DATA_MARKER_RE = re.compile(
    r"(kcal_box|payment_box|moveRentalStation\(\s*'ST-[^']+'\s*,\s*'[^']+'\s*\))",
    re.IGNORECASE,
)
_LOGIN_FORM_RE = re.compile(r'<form[^>]+action=["\'][^"\']*(j_spring_security_check|login)[^"\']*["\']', re.IGNORECASE)
_PASSWORD_INPUT_RE = re.compile(r'<input[^>]+type=["\']password["\']', re.IGNORECASE)
_LOGOUT_MARKER_RE = re.compile(r"(logout|/logout|logout\.do)", re.IGNORECASE)
_STATION_NO_RE = re.compile(r"^\s*(\d+)\s*(?:[.)-]|\s)")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return r * c


@dataclass(slots=True)
class Station:
    station_id: str
    station_no: str
    station_title: str
    lat: float
    lon: float
    bikes_total: int
    bikes_general: int
    bikes_sprout: int
    bikes_repair: int


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


def _to_int(text: str | int | None, default: int = 0) -> int:
    try:
        return int(str(text).strip())
    except Exception:
        return int(default)


def _parse_station_list(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
        return list(dict.fromkeys(items))
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace("\n", ",").replace("\r", ",").split(",")]
    parts = [p for p in parts if p]
    return list(dict.fromkeys(parts))


def _extract_div_by_class(html: str, class_name: str) -> str | None:
    pattern = (
        r'<div[^>]*class=["\'][^"\']*\b'
        + re.escape(class_name)
        + r'\b[^"\']*["\'][^>]*>(.*?)</div>'
    )
    m = re.search(pattern, html or "", flags=re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


class _KcalBoxParser(HTMLParser):
    """HTML parser to extract key-value pairs from the kcal_box div."""

    def __init__(self) -> None:
        super().__init__()
        self.in_kcal_div = False
        self.current_key: str | None = None
        self.data: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        if tag == "div":
            # Enter kcal_box div if class attribute contains "kcal_box"
            for name, value in attrs:
                if name == "class" and "kcal_box" in value:
                    self.in_kcal_div = True
                    return
        elif self.in_kcal_div and tag == "p":
            # Reset current key when encountering a new <p> tag
            if self.current_key is not None:
                # If we encounter two keys in a row without a value, ignore
                self.current_key = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.in_kcal_div:
            self.in_kcal_div = False

    def handle_data(self, data: str) -> None:
        if not self.in_kcal_div:
            return
        text = data.strip()
        if not text:
            return
        if self.current_key is None:
            self.current_key = text
        else:
            # Save the key/value pair
            self.data[self.current_key] = text
            self.current_key = None



def _extract_kcal_box(html: str) -> dict[str, str]:
    """Extract kcal_box key/value pairs using an HTML parser."""
    parser = _KcalBoxParser()
    parser.feed(html)
    return parser.data

   


def _extract_payment_history(html: str) -> list[dict[str, Any]]:
    if not html:
        return []

    block = _extract_div_by_class(html, "payment_box") or _extract_div_by_class(html, "paymentBox")
    if not block:
        # fallback: scan full html for history table
        block = html

    tables = re.findall(r"<table[^>]*>(.*?)</table>", block, flags=re.DOTALL | re.IGNORECASE)
    if not tables and block is not html:
        tables = re.findall(r"<table[^>]*>(.*?)</table>", html, flags=re.DOTALL | re.IGNORECASE)

    def _parse_table(table_html: str) -> list[dict[str, Any]]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE)
        out: list[dict[str, Any]] = []
        for r in rows:
            tds = re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.DOTALL | re.IGNORECASE)
            if len(tds) < 5:
                continue

            cells = [_strip_tags(x) for x in tds]
            if not any(cells):
                continue

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

    for table_html in tables:
        parsed = _parse_table(table_html)
        if parsed:
            return parsed

    return []


def _status_login_ok(status: dict[str, Any]) -> bool | None:
    if not status:
        return None
    login = str(status.get("loginYn") or "").strip().upper()
    if not login:
        return None
    if login != "Y":
        return False
    member = str(status.get("memberYn") or "").strip().upper()
    if member and member != "Y":
        return False
    return True



def _looks_like_login(html: str) -> bool:
    if not html:
        return True

    lower = html.lower()
    if _DATA_MARKER_RE.search(html):
        return False
    if _LOGOUT_MARKER_RE.search(html):
        return False
    has_password = _PASSWORD_INPUT_RE.search(html)
    has_login = ("j_spring_security_check" in lower and has_password) or (_LOGIN_FORM_RE.search(html) and has_password)
    return bool(has_login)


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


def _extract_period_range(html: str) -> tuple[str | None, str | None]:
    if not html:
        return None, None
    date_re = r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})"

    def _normalize(m: re.Match) -> str:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    start = None
    end = None

    for m in re.finditer(r'name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
        name = (m.group(1) or "").lower()
        value = m.group(2) or ""
        dm = re.search(date_re, value)
        if not dm:
            continue
        if ("start" in name or "from" in name) and not start:
            start = _normalize(dm)
        if ("end" in name or "to" in name) and not end:
            end = _normalize(dm)

    if not start or not end:
        dates = [m for m in re.finditer(date_re, html)]
        if len(dates) >= 2:
            start = start or _normalize(dates[0])
            end = end or _normalize(dates[1])

    return start, end


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
        station_id = ""
        station_name = ""

        m_anchor = re.search(
            r'<div[^>]*class=["\'][^"\']*\bplace\b[^"\']*["\'][^>]*>.*?<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            li,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not m_anchor:
            m_anchor = re.search(
                r'<a[^>]*class=["\'][^"\']*\bplace\b[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                li,
                flags=re.IGNORECASE | re.DOTALL,
            )
        if not m_anchor:
            m_anchor = re.search(
                r'<a[^>]*href=["\']([^"\']*ST-[^"\']+)["\'][^>]*>(.*?)</a>',
                li,
                flags=re.IGNORECASE | re.DOTALL,
            )
        if m_anchor:
            href = m_anchor.group(1) or ""
            text = _strip_tags(m_anchor.group(2) or "")
            m_st = re.search(r"(ST-\d+)", href, re.IGNORECASE)
            if m_st:
                station_id = m_st.group(1).upper()
            if text:
                station_name = text

        if not station_id or not station_name:
            m = re.search(
                r"moveRentalStation\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)",
                li,
                flags=re.IGNORECASE,
            )
            if m:
                station_id = station_id or (m.group(1) or "").strip()
                station_name = station_name or (m.group(2) or "").strip()

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


def _parse_use_history(html: str) -> dict[str, Any]:
    start, end = _extract_period_range(html)
    kcal = _extract_kcal_box(html)
    history = _extract_payment_history(html)
    last = history[0] if history else {}
    return {
        "period_start": start,
        "period_end": end,
        "kcal": kcal,
        "history": history,
        "last": last,
    }


def _fallback_station(
    prev: dict[str, Station],
    station_id: str | None,
    station_no: str | None,
    raw_id: str | None,
) -> Station | None:
    if not prev:
        return None
    if station_id and station_id in prev:
        return prev.get(station_id)
    if station_no:
        for st in prev.values():
            if st.station_no == station_no:
                return st
    if raw_id:
        for st in prev.values():
            if st.station_id == raw_id or st.station_no == raw_id:
                return st
    return None

class SeoulPublicBikeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        raw_cookie = entry.options.get(CONF_COOKIE) or entry.data.get(CONF_COOKIE) or ""
        self._api = SeoulPublicBikeSiteApi(async_get_clientsession(hass), raw_cookie)
        self.last_error: str | None = None
        self.last_http_status: int | None = None
        self.last_request_url: str | None = None
        self.validation_status: str | None = None
        self.location_entity_id: str = ""
        self.radius_m: int = DEFAULT_RADIUS_M
        self.max_results: int = DEFAULT_MAX_RESULTS
        self.min_bikes: int = DEFAULT_MIN_BIKES
        self.center_source: str = "homeassistant_home"
        self.center_lat: float | None = None
        self.center_lon: float | None = None
        self.nearby_status: str = "unknown"
        self.nearby: list[dict[str, Any]] = []
        self.nearby_total_bikes: int = 0
        self.nearby_recommended_bikes: int = 0
        self.station_ids: list[str] = []
        self.stations_by_id: dict[str, Station] = {}

        try:
            update_interval_s = int(
                entry.options.get(CONF_COOKIE_UPDATE_INTERVAL)
                or entry.data.get(CONF_COOKIE_UPDATE_INTERVAL)
                or DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS
            )
        except Exception:
            update_interval_s = DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS

        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=update_interval_s),
        )

    def _sync_last_request_meta(self) -> None:
        meta = self._api.last_meta or {}
        self.last_http_status = meta.get("status") or meta.get("http_status")
        self.last_request_url = meta.get("url")
        if self._api.last_error and not self.last_error:
            self.last_error = self._api.last_error

    def _compute_center(self) -> None:
        self.center_source = "homeassistant_home"
        self.center_lat = self.hass.config.latitude
        self.center_lon = self.hass.config.longitude

        ent_id = (self.location_entity_id or "").strip()
        if not ent_id:
            self.nearby_status = "ok"
            return

        st = self.hass.states.get(ent_id)
        if not st:
            self.nearby_status = "location_entity_not_found"
            return

        lat = st.attributes.get("latitude")
        lon = st.attributes.get("longitude")
        if lat is None or lon is None:
            self.nearby_status = "location_no_coords"
            return

        try:
            self.center_lat = float(lat)
            self.center_lon = float(lon)
            self.center_source = ent_id
            self.nearby_status = "ok"
        except Exception:
            self.nearby_status = "location_invalid_coords"

    def _station_from_status(
        self,
        status: dict[str, Any],
        fallback_station_id: str | None,
        fallback_station_no: str | None,
        fallback_name: str | None,
    ) -> Station | None:
        sid = str(status.get("stationId") or fallback_station_id or fallback_station_no or "").strip()
        if not sid:
            return None

        raw_name = str(status.get("stationName") or fallback_name or "").strip()
        station_no = str(status.get("stationNo") or fallback_station_no or "").strip()
        station_title = raw_name

        if raw_name:
            m = _STATION_NO_RE.match(raw_name)
            if m:
                station_no = station_no or m.group(1)
                station_title = raw_name[m.end() :].strip(" .-")

        lat = _to_float(status.get("stationLatitude")) or 0.0
        lon = _to_float(status.get("stationLongitude")) or 0.0

        bikes_total = _to_int(status.get("parkingBikeTotCnt"))
        bikes_general = _to_int(status.get("parkingBikeTotCntGeneral"), bikes_total)
        bikes_sprout = _to_int(status.get("parkingBikeTotCntTeen"), 0)
        bikes_repair = _to_int(status.get("parkingBikeTotCntRepair"), 0)

        if bikes_total <= 0:
            bikes_total = _to_int(status.get("bikes_total"))
        if bikes_general <= 0:
            bikes_general = _to_int(status.get("bikes_general"), bikes_total)
        if bikes_sprout <= 0:
            bikes_sprout = _to_int(status.get("bikes_sprout"), 0)
        if bikes_repair <= 0:
            bikes_repair = _to_int(status.get("bikes_repair"), 0)

        return Station(
            station_id=sid,
            station_no=station_no,
            station_title=station_title or raw_name or sid,
            lat=float(lat),
            lon=float(lon),
            bikes_total=bikes_total,
            bikes_general=bikes_general,
            bikes_sprout=bikes_sprout,
            bikes_repair=bikes_repair,
        )

    def _compute_nearby(self) -> None:
        self._compute_center()

        self.nearby = []
        self.nearby_total_bikes = 0
        self.nearby_recommended_bikes = 0

        if self.center_lat is None or self.center_lon is None:
            return

        radius = max(1, int(self.radius_m or DEFAULT_RADIUS_M))
        min_bikes = max(0, int(self.min_bikes or 0))
        max_results = int(self.max_results or 0)

        candidates: list[dict[str, Any]] = []
        total = 0

        for s in self.stations_by_id.values():
            if not s.lat or not s.lon:
                continue
            dist = haversine_m(self.center_lat, self.center_lon, s.lat, s.lon)
            if dist > radius:
                continue
            if s.bikes_total < min_bikes:
                continue

            total += s.bikes_total
            candidates.append(
                {
                    "station_id": s.station_id,
                    "station_no": s.station_no,
                    "station_name": f"{s.station_no}. {s.station_title}".strip() if s.station_no else s.station_title,
                    "bikes_total": s.bikes_total,
                    "distance_m": round(dist, 1),
                }
            )

        candidates.sort(key=lambda x: (-int(x.get("bikes_total") or 0), float(x.get("distance_m") or 0.0)))

        self.nearby_total_bikes = total
        if max_results > 0:
            self.nearby = candidates[:max_results]
        else:
            self.nearby = candidates
        self.nearby_recommended_bikes = sum(int(x.get("bikes_total") or 0) for x in self.nearby)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            self.last_error = None
            self.validation_status = "ok"
            raw_cookie = self.entry.options.get(CONF_COOKIE) or self.entry.data.get(CONF_COOKIE) or ""
            self._api.set_cookie(raw_cookie)

            opts = self.entry.options or {}
            use_week = bool(opts.get(CONF_USE_HISTORY_WEEK, DEFAULT_USE_HISTORY_WEEK))
            use_month = bool(opts.get(CONF_USE_HISTORY_MONTH, DEFAULT_USE_HISTORY_MONTH))
            if not (use_week or use_month):
                use_month = True

            station_raw = opts.get(CONF_STATION_IDS, self.entry.data.get(CONF_STATION_IDS, []))
            self.station_ids = _parse_station_list(station_raw)

            self.location_entity_id = str(
                opts.get(CONF_LOCATION_ENTITY, self.entry.data.get(CONF_LOCATION_ENTITY, "")) or ""
            ).strip()
            try:
                self.radius_m = int(
                    opts.get(CONF_RADIUS_M, self.entry.data.get(CONF_RADIUS_M, DEFAULT_RADIUS_M))
                )
            except Exception:
                self.radius_m = DEFAULT_RADIUS_M
            try:
                self.max_results = int(
                    opts.get(CONF_MAX_RESULTS, self.entry.data.get(CONF_MAX_RESULTS, DEFAULT_MAX_RESULTS))
                )
            except Exception:
                self.max_results = DEFAULT_MAX_RESULTS
            try:
                self.min_bikes = int(
                    opts.get(CONF_MIN_BIKES, self.entry.data.get(CONF_MIN_BIKES, DEFAULT_MIN_BIKES))
                )
            except Exception:
                self.min_bikes = DEFAULT_MIN_BIKES


            rent_status: dict[str, Any] = {}
            user_status: dict[str, Any] = {}
            reconsent_status: dict[str, Any] = {}
            login_ok: bool | None = None
            username = str(self.entry.data.get(CONF_COOKIE_USERNAME) or "").strip()
            password = str(self.entry.data.get(CONF_COOKIE_PASSWORD) or "").strip()
            try:
                rent_status = await self._api.fetch_rent_status()
                login_ok = _status_login_ok(rent_status)
            except Exception as err:
                rent_status = {"error": str(err)}
                login_ok = None

            if login_ok is False and username and password:
                try:
                    new_cookie = await self._api.login(username, password)
                    self.hass.config_entries.async_update_entry(
                        self.entry,
                        data={**self.entry.data, CONF_COOKIE: new_cookie},
                    )
                    self._api.set_cookie(new_cookie)
                    rent_status = await self._api.fetch_rent_status()
                    login_ok = _status_login_ok(rent_status)
                except Exception as err:
                    _LOGGER.debug("Re-login failed: %s", err)

            if login_ok is False:
                self.validation_status = "login_page"
                self.last_error = "login_page"
                self._sync_last_request_meta()
                return {
                    "error": "로그인 페이지로 응답됨(쿠키 만료/권한/세션 제한 가능)",
                    "updated_at": datetime.now().isoformat(),
                    "periods": {},
                    "ticket_expiry": None,
                    "favorites": [],
                    "favorite_status": {},
                    "rent_status": rent_status,
                    "user_status": user_status,
                    "reconsent_status": reconsent_status,
                    "validation_status": self.validation_status,
                    "last_request": {
                        "url": self.last_request_url,
                        "http_status": self.last_http_status,
                        "error": self.last_error,
                    },
                }

            if login_ok is not False:
                try:
                    user_status = await self._api.fetch_user_status()
                except Exception as err:
                    user_status = {"error": str(err)}
                try:
                    reconsent_status = await self._api.fetch_reconsent_status()
                except Exception as err:
                    reconsent_status = {"error": str(err)}

            base_html = await self._api.fetch_use_history_html()
            period_html: dict[str, str] = {}
            if use_week:
                period_html["1w"] = await self._api.fetch_use_history_html(period="1w", base_html=base_html)
            if use_month:
                period_html["1m"] = await self._api.fetch_use_history_html(period="1m", base_html=base_html)

            if period_html and all(_looks_like_login(h) for h in period_html.values()):
                self.validation_status = "login_page"
                self.last_error = "login_page"
                self._sync_last_request_meta()
                return {
                    "error": "로그인 페이지로 응답됨(쿠키 만료/권한/세션 제한 가능)",
                    "updated_at": datetime.now().isoformat(),
                    "periods": {},
                    "ticket_expiry": None,
                    "favorites": [],
                    "favorite_status": {},
                    "rent_status": rent_status,
                    "user_status": user_status,
                    "reconsent_status": reconsent_status,
                    "validation_status": self.validation_status,
                    "last_request": {
                        "url": self.last_request_url,
                        "http_status": self.last_http_status,
                        "error": self.last_error,
                    },
                }

            updated_at = datetime.now().isoformat()
            periods: dict[str, Any] = {}
            if "1w" in period_html:
                periods["1w"] = {
                    **_parse_use_history(period_html["1w"]),
                    "updated_at": updated_at,
                }
            if "1m" in period_html:
                periods["1m"] = {
                    **_parse_use_history(period_html["1m"]),
                    "updated_at": updated_at,
                }

            for pdata in periods.values():
                hist = pdata.get("history") or []
                hist_id = None
                if isinstance(hist, list) and hist:
                    hist_id = (hist[0] or {}).get("history_id")
                if hist_id:
                    try:
                        pdata["move_route"] = await self._api.fetch_move_route(str(hist_id))
                    except Exception as err:
                        pdata["move_route"] = {"error": str(err)}


            left_html = await self._api.fetch_left_page_html()
            ticket_expiry = None if _looks_like_login(left_html) else _parse_ticket_expiry(left_html)
            ticket_expiry_iso = ticket_expiry.isoformat() if ticket_expiry else None
            for pdata in periods.values():
                pdata["ticket_expiry"] = ticket_expiry_iso

            fav_html = await self._api.fetch_favorites_html()
            favorites = [] if _looks_like_login(fav_html) else _extract_favorites_with_counts(fav_html)

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

            prev_stations = dict(self.stations_by_id)
            stations_by_id: dict[str, Station] = {}
            if self.station_ids:
                for raw in self.station_ids:
                    raw_id = str(raw).strip()
                    if not raw_id:
                        continue
                    station_id = raw_id.upper() if raw_id.upper().startswith("ST-") else None
                    station_no = raw_id if raw_id.isdigit() else None
                    try:
                        status = await self._api.fetch_station_status(station_id, station_no)
                    except Exception as err:
                        _LOGGER.debug("Station status fetch failed (%s): %s", raw_id, err)
                        status = {}
                    st = self._station_from_status(status, station_id, station_no, raw_id)
                    if st:
                        stations_by_id[st.station_id] = st
                        continue
                    fallback = _fallback_station(prev_stations, station_id, station_no, raw_id)
                    if fallback:
                        stations_by_id[fallback.station_id] = fallback

            if stations_by_id or not prev_stations:
                self.stations_by_id = stations_by_id
            else:
                self.stations_by_id = prev_stations
            self._compute_nearby()

            self._sync_last_request_meta()
            return {
                "error": None,
                "updated_at": updated_at,
                "periods": periods,
                "ticket_expiry": ticket_expiry_iso,
                "favorites": favorites,          # counts 포함
                "favorite_status": favorite_status,
                "rent_status": rent_status,
                "user_status": user_status,
                "reconsent_status": reconsent_status,
                "validation_status": self.validation_status,
                "last_request": {
                    "url": self.last_request_url,
                    "http_status": self.last_http_status,
                    "error": self.last_error,
                },
                "nearby_count": len(self.nearby),
                "station_count": len(self.stations_by_id),
            }

        except Exception as err:
            self.last_error = str(err)
            self.validation_status = "error"
            self._sync_last_request_meta()
            raise UpdateFailed(f"업데이트 실패: {err}") from err
