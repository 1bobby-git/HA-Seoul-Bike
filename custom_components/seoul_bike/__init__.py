# custom_components/seoul_bike/__init__.py

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .modes.cookie import async_setup_entry as cookie_setup_entry

    return await cookie_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .modes.cookie import async_unload_entry as cookie_unload_entry

    return await cookie_unload_entry(hass, entry)
