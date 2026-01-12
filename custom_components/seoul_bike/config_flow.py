# custom_components/seoul_bike/config_flow.py

from __future__ import annotations

import hashlib
import logging
import re

import aiohttp

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_MODE, MODE_API, MODE_COOKIE
from .modes.api.api import SeoulBikeApi, SeoulBikeApiAuthError, SeoulBikeApiError
from .modes.api.const import (
    CONF_API_KEY,
    CONF_STATION_IDS,
    CONF_LOCATION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
)
from .modes.cookie.const import CONF_COOKIE
from .modes.cookie.api import SeoulPublicBikeSiteApi

_LOGGER = logging.getLogger(__name__)
_STATION_NO_RE = re.compile(r"^\s*(\d+)\s*(?:[\.．\)\-]|번|\s)")
_LOGIN_FORM_RE = re.compile(
    r'<form[^>]+action=["\'][^"\']*(j_spring_security_check|login)[^"\']*["\']',
    re.IGNORECASE,
)
_PASSWORD_INPUT_RE = re.compile(r'<input[^>]+type=["\']password["\']', re.IGNORECASE)
_COOKIE_PREFIX_RE = re.compile(r"^\s*cookie\s*[:\s]", re.IGNORECASE)
_DATA_MARKER_RE = re.compile(
    r"(kcal_box|payment_box|moveRentalStation\(\s*'ST-[^']+'\s*,\s*'[^']+'\s*\))",
    re.IGNORECASE,
)
_LOGOUT_MARKER_RE = re.compile(r"(logout|/logout|logout\.do)", re.IGNORECASE)


class CookieValidationError(Exception):
    """Invalid cookie error."""


def _has_cookie_data_markers(html: str) -> bool:
    if not html:
        return False
    return bool(_DATA_MARKER_RE.search(html))


def _has_login_markers(html: str) -> bool:
    if not html:
        return False
    lower = html.lower()
    has_password = _PASSWORD_INPUT_RE.search(html)
    if "j_spring_security_check" in lower and has_password:
        return True
    if _LOGIN_FORM_RE.search(html) and has_password:
        return True
    return False


def _extract_cookie_line(raw: str) -> str | None:
    if not raw:
        return None
    v = raw.strip().strip('"').strip("'")
    if not v:
        return None
    if "\n" in v or "\r" in v:
        lines = [line.strip() for line in re.split(r"[\r\n]+", v) if line.strip()]
        for line in lines:
            if _COOKIE_PREFIX_RE.match(line):
                return line
        return None
    if _COOKIE_PREFIX_RE.match(v):
        return v
    return None


def _normalize_cookie_input(raw: str) -> str | None:
    line = _extract_cookie_line(raw)
    if not line:
        return None
    cookie_value = _COOKIE_PREFIX_RE.sub("", line, count=1).strip()
    if "=" not in cookie_value:
        return None
    return line




def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in items:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _parse_station_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace("\n", ",").replace("\r", ",").split(",")]
    parts = [p for p in parts if p]
    return _dedup_keep_order(parts)


def _api_unique_id(api_key: str) -> str:
    key = (api_key or "").strip()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"api_{digest}"




async def _validate_api_key(hass, api_key: str) -> None:
    session = async_get_clientsession(hass)
    api = SeoulBikeApi(session, api_key)
    await api.fetch_page(1, 1)


async def _validate_cookie(hass, cookie: str) -> None:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        api = SeoulPublicBikeSiteApi(session, cookie)
        _LOGGER.debug("Cookie validation start (len=%s)", len(cookie or ""))
        htmls: list[str | None] = []
        errors: list[Exception] = []

        for fetch in (
            api.fetch_use_history_html,
            api.fetch_left_page_html,
            api.fetch_favorites_html,
        ):
            try:
                htmls.append(await fetch())
            except Exception as err:  # noqa: BLE001
                errors.append(err)
                htmls.append(None)

        found_data = False
        found_login = False
        found_html = False
        found_logout = False

        for html in htmls:
            if not html:
                continue
            found_html = True
            if _has_cookie_data_markers(html):
                found_data = True
            if _has_login_markers(html):
                found_login = True
            if _LOGOUT_MARKER_RE.search(html):
                found_logout = True

        _LOGGER.debug(
            "Cookie validation markers: found_html=%s found_data=%s found_login=%s found_logout=%s errors=%s",
            found_html,
            found_data,
            found_login,
            found_logout,
            [type(e).__name__ for e in errors],
        )

        if found_data:
            return
        if found_login:
            raise CookieValidationError("invalid_cookie")
        if found_logout:
            return
        if found_html:
            return

        if errors:
            raise errors[0]

        raise CookieValidationError("invalid_cookie")


def _resolve_station_inputs(inputs: list[str], rows: list[dict]) -> tuple[list[dict], list[dict]]:
    num_map: dict[str, list[str]] = {}
    id_set = set()

    for r in rows:
        sid = str(r.get("stationId", "")).strip()
        if sid:
            id_set.add(sid)

        name = str(r.get("stationName", "")).strip()
        m = _STATION_NO_RE.match(name)
        if m and sid:
            num = m.group(1)
            num_map.setdefault(num, [])
            if sid not in num_map[num]:
                num_map[num].append(sid)

    resolved: list[dict] = []
    unresolved: list[dict] = []

    for raw in inputs:
        v = str(raw).strip()
        if not v:
            continue

        if v.upper().startswith("ST-"):
            if v in id_set:
                resolved.append({"input": v, "station_id": v, "method": "station_id"})
            else:
                unresolved.append({"input": v, "reason": "station_id_not_found"})
            continue

        if v.isdigit():
            candidates = num_map.get(v, [])
            if len(candidates) == 1:
                resolved.append({"input": v, "station_id": candidates[0], "method": "station_number"})
            elif len(candidates) > 1:
                unresolved.append({"input": v, "reason": "ambiguous", "candidates": candidates})
            else:
                unresolved.append({"input": v, "reason": "number_not_found"})
            continue

        unresolved.append({"input": v, "reason": "invalid_format"})

    return resolved, unresolved


async def _validate_station_inputs(hass, api_key: str, inputs: list[str]) -> list[dict]:
    if not inputs:
        return []

    session = async_get_clientsession(hass)
    api = SeoulBikeApi(session, api_key)
    rows = await api.fetch_all(page_size=1000, max_pages=10, retries=2)
    if not isinstance(rows, list):
        raise SeoulBikeApiError("invalid_station_rows")

    _, unresolved = _resolve_station_inputs(inputs, rows)
    return unresolved


def _entry_mode(entry: config_entries.ConfigEntry) -> str:
    mode = (entry.data.get(CONF_MODE) or "").strip().lower()
    if not mode:
        if CONF_API_KEY in (entry.data or {}):
            mode = MODE_API
        elif CONF_COOKIE in (entry.data or {}):
            mode = MODE_COOKIE
    return mode or MODE_API


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            mode = (user_input.get(CONF_MODE) or "").strip().lower()
            if mode == MODE_API:
                return await self.async_step_api()
            if mode == MODE_COOKIE:
                return await self.async_step_cookie()
            errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=MODE_API): vol.In(
                    {
                        MODE_API: "API 방식 (Open API Polling)",
                        MODE_COOKIE: "Cookie 방식 (Web Pulling)",
                    }
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_api(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            station_raw = (user_input.get(CONF_STATION_IDS) or "").strip()
            location_entity = (user_input.get(CONF_LOCATION_ENTITY) or "").strip()
            update_interval = int(user_input.get(CONF_UPDATE_INTERVAL) or DEFAULT_UPDATE_INTERVAL_SECONDS)
            station_ids = _parse_station_list(station_raw)

            if api_key:
                await self.async_set_unique_id(_api_unique_id(api_key))
                self._abort_if_unique_id_configured()

            try:
                if station_ids:
                    unresolved = await _validate_station_inputs(self.hass, api_key, station_ids)
                    if unresolved:
                        errors["base"] = "station_not_found"
                else:
                    await _validate_api_key(self.hass, api_key)
            except SeoulBikeApiAuthError:
                errors["base"] = "invalid_auth"
            except SeoulBikeApiError as err:
                _LOGGER.warning("API key validation failed (api): %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during config validation: %s", err)
                errors["base"] = "unknown"

            if not errors:
                data = {
                    CONF_MODE: MODE_API,
                    CONF_API_KEY: api_key,
                    CONF_STATION_IDS: station_ids,
                    CONF_LOCATION_ENTITY: location_entity,
                    CONF_UPDATE_INTERVAL: update_interval,
                }
                return self.async_create_entry(title="따릉이 (API)", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_LOCATION_ENTITY, default=""): str,
                vol.Optional(CONF_UPDATE_INTERVAL, default=int(DEFAULT_UPDATE_INTERVAL_SECONDS)): int,
                vol.Optional(CONF_STATION_IDS, default=""): str,
            }
        )

        return self.async_show_form(step_id="api", data_schema=schema, errors=errors)

    async def async_step_cookie(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            cookie = (user_input.get(CONF_COOKIE) or "").strip()
            cookie_line = _normalize_cookie_input(cookie)
            if not cookie:
                errors["base"] = "cookie_required"
            elif not cookie_line:
                errors["base"] = "cookie_invalid_format"
            else:
                try:
                    await _validate_cookie(self.hass, cookie_line)
                except CookieValidationError:
                    errors["base"] = "invalid_cookie"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Cookie validation failed: %s", err)
                    errors["base"] = "cannot_connect"

                if not errors:
                    return self.async_create_entry(
                        title="따릉이 (Cookie)",
                        data={
                            CONF_MODE: MODE_COOKIE,
                            CONF_COOKIE: cookie_line,
                        },
                    )

        schema = vol.Schema({vol.Required(CONF_COOKIE): str})
        return self.async_show_form(step_id="cookie", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._mode = _entry_mode(config_entry)

    async def async_step_init(self, user_input=None):
        if self._mode == MODE_COOKIE:
            return await self.async_step_cookie()
        return await self.async_step_api()

    async def async_step_api(self, user_input=None):
        errors: dict[str, str] = {}
        opts = self._config_entry.options or {}
        data = self._config_entry.data or {}

        if user_input is not None:
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            station_raw = (user_input.get(CONF_STATION_IDS) or "").strip()
            location_entity = (user_input.get(CONF_LOCATION_ENTITY) or "").strip()
            update_interval = int(user_input.get(CONF_UPDATE_INTERVAL) or DEFAULT_UPDATE_INTERVAL_SECONDS)
            station_ids = _parse_station_list(station_raw)

            try:
                if station_ids:
                    unresolved = await _validate_station_inputs(self.hass, api_key, station_ids)
                    if unresolved:
                        errors["base"] = "station_not_found"
                else:
                    await _validate_api_key(self.hass, api_key)
            except SeoulBikeApiAuthError:
                errors["base"] = "invalid_auth"
            except SeoulBikeApiError as err:
                _LOGGER.warning("API key validation failed (api/options): %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during options validation: %s", err)
                errors["base"] = "unknown"

            if not errors:
                new_data = dict(data)
                new_data[CONF_MODE] = MODE_API
                new_data[CONF_API_KEY] = api_key
                new_data.pop(CONF_COOKIE, None)

                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=new_data,
                    title="따릉이 (API)",
                )

                return self.async_create_entry(
                    title="",
                    data={
                        CONF_API_KEY: api_key,
                        CONF_STATION_IDS: station_ids,
                        CONF_LOCATION_ENTITY: location_entity,
                        CONF_UPDATE_INTERVAL: update_interval,
                    },
                )

        station_default = (
            opts.get(CONF_STATION_IDS)
            if CONF_STATION_IDS in opts
            else data.get(CONF_STATION_IDS, [])
        )
        station_default = station_default or []

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY, default=opts.get(CONF_API_KEY, data.get(CONF_API_KEY, ""))): str,
                vol.Required(
                    CONF_LOCATION_ENTITY,
                    default=str(opts.get(CONF_LOCATION_ENTITY, data.get(CONF_LOCATION_ENTITY, "")) or ""),
                ): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=int(opts.get(CONF_UPDATE_INTERVAL, data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS))),
                ): int,
                vol.Optional(
                    CONF_STATION_IDS,
                    default=",".join(station_default),
                ): str,
            }
        )

        return self.async_show_form(step_id="api", data_schema=schema, errors=errors)

    async def async_step_cookie(self, user_input=None):
        errors: dict[str, str] = {}
        opts = self._config_entry.options or {}
        data = self._config_entry.data or {}

        if user_input is not None:
            cookie = (user_input.get(CONF_COOKIE) or "").strip()
            cookie_line = _normalize_cookie_input(cookie)
            if not cookie:
                errors["base"] = "cookie_required"
            elif not cookie_line:
                errors["base"] = "cookie_invalid_format"
            else:
                try:
                    await _validate_cookie(self.hass, cookie_line)
                except CookieValidationError:
                    errors["base"] = "invalid_cookie"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Cookie validation failed (options): %s", err)
                    errors["base"] = "cannot_connect"

                if not errors:
                    new_data = dict(data)
                    new_data[CONF_MODE] = MODE_COOKIE
                    new_data[CONF_COOKIE] = cookie_line
                    new_data.pop(CONF_API_KEY, None)
                    new_data.pop(CONF_STATION_IDS, None)
                    new_data.pop(CONF_LOCATION_ENTITY, None)
                    new_data.pop(CONF_UPDATE_INTERVAL, None)

                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data=new_data,
                        title="따릉이 (Cookie)",
                    )

                    return self.async_create_entry(title="", data={CONF_COOKIE: cookie_line})

        schema = vol.Schema(
            {
                vol.Required(CONF_COOKIE, default=opts.get(CONF_COOKIE, data.get(CONF_COOKIE, ""))): str,
            }
        )
        return self.async_show_form(step_id="cookie", data_schema=schema, errors=errors)
