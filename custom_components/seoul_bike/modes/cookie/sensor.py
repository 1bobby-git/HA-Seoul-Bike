# custom_components/seoul_bike/modes/cookie/sensor.py

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MANUFACTURER,
    MODEL_USE_HISTORY,
    MODEL_FAVORITE_STATION,
    FAVORITE_DEVICE_PREFIX,
    DEVICE_NAME_USE_HISTORY_WEEK,
    DEVICE_NAME_USE_HISTORY_MONTH,
    CONF_USE_HISTORY_WEEK,
    CONF_USE_HISTORY_MONTH,
    DEFAULT_USE_HISTORY_WEEK,
    DEFAULT_USE_HISTORY_MONTH,
)
from .coordinator import SeoulPublicBikeCoordinator



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


def _period_identifier(period_key: str) -> str:
    return "week" if period_key == "1w" else "month"


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
    if isinstance(ent, TicketExpirySensor):
        return _object_id("cookie", _period_identifier(ent._period_key), "ticket_expiry")
    if isinstance(ent, LastUpdateTimeSensor):
        return _object_id("cookie", _period_identifier(ent._period_key), "last_update_time")
    if isinstance(ent, UseHistoryPeriodSensor):
        return _object_id("cookie", _period_identifier(ent._period_key), "period_range")
    if isinstance(ent, CookieLastHttpStatusSensor):
        ident = "week" if ent._device_id.endswith("use_history_week") else "month"
        return _object_id("cookie", ident, "last_http_status")
    if isinstance(ent, CookieLastErrorSensor):
        ident = "week" if ent._device_id.endswith("use_history_week") else "month"
        return _object_id("cookie", ident, "last_error")
    if isinstance(ent, FavoriteStationBikeCountSensor):
        name = "rent_bike_normal" if ent._kind == "normal" else "rent_bike_sprout"
        return _object_id("cookie", ent._station_id, name)
    if isinstance(ent, FavoriteStationIdSensor):
        return _object_id("cookie", ent._station_id, "station_id")
    return None


def _register_entity_ids(hass: HomeAssistant, entry: ConfigEntry, entities: list[SensorEntity]) -> None:
    for ent in entities:
        object_id = _object_id_for_entity(ent)
        if object_id:
            _ensure_entity_id(hass, entry, ent.unique_id, object_id, "sensor")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    opts = entry.options or {}
    use_week = bool(opts.get(CONF_USE_HISTORY_WEEK, DEFAULT_USE_HISTORY_WEEK))
    use_month = bool(opts.get(CONF_USE_HISTORY_MONTH, DEFAULT_USE_HISTORY_MONTH))
    periods: list[tuple[str, str, str]] = []
    if use_week:
        periods.append(("1w", DEVICE_NAME_USE_HISTORY_WEEK, "use_history_week"))
    if use_month:
        periods.append(("1m", DEVICE_NAME_USE_HISTORY_MONTH, "use_history_month"))
    if not periods:
        periods = [("1m", DEVICE_NAME_USE_HISTORY_MONTH, "use_history_month")]

    for period_key, device_name, device_suffix in periods:
        device_id = f"{entry.entry_id}_{device_suffix}"
        entities.extend(
            [
                # kcal_box
                KcalBoxTextSensor(coordinator, period_key, device_id, device_name, "이용 시간", "이용시간"),
                KcalBoxFloatSensor(coordinator, period_key, device_id, device_name, "거리 (km)", "거리", unit="km"),
                KcalBoxFloatSensor(coordinator, period_key, device_id, device_name, "칼로리 (kcal)", "칼로리", unit="kcal"),
                KcalBoxFloatSensor(coordinator, period_key, device_id, device_name, "탄소 절감 효과 (kg)", "탄소절감효과", unit="kg"),

                # 최근 이력
                LastFieldSensor(coordinator, period_key, device_id, device_name, "최근 자전거", "bike"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "최근 대여소", "rent_station"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "최근 대여 일시", "rent_datetime"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "최근 반납 대여소", "return_station"),
                LastFieldSensor(coordinator, period_key, device_id, device_name, "최근 반납 일시", "return_datetime"),

                # 이용권 유효기간
                TicketExpirySensor(coordinator, period_key, device_id, device_name),

                UseHistoryPeriodSensor(coordinator, period_key, device_id, device_name),

                LastUpdateTimeSensor(coordinator, period_key, device_id, device_name),
            ]
        )

    primary_period = next((p for p in periods if p[0] == "1m"), periods[0])
    primary_device_id = f"{entry.entry_id}_{primary_period[2]}"
    primary_name = primary_period[1]
    entities.extend(
        [
            CookieLastHttpStatusSensor(coordinator, primary_device_id, primary_name),
            CookieLastErrorSensor(coordinator, primary_device_id, primary_name),
        ]
    )

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

    _register_entity_ids(hass, entry, entities)
    async_add_entities(entities)

    ent_reg = er.async_get(hass)

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

    # 최초 상태 기준으로 "관리 중인 즐겨찾기" 세트 저장
    coordinator._spb_fav_station_ids = _current_station_ids()  # type: ignore[attr-defined]

    async def _async_sync_favorites() -> None:
        prev: set[str] = set(getattr(coordinator, "_spb_fav_station_ids", set()))
        curr: set[str] = _current_station_ids()

        added = curr - prev
        removed = prev - curr

        new_entities: list[SensorEntity] = []
        for sid in sorted(added):
            sname = _name_by_station_id(sid) or sid
            new_entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="normal"))
            new_entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="sprout"))
            new_entities.append(FavoriteStationIdSensor(coordinator, sid, sname))

        if new_entities:
            _register_entity_ids(hass, entry, new_entities)
            async_add_entities(new_entities)

        # entity_id는 entity_registry에서 unique_id로 찾아서 제거
        for sid in sorted(removed):
            for uid in (_uid_normal(sid), _uid_sprout(sid), _uid_station_id(sid)):
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)

        coordinator._spb_fav_station_ids = curr  # type: ignore[attr-defined]

    @callback
    def _on_coordinator_update() -> None:
        # DataUpdateCoordinator listener는 async를 직접 await 못하므로 task로 실행
        hass.async_create_task(_async_sync_favorites())

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
        import re
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


class TicketExpirySensor(_BaseUseHistorySensor):
    _attr_name = "이용권 유효 기간"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, period_key, device_id, device_name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{period_key}_ticket_expiry"

    @property
    def native_value(self):
        iso = (self._data.get("ticket_expiry") or "")
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt_util.as_utc(dt)
        except Exception:
            return None


class LastUpdateTimeSensor(_BaseUseHistorySensor):
    _attr_name = "마지막 업데이트 시간"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:update"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, period_key, device_id, device_name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{period_key}_last_update_time"

    @property
    def native_value(self):
        iso = (self._data.get("updated_at") or "")
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt_util.as_utc(dt)
        except Exception:
            return None


class UseHistoryPeriodSensor(_BaseUseHistorySensor):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-range"

    def __init__(
        self,
        coordinator: SeoulPublicBikeCoordinator,
        period_key: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, period_key, device_id, device_name)
        self._attr_name = "조회 기간"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{period_key}_period_range"

    @property
    def native_value(self):
        start = self._data.get("period_start")
        end = self._data.get("period_end")
        if start and end:
            return f"{start} ~ {end}"

        days = 7 if self._period_key == "1w" else 30
        today = datetime.now().date()
        start_dt = today - timedelta(days=days)
        return f"{start_dt.isoformat()} ~ {today.isoformat()}"


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
            "model": MODEL_USE_HISTORY,
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
            "model": MODEL_USE_HISTORY,
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
