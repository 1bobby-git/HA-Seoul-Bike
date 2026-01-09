from __future__ import annotations

import hashlib
import logging

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

_LOGGER = logging.getLogger(__name__)


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


def _cookie_unique_id(cookie: str) -> str:
    key = (cookie or "").strip()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"cookie_{digest}"


async def _validate_api_key(hass, api_key: str) -> None:
    session = async_get_clientsession(hass)
    api = SeoulBikeApi(session, api_key)
    await api.fetch_page(1, 1)


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
                        MODE_API: "API 방식 (OpenAPI Polling)",
                        MODE_COOKIE: "Cookie 방식 (bikeseoul.com Pulling)",
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

            if api_key:
                await self.async_set_unique_id(_api_unique_id(api_key))
                self._abort_if_unique_id_configured()

            try:
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
                    CONF_STATION_IDS: _parse_station_list(station_raw),
                    CONF_LOCATION_ENTITY: location_entity,
                    CONF_UPDATE_INTERVAL: update_interval,
                }
                return self.async_create_entry(title="따릉이(API)", data=data)

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
            if not cookie:
                errors["base"] = "cookie_required"
            else:
                await self.async_set_unique_id(_cookie_unique_id(cookie))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="따릉이 (Cookie)",
                    data={
                        CONF_MODE: MODE_COOKIE,
                        CONF_COOKIE: cookie,
                    },
                )

        schema = vol.Schema({vol.Required(CONF_COOKIE): str})
        return self.async_show_form(step_id="cookie", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        mode = (config_entry.data.get(CONF_MODE) or "").strip().lower()
        if mode == MODE_COOKIE or "cookie" in (config_entry.data or {}):
            from .modes.cookie.config_flow import OptionsFlowHandler as CookieOptions

            return CookieOptions(config_entry)

        from .modes.api.config_flow import SeoulBikeOptionsFlowHandler as ApiOptions

        return ApiOptions(config_entry)
