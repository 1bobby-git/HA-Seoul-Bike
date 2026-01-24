# custom_components/seoul_bike/api.py

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from .const import (
    BIKESEOUL_BASE_URL,
    API_PATH_LOGIN,
    API_PATH_RENT_STATUS,
    API_PATH_RENT_STATUS_ALT,
    API_PATH_USER_STATUS,
    API_PATH_RECONSENT,
    API_PATH_USE_HISTORY,
    API_PATH_MOVE_ROUTE,
    API_PATH_VOUCHER_INFO,
    API_PATH_LEFT_PAGE,
    API_PATH_FAVORITES,
    API_PATH_STATION_REALTIME,
    API_PATH_STATION_REALTIME_ALL,
)

_LOGGER = logging.getLogger(__name__)


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
    BASE = BIKESEOUL_BASE_URL

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
        login_page = await self._get_text(API_PATH_LOGIN, referer_path=API_PATH_LOGIN)
        action, inputs, user_field, pass_field = self._extract_login_form(login_page)
        if not user_field:
            user_field = "j_username"
        if not pass_field:
            pass_field = "j_password"
        inputs[user_field] = username
        inputs[pass_field] = password
        await self._post_text(action, inputs, referer_path=API_PATH_LOGIN)

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

    async def fetch_use_history_html(self) -> str:
        return await self._get_text(API_PATH_USE_HISTORY, referer_path=API_PATH_USE_HISTORY)

    async def fetch_rent_status(self) -> dict[str, Any]:
        last_exc: Exception | None = None
        for path in (API_PATH_RENT_STATUS, API_PATH_RENT_STATUS_ALT):
            try:
                return await self._get_json(path, referer_path=path)
            except Exception as err:
                last_exc = err
        if last_exc:
            raise last_exc
        return {}

    async def fetch_user_status(self) -> dict[str, Any]:
        return await self._get_json(API_PATH_USER_STATUS, referer_path=API_PATH_USER_STATUS)

    async def fetch_reconsent_status(self) -> dict[str, Any]:
        return await self._get_json(API_PATH_RECONSENT, referer_path="/")

    async def fetch_move_route(self, rent_hist_seq: str | None) -> dict[str, Any]:
        if not rent_hist_seq:
            return {}
        return await self._post_json(
            API_PATH_MOVE_ROUTE,
            data={"rentHistSeq": str(rent_hist_seq)},
            referer_path=API_PATH_USE_HISTORY,
        )

    async def fetch_voucher_info(self) -> dict[str, Any]:
        return await self._post_json(
            API_PATH_VOUCHER_INFO,
            data={},
            referer_path="/app/mybike/coupon/validChkVoucher.do",
        )

    async def fetch_left_page_html(self) -> str:
        return await self._get_text(API_PATH_LEFT_PAGE, referer_path=API_PATH_LEFT_PAGE)

    async def fetch_favorites_html(self) -> str:
        return await self._get_text(API_PATH_FAVORITES, referer_path=API_PATH_FAVORITES)

    async def fetch_station_realtime_html(self, station_id: str | None, station_no: str | None) -> str:
        """
        즐겨찾기 대여소 수량 파싱용.
        사이트 구현이 케이스별로 달라서, 가능한 범위에서 가장 보수적으로 시도한다.
        """
        tries: list[tuple[dict | None, str | None]] = []

        if station_id:
            tries.append(({"stationId": station_id}, API_PATH_FAVORITES))
        if station_no:
            tries.append(({"stationNo": station_no}, API_PATH_FAVORITES))
        if station_id and station_no:
            tries.append(({"stationId": station_id, "stationNo": station_no}, API_PATH_FAVORITES))

        # 마지막 fallback: 파라미터 없이
        tries.append((None, API_PATH_FAVORITES))

        last_exc: Exception | None = None
        for params, ref in tries:
            try:
                return await self._get_text(API_PATH_STATION_REALTIME, params=params, referer_path=ref)
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
                API_PATH_STATION_REALTIME,
                params=params,
                referer_path=API_PATH_FAVORITES,
            )
            if data:
                return data
        except Exception:
            data = {}

        html = await self.fetch_station_realtime_html(station_id, station_no)
        parsed = self._extract_station_status_html(html)
        return parsed or data

    async def fetch_station_realtime_all(self) -> list[dict[str, Any]]:
        data = await self._post_json(
            API_PATH_STATION_REALTIME_ALL,
            data={"stationGrpSeq": "ALL"},
            referer_path=API_PATH_STATION_REALTIME_ALL,
        )
        if isinstance(data, dict):
            items = data.get("realtimeList") or data.get("list") or data.get("data")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []
