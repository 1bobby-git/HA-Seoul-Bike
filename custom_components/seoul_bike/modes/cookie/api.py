# custom_components/seoul_bike/modes/cookie/api.py

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import aiohttp

_LOGGER = logging.getLogger(__name__)


class _AnchorFinder(HTMLParser):
    def __init__(self, target_id: str) -> None:
        super().__init__()
        self._target_id = target_id
        self.attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = {k: (v or "") for k, v in attrs}
        if attr_map.get("id") == self._target_id:
            self.attrs = attr_map


def _normalize_cookie(raw: str) -> str:
    v = (raw or "").strip().strip('"').strip("'")
    if v:
        if "\n" in v or "\r" in v:
            parts = [p.strip() for p in v.replace("\r", "\n").split("\n") if p.strip()]
            cookie_line = None
            for line in parts:
                if line.lower().startswith("cookie:"):
                    cookie_line = line
                    break
            if cookie_line is None:
                for line in parts:
                    if line.lower().startswith("cookie "):
                        cookie_line = line
                        break
            v = cookie_line or " ".join(parts)
        v = " ".join(v.replace("\r", " ").replace("\n", " ").split())
    low = v.lower()
    if low.startswith("cookie "):
        v = v[7:].strip()
    low = v.lower()
    if low.startswith("cookie:"):
        v = v[7:].strip()
    return v


def _strip_tags(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


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
        self.last_meta: dict[str, Any] | None = None
        self.last_error: str | None = None

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

    def _headers_json(self, referer_path: str | None = None) -> dict[str, str]:
        h = self._headers(referer_path)
        h["Accept"] = "application/json, text/plain, */*"
        return h

    def _cookie_header_from_session(self) -> str:
        try:
            cookies = self._session.cookie_jar.filter_cookies(self.BASE)
        except Exception:
            cookies = {}
        parts: list[str] = []
        for name, morsel in cookies.items():
            value = getattr(morsel, "value", None)
            if value is None:
                continue
            parts.append(f"{name}={value}")
        return "; ".join(parts)

    def _record_meta(self, method: str, url: str, status: int | None, error: str | None = None) -> None:
        self.last_meta = {
            "method": method,
            "url": url,
            "status": status,
        }
        if error:
            self.last_meta["error"] = error
        self.last_error = error

    async def _get_text(self, path: str, params: dict | None = None, referer_path: str | None = None) -> str:
        url = f"{self.BASE}{path}"
        try:
            async with self._session.get(url, params=params, headers=self._headers(referer_path), allow_redirects=True) as resp:
                text = await resp.text(errors="ignore")
                _LOGGER.debug("Cookie fetch %s status=%s len=%s", path, resp.status, len(text))
                err = f"http_{resp.status}" if resp.status >= 400 else None
                self._record_meta("GET", str(resp.url), resp.status, err)
                if resp.status >= 400:
                    resp.raise_for_status()
                return text
        except Exception as err:
            if not self.last_meta or self.last_meta.get("url") != url or self.last_meta.get("status") is None:
                self._record_meta("GET", url, None, str(err))
            raise

    async def _get_json(self, path: str, params: dict | None = None, referer_path: str | None = None) -> dict[str, Any]:
        url = f"{self.BASE}{path}"
        try:
            async with self._session.get(url, params=params, headers=self._headers_json(referer_path), allow_redirects=True) as resp:
                text = await resp.text(errors="ignore")
                err = f"http_{resp.status}" if resp.status >= 400 else None
                try:
                    data = json.loads(text)
                except Exception:
                    data = None
                    err = err or "non_json_response"
                self._record_meta("GET", str(resp.url), resp.status, err)
                if resp.status >= 400:
                    resp.raise_for_status()
                if not isinstance(data, dict):
                    raise ValueError("non_json_response")
                return data
        except Exception as err:
            if not self.last_meta or self.last_meta.get("url") != url or self.last_meta.get("status") is None:
                self._record_meta("GET", url, None, str(err))
            raise

    async def _get_text_url(self, url: str, referer_path: str | None = None) -> str:
        try:
            async with self._session.get(url, headers=self._headers(referer_path), allow_redirects=True) as resp:
                text = await resp.text(errors="ignore")
                _LOGGER.debug("Cookie fetch %s status=%s len=%s", url, resp.status, len(text))
                err = f"http_{resp.status}" if resp.status >= 400 else None
                self._record_meta("GET", str(resp.url), resp.status, err)
                if resp.status >= 400:
                    resp.raise_for_status()
                return text
        except Exception as err:
            if not self.last_meta or self.last_meta.get("url") != url or self.last_meta.get("status") is None:
                self._record_meta("GET", url, None, str(err))
            raise

    async def _post_text(self, path: str, data: dict[str, str], referer_path: str | None = None) -> str:
        url = f"{self.BASE}{path}" if path.startswith("/") else self._absolute_url(path)
        try:
            async with self._session.post(url, data=data, headers=self._headers(referer_path), allow_redirects=True) as resp:
                text = await resp.text(errors="ignore")
                _LOGGER.debug("Cookie post %s status=%s len=%s", url, resp.status, len(text))
                err = f"http_{resp.status}" if resp.status >= 400 else None
                self._record_meta("POST", str(resp.url), resp.status, err)
                if resp.status >= 400:
                    resp.raise_for_status()
                return text
        except Exception as err:
            if not self.last_meta or self.last_meta.get("url") != url or self.last_meta.get("status") is None:
                self._record_meta("POST", url, None, str(err))
            raise

    async def _post_json(
        self,
        path: str,
        data: dict[str, str] | None = None,
        referer_path: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.BASE}{path}" if path.startswith("/") else self._absolute_url(path)
        try:
            async with self._session.post(
                url,
                data=data or {},
                headers=self._headers_json(referer_path),
                allow_redirects=True,
            ) as resp:
                text = await resp.text(errors="ignore")
                err = f"http_{resp.status}" if resp.status >= 400 else None
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = None
                    err = err or "non_json_response"
                self._record_meta("POST", str(resp.url), resp.status, err)
                if resp.status >= 400:
                    resp.raise_for_status()
                if not isinstance(payload, dict):
                    raise ValueError("non_json_response")
                return payload
        except Exception as err:
            if not self.last_meta or self.last_meta.get("url") != url or self.last_meta.get("status") is None:
                self._record_meta("POST", url, None, str(err))
            raise

    def _extract_login_form(self, html: str) -> tuple[str, dict[str, str], str | None, str | None]:
        action = ""
        form_html = ""
        for m in re.finditer(r"<form[^>]*>(.*?)</form>", html or "", flags=re.DOTALL | re.IGNORECASE):
            form_html = m.group(0)
            action_m = re.search(r'action=["\']([^"\']+)["\']', form_html, flags=re.IGNORECASE)
            if not action_m:
                continue
            cand = action_m.group(1).strip()
            if "j_spring_security_check" in cand or "login" in cand:
                action = cand
                break
            if not action:
                action = cand
        if not action:
            action = "/j_spring_security_check"

        inputs: dict[str, str] = {}
        user_field: str | None = None
        pass_field: str | None = None

        for im in re.finditer(r"<input[^>]*>", form_html, flags=re.IGNORECASE):
            tag = im.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
            if not name_m:
                continue
            name = name_m.group(1).strip()
            type_m = re.search(r'type=["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
            itype = (type_m.group(1).strip().lower() if type_m else "text")
            value_m = re.search(r'value=["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
            value = value_m.group(1) if value_m else ""
            inputs[name] = value

            lname = name.lower()
            if itype == "password" and pass_field is None:
                pass_field = name
            if user_field is None and itype in ("text", "email"):
                if any(k in lname for k in ("user", "id", "login")):
                    user_field = name
        if user_field is None:
            for name in inputs:
                if any(k in name.lower() for k in ("user", "id", "login")):
                    user_field = name
                    break
        return action, inputs, user_field, pass_field

    async def login(self, username: str, password: str) -> str:
        login_page = await self._get_text("/login.do", referer_path="/login.do")
        action, inputs, user_field, pass_field = self._extract_login_form(login_page)
        if not user_field:
            user_field = "j_username"
        if not pass_field:
            pass_field = "j_password"
        inputs[user_field] = username
        inputs[pass_field] = password
        await self._post_text(action, inputs, referer_path="/login.do")

        status = await self.fetch_rent_status()
        login = str(status.get("loginYn") or "").strip().upper()
        if login != "Y":
            raise ValueError("login_failed")

        cookie_header = self._cookie_header_from_session()
        if not cookie_header:
            raise ValueError("cookie_not_found")
        self._cookie = cookie_header
        return cookie_header

    def _absolute_url(self, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("/"):
            return f"{self.BASE}{href}"
        return f"{self.BASE}/{href.lstrip('./')}"

    def _extract_period_href(self, html: str, button_id: str) -> str | None:
        if not html:
            return None
        parser = _AnchorFinder(button_id)
        parser.feed(html)
        attrs = parser.attrs or {}
        href = attrs.get("href") or attrs.get("data-href") or attrs.get("data-url")
        if href:
            href = href.strip()
            if href and href != "#" and not href.lower().startswith("javascript"):
                return href

        onclick = attrs.get("onclick", "")
        if onclick:
            m = re.search(r"(?:location\.href|window\.location|location)\s*=\s*['\"]([^'\"]+)['\"]", onclick)
            if m:
                return m.group(1).strip()
            m = re.search(r"(/app/mybike/getMemberUseHistory\.do[^'\"]*)", onclick, re.IGNORECASE)
            if m:
                return m.group(1).strip()

        return None

    def _find_period_attrs(self, html: str, button_id: str) -> dict[str, str]:
        if not html:
            return {}
        parser = _AnchorFinder(button_id)
        parser.feed(html)
        return parser.attrs or {}

    def _extract_form(self, html: str) -> tuple[str, dict[str, str], str] | None:
        if not html:
            return None
        m = re.search(
            r"<form[^>]*\bid=['\"]searchFrm['\"][^>]*>(.*?)</form>",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not m:
            m = re.search(r"<form[^>]*>(.*?)</form>", html, flags=re.DOTALL | re.IGNORECASE)
            if not m:
                return None
        form_html = m.group(0)
        action_m = re.search(r'action=["\']([^"\']+)["\']', form_html, flags=re.IGNORECASE)
        action = action_m.group(1).strip() if action_m else "/app/mybike/getMemberUseHistory.do"
        method_m = re.search(r'method=["\']([^"\']+)["\']', form_html, flags=re.IGNORECASE)
        method = (method_m.group(1).strip() if method_m else "post").lower()

        inputs: dict[str, str] = {}
        for im in re.finditer(r"<input[^>]*>", form_html, flags=re.IGNORECASE):
            tag = im.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
            if not name_m:
                continue
            name = name_m.group(1).strip()
            value_m = re.search(r'value=["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
            value = value_m.group(1) if value_m else ""
            inputs[name] = value

        return action, inputs, method

    def _extract_action_urls(self, html: str) -> list[str]:
        if not html:
            return []
        urls: list[str] = []
        for m in re.finditer(r"/app/mybike/getMemberUseHistory[^\"'\\s<>]*", html, flags=re.IGNORECASE):
            url = (m.group(0) or "").strip()
            if url and url not in urls:
                urls.append(url)
        return urls

    def _looks_like_use_history(self, html: str) -> bool:
        if not html:
            return False
        if re.search(r"(payment_box|paymentBox|kcal_box|kcalBox)", html, re.IGNORECASE):
            return True
        return bool(re.search(r"(getMemberUseHistory|searchStartDate|searchEndDate)", html, re.IGNORECASE))

    def _extract_days_from_onclick(self, onclick: str) -> int | None:
        if not onclick:
            return None
        lower = onclick.lower()
        if "week" in lower or "1w" in lower:
            return 7
        if "onem" in lower or "month" in lower or "1m" in lower:
            return 30
        if re.search(r"['\"]w['\"]", lower):
            return 7
        if re.search(r"['\"]m['\"]", lower):
            return 30
        m = re.search(r"(\d+)", onclick)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    def _apply_period_to_inputs(self, inputs: dict[str, str], days: int) -> dict[str, str]:
        today = datetime.now().date()
        start = today - timedelta(days=days)
        start_str = start.strftime("%Y-%m-%d")
        end_str = today.strftime("%Y-%m-%d")

        date_like: list[str] = []
        date_value_re = re.compile(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}")

        for name in list(inputs.keys()):
            lname = name.lower()
            if date_value_re.search(inputs.get(name, "")):
                date_like.append(name)
            if "start" in lname or "from" in lname or "sdate" in lname:
                inputs[name] = start_str
            elif "end" in lname or "to" in lname or "edate" in lname:
                inputs[name] = end_str
            elif "day" in lname or "period" in lname or "term" in lname:
                inputs[name] = str(days)

        if date_like:
            date_like = sorted(date_like)
            if len(date_like) >= 1:
                inputs[date_like[0]] = start_str
            if len(date_like) >= 2:
                inputs[date_like[1]] = end_str
        return inputs

    async def fetch_use_history_html(self, period: str | None = None, base_html: str | None = None) -> str:
        path = "/app/mybike/getMemberUseHistory.do"
        html = base_html or await self._get_text(path, referer_path=path)
        if not period:
            return html

        button_id = "oneMBtn" if period == "1m" else "weekBtn" if period == "1w" else ""
        if not button_id:
            return html

        href = self._extract_period_href(html, button_id)
        if not href:
            attrs = self._find_period_attrs(html, button_id)
            action = attrs.get("onclick") or attrs.get("href") or ""
            days = self._extract_days_from_onclick(action)
            if not days:
                days = 7 if button_id == "weekBtn" else 30 if button_id == "oneMBtn" else None
            form = self._extract_form(html)
            if days and form:
                action, inputs, method = form
                inputs = self._apply_period_to_inputs(inputs, days)
                try:
                    if method == "get":
                        qs = urlencode(inputs)
                        url = self._absolute_url(action)
                        url = f"{url}?{qs}" if qs else url
                        action_html = await self._get_text_url(url, referer_path=path)
                    else:
                        action_html = await self._post_text(action, inputs, referer_path=path)
                    if self._looks_like_use_history(action_html):
                        return action_html
                    for alt in self._extract_action_urls(html):
                        if alt == action:
                            continue
                        try:
                            alt_html = await self._post_text(alt, inputs, referer_path=path)
                            if self._looks_like_use_history(alt_html):
                                return alt_html
                        except Exception:
                            try:
                                qs = urlencode(inputs)
                                url = self._absolute_url(alt)
                                url = f"{url}?{qs}" if qs else url
                                alt_html = await self._get_text_url(url, referer_path=path)
                                if self._looks_like_use_history(alt_html):
                                    return alt_html
                            except Exception:
                                continue
                    return await self._get_text(path, referer_path=path)
                except Exception:
                    return html
            return html

        action_html = await self._get_text_url(self._absolute_url(href), referer_path=path)
        if self._looks_like_use_history(action_html):
            return action_html
        return await self._get_text(path, referer_path=path)

    async def fetch_rent_status(self) -> dict[str, Any]:
        last_exc: Exception | None = None
        for path in ("/app/rentCheck/isChkRentStatus.do", "/app/rent/isChkRentStatus.do"):
            try:
                return await self._get_json(path, referer_path=path)
            except Exception as err:
                last_exc = err
        if last_exc:
            raise last_exc
        return {}

    async def fetch_user_status(self) -> dict[str, Any]:
        return await self._get_json("/app/rent/chkUserSataus.do", referer_path="/app/rent/chkUserSataus.do")

    async def fetch_reconsent_status(self) -> dict[str, Any]:
        return await self._get_json("/checkReconsentAjax.do", referer_path="/")

    async def fetch_move_route(self, rent_hist_seq: str | None) -> dict[str, Any]:
        if not rent_hist_seq:
            return {}
        return await self._post_json(
            "/app/mybike/getHistoryMoveRoute.do",
            data={"rentHistSeq": str(rent_hist_seq)},
            referer_path="/app/mybike/getMemberUseHistory.do",
        )

    async def fetch_coupon_validation(self, coupon_no: str | None) -> dict[str, Any]:
        if not coupon_no:
            return {}
        return await self._post_json(
            "/app/mybike/coupon/validChkVoucherAjax.do",
            data={"couponNo": str(coupon_no)},
            referer_path="/app/mybike/coupon/validChkVoucher.do",
        )

    async def fetch_booking_cancel(self) -> dict[str, Any]:
        return await self._post_json(
            "/app/rent/exeBookingCancelProc.do",
            data={},
            referer_path="/app/rent/",
        )

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

    def _extract_station_status_html(self, html: str) -> dict[str, Any]:
        if not html:
            return {}

        def _extract_value(key: str) -> str | None:
            pattern = rf"{re.escape(key)}\\s*[:=]\\s*['\\\"]?([^'\\\"\\s,<>]+)"
            m = re.search(pattern, html, flags=re.IGNORECASE)
            if m:
                return m.group(1)
            pattern = rf"['\\\"]{re.escape(key)}['\\\"]\\s*:\\s*['\\\"]([^'\\\"]+)"
            m = re.search(pattern, html, flags=re.IGNORECASE)
            if m:
                return m.group(1)
            pattern = rf"['\\\"]{re.escape(key)}['\\\"]\\s*:\\s*(\\d+)"
            m = re.search(pattern, html, flags=re.IGNORECASE)
            if m:
                return m.group(1)
            return None

        out: dict[str, Any] = {}
        for key in (
            "stationId",
            "stationNo",
            "stationName",
            "stationLatitude",
            "stationLongitude",
            "parkingBikeTotCnt",
            "parkingBikeTotCntGeneral",
            "parkingBikeTotCntTeen",
            "parkingBikeTotCntRepair",
        ):
            v = _extract_value(key)
            if v is not None:
                out[key] = v

        if "stationId" not in out:
            m = re.search(r"(ST-\\d+)", html, re.IGNORECASE)
            if m:
                out["stationId"] = m.group(1).upper()

        if "stationName" not in out:
            m = re.search(r"<h2[^>]*>(.*?)</h2>", html, flags=re.IGNORECASE | re.DOTALL)
            if m:
                out["stationName"] = _strip_tags(m.group(1))

        if "parkingBikeTotCntGeneral" not in out or "parkingBikeTotCntTeen" not in out:
            m = re.search(r"<p>\\s*(\\d+)\\s*/\\s*(\\d+)\\s*</p>", html, flags=re.IGNORECASE)
            if m:
                out.setdefault("parkingBikeTotCntGeneral", m.group(1))
                out.setdefault("parkingBikeTotCntTeen", m.group(2))

        if "parkingBikeTotCnt" not in out:
            try:
                total = int(out.get("parkingBikeTotCntGeneral") or 0) + int(out.get("parkingBikeTotCntTeen") or 0)
                if total > 0:
                    out["parkingBikeTotCnt"] = str(total)
            except Exception:
                pass

        return out

    async def fetch_station_status(self, station_id: str | None, station_no: str | None) -> dict[str, Any]:
        params = None
        if station_id and station_no:
            params = {"stationId": station_id, "stationNo": station_no}
        elif station_id:
            params = {"stationId": station_id}
        elif station_no:
            params = {"stationNo": station_no}

        try:
            data = await self._get_json(
                "/app/station/moveStationRealtimeStatus.do",
                params=params,
                referer_path="/app/mybike/favoriteStation.do",
            )
            if data:
                return data
        except Exception:
            data = {}

        html = await self.fetch_station_realtime_html(station_id, station_no)
        parsed = self._extract_station_status_html(html)
        return parsed or data
