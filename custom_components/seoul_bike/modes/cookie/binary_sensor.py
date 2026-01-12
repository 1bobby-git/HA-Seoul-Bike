# custom_components/seoul_bike/modes/cookie/binary_sensor.py

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_NAME_USE_HISTORY, MANUFACTURER, MODEL_USE_HISTORY
from .coordinator import SeoulPublicBikeCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UseHistoryDumpBinarySensor(coordinator)])


class UseHistoryDumpBinarySensor(CoordinatorEntity[SeoulPublicBikeCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "원본 데이터"
    _attr_unique_id = None

    def __init__(self, coordinator: SeoulPublicBikeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_dump"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_use_history")},
            "name": DEVICE_NAME_USE_HISTORY,
            "manufacturer": MANUFACTURER,
            "model": MODEL_USE_HISTORY,
        }

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return self.coordinator.last_update_success and not data.get("error")

    @property
    def extra_state_attributes(self):
        # ✅ 수집 결과 전체 저장 (요구사항)
        return self.coordinator.data or {}
