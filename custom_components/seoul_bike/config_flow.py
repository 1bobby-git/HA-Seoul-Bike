# custom_components/seoul_bike/config_flow.py

from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .api import SeoulPublicBikeSiteApi
from .const import (
    DOMAIN,
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


def _user_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_COOKIE_USERNAME,
                default=str(defaults.get(CONF_COOKIE_USERNAME, "") or ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT, autocomplete="username")
            ),
            vol.Required(
                CONF_COOKIE_PASSWORD,
                default=str(defaults.get(CONF_COOKIE_PASSWORD, "") or ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD, autocomplete="current-password")
            ),
            **(
                {
                    vol.Optional(
                        CONF_LOCATION_ENTITY,
                        default=str(defaults.get(CONF_LOCATION_ENTITY) or ""),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["device_tracker", "person", "zone", "sensor"],
                            multiple=False,
                        )
                    )
                }
                if str(defaults.get(CONF_LOCATION_ENTITY) or "").strip()
                else {
                    vol.Optional(CONF_LOCATION_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["device_tracker", "person", "zone", "sensor"],
                            multiple=False,
                        )
                    )
                }
            ),
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow using HA-provided self.config_entry."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        data = self.config_entry.data or {}
        opts = self.config_entry.options or {}

        defaults = {
            CONF_COOKIE_USERNAME: opts.get(CONF_COOKIE_USERNAME, data.get(CONF_COOKIE_USERNAME, "")),
            CONF_COOKIE_PASSWORD: opts.get(CONF_COOKIE_PASSWORD, data.get(CONF_COOKIE_PASSWORD, "")),
            CONF_LOCATION_ENTITY: opts.get(CONF_LOCATION_ENTITY, data.get(CONF_LOCATION_ENTITY, "")),
        }

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
                        self.config_entry,
                        data=new_data,
                        title=username,
                    )

                    return self.async_create_entry(
                        title="",
                        data={CONF_LOCATION_ENTITY: location_entity},
                    )

        return self.async_show_form(
            step_id="init",
            data_schema=_user_schema(defaults),
            errors=errors,
        )
