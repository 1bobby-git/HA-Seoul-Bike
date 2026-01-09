from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MODE, MODE_API, MODE_COOKIE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    mode = (entry.data.get(CONF_MODE) or "").strip().lower()

    # Backward-compat fallback (if someone migrated old entries manually)
    if not mode:
        if "api_key" in (entry.data or {}):
            mode = MODE_API
        elif "cookie" in (entry.data or {}):
            mode = MODE_COOKIE

    if mode == MODE_API:
        from .modes.api import async_setup_entry as api_setup_entry

        return await api_setup_entry(hass, entry)

    if mode == MODE_COOKIE:
        from .modes.cookie import async_setup_entry as cookie_setup_entry

        return await cookie_setup_entry(hass, entry)

    # Unknown mode -> refuse setup (will show as setup failed)
    return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    mode = (entry.data.get(CONF_MODE) or "").strip().lower()

    if not mode:
        if "api_key" in (entry.data or {}):
            mode = MODE_API
        elif "cookie" in (entry.data or {}):
            mode = MODE_COOKIE

    if mode == MODE_API:
        from .modes.api import async_unload_entry as api_unload_entry

        return await api_unload_entry(hass, entry)

    if mode == MODE_COOKIE:
        from .modes.cookie import async_unload_entry as cookie_unload_entry

        return await cookie_unload_entry(hass, entry)

    return False
