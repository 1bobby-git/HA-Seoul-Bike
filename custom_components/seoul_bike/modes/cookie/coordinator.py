# custom_components/seoul_bike/modes/cookie/coordinator.py

from __future__ import annotations

import logging
import re
from datetime import timedelta, datetime
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
    CONF_COOKIE_UPDATE_INTERVAL,
    CONF_USE_HISTORY_WEEK,
    CONF_USE_HISTORY_MONTH,
    DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS,
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


            rent_status: dict[str, Any] = {}
            user_status: dict[str, Any] = {}
            reconsent_status: dict[str, Any] = {}
            login_ok: bool | None = None
            try:
                rent_status = await self._api.fetch_rent_status()
                login_ok = _status_login_ok(rent_status)
            except Exception as err:
                rent_status = {"error": str(err)}
                login_ok = None

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
            }

        except Exception as err:
            self.last_error = str(err)
            self.validation_status = "error"
            self._sync_last_request_meta()
            raise UpdateFailed(f"업데이트 실패: {err}") from err
