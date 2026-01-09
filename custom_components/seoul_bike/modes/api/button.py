"""Buttons for Seoul Bike integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_NAME, MANUFACTURER, MODEL_CONTROLLER, MODEL_STATION
from .coordinator import SeoulBikeCoordinator


def _main_device(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=INTEGRATION_NAME,
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulBikeCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[ButtonEntity] = [MainRefreshButton(coordinator, entry)]

    # ✅ station_ids에 대해 정류소 새로고침 버튼 생성
    for station_id in coordinator.station_ids:
        entities.append(StationRefreshButton(coordinator, entry, station_id))

    async_add_entities(entities)


class MainRefreshButton(CoordinatorEntity[SeoulBikeCoordinator], ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_refresh_all"
        self._attr_name = f"{INTEGRATION_NAME} 지금 새로고침"

    @property
    def device_info(self) -> DeviceInfo:
        return _main_device(self._entry)

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


class StationRefreshButton(CoordinatorEntity[SeoulBikeCoordinator], ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._station_id = station_id
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_refresh"
        self._attr_name = "정류소 새로고침"

    @property
    def device_info(self) -> DeviceInfo:
        return _station_device(self._entry, self.coordinator, self._station_id)

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
