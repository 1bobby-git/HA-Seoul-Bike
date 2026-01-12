# custom_components/seoul_bike/modes/api/__init__.py

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_API_KEY,
    CONF_STATION_IDS,
    CONF_LOCATION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DEFAULT_RADIUS_M,
    INTEGRATION_NAME,
    MANUFACTURER,
    MODEL_CONTROLLER,
    MODEL_STATION,
)
from .coordinator import SeoulBikeCoordinator

try:
    from .device import resolve_location_device_name
except Exception:  # pragma: no cover - runtime fallback
    def resolve_location_device_name(hass, location_entity_id: str) -> str | None:
        return None


_STATION_NO_RE = re.compile(r"^\s*(\d+)\s*(?:[\.．\)\-]|번|\s)")


def _normalize_station_input(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for v in value:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                out.append(s)
        return out

    raw = str(value).strip()
    if not raw:
        return []

    items: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        s = chunk.strip()
        if s:
            items.append(s)
    return items


def _collect_station_inputs(entry: ConfigEntry) -> list[str]:
    data = entry.data or {}
    opts = entry.options or {}

    def _dedup(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for v in values:
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    if CONF_STATION_IDS in opts:
        return _dedup(_normalize_station_input(opts.get(CONF_STATION_IDS)))

    if CONF_STATION_IDS in data:
        return _dedup(_normalize_station_input(data.get(CONF_STATION_IDS)))

    candidates: list[Any] = []
    for k in (
        "station_list",
        "station_list_raw",
        "stations",
        "station_tokens",
        "station_tokens_old",
        "station_ids_old",
        "station_id",
    ):
        if k in opts:
            candidates.append(opts.get(k))
        if k in data:
            candidates.append(data.get(k))

    merged: list[str] = []
    seen = set()

    for c in candidates:
        for s in _normalize_station_input(c):
            if s not in seen:
                seen.add(s)
                merged.append(s)

    return merged


def _resolve_station_inputs(inputs: list[str], rows: list[dict[str, Any]]):
    num_map: dict[str, list[str]] = {}
    id_set = set()

    for r in rows:
        sid = str(r.get("stationId", "")).strip()
        if sid:
            id_set.add(sid)

        name = str(r.get("stationName", "")).strip()
        m = _STATION_NO_RE.match(name)
        if m and sid:
            num = m.group(1)
            num_map.setdefault(num, [])
            if sid not in num_map[num]:
                num_map[num].append(sid)

    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for raw in inputs:
        v = str(raw).strip()
        if not v:
            continue

        if v.upper().startswith("ST-"):
            if v in id_set:
                resolved.append({"input": v, "station_id": v, "method": "station_id"})
            else:
                unresolved.append({"input": v, "reason": "station_id_not_found"})
            continue

        if v.isdigit():
            candidates = num_map.get(v, [])
            if len(candidates) == 1:
                resolved.append({"input": v, "station_id": candidates[0], "method": "station_number"})
            elif len(candidates) > 1:
                unresolved.append({"input": v, "reason": "ambiguous", "candidates": candidates})
            else:
                unresolved.append({"input": v, "reason": "number_not_found"})
            continue

        unresolved.append({"input": v, "reason": "invalid_format"})

    return resolved, unresolved


def _make_coordinator(hass: HomeAssistant, api_key: str, interval_s: int) -> SeoulBikeCoordinator:
    try:
        return SeoulBikeCoordinator(hass, api_key, update_interval_seconds=interval_s)
    except TypeError:
        pass

    try:
        return SeoulBikeCoordinator(hass, api_key, update_interval_s=interval_s)
    except TypeError:
        pass

    return SeoulBikeCoordinator(hass, api_key, interval_s)


def _cleanup_removed_station_entities(hass: HomeAssistant, entry: ConfigEntry, keep_station_ids: set[str]) -> None:
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    prefix = f"{entry.entry_id}_"
    keep_upper = {sid.upper() for sid in keep_station_ids}
    removed_device_ids: set[str] = set()
    main_device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    main_device_id = main_device.id if main_device else None

    def _extract_station_id(ident: str) -> str | None:
        if ident.startswith(f"{entry.entry_id}:"):
            return ident.split(":", 1)[1]
        if ident.startswith(f"{entry.entry_id}_"):
            return ident.split("_", 1)[1]
        m = re.search(r"(ST-\d+)", ident, re.IGNORECASE)
        if m:
            return m.group(1)
        if ident[:1].isdigit() and ident.replace(" ", "").isdigit():
            return ident
        return None

    for ent in list(ent_reg.entities.values()):
        if ent.config_entry_id != entry.entry_id:
            continue

        uid = ent.unique_id or ""
        if not uid.startswith(prefix):
            continue

        rest = uid[len(prefix) :]
        rest_upper = rest.upper()
        if not (rest_upper.startswith("ST-") or (rest and rest[0].isdigit())):
            continue

        station_id = rest.split("_", 1)[0].strip()
        if station_id and station_id.upper() not in keep_upper:
            if ent.device_id:
                removed_device_ids.add(ent.device_id)
            ent_reg.async_remove(ent.entity_id)

    for device in list(dev_reg.devices.values()):
        if device.config_entries and entry.entry_id not in device.config_entries:
            continue
        ids = device.identifiers or set()
        for (dom, ident) in ids:
            if dom != DOMAIN:
                continue
            if not isinstance(ident, str):
                continue

            sid = _extract_station_id(ident)

            if sid and sid.upper() not in keep_upper:
                dev_reg.async_remove_device(device.id)
                removed_device_ids.discard(device.id)
                break
        else:
            if main_device_id and device.via_device_id == main_device_id:
                name = (device.name_by_user or device.name or "").strip()
                name_sid = None
                m = re.search(r"(ST-\d+)", name, re.IGNORECASE)
                if m:
                    name_sid = m.group(1)
                elif name and name.split()[0].isdigit():
                    name_sid = name.split()[0]

                if (name_sid and name_sid.upper() not in keep_upper) or (not name_sid and not keep_upper):
                    dev_reg.async_remove_device(device.id)
                    removed_device_ids.discard(device.id)

    if removed_device_ids:
        active_device_ids = {ent.device_id for ent in ent_reg.entities.values() if ent.device_id}
        for device_id in removed_device_ids:
            if device_id in active_device_ids:
                continue
            device = dev_reg.devices.get(device_id)
            if not device:
                continue
            if (DOMAIN, entry.entry_id) in (device.identifiers or set()):
                continue
            dev_reg.async_remove_device(device_id)


def _update_device_registry(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: SeoulBikeCoordinator
) -> None:
    dev_reg = dr.async_get(hass)
    desired_name = resolve_location_device_name(hass, coordinator.location_entity_id) or INTEGRATION_NAME

    main_device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if main_device:
        dev_reg.async_update_device(
            main_device.id,
            name=desired_name,
            model=MODEL_CONTROLLER,
            manufacturer=MANUFACTURER,
        )

    for station_id in coordinator.station_ids:
        station_device = dev_reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}:{station_id}")})
        if station_device:
            dev_reg.async_update_device(
                station_device.id,
                name=coordinator.get_station_device_name(station_id),
                model=MODEL_STATION,
                manufacturer=MANUFACTURER,
            )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _read_int_any(entry: ConfigEntry, key: str, default: int) -> int:
    opts = entry.options or {}
    data = entry.data or {}
    try:
        if key in opts and opts.get(key) is not None:
            return int(opts.get(key))
    except Exception:
        pass
    try:
        if key in data and data.get(key) is not None:
            return int(data.get(key))
    except Exception:
        pass
    return int(default)


def _read_str_any(entry: ConfigEntry, key: str, default: str = "") -> str:
    opts = entry.options or {}
    data = entry.data or {}
    v = opts.get(key)
    if v is None or str(v).strip() == "":
        v = data.get(key)
    return str(v or default).strip()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api_key = _read_str_any(entry, CONF_API_KEY, "")

    # ✅ UI에서 남긴 업데이트 주기 반영(옵션 우선, 없으면 최초 data)
    interval_s = _read_int_any(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS)

    coordinator = _make_coordinator(hass, api_key, interval_s)

    # ✅ 내 위치 엔티티도 옵션 우선, 없으면 최초 data
    coordinator.location_entity_id = _read_str_any(entry, CONF_LOCATION_ENTITY, "")

    # ✅ 고정값(숨김): 반경 500m, 최소 자전거 1, 최대목록 무제한
    coordinator.radius_m = int(DEFAULT_RADIUS_M)
    coordinator.min_bikes = 1
    coordinator.max_results = 0  # 0 = 무제한

    inputs = _collect_station_inputs(entry)
    coordinator.configured_station_inputs = inputs

    await coordinator.async_config_entry_first_refresh()
    rows = (coordinator.data or {}).get("rows") or []
    resolved, unresolved = _resolve_station_inputs(inputs, rows)
    station_ids = [r["station_id"] for r in resolved]

    coordinator.station_ids = station_ids
    coordinator.resolved_stations = resolved
    coordinator.unresolved_stations = unresolved
    coordinator.configured_station_inputs = inputs

    if coordinator.data is not None:
        coordinator.data["configured_station_inputs"] = inputs
        coordinator.data["resolved"] = resolved
        coordinator.data["unresolved"] = unresolved

    _cleanup_removed_station_entities(hass, entry, set(station_ids))
    _update_device_registry(hass, entry, coordinator)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
