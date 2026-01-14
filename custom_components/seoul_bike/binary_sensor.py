# custom_components/seoul_bike/binary_sensor.py

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    from .modes.cookie.binary_sensor import async_setup_entry as cookie_setup_entry

    return await cookie_setup_entry(hass, entry, async_add_entities)
