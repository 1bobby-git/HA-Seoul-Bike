from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    DEVICE_NAME_USE_HISTORY,
    MANUFACTURER,
    MODEL_USE_HISTORY,
    MODEL_FAVORITE_STATION,
    FAVORITE_DEVICE_PREFIX,
)
from .coordinator import SeoulPublicBikeCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        # kcal_box
        KcalBoxTextSensor(coordinator, "이용시간", "이용시간"),
        KcalBoxFloatSensor(coordinator, "거리(km)", "거리", unit="km"),
        KcalBoxFloatSensor(coordinator, "칼로리(kcal)", "칼로리", unit="kcal"),
        KcalBoxFloatSensor(coordinator, "탄소절감효과(kg)", "탄소절감효과", unit="kg"),

        # 최근 이력
        LastFieldSensor(coordinator, "최근 자전거", "bike"),
        LastFieldSensor(coordinator, "최근 대여소", "rent_station"),
        LastFieldSensor(coordinator, "최근 대여일시", "rent_datetime"),
        LastFieldSensor(coordinator, "최근 반납 대여소", "return_station"),
        LastFieldSensor(coordinator, "최근 반납일시", "return_datetime"),

        # 이용권 유효기간
        TicketExpirySensor(coordinator),

        # ✅ 마지막 업데이트 시간(서버에서 가져와 반영한 시점)
        LastUpdateTimeSensor(coordinator),
    ]

    # 초기 즐겨찾기 엔티티 생성
    favs = (coordinator.data or {}).get("favorites") or []
    for f in favs:
        sid = f.get("station_id") or ""
        sname = f.get("station_name") or ""
        if not sid or not sname:
            continue
        entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="normal"))
        entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="sprout"))

    async_add_entities(entities)

    # ✅ 새로고침 시 즐겨찾기 변경되면 엔티티 자동 추가/삭제
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

    # 최초 상태 기준으로 "관리 중인 즐겨찾기" 세트 저장
    coordinator._spb_fav_station_ids = _current_station_ids()  # type: ignore[attr-defined]

    async def _async_sync_favorites() -> None:
        prev: set[str] = set(getattr(coordinator, "_spb_fav_station_ids", set()))
        curr: set[str] = _current_station_ids()

        added = curr - prev
        removed = prev - curr

        # 추가: 새 즐겨찾기 → 엔티티 2개 생성
        new_entities: list[SensorEntity] = []
        for sid in sorted(added):
            sname = _name_by_station_id(sid) or sid
            new_entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="normal"))
            new_entities.append(FavoriteStationBikeCountSensor(coordinator, sid, sname, kind="sprout"))

        if new_entities:
            async_add_entities(new_entities)

        # 삭제: 제거된 즐겨찾기 → 엔티티 2개 제거
        # entity_id는 entity_registry에서 unique_id로 찾아서 제거
        for sid in sorted(removed):
            for uid in (_uid_normal(sid), _uid_sprout(sid)):
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

    def __init__(self, coordinator: SeoulPublicBikeCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_use_history")},
            "name": DEVICE_NAME_USE_HISTORY,
            "manufacturer": MANUFACTURER,
            "model": MODEL_USE_HISTORY,
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def _kcal(self) -> dict[str, str]:
        return self._data.get("kcal") or {}

    @property
    def _last(self) -> dict[str, Any]:
        return self._data.get("last") or {}


class KcalBoxTextSensor(_BaseUseHistorySensor):
    def __init__(self, coordinator: SeoulPublicBikeCoordinator, name: str, key: str) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_kcal_{key}"

    @property
    def native_value(self):
        return self._kcal.get(self._key)


class KcalBoxFloatSensor(_BaseUseHistorySensor):
    def __init__(self, coordinator: SeoulPublicBikeCoordinator, name: str, key: str, unit: str) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._key = key
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{coordinator.entry.entry_id}_kcal_{key}_float"

    @property
    def native_value(self):
        v = self._kcal.get(self._key)
        if not v:
            return None
        import re
        m = re.search(r"[-+]?\d+(?:\.\d+)?", v)
        return float(m.group(0)) if m else None


class LastFieldSensor(_BaseUseHistorySensor):
    def __init__(self, coordinator: SeoulPublicBikeCoordinator, name: str, key: str) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_{key}"

    @property
    def native_value(self):
        return self._last.get(self._key)


class TicketExpirySensor(_BaseUseHistorySensor):
    _attr_name = "이용권 유효기간"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SeoulPublicBikeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_ticket_expiry"

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

    def __init__(self, coordinator: SeoulPublicBikeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_update_time"

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
        else:
            self._attr_name = "대여 가능 자전거 (새싹)"
            suffix = "sprout"

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

    @property
    def extra_state_attributes(self):
        return {"station_id": self._station_id}
