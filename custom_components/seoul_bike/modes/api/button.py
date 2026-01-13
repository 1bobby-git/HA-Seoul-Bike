from __future__ import annotations

"""Buttons for Seoul Bike integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, INTEGRATION_NAME, MANUFACTURER, MODEL_CONTROLLER, MODEL_STATION
from .coordinator import SeoulBikeCoordinator

try:
    from .device import resolve_location_device_name
except Exception:  # pragma: no cover - runtime fallback
    def resolve_location_device_name(hass, location_entity_id: str) -> str | None:
        return None


def _main_device(entry: ConfigEntry, coordinator: SeoulBikeCoordinator) -> DeviceInfo:
    name = resolve_location_device_name(coordinator.hass, coordinator.location_entity_id)
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=name or INTEGRATION_NAME,
        manufacturer=MANUFACTURER,
        model=MODEL_CONTROLLER,
        sw_version="1.0",
    )


def _station_device(entry: ConfigEntry, coordinator: SeoulBikeCoordinator, station_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}:{station_id}")},
        name=coordinator.get_station_device_name(station_id),
        manufacturer=MANUFACTURER,
        model=MODEL_STATION,
        via_device=(DOMAIN, entry.entry_id),
        sw_version="1.0",
    )



def _object_id(mode: str, identifier: str, name: str) -> str:
    return slugify(f"seoul_bike_{mode}_{identifier}_{name}")


def _ensure_entity_id(hass: HomeAssistant, entry: ConfigEntry, unique_id: str | None, object_id: str) -> None:
    if not unique_id or not object_id:
        return
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "button",
        DOMAIN,
        unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
    )


def _object_id_for_entity(ent: ButtonEntity) -> str | None:
    if isinstance(ent, MainRefreshButton):
        return _object_id("api", "main", "refresh")
    if isinstance(ent, StationRefreshButton):
        return _object_id("api", ent._station_id, "refresh")
    return None


def _register_entity_ids(hass: HomeAssistant, entry: ConfigEntry, entities: list[ButtonEntity]) -> None:
    for ent in entities:
        object_id = _object_id_for_entity(ent)
        if object_id:
            _ensure_entity_id(hass, entry, ent.unique_id, object_id)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulBikeCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[ButtonEntity] = [MainRefreshButton(coordinator, entry)]

    for station_id in coordinator.station_ids:
        entities.append(StationRefreshButton(coordinator, entry, station_id))

    _register_entity_ids(hass, entry, entities)
    async_add_entities(entities)


class MainRefreshButton(CoordinatorEntity[SeoulBikeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "새로 고침"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_refresh_all"

    @property
    def device_info(self) -> DeviceInfo:
        return _main_device(self._entry, self.coordinator)

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class StationRefreshButton(CoordinatorEntity[SeoulBikeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "새로 고침"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._station_id = station_id
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_refresh"

    @property
    def device_info(self) -> DeviceInfo:
        return _station_device(self._entry, self.coordinator, self._station_id)

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
