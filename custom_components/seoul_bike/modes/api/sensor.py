"""Sensors for Seoul Bike integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_NAME, MANUFACTURER, MODEL_CONTROLLER, MODEL_STATION
from .coordinator import SeoulBikeCoordinator, haversine_m


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

    entities: list[SensorEntity] = [
        NearbyTotalBikesSensor(coordinator, entry),
        NearbyRecommendedBikesSensor(coordinator, entry),
        NearbyStationsListSensor(coordinator, entry),
        ApiDiagnosticSensor(coordinator, entry),
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

    async_add_entities(entities)


class BaseSeoulBikeSensor(CoordinatorEntity[SeoulBikeCoordinator], SensorEntity):
    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return _main_device(self._entry)


class NearbyTotalBikesSensor(BaseSeoulBikeSensor):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_total_bikes"
        self._attr_name = f"{INTEGRATION_NAME} 주변 총 대여가능"

    @property
    def native_value(self) -> int:
        return int(getattr(self.coordinator, "nearby_total_bikes", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "내 위치 엔티티": self.coordinator.location_entity_id,
            "주변 반경(m)": self.coordinator.radius_m,
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
        self._attr_name = f"{INTEGRATION_NAME} 주변 추천 대여소 대여가능"

    @property
    def native_value(self) -> int:
        return int(getattr(self.coordinator, "nearby_recommended_bikes", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "추천 목록 개수": len(self.coordinator.nearby),
            "추천 목록": self.coordinator.nearby,
            "주변 반경(m)": self.coordinator.radius_m,
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
            "주변 반경(m)": self.coordinator.radius_m,
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
            "마지막 업데이트 성공": self.coordinator.last_update_success,
            "마지막 예외": str(last_exc) if last_exc else None,
            "전체 row 수": d.get("total_rows"),
            "대여가능>0 정류소 수": d.get("nonzero_station_count"),
            "요청 메타": d.get("fetch_meta"),
            "입력한 정류소": d.get("configured_station_inputs"),
            "변환 성공": d.get("resolved"),
            "변환 실패": d.get("unresolved"),
            "주변 결과 개수": d.get("nearby_count"),
        }


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
            "정류소명": s.station_title,
        }


class StationBikesTotalSensor(_StationBase):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_total"
        self._attr_name = "대여가능 자전거"

    @property
    def native_value(self) -> int | None:
        s = self._station
        return None if not s else int(s.bikes_total)


class StationBikesGeneralSensor(_StationBase):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_general"
        self._attr_name = "대여가능(일반)"

    @property
    def native_value(self) -> int | None:
        s = self._station
        return None if not s else int(s.bikes_general)


class StationBikesTeenSensor(_StationBase):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulBikeCoordinator, entry: ConfigEntry, station_id: str) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_teen"
        self._attr_name = "대여가능(새싹)"

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

        # ✅ 옵션에서 내 위치 엔티티를 나중에 추가해도 즉시 반영되도록,
        # 센서 계산 시점마다 현재 중심점 재계산
        try:
            self.coordinator._compute_center()
        except Exception:
            pass

        if self.coordinator.center_lat is None or self.coordinator.center_lon is None:
            return None

        return round(haversine_m(self.coordinator.center_lat, self.coordinator.center_lon, s.lat, s.lon), 1)
