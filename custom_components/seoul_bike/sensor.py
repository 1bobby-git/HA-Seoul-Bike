# custom_components/seoul_bike/sensor.py

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import re

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MANUFACTURER,
    INTEGRATION_NAME,
    MODEL_USE_HISTORY,
    MODEL_FAVORITE_STATION,
    MODEL_STATION,
    MODEL_CONTROLLER,
    MODEL_MY_PAGE,
    FAVORITE_DEVICE_PREFIX,
    DEVICE_NAME_USE_HISTORY,
    DEVICE_NAME_MY_PAGE,
    CONF_COOKIE_USERNAME,
    make_object_id,
    station_display_name,
)
from .coordinator import SeoulPublicBikeCoordinator, haversine_m


# Alias for local usage
_object_id = make_object_id


def _resolve_location_device_name(hass: HomeAssistant, location_entity_id: str) -> str | None:
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


# Use centralized station_display_name from const.py
_station_display_name = station_display_name


def _coords_from_entity(hass: HomeAssistant, entity_id: str) -> tuple[float, float] | None:
    ent_id = (entity_id or "").strip()
    if not ent_id:
        return None
    state = hass.states.get(ent_id)
    if not state:
        return None
    lat = state.attributes.get("latitude")
    lon = state.attributes.get("longitude")
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except Exception:
            return None
    m = re.search(r"^\s*(-?\d+(?:\.\d+)?)\s*[,/ ]\s*(-?\d+(?:\.\d+)?)\s*$", str(state.state))
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except Exception:
        return None


def _distance_enabled(hass: HomeAssistant, coordinator: SeoulPublicBikeCoordinator) -> bool:
    return _coords_from_entity(hass, coordinator.location_entity_id or "") is not None


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


def _period_identifier(period_key: str) -> str:
    if period_key == "1w":
        return "week"
    if period_key == "1m":
        return "month"
    return "history"


def _object_id_for_entity(ent: SensorEntity) -> str | None:
    if isinstance(ent, KcalBoxTextSensor):
        return _object_id("cookie", _period_identifier(ent._period_key), "usage_time")
    if isinstance(ent, KcalBoxFloatSensor):
        unit = (ent._attr_native_unit_of_measurement or "").lower()
        name_map = {
            "km": "distance_km",
            "kcal": "calories_kcal",
            "kg": "carbon_reduction_kg",
        }
        return _object_id("cookie", _period_identifier(ent._period_key), name_map.get(unit, "distance_km"))
    if isinstance(ent, LastFieldSensor):
        name_map = {
            "bike": "last_bike",
            "rent_station": "last_rent_station",
            "rent_datetime": "last_rent_datetime",
            "return_station": "last_return_station",
            "return_datetime": "last_return_datetime",
        }
        return _object_id("cookie", _period_identifier(ent._period_key), name_map.get(ent._key, "last_bike"))
    if isinstance(ent, MyPageTicketExpirySensor):
        return _object_id("cookie", "my_page", "ticket_expiry")
    if isinstance(ent, MyPageLastUpdateTimeSensor):
        return _object_id("cookie", "my_page", "last_update_time")
    if isinstance(ent, CookieLastHttpStatusSensor):
        return _object_id("cookie", "my_page", "last_http_status")
    if isinstance(ent, CookieLastErrorSensor):
        return _object_id("cookie", "my_page", "last_error")
    if isinstance(ent, FavoriteStationBikeCountSensor):
        name = "rent_bike_normal" if ent._kind == "normal" else "rent_bike_sprout"
        return _object_id("cookie", ent._station_id, name)
    if isinstance(ent, FavoriteStationIdSensor):
        return _object_id("cookie", ent._station_id, "station_id")
    if isinstance(ent, FavoriteStationDistanceSensor):
        return _object_id("cookie", ent._station_id, "favorite_distance_m")
    if isinstance(ent, NearbyTotalBikesSensor):
        return _object_id("cookie", "main", "nearby_total_bikes")
    if isinstance(ent, NearbyRecommendedBikesSensor):
        return _object_id("cookie", "main", "nearby_recommended_bikes")
    if isinstance(ent, NearbyStationsListSensor):
        return _object_id("cookie", "main", "nearby_station_list")
    if isinstance(ent, StationBikesTotalSensor):
        return _object_id("cookie", ent._station_id, "rent_bike_total")
    if isinstance(ent, StationBikesGeneralSensor):
        return _object_id("cookie", ent._station_id, "rent_bike_normal")
    if isinstance(ent, StationBikesSproutSensor):
        return _object_id("cookie", ent._station_id, "rent_bike_sprout")
    if isinstance(ent, StationBikesRepairSensor):
        return _object_id("cookie", ent._station_id, "rent_bike_repair")
    if isinstance(ent, StationIdSensor):
        return _object_id("cookie", ent._station_id, "station_id_status")
    if isinstance(ent, StationDistanceSensor):
        return _object_id("cookie", ent._station_id, "distance_m")
    return None


def _register_entity_ids(hass: HomeAssistant, entry: ConfigEntry, entities: list[SensorEntity]) -> None:
    for ent in entities:
        object_id = _object_id_for_entity(ent)
        if object_id:
            _ensure_entity_id(hass, entry, ent.unique_id, object_id, "sensor")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    periods: list[tuple[str, str, str]] = [("history", DEVICE_NAME_USE_HISTORY, "use_history")]

    my_page_device_id = f"{entry.entry_id}_my_page"
    my_page_device_name = DEVICE_NAME_MY_PAGE

    for period_key, device_name, device_suffix in periods:
        device_id = f"{entry.entry_id}_{device_suffix}"
        entities.extend(
            [
                # kcal_box
                KcalBoxTextSensor(coordinator, period_key, device_id, device_name, "이용 시간", "이용시간"),
                KcalBoxFloatSensor(coordinator, period_key, device_id, device_name, "거리 (km)", "거리", unit="km"),
                KcalBoxFloatSensor(coordinator, period_key, device_id, device_name, "칼로리 (kcal)", "칼로리", unit="kcal"),
                KcalBoxFloatSensor(coordinator, period_key, device_id, device_name, "탄소 절감 효과 (kg)", "탄소절감효과", unit="kg"),

                # 대여 반납 이력
                LastFieldSensor(coordinator, period_key, device_id, device_name, "자전거", "bike"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "대여소", "rent_station"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "대여 일시", "rent_datetime"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "반납 대여소", "return_station"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "반납 일시", "return_datetime"),

                # 이동 경로
                MoveRouteDistanceSensor(coordinator, period_key, device_id, device_name),
            ]
        )

    entities.extend(
        [
            CookieLastHttpStatusSensor(coordinator, my_page_device_id, my_page_device_name),
            CookieLastErrorSensor(coordinator, my_page_device_id, my_page_device_name),
        ]
    )

    entities.extend(
        [
            MyPageLastUpdateTimeSensor(coordinator, my_page_device_id, my_page_device_name),
            MyPageTicketExpirySensor(coordinator, my_page_device_id, my_page_device_name),
            MyPageRegDttmSensor(coordinator, my_page_device_id, my_page_device_name),
            MyPageLastLoginSensor(coordinator, my_page_device_id, my_page_device_name),
        ]
    )

    station_ids = list(getattr(coordinator, "stations_by_id", {}) or {})
    distance_enabled = _distance_enabled(hass, coordinator)
    if station_ids:
        entities.extend(
            [
                NearbyTotalBikesSensor(coordinator, entry),
                NearbyRecommendedBikesSensor(coordinator, entry),
                NearbyStationsListSensor(coordinator, entry),
            ]
        )

        for sid in station_ids:
            st = coordinator.stations_by_id.get(sid)
            station_name = _station_display_name(st, sid)
            entities.extend(
                [
                    StationBikesTotalSensor(coordinator, entry, sid, station_name),
                    StationBikesGeneralSensor(coordinator, entry, sid, station_name),
                    StationBikesSproutSensor(coordinator, entry, sid, station_name),
                    StationBikesRepairSensor(coordinator, entry, sid, station_name),
                    StationIdSensor(coordinator, entry, sid, station_name),
                ]
            )
            if distance_enabled:
                entities.append(StationDistanceSensor(coordinator, entry, sid, station_name))

    # 초기 즐겨찾기 엔티티 생성
    favs = (coordinator.data or {}).get("favorites") or []
    for f in favs:
        sid = f.get("station_id") or ""
        sname = f.get("station_name") or ""
        if not sid or not sname:
            continue
        entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="normal"))
        entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="sprout"))
        entities.append(FavoriteStationIdSensor(coordinator, sid, sname))
        if distance_enabled:
            entities.append(FavoriteStationDistanceSensor(coordinator, sid, sname))

    _register_entity_ids(hass, entry, entities)
    async_add_entities(entities)

    ent_reg = er.async_get(hass)

    async def _cleanup_legacy_use_history_sensors() -> None:
        for period_key in ("1w", "1m"):
            for suffix in ("ticket_expiry", "last_update_time"):
                uid = f"{entry.entry_id}_{period_key}_{suffix}"
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)
        for suffix in ("http_status", "last_error"):
            for period in ("use_history_week", "use_history_month"):
                uid = f"{entry.entry_id}_{period}_{suffix}"
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)

    await _cleanup_legacy_use_history_sensors()

    def _current_station_ids() -> set[str]:
        data = coordinator.data or {}
        favs2 = data.get("favorites") or []
        return {str(x.get("station_id") or "").strip() for x in favs2 if (x.get("station_id") or "").strip()}

    def _name_by_station_id(station_id: str) -> str | None:
        data = coordinator.data or {}
        favs2 = data.get("favorites") or []
        for x in favs2:
            sid = (x.get("station_id") or "").strip()
            if sid == station_id:
                return (x.get("station_name") or "").strip() or None
        return None

    # sensor unique_id 규칙(기존과 동일하게 유지)
    def _uid_normal(station_id: str) -> str:
        return f"{entry.entry_id}_fav_{station_id}_normal"

    def _uid_sprout(station_id: str) -> str:
        return f"{entry.entry_id}_fav_{station_id}_sprout"

    def _uid_station_id(station_id: str) -> str:
        return f"{entry.entry_id}_fav_{station_id}_station_id"

    def _uid_fav_distance(station_id: str) -> str:
        return f"{entry.entry_id}_fav_{station_id}_distance_m"

    # 최초 상태 기준으로 "관리 중인 즐겨찾기" 세트 저장
    coordinator._spb_fav_station_ids = _current_station_ids()  # type: ignore[attr-defined]
    coordinator._spb_fav_distance_enabled = distance_enabled  # type: ignore[attr-defined]

    def _current_station_ids_from_status() -> set[str]:
        stations = getattr(coordinator, "stations_by_id", {}) or {}
        return {str(sid).strip() for sid in stations.keys() if str(sid).strip()}

    def _station_name_from_status(station_id: str) -> str:
        station = (getattr(coordinator, "stations_by_id", {}) or {}).get(station_id)
        return _station_display_name(station, station_id)

    def _uid_station_bikes_total(station_id: str) -> str:
        return f"{entry.entry_id}_{station_id}_bikes_total"

    def _uid_station_bikes_general(station_id: str) -> str:
        return f"{entry.entry_id}_{station_id}_bikes_general"

    def _uid_station_bikes_sprout(station_id: str) -> str:
        return f"{entry.entry_id}_{station_id}_bikes_sprout"

    def _uid_station_bikes_repair(station_id: str) -> str:
        return f"{entry.entry_id}_{station_id}_bikes_repair"

    def _uid_station_id_status(station_id: str) -> str:
        return f"{entry.entry_id}_{station_id}_station_id"

    def _uid_station_distance(station_id: str) -> str:
        return f"{entry.entry_id}_{station_id}_distance_m"

    def _nearby_uids() -> list[str]:
        return [
            f"{entry.entry_id}_nearby_total_bikes",
            f"{entry.entry_id}_nearby_recommended_bikes",
            f"{entry.entry_id}_nearby_station_list",
        ]

    async def _async_sync_favorites() -> None:
        prev: set[str] = set(getattr(coordinator, "_spb_fav_station_ids", set()))
        curr: set[str] = _current_station_ids()
        distance_enabled = _distance_enabled(hass, coordinator)
        prev_distance_enabled = getattr(coordinator, "_spb_fav_distance_enabled", distance_enabled)

        added = curr - prev
        removed = prev - curr

        new_entities: list[SensorEntity] = []
        for sid in sorted(added):
            sname = _name_by_station_id(sid) or sid
            new_entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="normal"))
            new_entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="sprout"))
            new_entities.append(FavoriteStationIdSensor(coordinator, sid, sname))
            if distance_enabled:
                new_entities.append(FavoriteStationDistanceSensor(coordinator, sid, sname))

        if distance_enabled and not prev_distance_enabled:
            for sid in sorted(curr):
                if sid in added:
                    continue
                sname = _name_by_station_id(sid) or sid
                new_entities.append(FavoriteStationDistanceSensor(coordinator, sid, sname))

        if new_entities:
            _register_entity_ids(hass, entry, new_entities)
            async_add_entities(new_entities)

        # entity_id는 entity_registry에서 unique_id로 찾아서 제거
        for sid in sorted(removed):
            for uid in (_uid_normal(sid), _uid_sprout(sid), _uid_station_id(sid), _uid_fav_distance(sid)):
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)

        if prev_distance_enabled and not distance_enabled:
            for sid in sorted(curr):
                uid = _uid_fav_distance(sid)
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)

        coordinator._spb_fav_station_ids = curr  # type: ignore[attr-defined]
        coordinator._spb_fav_distance_enabled = distance_enabled  # type: ignore[attr-defined]

    async def _async_sync_stations() -> None:
        prev: set[str] = set(getattr(coordinator, "_spb_station_ids", set()))
        curr: set[str] = _current_station_ids_from_status()
        distance_enabled = _distance_enabled(hass, coordinator)
        prev_distance_enabled = getattr(coordinator, "_spb_distance_enabled", distance_enabled)

        added = curr - prev
        removed = prev - curr

        new_entities: list[SensorEntity] = []
        if not prev and curr:
            new_entities.extend(
                [
                    NearbyTotalBikesSensor(coordinator, entry),
                    NearbyRecommendedBikesSensor(coordinator, entry),
                    NearbyStationsListSensor(coordinator, entry),
                ]
            )

        for sid in sorted(added):
            sname = _station_name_from_status(sid)
            new_entities.extend(
                [
                    StationBikesTotalSensor(coordinator, entry, sid, sname),
                    StationBikesGeneralSensor(coordinator, entry, sid, sname),
                    StationBikesSproutSensor(coordinator, entry, sid, sname),
                    StationBikesRepairSensor(coordinator, entry, sid, sname),
                    StationIdSensor(coordinator, entry, sid, sname),
                ]
            )
            if distance_enabled:
                new_entities.append(StationDistanceSensor(coordinator, entry, sid, sname))

        if distance_enabled and not prev_distance_enabled:
            for sid in sorted(curr):
                if sid in added:
                    continue
                sname = _station_name_from_status(sid)
                new_entities.append(StationDistanceSensor(coordinator, entry, sid, sname))

        if new_entities:
            _register_entity_ids(hass, entry, new_entities)
            async_add_entities(new_entities)

        if prev_distance_enabled and not distance_enabled:
            for sid in sorted(curr):
                uid = _uid_station_distance(sid)
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)

        if removed:
            dev_reg = dr.async_get(hass)
            for sid in sorted(removed):
                for uid in (
                    _uid_station_bikes_total(sid),
                    _uid_station_bikes_general(sid),
                    _uid_station_bikes_sprout(sid),
                    _uid_station_bikes_repair(sid),
                    _uid_station_id_status(sid),
                    _uid_station_distance(sid),
                ):
                    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                    if entity_id:
                        await ent_reg.async_remove(entity_id)

                device = dev_reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_station_{sid}")})
                if device:
                    dev_reg.async_remove_device(device.id)

        if prev and not curr:
            for uid in _nearby_uids():
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)

            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_stations")})
            if device:
                dev_reg.async_remove_device(device.id)

        coordinator._spb_station_ids = curr  # type: ignore[attr-defined]
        coordinator._spb_distance_enabled = distance_enabled  # type: ignore[attr-defined]

    @callback
    def _on_coordinator_update() -> None:
        # DataUpdateCoordinator listener는 async를 직접 await 못하므로 task로 실행
        async def _sync_all() -> None:
            await _async_sync_favorites()
            await _async_sync_stations()

        hass.async_create_task(_sync_all())

    coordinator.async_add_listener(_on_coordinator_update)


class _BaseUseHistorySensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._period_key = period_key
        self._device_id = device_id
        self._device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_USE_HISTORY,
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def _data(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        periods = data.get("periods") or {}
        return periods.get(self._period_key, {}) if isinstance(periods, dict) else {}

    @property
    def _kcal(self) -> dict[str, str]:
        raw = self._data.get("kcal") or {}
        if not raw:
            return {}
        normalized: dict[str, str] = {}
        for k, v in raw.items():
            if not isinstance(k, str):
                continue
            normalized[k] = v
            normalized[k.replace(" ", "")] = v
        return normalized

    @property
    def _last(self) -> dict[str, Any]:
        return self._data.get("last") or {}


class KcalBoxTextSensor(_BaseUseHistorySensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
        name: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, period_key, device_id, device_name)
        self._attr_name = name
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{period_key}_kcal_{key}"
        self._attr_icon = "mdi:ticket-confirmation-outline"

    @property
    def native_value(self):
        v = self._kcal.get(self._key)
        return v if v else "조회된 데이터가 없음"


class KcalBoxFloatSensor(_BaseUseHistorySensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
        name: str,
        key: str,
        unit: str,
    ) -> None:
        super().__init__(coordinator, period_key, device_id, device_name)
        self._attr_name = name
        self._key = key
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{period_key}_kcal_{key}_float"
        icon_by_unit = {
            "km": "mdi:map-marker-distance",
            "kcal": "mdi:fire",
            "kg": "mdi:leaf",
        }
        self._attr_icon = icon_by_unit.get((unit or "").lower())

    @property
    def native_value(self):
        v = self._kcal.get(self._key)
        if not v:
            return 0
        m = re.search(r"[-+]?\d+(?:\.\d+)?", v)
        return float(m.group(0)) if m else 0


class LastFieldSensor(_BaseUseHistorySensor):
    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
        name: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, period_key, device_id, device_name)
        self._attr_name = name
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{period_key}_last_{key}"
        icon_by_key = {
            "bike": "mdi:bicycle",
            "rent_station": "mdi:map-marker",
            "rent_datetime": "mdi:clock-outline",
            "return_station": "mdi:map-marker-check",
            "return_datetime": "mdi:clock-outline",
        }
        self._attr_icon = icon_by_key.get(key)

    @property
    def native_value(self):
        v = self._last.get(self._key)
        if v:
            return v
        history = (self._data.get("history") or [])
        if isinstance(history, list) and history:
            latest = history[0] if isinstance(history[0], dict) else {}
            v = latest.get(self._key)
            if v:
                return v
        return "조회된 데이터가 없음"


class MoveRouteDistanceSensor(_BaseUseHistorySensor):
    _attr_native_unit_of_measurement = "m"
    _attr_icon = "mdi:map-marker-distance"

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, period_key, device_id, device_name)
        self._attr_name = "최근 이동 거리"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{period_key}_move_distance"

    @property
    def native_value(self) -> float | None:
        move_route = self._data.get("move_route") or {}
        if not isinstance(move_route, dict):
            return None
        dist = move_route.get("moveDist") or move_route.get("distance")
        if dist is None:
            return None
        try:
            return float(dist)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        move_route = self._data.get("move_route") or {}
        if not isinstance(move_route, dict):
            return {}
        return {
            "이동 시간 (초)": move_route.get("moveTime"),
            "경로 좌표": move_route.get("routeList"),
        }


class _BaseMyPageSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_MY_PAGE,
        }

    @property
    def _data(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("my_page") or {}

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt_util.as_utc(dt)
        except Exception:
            return None


class MyPageLastUpdateTimeSensor(_BaseMyPageSensor):
    _attr_name = "마지막 업데이트 시간"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:update"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_my_page_last_update_time"

    @property
    def native_value(self):
        return self._parse_timestamp(self._data.get("updated_at"))


class MyPageTicketExpirySensor(_BaseMyPageSensor):
    _attr_name = "이용권 유효 기간"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = None

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_my_page_ticket_expiry"

    @property
    def native_value(self):
        return self._parse_timestamp(self._data.get("voucher_end_dttm"))


class MyPageRegDttmSensor(_BaseMyPageSensor):
    _attr_name = "가입일"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:account-plus"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_my_page_reg_dttm"

    @property
    def native_value(self):
        return self._parse_timestamp(self._data.get("reg_dttm"))


class MyPageLastLoginSensor(_BaseMyPageSensor):
    _attr_name = "마지막 로그인"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:login"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator, device_id, device_name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_my_page_last_login"

    @property
    def native_value(self):
        return self._parse_timestamp(self._data.get("last_login_dttm"))


class CookieLastHttpStatusSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "마지막 HTTP 상태"
    _attr_icon = "mdi:cloud-check"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_http_status"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_MY_PAGE,
        }

    @property
    def native_value(self):
        return getattr(self.coordinator, "last_http_status", None)


class CookieLastErrorSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "마지막 오류"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_last_error"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_MY_PAGE,
        }

    @property
    def native_value(self):
        return getattr(self.coordinator, "last_error", None) or "없음"

    @property
    def extra_state_attributes(self):
        return {
            "마지막 요청 URL": getattr(self.coordinator, "last_request_url", None),
            "쿠키 검증 상태": getattr(self.coordinator, "validation_status", None),
        }
class FavoriteStationBikeCountSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, station_id: str, station_name: str, kind: str) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._kind = kind

        if kind == "normal":
            self._attr_name = "대여 가능 자전거 (일반)"
            suffix = "normal"
            self._attr_icon = "mdi:bicycle"
        else:
            self._attr_name = "대여 가능 자전거 (새싹)"
            suffix = "sprout"
            self._attr_icon = "mdi:sprout"

        # unique_id 규칙 유지(삭제 시 lookup에 사용)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fav_{station_id}_{suffix}"
        self._device_id = f"{FAVORITE_DEVICE_PREFIX}_{coordinator.entry.entry_id}_{station_id}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._station_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_FAVORITE_STATION,
        }

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        st = (data.get("favorite_status") or {}).get(self._station_id) or {}
        if self._kind == "normal":
            return st.get("normal")
        return st.get("sprout")


class FavoriteStationIdSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, station_id: str, station_name: str) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._attr_name = "정류소 ID"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fav_{station_id}_station_id"
        self._device_id = f"{FAVORITE_DEVICE_PREFIX}_{coordinator.entry.entry_id}_{station_id}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._station_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_FAVORITE_STATION,
        }

    @property
    def native_value(self):
        return self._station_id


class FavoriteStationDistanceSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "m"
    _attr_icon = "mdi:map-marker-distance"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, station_id: str, station_name: str) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._attr_name = "거리"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fav_{station_id}_distance_m"
        self._device_id = f"{FAVORITE_DEVICE_PREFIX}_{coordinator.entry.entry_id}_{station_id}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._station_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_FAVORITE_STATION,
        }

    @property
    def native_value(self) -> float | None:
        st = (self.coordinator.stations_by_id or {}).get(self._station_id)
        lat = None
        lon = None
        if st and st.lat and st.lon:
            lat = st.lat
            lon = st.lon
        if lat is None or lon is None:
            fav = (self.coordinator.data or {}).get("favorite_status") or {}
            fdata = fav.get(self._station_id) or {}
            try:
                lat = float(fdata.get("lat"))
                lon = float(fdata.get("lon"))
            except Exception:
                lat = None
                lon = None
        if lat is None or lon is None:
            return None
        coords = _coords_from_entity(self.coordinator.hass, self.coordinator.location_entity_id or "")
        if not coords:
            return None
        center_lat, center_lon = coords
        dist = haversine_m(center_lat, center_lon, lat, lon)
        return round(dist, 1)


class _StationControllerSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._controller_id = f"{entry.entry_id}_stations"

    @property
    def device_info(self):
        username = str(self._entry.data.get(CONF_COOKIE_USERNAME) or "").strip()
        name = _resolve_location_device_name(self.coordinator.hass, self.coordinator.location_entity_id)
        return {
            "identifiers": {(DOMAIN, self._controller_id)},
            "name": username or name or INTEGRATION_NAME,
            "manufacturer": MANUFACTURER,
            "model": MODEL_CONTROLLER,
        }


class NearbyTotalBikesSensor(_StationControllerSensor):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_total_bikes"
        self._attr_name = "주변 대여 가능 자전거 (전체)"

    @property
    def native_value(self) -> int:
        return int(getattr(self.coordinator, "nearby_total_bikes", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "위치 엔티티": self.coordinator.location_entity_id,
            "주변 반경 (m)": self.coordinator.radius_m,
            "최소 자전거 수": self.coordinator.min_bikes,
            "중심 위치": self.coordinator.center_source,
            "중심 위도": self.coordinator.center_lat,
            "중심 경도": self.coordinator.center_lon,
            "상태": self.coordinator.nearby_status,
        }
class NearbyRecommendedBikesSensor(_StationControllerSensor):
    _attr_icon = "mdi:bicycle-basket"
    _attr_native_unit_of_measurement = "대"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_recommended_bikes"
        self._attr_name = "주변 추천 대여소 대여 가능 자전거"

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
class NearbyStationsListSensor(_StationControllerSensor):
    _attr_icon = "mdi:map-marker-radius"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearby_station_list"
        self._attr_name = "주변 대여소 목록"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.nearby)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "추천 목록": self.coordinator.nearby,
            "주변 반경 (m)": self.coordinator.radius_m,
            "최소 자전거 수": self.coordinator.min_bikes,
            "상태": self.coordinator.nearby_status,
        }
class _StationSensor(CoordinatorEntity[SeoulPublicBikeCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry, station_id: str, station_name: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._station_id = station_id
        self._station_name = station_name
        self._device_id = f"{entry.entry_id}_station_{station_id}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._station_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_STATION,
            "via_device": (DOMAIN, f"{self._entry.entry_id}_stations"),
        }


class StationBikesTotalSensor(_StationSensor):
    _attr_native_unit_of_measurement = "대"
    _attr_icon = "mdi:bicycle"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, entry, station_id, station_name)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_total"
        self._attr_name = "대여 가능 자전거 (전체)"

    @property
    def native_value(self) -> int:
        st = self.coordinator.stations_by_id.get(self._station_id)
        return int(st.bikes_total) if st else 0


class StationBikesGeneralSensor(_StationSensor):
    _attr_native_unit_of_measurement = "대"
    _attr_icon = "mdi:bicycle"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, entry, station_id, station_name)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_general"
        self._attr_name = "대여 가능 자전거 (일반)"

    @property
    def native_value(self) -> int:
        st = self.coordinator.stations_by_id.get(self._station_id)
        return int(st.bikes_general) if st else 0


class StationBikesSproutSensor(_StationSensor):
    _attr_native_unit_of_measurement = "대"
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, entry, station_id, station_name)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_sprout"
        self._attr_name = "대여 가능 자전거 (새싹)"

    @property
    def native_value(self) -> int:
        st = self.coordinator.stations_by_id.get(self._station_id)
        return int(st.bikes_sprout) if st else 0


class StationBikesRepairSensor(_StationSensor):
    _attr_native_unit_of_measurement = "대"
    _attr_icon = "mdi:tools"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, entry, station_id, station_name)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_bikes_repair"
        self._attr_name = "대여 불가 자전거 (정비)"

    @property
    def native_value(self) -> int:
        st = self.coordinator.stations_by_id.get(self._station_id)
        return int(st.bikes_repair) if st else 0


class StationIdSensor(_StationSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:identifier"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, entry, station_id, station_name)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_station_id"
        self._attr_name = "정류소 ID"

    @property
    def native_value(self) -> str:
        return self._station_id


class StationDistanceSensor(_StationSensor):
    _attr_native_unit_of_measurement = "m"
    _attr_icon = "mdi:map-marker-distance"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry: ConfigEntry, station_id: str, station_name: str) -> None:
        super().__init__(coordinator, entry, station_id, station_name)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_distance_m"
        self._attr_name = "거리"

    @property
    def native_value(self) -> float | None:
        st = self.coordinator.stations_by_id.get(self._station_id)
        if not st or not st.lat or not st.lon:
            return None
        coords = _coords_from_entity(self.coordinator.hass, self.coordinator.location_entity_id or "")
        if not coords:
            return None
        center_lat, center_lon = coords
        dist = haversine_m(center_lat, center_lon, st.lat, st.lon)
        return round(dist, 1)
