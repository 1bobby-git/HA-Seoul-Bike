"""Validate favorite snapshots and reconcile only this account's favorites."""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from .const import DOMAIN, FAVORITE_DEVICE_PREFIX


class _FavoriteListParser(HTMLParser):
    """Distinguish a real empty list from a login/error/changed-markup page."""

    def __init__(self) -> None:
        super().__init__()
        self.found = False
        self.closed = False
        self.depth = 0
        self.tag = ""
        self.text: list[str] = []
        self.has_station_markup = False
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self.depth:
            if (attributes.get("id") or "").lower() != "favoritelist":
                return
            self.found = True
            self.tag = tag
            self.depth = 1
            return
        if tag == self.tag:
            self.depth += 1
        if tag in ("script", "style"):
            self.ignored += 1
        classes = (attributes.get("class") or "").split()
        onclick = attributes.get("onclick") or ""
        if "place" in classes or "delFavoriteFnc" in onclick or "moveRentalStation" in onclick:
            self.has_station_markup = True

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag in ("script", "style") and self.ignored:
            self.ignored -= 1
        if tag == self.tag:
            self.depth -= 1
            if not self.depth:
                self.closed = True

    def handle_data(self, data: str) -> None:
        if self.depth and not self.ignored and data.strip():
            self.text.append(data.strip())


def validate_favorites_html(html: str, favorites: list[dict[str, Any]]) -> None:
    """Raise instead of interpreting an unrecognized response as 'delete all'."""
    if favorites:
        return
    parser = _FavoriteListParser()
    parser.feed(html)
    parser.close()
    text = " ".join(parser.text).lower()
    known_empty = not text or any(
        marker in text
        for marker in ("없습니다", "없어요", "없음", "no favorites", "no stations")
    )
    if not parser.found or not parser.closed or parser.has_station_markup or not known_empty:
        raise ValueError("즐겨찾기 목록 응답을 확인할 수 없습니다. 기존 즐겨찾기를 유지합니다.")


def sync_favorite_registry(hass: Any, entry: Any, data: dict[str, Any]) -> None:
    """Remove stale favorite entities/devices, never unrelated or shared items.

    Called before platform setup too: a reload has no in-memory 'previous list',
    but the entity/device registries still contain favorites removed in the app.
    """
    if data.get("error") or data.get("validation_status") != "ok":
        return
    favorites = data.get("favorites")
    if not isinstance(favorites, list):
        return

    from homeassistant.helpers import device_registry as dr, entity_registry as er

    names = {
        str(item.get("station_id") or "").strip(): str(item.get("station_name") or "").strip()
        for item in favorites
        if isinstance(item, dict) and str(item.get("station_id") or "").strip()
    }
    if any(not isinstance(item, dict) or not str(item.get("station_id") or "").strip() for item in favorites):
        return
    entity_prefix = f"{entry.entry_id}_fav_"
    current_prefixes = tuple(f"{entity_prefix}{sid}_" for sid in names)
    entities = er.async_get(hass)
    for entity in list(entities.entities.values()):
        if entity.config_entry_id != entry.entry_id or entity.platform != DOMAIN:
            continue
        if not entity.unique_id.startswith(entity_prefix):
            continue
        if not entity.unique_id.startswith(current_prefixes):
            # Registry async_ methods are loop callbacks, not coroutines.
            entities.async_remove(entity.entity_id)

    devices = dr.async_get(hass)
    device_prefix = f"{FAVORITE_DEVICE_PREFIX}_{entry.entry_id}_"
    current_devices = {f"{device_prefix}{sid}": name for sid, name in names.items()}
    for device in list(devices.devices.values()):
        if entry.entry_id not in device.config_entries:
            continue
        identifiers = {
            identifier for domain, identifier in device.identifiers
            if domain == DOMAIN and identifier.startswith(device_prefix)
        }
        if not identifiers:
            continue
        current = identifiers & current_devices.keys()
        if current:
            name = current_devices[next(iter(current))]
            if name and device.name != name:
                devices.async_update_device(device.id, name=name)
            continue
        # Do not remove a device shared with another entry or another entity.
        if any(domain != DOMAIN or not identifier.startswith(device_prefix) for domain, identifier in device.identifiers):
            continue
        if set(device.config_entries) != {entry.entry_id}:
            continue
        if any(entity.device_id == device.id for entity in entities.entities.values()):
            continue
        devices.async_remove_device(device.id)
