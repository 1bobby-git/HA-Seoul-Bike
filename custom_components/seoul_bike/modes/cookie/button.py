# custom_components/seoul_bike/modes/cookie/button.py

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEVICE_NAME_USE_HISTORY, MANUFACTURER, MODEL_USE_HISTORY
from .coordinator import SeoulPublicBikeCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UseHistoryRefreshButton(coordinator)])


class UseHistoryRefreshButton(CoordinatorEntity[SeoulPublicBikeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "새로 고침"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_refresh"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_use_history")},
            "name": DEVICE_NAME_USE_HISTORY,
            "manufacturer": MANUFACTURER,
            "model": MODEL_USE_HISTORY,
        }

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
