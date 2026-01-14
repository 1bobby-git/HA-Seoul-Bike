from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    DEVICE_NAME_USE_HISTORY_WEEK,
    DEVICE_NAME_USE_HISTORY_MONTH,
    INTEGRATION_NAME,
    MANUFACTURER,
    MODEL_CONTROLLER,
    MODEL_USE_HISTORY,
    MODEL_FAVORITE_STATION,
    MODEL_STATION,
    FAVORITE_DEVICE_PREFIX,
    CONF_USE_HISTORY_WEEK,
    CONF_USE_HISTORY_MONTH,
    DEFAULT_USE_HISTORY_WEEK,
    DEFAULT_USE_HISTORY_MONTH,
    CONF_COOKIE_USERNAME,
)
from .coordinator import SeoulPublicBikeCoordinator



def _object_id(mode: str, identifier: str, name: str) -> str:
    return slugify(f"seoul_bike_{mode}_{identifier}_{name}")


def _station_display_name(station: object | None, fallback: str) -> str:
    if not station:
        return fallback
    station_no = str(getattr(station, "station_no", "") or "").strip()
    title = str(getattr(station, "station_title", "") or "").strip()
    if station_no and title:
        return f"{station_no}. {title}"
    return title or station_no or fallback


def _ensure_entity_id(hass: HomeAssistant, entry: ConfigEntry, unique_id: str | None, object_id: str) -> None:
    if not unique_id or not object_id:
        return
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "button",
        DOMAIN,
        unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
    )


def _object_id_for_entity(ent: ButtonEntity) -> str | None:
    if isinstance(ent, UseHistoryRefreshButton):
        ident = "week" if ent._device_id.endswith("use_history_week") else "month"
        return _object_id("cookie", ident, "refresh")
    if isinstance(ent, FavoriteStationRefreshButton):
        return _object_id("cookie", ent._station_id, "refresh")
    if isinstance(ent, StationControllerRefreshButton):
        return _object_id("cookie", "main", "station_refresh")
    if isinstance(ent, StationRefreshButton):
        return _object_id("cookie", ent._station_id, "station_refresh")
    return None


def _register_entity_ids(hass: HomeAssistant, entry: ConfigEntry, entities: list[ButtonEntity]) -> None:
    for ent in entities:
        object_id = _object_id_for_entity(ent)
        if object_id:
            _ensure_entity_id(hass, entry, ent.unique_id, object_id)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: SeoulPublicBikeCoordinator = hass.data[DOMAIN][entry.entry_id]

    opts = entry.options or {}
    use_week = bool(opts.get(CONF_USE_HISTORY_WEEK, DEFAULT_USE_HISTORY_WEEK))
    use_month = bool(opts.get(CONF_USE_HISTORY_MONTH, DEFAULT_USE_HISTORY_MONTH))
    if not (use_week or use_month):
        use_month = True

    entities: list[ButtonEntity] = []
    if use_week:
        entities.append(
            UseHistoryRefreshButton(coordinator, entry.entry_id, "use_history_week", DEVICE_NAME_USE_HISTORY_WEEK)
        )
    if use_month:
        entities.append(
            UseHistoryRefreshButton(coordinator, entry.entry_id, "use_history_month", DEVICE_NAME_USE_HISTORY_MONTH)
        )

    favs = (coordinator.data or {}).get("favorites") or []
    for f in favs:
        sid = f.get("station_id") or ""
        sname = f.get("station_name") or ""
        if not sid or not sname:
            continue
        entities.append(FavoriteStationRefreshButton(coordinator, entry.entry_id, sid, sname))

    station_ids = list(getattr(coordinator, "stations_by_id", {}) or {})
    if station_ids:
        entities.append(StationControllerRefreshButton(coordinator, entry.entry_id))
        for sid in station_ids:
            st = coordinator.stations_by_id.get(sid)
            station_name = _station_display_name(st, sid)
            entities.append(StationRefreshButton(coordinator, entry.entry_id, sid, station_name))

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

    def _uid_refresh(station_id: str) -> str:
        return f"{entry.entry_id}_fav_{station_id}_refresh"

    coordinator._spb_fav_station_ids_btn = _current_station_ids()  # type: ignore[attr-defined]

    def _current_station_ids_from_status() -> set[str]:
        stations = getattr(coordinator, "stations_by_id", {}) or {}
        return {str(sid).strip() for sid in stations.keys() if str(sid).strip()}

    def _station_name_from_status(station_id: str) -> str:
        station = (getattr(coordinator, "stations_by_id", {}) or {}).get(station_id)
        return _station_display_name(station, station_id)

    def _uid_station_refresh(station_id: str) -> str:
        return f"{entry.entry_id}_{station_id}_station_refresh"

    def _uid_station_refresh_all() -> str:
        return f"{entry.entry_id}_station_refresh_all"

    async def _async_sync_favorites() -> None:
        prev: set[str] = set(getattr(coordinator, "_spb_fav_station_ids_btn", set()))
        curr: set[str] = _current_station_ids()

        added = curr - prev
        removed = prev - curr

        new_entities: list[ButtonEntity] = []
        for sid in sorted(added):
            sname = _name_by_station_id(sid) or sid
            new_entities.append(FavoriteStationRefreshButton(coordinator, entry.entry_id, sid, sname))

        if new_entities:
            _register_entity_ids(hass, entry, new_entities)
            async_add_entities(new_entities)

        for sid in sorted(removed):
            uid = _uid_refresh(sid)
            entity_id = ent_reg.async_get_entity_id("button", DOMAIN, uid)
            if entity_id:
                await ent_reg.async_remove(entity_id)

        coordinator._spb_fav_station_ids_btn = curr  # type: ignore[attr-defined]

    async def _async_sync_stations() -> None:
        prev: set[str] = set(getattr(coordinator, "_spb_station_ids_btn", set()))
        curr: set[str] = _current_station_ids_from_status()

        added = curr - prev
        removed = prev - curr

        new_entities: list[ButtonEntity] = []
        if not prev and curr:
            new_entities.append(StationControllerRefreshButton(coordinator, entry.entry_id))

        for sid in sorted(added):
            sname = _station_name_from_status(sid)
            new_entities.append(StationRefreshButton(coordinator, entry.entry_id, sid, sname))

        if new_entities:
            _register_entity_ids(hass, entry, new_entities)
            async_add_entities(new_entities)

        if removed:
            for sid in sorted(removed):
                uid = _uid_station_refresh(sid)
                entity_id = ent_reg.async_get_entity_id("button", DOMAIN, uid)
                if entity_id:
                    await ent_reg.async_remove(entity_id)

        if prev and not curr:
            entity_id = ent_reg.async_get_entity_id("button", DOMAIN, _uid_station_refresh_all())
            if entity_id:
                await ent_reg.async_remove(entity_id)

        coordinator._spb_station_ids_btn = curr  # type: ignore[attr-defined]

    @callback
    def _on_coordinator_update() -> None:
        async def _sync_all() -> None:
            await _async_sync_favorites()
            await _async_sync_stations()

        hass.async_create_task(_sync_all())

    coordinator.async_add_listener(_on_coordinator_update)


class UseHistoryRefreshButton(CoordinatorEntity[SeoulPublicBikeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "새로 고침"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry_id: str, device_suffix: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = f"{entry_id}_{device_suffix}"
        self._device_name = device_name
        self._attr_unique_id = f"{entry_id}_{device_suffix}_refresh"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_USE_HISTORY,
        }

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class FavoriteStationRefreshButton(CoordinatorEntity[SeoulPublicBikeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "새로 고침"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry_id: str, station_id: str, station_name: str) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._device_id = f"{FAVORITE_DEVICE_PREFIX}_{entry_id}_{station_id}"
        self._attr_unique_id = f"{entry_id}_fav_{station_id}_refresh"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._station_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_FAVORITE_STATION,
        }

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class StationControllerRefreshButton(CoordinatorEntity[SeoulPublicBikeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "새로 고침"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_station_refresh_all"
        self._device_id = f"{entry_id}_stations"

    @property
    def device_info(self):
        username = str(self.coordinator.entry.data.get(CONF_COOKIE_USERNAME) or "").strip()
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": username or INTEGRATION_NAME,
            "manufacturer": MANUFACTURER,
            "model": MODEL_CONTROLLER,
        }

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class StationRefreshButton(CoordinatorEntity[SeoulPublicBikeCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "새로 고침"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SeoulPublicBikeCoordinator, entry_id: str, station_id: str, station_name: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._station_id = station_id
        self._station_name = station_name
        self._device_id = f"{entry_id}_station_{station_id}"
        self._attr_unique_id = f"{entry_id}_{station_id}_station_refresh"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._station_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL_STATION,
            "via_device": (DOMAIN, f"{self._entry_id}_stations"),
        }

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
