from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_NAME_MY_PAGE,
    DOMAIN,
    MANUFACTURER,
    MODEL_MY_PAGE,
    make_object_id,
)
from .rent_status import normalize_rent_status
from .runtime_coordinator import SeoulPublicBikeCoordinator

_MAX_FAVORITE_IDS = 20
_object_id = make_object_id


def _summarize_data(data: dict) -> dict:
    periods_out: dict = {}
    periods = data.get("periods") if isinstance(data, dict) else None
    if isinstance(periods, dict):
        for key, payload in periods.items():
            if not isinstance(payload, dict):
                continue
            history = payload.get("history") or []
            periods_out[key] = {
                "period_start": payload.get("period_start"),
                "period_end": payload.get("period_end"),
                "history_count": len(history) if isinstance(history, list) else 0,
                "last": payload.get("last"),
                "kcal": payload.get("kcal"),
            }

    favorites = data.get("favorites") if isinstance(data, dict) else None
    favorite_ids: list[str] = []
    if isinstance(favorites, list):
        for favorite in favorites:
            if isinstance(favorite, dict):
                station_id = favorite.get("station_id")
                if station_id:
                    favorite_ids.append(str(station_id))
            if len(favorite_ids) >= _MAX_FAVORITE_IDS:
                break

    return {
        "updated_at": data.get("updated_at") if isinstance(data, dict) else None,
        "error": data.get("error") if isinstance(data, dict) else None,
        "validation_status": (
            data.get("validation_status") if isinstance(data, dict) else None
        ),
        "last_request": data.get("last_request") if isinstance(data, dict) else None,
        "periods": periods_out,
        "station_count": data.get("station_count") if isinstance(data, dict) else None,
        "nearby_count": data.get("nearby_count") if isinstance(data, dict) else None,
        "favorites_count": len(favorites) if isinstance(favorites, list) else 0,
        "favorite_station_ids": favorite_ids,
        "favorite_station_ids_truncated": (
            isinstance(favorites, list) and len(favorites) > _MAX_FAVORITE_IDS
        ),
    }


def _ensure_entity_id(
    hass: HomeAssistant,
    entry: ConfigEntry,
    unique_id: str | None,
    object_id: str,
) -> None:
    if not unique_id or not object_id:
        return
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]
    device_id = f"{entry.entry_id}_my_page"
    device_name = DEVICE_NAME_MY_PAGE

    entities = [
        UseHistoryDumpBinarySensor(coordinator, device_id, device_name),
        CurrentRentStatusBinarySensor(coordinator, device_id, device_name),
    ]

    entity_registry = er.async_get(hass)
    for entity in entities:
        existing_id = entity_registry.async_get_entity_id(
            "binary_sensor",
            DOMAIN,
            entity.unique_id,
        )
        if existing_id:
            existing = entity_registry.async_get(existing_id)
            if existing and existing.device_id:
                device_registry = dr.async_get(hass)
                device = device_registry.devices.get(existing.device_id)
                if device and (DOMAIN, device_id) not in (
                    device.identifiers or set()
                ):
                    await entity_registry.async_remove(existing_id)

    _ensure_entity_id(
        hass,
        entry,
        entities[0].unique_id,
        _object_id("cookie", "my_page", "raw_data"),
    )
    _ensure_entity_id(
        hass,
        entry,
        entities[1].unique_id,
        _object_id("cookie", "my_page", "rent_status"),
    )
    async_add_entities(entities)


class UseHistoryDumpBinarySensor(
    CoordinatorEntity[SeoulPublicBikeCoordinator],
    BinarySensorEntity,
):
    _attr_has_entity_name = True
    _attr_name = "원본 데이터"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_unique_id = None

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
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
            "model": MODEL_MY_PAGE,
        }

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return self.coordinator.last_update_success and not data.get("error")

    @property
    def extra_state_attributes(self):
        return _summarize_data(self.coordinator.data or {})


class CurrentRentStatusBinarySensor(
    CoordinatorEntity[SeoulPublicBikeCoordinator],
    BinarySensorEntity,
):
    _attr_has_entity_name = True
    _attr_name = "현재 대여 중"
    _attr_icon = "mdi:bicycle"

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_current_rent"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_MY_PAGE,
        }

    def _status(self) -> dict:
        data = self.coordinator.data or {}
        return normalize_rent_status(data.get("rent_status"))

    @property
    def is_on(self) -> bool:
        return str(self._status().get("rentYn") or "").strip().upper() == "Y"

    @property
    def extra_state_attributes(self):
        rent_status = self._status()
        return {
            "대여소": rent_status.get("stationName"),
            "자전거 번호": rent_status.get("bikeNo"),
            "대여 시작": rent_status.get("rentDttm"),
        }
