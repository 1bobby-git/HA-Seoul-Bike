from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    DEVICE_NAME_USE_HISTORY_WEEK,
    DEVICE_NAME_USE_HISTORY_MONTH,
    MANUFACTURER,
    MODEL_USE_HISTORY,
    CONF_USE_HISTORY_WEEK,
    CONF_USE_HISTORY_MONTH,
    DEFAULT_USE_HISTORY_WEEK,
    DEFAULT_USE_HISTORY_MONTH,
)
from .coordinator import SeoulPublicBikeCoordinator



def _object_id(mode: str, identifier: str, name: str) -> str:
    return slugify(f"seoul_bike_{mode}_{identifier}_{name}")


def _ensure_entity_id(hass: HomeAssistant, entry: ConfigEntry, unique_id: str | None, object_id: str) -> None:
    if not unique_id or not object_id:
        return
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
    )

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]
    opts = entry.options or {}
    use_week = bool(opts.get(CONF_USE_HISTORY_WEEK, DEFAULT_USE_HISTORY_WEEK))
    use_month = bool(opts.get(CONF_USE_HISTORY_MONTH, DEFAULT_USE_HISTORY_MONTH))
    if not (use_week or use_month):
        use_month = True
    device_id = f"{entry.entry_id}_use_history_month" if use_month else f"{entry.entry_id}_use_history_week"
    device_name = DEVICE_NAME_USE_HISTORY_MONTH if use_month else DEVICE_NAME_USE_HISTORY_WEEK
    ent = UseHistoryDumpBinarySensor(coordinator, device_id, device_name)
    _ensure_entity_id(hass, entry, ent.unique_id, _object_id("cookie", "month" if "month" in device_id else "week", "raw_data"))
    async_add_entities([ent])


class UseHistoryDumpBinarySensor(CoordinatorEntity[SeoulPublicBikeCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "원본 데이터"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_unique_id = None

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_dump"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_USE_HISTORY,
        }

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return self.coordinator.last_update_success and not data.get("error")

    @property
    def extra_state_attributes(self):
        return self.coordinator.data or {}
