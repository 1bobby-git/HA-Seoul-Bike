# custom_components/seoul_bike/modes/cookie/__init__.py

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN, DEVICE_NAME_USE_HISTORY, MANUFACTURER, MODEL_USE_HISTORY
from .coordinator import SeoulPublicBikeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    coordinator = SeoulPublicBikeCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        _LOGGER.warning("Cookie refresh failed during setup: %s", err)
        return False

    if (coordinator.data or {}).get("error"):
        _LOGGER.warning("Cookie validation failed during setup: %s", coordinator.data.get("error"))
        _cleanup_cookie_entities(hass, entry)
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _update_device_registry(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


def _update_device_registry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_use_history")})
    if device:
        dev_reg.async_update_device(
            device.id,
            name=DEVICE_NAME_USE_HISTORY,
            model=MODEL_USE_HISTORY,
            manufacturer=MANUFACTURER,
        )


def _cleanup_cookie_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    for ent in list(ent_reg.entities.values()):
        if ent.config_entry_id == entry.entry_id:
            ent_reg.async_remove(ent.entity_id)

    for device in list(dev_reg.devices.values()):
        if entry.entry_id in (device.config_entries or set()):
            dev_reg.async_remove_device(device.id)
