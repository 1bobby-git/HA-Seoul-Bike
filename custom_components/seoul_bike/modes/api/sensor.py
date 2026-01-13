# custom_components/seoul_bike/modes/api/sensor.py

"""Sensors for Seoul Bike integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, INTEGRATION_NAME, MANUFACTURER, MODEL_CONTROLLER, MODEL_STATION
from .coordinator import SeoulBikeCoordinator, haversine_m

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


def _ensure_entity_id(hass: HomeAssistant, entry: ConfigEntry, unique_id: str | None, object_id: str, domain: str) -> None:
    if not unique_id or not object_id:
        return
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        domain,
        DOMAIN,
        unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
    )


def _object_id_for_entity(ent: SensorEntity) -> str | None:
    if isinstance(ent, NearbyTotalBikesSensor):
        return _object_id("api", "main", "nearby_total_bikes")
    if isinstance(ent, NearbyRecommendedBikesSensor):
        return _object_id("api", "main", "nearby_recommended_bikes")
    if isinstance(ent, NearbyStationsListSensor):
        return _object_id("api", "main", "nearby_station_list")
    if isinstance(ent, ApiDiagnosticSensor):
        return _object_id("api", "main", "api_diagnostic")
    if isinstance(ent, ApiLastHttpStatusSensor):
        return _object_id("api", "main", "last_http_status")
    if isinstance(ent, ApiLastErrorSensor):
        return _object_id("api", "main", "last_error")
    if isinstance(ent, StationBikesTotalSensor):
        return _object_id("api", ent._station_id, "rent_bike_total")
    if isinstance(ent, StationBikesGeneralSensor):
        return _object_id("api", ent._station_id, "rent_bike_normal")
    if isinstance(ent, StationBikesTeenSensor):
        return _object_id("api", ent._station_id, "rent_bike_sprout")
    if isinstance(ent, StationBikesRepairSensor):
        return _object_id("api", ent._station_id, "rent_bike_repair")
    if isinstance(ent, StationIdSensor):
        return _object_id("api", ent._station_id, "station_id")
    if isinstance(ent, StationDistanceSensor):
        return _object_id("api", ent._station_id, "distance_m")
    return None


def _register_entity_ids(hass: HomeAssistant, entry: ConfigEntry, entities: list[SensorEntity]) -> None:
    for ent in entities:
        object_id = _object_id_for_entity(ent)
        if object_id:
            _ensure_entity_id(hass, entry, ent.unique_id, object_id, "sensor")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulBikeCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SensorEntity] = [
        NearbyTotalBikesSensor(coordinator, entry),
        NearbyRecommendedBikesSensor(coordinator, entry),
        NearbyStationsListSensor(coordinator, entry),
        ApiDiagnosticSensor(coordinator, entry),
        ApiLastHttpStatusSensor(coordinator, entry),
        ApiLastErrorSensor(coordinator, entry),
    ]

    for station_id in coordinator.station_ids:
        entities.extend(
            [
                StationBikesTotalSensor(coordinator, entry, station_id),
                StationBikesGeneralSensor(coordinator, entry, station_id),
                StationBikesTeenSensor(coordinator, entry, station_id),
                StationBikesRepairSensor(coordinator, entry, station_id),
                StationIdSensor(coordinator, entry, station_id),
                StationDistanceSensor(coordinator, entry, station_id),
            ]
        )

    _register_entity_ids(hass, entry, entities)
    async_add_entities(entities)


class BaseSeoulBikeSensor(CoordinatorEntity[SeoulBikeCoordinator], SensorEntity):
    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return _main_device(self._entry, self.coordinator)


class NearbyTotalBikesSensor(BaseSeoulBikeSensor):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_total_bikes"
        self._attr_name = f"{INTEGRATION_NAME} 주변 총 대여 가능"

    @property
    def native_value(self) -> int:
        return int(getattr(self.coordinator, "nearby_total_bikes", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "내 위치 엔티티": self.coordinator.location_entity_id,
            "주변 반경 (m)": self.coordinator.radius_m,
            "최소 자전거 수": self.coordinator.min_bikes,
            "중심점 소스": self.coordinator.center_source,
            "중심 위도": self.coordinator.center_lat,
            "중심 경도": self.coordinator.center_lon,
            "상태": self.coordinator.nearby_status,
        }


class NearbyRecommendedBikesSensor(BaseSeoulBikeSensor):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_recommended_bikes"
        self._attr_name = f"{INTEGRATION_NAME} 주변 추천 대여소 대여 가능"

    @property
    def native_value(self) -> int:
        return int(getattr(self.coordinator, "nearby_recommended_bikes", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "추천 목록 개수": len(self.coordinator.nearby),
            "추천 목록": self.coordinator.nearby,
            "주변 반경 (m)": self.coordinator.radius_m,
            "최소 자전거 수": self.coordinator.min_bikes,
            "상태": self.coordinator.nearby_status,
        }


class NearbyStationsListSensor(BaseSeoulBikeSensor):
    _attr_icon = "mdi:map-marker-radius"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_station_list"
        self._attr_name = f"{INTEGRATION_NAME} 주변 대여소 목록"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.nearby)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "내 위치 엔티티": self.coordinator.location_entity_id,
            "주변 반경 (m)": self.coordinator.radius_m,
            "최소 자전거 수": self.coordinator.min_bikes,
            "중심점 소스": self.coordinator.center_source,
            "중심 위도": self.coordinator.center_lat,
            "중심 경도": self.coordinator.center_lon,
            "개수": len(self.coordinator.nearby),
            "목록": self.coordinator.nearby,
            "상태": self.coordinator.nearby_status,
        }


class ApiDiagnosticSensor(BaseSeoulBikeSensor):
    _attr_icon = "mdi:database-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api_diagnostic"
        self._attr_name = f"{INTEGRATION_NAME} API 데이터 진단"

    @property
    def native_value(self) -> str:
        return "ok" if self.coordinator.last_update_success else "error"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last_exc = self.coordinator.last_exception
        d = self.coordinator.data or {}
        return {
            "last_error": self.coordinator.last_error,
            "last_http_status": self.coordinator.last_http_status,
            "마지막 업데이트 성공": self.coordinator.last_update_success,
            "마지막 예외": str(last_exc) if last_exc else None,
            "전체 row 수": d.get("total_rows"),
            "대여 가능 > 0 정류소 수": d.get("nonzero_station_count"),
            "요청 메타": d.get("fetch_meta"),
            "입력한 정류소": list(self.coordinator.configured_station_inputs),
            "변환 성공": list(self.coordinator.resolved_stations),
            "변환 실패": list(self.coordinator.unresolved_stations),
            "주변 결과 개수": d.get("nearby_count"),
        }


class ApiLastHttpStatusSensor(BaseSeoulBikeSensor):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Last HTTP Status"
    _attr_icon = "mdi:cloud-check"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api_last_http_status"

    @property
    def native_value(self):
        return self.coordinator.last_http_status


class ApiLastErrorSensor(BaseSeoulBikeSensor):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Last Error"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api_last_error"

    @property
    def native_value(self):
        return self.coordinator.last_error or "none"

class _StationBase(CoordinatorEntity[SeoulBikeCoordinator], SensorEntity):
    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._station_id = station_id

    @property
    def device_info(self) -> DeviceInfo:
        return _station_device(self._entry, self.coordinator, self._station_id)

    @property
    def _station(self):
        return self.coordinator.stations_by_id.get(self._station_id)

    @property
    def available(self) -> bool:
        return self._station is not None and self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._station
        if not s:
            return {"정류소 ID": self._station_id, "상태": "not_in_latest_dataset"}

        return {
            "정류소 ID": s.station_id,
            "정류소 번호": s.station_no,
            "정류소 명": s.station_title,
        }


class StationBikesTotalSensor(_StationBase):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_total"
        self._attr_name = "대여 가능 자전거"

    @property
    def native_value(self) -> int | None:
        s = self._station
        return None if not s else int(s.bikes_total)


class StationBikesGeneralSensor(_StationBase):
    _attr_icon = "mdi:bicycle"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_general"
        self._attr_name = "대여 가능 자전거 (일반)"

    @property
    def native_value(self) -> int | None:
        s = self._station
        return None if not s else int(s.bikes_general)


class StationBikesTeenSensor(_StationBase):
    _attr_icon = "mdi:sprout"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_teen"
        self._attr_name = "대여 가능 자전거 (새싹)"

    @property
    def native_value(self) -> int | None:
        s = self._station
        return None if not s else int(s.bikes_teen)


class StationBikesRepairSensor(_StationBase):
    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_repair"
        self._attr_name = "점검 필요"

    @property
    def native_value(self) -> int | None:
        s = self._station
        return None if not s else int(s.bikes_repair)


class StationIdSensor(_StationBase):
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_station_id"
        self._attr_name = "정류소 ID"

    @property
    def native_value(self) -> str | None:
        s = self._station
        return None if not s else s.station_id


class StationDistanceSensor(_StationBase):
    _attr_icon = "mdi:map-marker-distance"
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_distance_m"
        self._attr_name = "중심점 거리"

    @property
    def native_value(self) -> float | None:
        s = self._station
        if not s:
            return None

        # 센서 계산 시점마다 현재 중심점 재계산
        try:
            self.coordinator._compute_center()
        except Exception:
            pass

        if self.coordinator.center_lat is None or self.coordinator.center_lon is None:
            return None

        return round(haversine_m(self.coordinator.center_lat, self.coordinator.center_lon, s.lat, s.lon), 1)
