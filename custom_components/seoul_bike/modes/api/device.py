# custom_components/seoul_bike/modes/api/device.py

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, INTEGRATION_NAME, MANUFACTURER, MODEL_CONTROLLER, MODEL_STATION


def resolve_location_device_name(hass: HomeAssistant, location_entity_id: str) -> str | None:
    entity_id = (location_entity_id or "").strip()
    if not entity_id:
        return None

    state = hass.states.get(entity_id)
    if state:
        name = state.attributes.get("friendly_name")
        if name:
            return str(name)

    ent_reg = er.async_get(hass)
    ent = ent_reg.async_get(entity_id)
    if ent and ent.device_id:
        dev = dr.async_get(hass).devices.get(ent.device_id)
        if dev:
            return dev.name_by_user or dev.name

    return None


def controller_device_info(entry_id: str, name: str | None = None) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=name or INTEGRATION_NAME,
        manufacturer=MANUFACTURER,
        model=MODEL_CONTROLLER,
        sw_version="1.0",
    )


def station_device_info(entry_id: str, station_id: str, name: str, hw_version: str | None = None) -> DeviceInfo:
    info = DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}:{station_id}")},
        name=name,
        manufacturer=MANUFACTURER,
        model=MODEL_STATION,
        via_device=(DOMAIN, entry_id),
        sw_version="1.0",
    )
    if hw_version:
        info["hw_version"] = hw_version
    return info
