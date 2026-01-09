from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MODE, MODE_API, MODE_COOKIE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    mode = (entry.data.get(CONF_MODE) or "").strip().lower()

    if not mode:
        mode = MODE_API if "api_key" in (entry.data or {}) else MODE_COOKIE

    if mode == MODE_API:
        from .modes.api.sensor import async_setup_entry as api_setup_entry

        return await api_setup_entry(hass, entry, async_add_entities)

    if mode == MODE_COOKIE:
        from .modes.cookie.sensor import async_setup_entry as cookie_setup_entry

        return await cookie_setup_entry(hass, entry, async_add_entities)

    return None
