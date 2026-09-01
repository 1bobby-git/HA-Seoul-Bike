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
    CONF_COOKIE,
    CONF_COOKIE_PASSWORD,
    CONF_COOKIE_REVISION,
    CONF_COOKIE_USERNAME,
    CONF_LOCATION_ENTITY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
_LOGIN_ERRORS = {"login_failed", "cookie_not_found"}


def _login_unique_id(username: str) -> str:
    key = (username or "").strip()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"login_{digest}"


async def _login_and_get_cookie(hass, username: str, password: str) -> str:
    """Log in with a bounded HTTP timeout and return the resulting cookie."""
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
        timeout=timeout,
    ) as session:
        api = SeoulPublicBikeSiteApi(session, "")
        return await api.login(username, password)


def _login_error_key(error: Exception) -> str:
    if isinstance(error, (aiohttp.ClientError, TimeoutError)):
        return "cannot_connect"
    if isinstance(error, ValueError) and str(error) in _LOGIN_ERRORS:
        return "invalid_login"
    return "cannot_connect"


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    location = str(defaults.get(CONF_LOCATION_ENTITY) or "").strip()
    location_field = selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["device_tracker", "person", "zone", "sensor"],
            multiple=False,
        )
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_COOKIE_USERNAME,
                default=str(defaults.get(CONF_COOKIE_USERNAME, "") or ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    autocomplete="username",
                )
            ),
            vol.Required(
                CONF_COOKIE_PASSWORD,
                default=str(defaults.get(CONF_COOKIE_PASSWORD, "") or ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            ),
            **(
                {vol.Optional(CONF_LOCATION_ENTITY, default=location): location_field}
                if location
                else {vol.Optional(CONF_LOCATION_ENTITY): location_field}
            ),
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Seoul Bike account."""

    VERSION = 1
    _reauth_entry_id: str | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = str(user_input.get(CONF_COOKIE_USERNAME) or "").strip()
            password = str(user_input.get(CONF_COOKIE_PASSWORD) or "").strip()
            location_entity = str(
                user_input.get(CONF_LOCATION_ENTITY) or ""
            ).strip()

            if not username or not password:
                errors["base"] = "login_required"
            else:
                try:
                    cookie_line = await _login_and_get_cookie(
                        self.hass,
                        username,
                        password,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Seoul Bike login validation failed: %s",
                        type(err).__name__,
                    )
                    errors["base"] = _login_error_key(err)
                else:
                    if self._reauth_entry_id is not None:
                        entry = self.hass.config_entries.async_get_entry(
                            self._reauth_entry_id
                        )
                        if entry is None:
                            return self.async_abort(reason="reauth_failed")
                        revision = int(
                            entry.data.get(CONF_COOKIE_REVISION, 0) or 0
                        ) + 1
                        self.hass.config_entries.async_update_entry(
                            entry,
                            data={
                                **entry.data,
                                CONF_COOKIE: cookie_line,
                                CONF_COOKIE_USERNAME: username,
                                CONF_COOKIE_PASSWORD: password,
                                CONF_COOKIE_REVISION: revision,
                                CONF_LOCATION_ENTITY: location_entity,
                            },
                            title=username,
                        )
                        await self.hass.config_entries.async_reload(entry.entry_id)
                        return self.async_abort(reason="reauth_successful")

                    await self.async_set_unique_id(_login_unique_id(username))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=username,
                        data={
                            CONF_COOKIE: cookie_line,
                            CONF_COOKIE_USERNAME: username,
                            CONF_COOKIE_PASSWORD: password,
                            CONF_COOKIE_REVISION: 1,
                            CONF_LOCATION_ENTITY: location_entity,
                        },
                    )

        defaults: dict[str, Any] = {}
        if self._reauth_entry_id is not None:
            entry = self.hass.config_entries.async_get_entry(
                self._reauth_entry_id
            )
            if entry:
                defaults = dict(entry.data)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(defaults),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Start credential renewal after the site rejects the session."""
        self._reauth_entry_id = self.context.get("entry_id")
        return await self.async_step_user()

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Update credentials and the location source."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        data = self.config_entry.data or {}
        options = self.config_entry.options or {}

        defaults = {
            CONF_COOKIE_USERNAME: options.get(
                CONF_COOKIE_USERNAME,
                data.get(CONF_COOKIE_USERNAME, ""),
            ),
            CONF_COOKIE_PASSWORD: options.get(
                CONF_COOKIE_PASSWORD,
                data.get(CONF_COOKIE_PASSWORD, ""),
            ),
            CONF_LOCATION_ENTITY: options.get(
                CONF_LOCATION_ENTITY,
                data.get(CONF_LOCATION_ENTITY, ""),
            ),
        }

        if user_input is not None:
            username = str(user_input.get(CONF_COOKIE_USERNAME) or "").strip()
            password = str(user_input.get(CONF_COOKIE_PASSWORD) or "").strip()
            location_entity = str(
                user_input.get(CONF_LOCATION_ENTITY) or ""
            ).strip()

            if not username or not password:
                errors["base"] = "login_required"
            else:
                try:
                    cookie_line = await _login_and_get_cookie(
                        self.hass,
                        username,
                        password,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Seoul Bike options login validation failed: %s",
                        type(err).__name__,
                    )
                    errors["base"] = _login_error_key(err)
                else:
                    revision = int(
                        data.get(CONF_COOKIE_REVISION, 0) or 0
                    ) + 1
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={
                            **data,
                            CONF_COOKIE: cookie_line,
                            CONF_COOKIE_USERNAME: username,
                            CONF_COOKIE_PASSWORD: password,
                            CONF_COOKIE_REVISION: revision,
                            CONF_LOCATION_ENTITY: location_entity,
                        },
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
