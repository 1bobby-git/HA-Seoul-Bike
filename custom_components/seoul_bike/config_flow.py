# custom_components/seoul_bike/config_flow.py

from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN
from .modes.cookie.api import SeoulPublicBikeSiteApi
from .modes.cookie.const import (
    CONF_COOKIE,
    CONF_COOKIE_PASSWORD,
    CONF_COOKIE_USERNAME,
    CONF_COOKIE_UPDATE_INTERVAL,
    CONF_LOCATION_ENTITY,
    CONF_MAX_RESULTS,
    CONF_MIN_BIKES,
    CONF_RADIUS_M,
    CONF_STATION_IDS,
    CONF_USE_HISTORY_MONTH,
    CONF_USE_HISTORY_WEEK,
    DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_MIN_BIKES,
    DEFAULT_RADIUS_M,
    DEFAULT_USE_HISTORY_MONTH,
    DEFAULT_USE_HISTORY_WEEK,
)

_LOGGER = logging.getLogger(__name__)


class CookieValidationError(Exception):
    """Invalid login error."""


def _login_unique_id(username: str) -> str:
    key = (username or "").strip()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"login_{digest}"


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


async def _login_and_get_cookie(hass, username: str, password: str) -> str:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
        api = SeoulPublicBikeSiteApi(session, "")
        return await api.login(username, password)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            username = (user_input.get(CONF_COOKIE_USERNAME) or "").strip()
            password = (user_input.get(CONF_COOKIE_PASSWORD) or "").strip()
            station_raw = (user_input.get(CONF_STATION_IDS) or "").strip()
            location_entity = (user_input.get(CONF_LOCATION_ENTITY) or "").strip()
            use_week = bool(user_input.get(CONF_USE_HISTORY_WEEK, DEFAULT_USE_HISTORY_WEEK))
            use_month = bool(user_input.get(CONF_USE_HISTORY_MONTH, DEFAULT_USE_HISTORY_MONTH))
            try:
                update_interval = int(
                    user_input.get(CONF_COOKIE_UPDATE_INTERVAL, DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS)
                )
            except Exception:
                update_interval = DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS
            try:
                radius_m = int(user_input.get(CONF_RADIUS_M, DEFAULT_RADIUS_M))
            except Exception:
                radius_m = DEFAULT_RADIUS_M
            try:
                max_results = int(user_input.get(CONF_MAX_RESULTS, DEFAULT_MAX_RESULTS))
            except Exception:
                max_results = DEFAULT_MAX_RESULTS
            try:
                min_bikes = int(user_input.get(CONF_MIN_BIKES, DEFAULT_MIN_BIKES))
            except Exception:
                min_bikes = DEFAULT_MIN_BIKES

            if not username or not password:
                errors["base"] = "login_required"
            elif not (use_week or use_month):
                errors["base"] = "period_required"
            else:
                try:
                    cookie_line = await _login_and_get_cookie(self.hass, username, password)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Login validation failed: %s", err)
                    errors["base"] = "invalid_login"
                else:
                    await self.async_set_unique_id(_login_unique_id(username))
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title="따릉이 (로그인)",
                        data={
                            CONF_COOKIE: cookie_line,
                            CONF_COOKIE_USERNAME: username,
                            CONF_COOKIE_PASSWORD: password,
                            CONF_USE_HISTORY_WEEK: use_week,
                            CONF_USE_HISTORY_MONTH: use_month,
                            CONF_COOKIE_UPDATE_INTERVAL: update_interval,
                            CONF_STATION_IDS: _parse_station_list(station_raw),
                            CONF_LOCATION_ENTITY: location_entity,
                            CONF_RADIUS_M: radius_m,
                            CONF_MAX_RESULTS: max_results,
                            CONF_MIN_BIKES: min_bikes,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_COOKIE_USERNAME,
                    default=str(opts.get(CONF_COOKIE_USERNAME, data.get(CONF_COOKIE_USERNAME, "")) or ""),
                ): str,
                vol.Required(
                    CONF_COOKIE_PASSWORD,
                    default=str(opts.get(CONF_COOKIE_PASSWORD, data.get(CONF_COOKIE_PASSWORD, "")) or ""),
                ): str,
                vol.Optional(CONF_USE_HISTORY_WEEK, default=DEFAULT_USE_HISTORY_WEEK): bool,
                vol.Optional(CONF_USE_HISTORY_MONTH, default=DEFAULT_USE_HISTORY_MONTH): bool,
                vol.Optional(
                    CONF_COOKIE_UPDATE_INTERVAL,
                    default=int(DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS),
                ): int,
                vol.Optional(CONF_STATION_IDS, default=""): str,
                vol.Optional(CONF_LOCATION_ENTITY, default=""): str,
                vol.Optional(CONF_RADIUS_M, default=int(DEFAULT_RADIUS_M)): int,
                vol.Optional(CONF_MAX_RESULTS, default=int(DEFAULT_MAX_RESULTS)): int,
                vol.Optional(CONF_MIN_BIKES, default=int(DEFAULT_MIN_BIKES)): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}
        data = self._config_entry.data or {}
        opts = self._config_entry.options or {}

        if user_input is not None:
            username = (user_input.get(CONF_COOKIE_USERNAME) or "").strip()
            password = (user_input.get(CONF_COOKIE_PASSWORD) or "").strip()
            station_raw = (user_input.get(CONF_STATION_IDS) or "").strip()
            location_entity = (user_input.get(CONF_LOCATION_ENTITY) or "").strip()
            use_week = bool(user_input.get(CONF_USE_HISTORY_WEEK, DEFAULT_USE_HISTORY_WEEK))
            use_month = bool(user_input.get(CONF_USE_HISTORY_MONTH, DEFAULT_USE_HISTORY_MONTH))
            try:
                update_interval = int(
                    user_input.get(CONF_COOKIE_UPDATE_INTERVAL, DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS)
                )
            except Exception:
                update_interval = DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS
            try:
                radius_m = int(user_input.get(CONF_RADIUS_M, DEFAULT_RADIUS_M))
            except Exception:
                radius_m = DEFAULT_RADIUS_M
            try:
                max_results = int(user_input.get(CONF_MAX_RESULTS, DEFAULT_MAX_RESULTS))
            except Exception:
                max_results = DEFAULT_MAX_RESULTS
            try:
                min_bikes = int(user_input.get(CONF_MIN_BIKES, DEFAULT_MIN_BIKES))
            except Exception:
                min_bikes = DEFAULT_MIN_BIKES

            if not username or not password:
                errors["base"] = "login_required"
            elif not (use_week or use_month):
                errors["base"] = "period_required"
            else:
                try:
                    cookie_line = await _login_and_get_cookie(self.hass, username, password)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Login validation failed (options): %s", err)
                    errors["base"] = "invalid_login"
                else:
                    new_data = dict(data)
                    new_data[CONF_COOKIE] = cookie_line
                    new_data[CONF_COOKIE_USERNAME] = username
                    new_data[CONF_COOKIE_PASSWORD] = password
                    new_data[CONF_USE_HISTORY_WEEK] = use_week
                    new_data[CONF_USE_HISTORY_MONTH] = use_month
                    new_data[CONF_COOKIE_UPDATE_INTERVAL] = update_interval
                    new_data[CONF_STATION_IDS] = _parse_station_list(station_raw)
                    new_data[CONF_LOCATION_ENTITY] = location_entity
                    new_data[CONF_RADIUS_M] = radius_m
                    new_data[CONF_MAX_RESULTS] = max_results
                    new_data[CONF_MIN_BIKES] = min_bikes

                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data=new_data,
                        title="따릉이 (로그인)",
                    )

                    return self.async_create_entry(
                        title="",
                        data={
                            CONF_USE_HISTORY_WEEK: use_week,
                            CONF_USE_HISTORY_MONTH: use_month,
                            CONF_COOKIE_UPDATE_INTERVAL: update_interval,
                            CONF_STATION_IDS: _parse_station_list(station_raw),
                            CONF_LOCATION_ENTITY: location_entity,
                            CONF_RADIUS_M: radius_m,
                            CONF_MAX_RESULTS: max_results,
                            CONF_MIN_BIKES: min_bikes,
                        },
                    )

        station_default = opts.get(CONF_STATION_IDS)
        if station_default is None:
            station_default = data.get(CONF_STATION_IDS, [])
        station_default = station_default or []

        schema = vol.Schema(
            {
                vol.Required(CONF_COOKIE_USERNAME, default=""): str,
                vol.Required(CONF_COOKIE_PASSWORD, default=""): str,
                vol.Optional(
                    CONF_USE_HISTORY_WEEK,
                    default=bool(opts.get(CONF_USE_HISTORY_WEEK, data.get(CONF_USE_HISTORY_WEEK, DEFAULT_USE_HISTORY_WEEK))),
                ): bool,
                vol.Optional(
                    CONF_USE_HISTORY_MONTH,
                    default=bool(opts.get(CONF_USE_HISTORY_MONTH, data.get(CONF_USE_HISTORY_MONTH, DEFAULT_USE_HISTORY_MONTH))),
                ): bool,
                vol.Optional(
                    CONF_COOKIE_UPDATE_INTERVAL,
                    default=int(
                        opts.get(
                            CONF_COOKIE_UPDATE_INTERVAL,
                            data.get(CONF_COOKIE_UPDATE_INTERVAL, DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS),
                        )
                    ),
                ): int,
                vol.Optional(CONF_STATION_IDS, default=",".join(station_default)): str,
                vol.Optional(
                    CONF_LOCATION_ENTITY,
                    default=str(opts.get(CONF_LOCATION_ENTITY, data.get(CONF_LOCATION_ENTITY, "")) or ""),
                ): str,
                vol.Optional(
                    CONF_RADIUS_M,
                    default=int(opts.get(CONF_RADIUS_M, data.get(CONF_RADIUS_M, DEFAULT_RADIUS_M))),
                ): int,
                vol.Optional(
                    CONF_MAX_RESULTS,
                    default=int(opts.get(CONF_MAX_RESULTS, data.get(CONF_MAX_RESULTS, DEFAULT_MAX_RESULTS))),
                ): int,
                vol.Optional(
                    CONF_MIN_BIKES,
                    default=int(opts.get(CONF_MIN_BIKES, data.get(CONF_MIN_BIKES, DEFAULT_MIN_BIKES))),
                ): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
