# custom_components/seoul_bike/config_flow.py

from __future__ import annotations

import hashlib
import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN
from .api import SeoulPublicBikeSiteApi
from .const import (
    CONF_COOKIE,
    CONF_COOKIE_PASSWORD,
    CONF_COOKIE_USERNAME,
    CONF_LOCATION_ENTITY,
)

_LOGGER = logging.getLogger(__name__)


def _login_unique_id(username: str) -> str:
    key = (username or "").strip()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"login_{digest}"


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
            location_entity = (user_input.get(CONF_LOCATION_ENTITY) or "").strip()

            if not username or not password:
                errors["base"] = "login_required"
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
                        title=username,
                        data={
                            CONF_COOKIE: cookie_line,
                            CONF_COOKIE_USERNAME: username,
                            CONF_COOKIE_PASSWORD: password,
                            CONF_LOCATION_ENTITY: location_entity,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_COOKIE_USERNAME, default=""): str,
                vol.Required(CONF_COOKIE_PASSWORD, default=""): str,
                vol.Optional(CONF_LOCATION_ENTITY, default=""): str,
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
            location_entity = (user_input.get(CONF_LOCATION_ENTITY) or "").strip()

            if not username or not password:
                errors["base"] = "login_required"
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
                    new_data[CONF_LOCATION_ENTITY] = location_entity

                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data=new_data,
                        title=username,
                    )

                    return self.async_create_entry(
                        title="",
                        data={CONF_LOCATION_ENTITY: location_entity},
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
                vol.Optional(
                    CONF_LOCATION_ENTITY,
                    default=str(opts.get(CONF_LOCATION_ENTITY, data.get(CONF_LOCATION_ENTITY, "")) or ""),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
