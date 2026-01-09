from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, CONF_COOKIE


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            cookie = (user_input.get(CONF_COOKIE) or "").strip()
            if not cookie:
                errors["base"] = "cookie_required"
            else:
                return self.async_create_entry(
                    title="따릉이 (Seoul Public Bike)",
                    data={CONF_COOKIE: cookie},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_COOKIE): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            cookie = (user_input.get(CONF_COOKIE) or "").strip()
            if not cookie:
                errors["base"] = "cookie_required"
            else:
                return self.async_create_entry(title="", data={CONF_COOKIE: cookie})

        schema = vol.Schema(
            {
                vol.Required(CONF_COOKIE, default=self.config_entry.options.get(CONF_COOKIE, self.config_entry.data.get(CONF_COOKIE, ""))): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
