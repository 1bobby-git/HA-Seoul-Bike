# custom_components/seoul_bike/modes/api/config_flow.py

from __future__ import annotations

import hashlib
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SeoulBikeApi, SeoulBikeApiAuthError, SeoulBikeApiError
from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_STATION_IDS,
    CONF_LOCATION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


def _parse_list(raw: str) -> list[str]:
    if not raw:
        return []
    items: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        v = chunk.strip()
        if v:
            items.append(v)
    seen = set()
    out: list[str] = []
    for v in items:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _placeholders() -> dict[str, str]:
    return {
        "open_data_url": "https://data.seoul.go.kr/dataList/OA-15493/A/1/datasetView.do",
        "open_api_test_url": "https://data.seoul.go.kr/together/mypage/actkeyMain.do",
    }


def _api_unique_id(api_key: str) -> str:
    key = (api_key or "").strip()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"api_{digest}"


async def _validate_api_key(hass, api_key: str) -> None:
    session = async_get_clientsession(hass)
    api = SeoulBikeApi(session, api_key)
    await api.fetch_page(1, 1)


class SeoulBikeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
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
            except SeoulBikeApiAuthError as err:
                _LOGGER.warning("API key validation failed (auth): %s", err)
                errors["base"] = "invalid_auth"
            except SeoulBikeApiError as err:
                _LOGGER.warning("API key validation failed (api): %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error during config validation: %s", err)
                errors["base"] = "unknown"

            if not errors:
                data = {
                    CONF_API_KEY: api_key,
                    CONF_STATION_IDS: _parse_list(station_raw),
                    CONF_LOCATION_ENTITY: location_entity,
                    CONF_UPDATE_INTERVAL: update_interval,
                }
                return self.async_create_entry(title="따릉이 (Seoul Bike)", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_LOCATION_ENTITY, default=""): str,
                vol.Optional(CONF_UPDATE_INTERVAL, default=int(DEFAULT_UPDATE_INTERVAL_SECONDS)): int,
                vol.Optional(CONF_STATION_IDS, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=_placeholders(),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return SeoulBikeOptionsFlowHandler(config_entry)


class SeoulBikeOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            station_raw = (user_input.get(CONF_STATION_IDS) or "")
            return self.async_create_entry(
                title="",
                data={
                    CONF_STATION_IDS: _parse_list(station_raw),
                    CONF_LOCATION_ENTITY: (user_input.get(CONF_LOCATION_ENTITY) or "").strip(),
                    CONF_UPDATE_INTERVAL: int(
                        user_input.get(CONF_UPDATE_INTERVAL) or DEFAULT_UPDATE_INTERVAL_SECONDS
                    ),
                },
            )

        opts = self._config_entry.options or {}
        data = self._config_entry.data or {}

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_STATION_IDS,
                    default=",".join(data.get(CONF_STATION_IDS, [])),
                ): str,
                vol.Required(
                    CONF_LOCATION_ENTITY,
                    default=str(opts.get(CONF_LOCATION_ENTITY, data.get(CONF_LOCATION_ENTITY, "")) or ""),
                ): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=int(opts.get(CONF_UPDATE_INTERVAL, data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS))),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors={},
            description_placeholders=_placeholders(),
        )
