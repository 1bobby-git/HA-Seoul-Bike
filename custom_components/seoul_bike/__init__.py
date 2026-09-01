from __future__ import annotations

import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_COOKIE,
    CONF_COOKIE_USERNAME,
    DEVICE_NAME_MY_PAGE,
    DEVICE_NAME_USE_HISTORY,
    DOMAIN,
    MANUFACTURER,
    MODEL_MY_PAGE,
    MODEL_USE_HISTORY,
)
from .runtime_coordinator import SeoulPublicBikeCoordinator

_LOGGER = logging.getLogger(__name__)
_RELOAD_FINGERPRINT_ATTR = "_seoul_bike_reload_fingerprint"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]


def _entry_reload_fingerprint(entry: ConfigEntry) -> str:
    """Ignore the rotating cookie but retain explicit credential revision changes."""
    data = {key: value for key, value in entry.data.items() if key != CONF_COOKIE}
    options = {
        key: value for key, value in entry.options.items() if key != CONF_COOKIE
    }
    return json.dumps(
        {"data": data, "options": options},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload for user configuration changes, not automatic cookie rotation."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    current = _entry_reload_fingerprint(entry)
    previous = getattr(coordinator, _RELOAD_FINGERPRINT_ATTR, None)
    if coordinator is not None:
        setattr(coordinator, _RELOAD_FINGERPRINT_ATTR, current)
    if previous == current:
        _LOGGER.debug("Skipped Seoul Bike reload after cookie-only update")
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Seoul Bike account."""
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    coordinator = SeoulPublicBikeCoordinator(hass, entry)
    setattr(
        coordinator,
        _RELOAD_FINGERPRINT_ATTR,
        _entry_reload_fingerprint(entry),
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except UpdateFailed as err:
        raise ConfigEntryNotReady(f"Seoul Bike refresh failed: {err}") from err

    data = coordinator.data or {}
    if data.get("error"):
        error_message = str(data.get("error"))
        validation_status = str(data.get("validation_status") or "")
        if validation_status == "login_page" or "로그인" in error_message:
            raise ConfigEntryAuthFailed("invalid_login")
        raise ConfigEntryNotReady(error_message)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    reauth_started = False

    @callback
    def _handle_auth_state() -> None:
        nonlocal reauth_started
        current_data = coordinator.data or {}
        validation_status = str(current_data.get("validation_status") or "")
        if validation_status == "login_page":
            if not reauth_started:
                reauth_started = True
                entry.async_start_reauth(hass)
            return
        if validation_status == "ok":
            reauth_started = False

    entry.async_on_unload(coordinator.async_add_listener(_handle_auth_state))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _cleanup_legacy_use_history_devices(hass, entry)
    _update_device_registry(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one Seoul Bike account."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


def _get_scoped_device(
    registry: dr.DeviceRegistry,
    entry: ConfigEntry,
    identifier: tuple[str, str],
):
    scoped_get = getattr(registry, "async_get_device_by_identifier", None)
    if callable(scoped_get):
        return scoped_get(identifier, entry.entry_id)
    legacy_get = getattr(registry, "async_get_device", None)
    if callable(legacy_get):
        return legacy_get({identifier})
    return None


def _update_device_registry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    device_registry = dr.async_get(hass)
    device = _get_scoped_device(
        device_registry,
        entry,
        (DOMAIN, f"{entry.entry_id}_use_history"),
    )
    if device:
        device_registry.async_update_device(
            device.id,
            name=DEVICE_NAME_USE_HISTORY,
            model=MODEL_USE_HISTORY,
            manufacturer=MANUFACTURER,
        )

    my_page_device = _get_scoped_device(
        device_registry,
        entry,
        (DOMAIN, f"{entry.entry_id}_my_page"),
    )
    if my_page_device:
        device_registry.async_update_device(
            my_page_device.id,
            name=DEVICE_NAME_MY_PAGE,
            model=MODEL_MY_PAGE,
            manufacturer=MANUFACTURER,
        )

    username = str(entry.data.get(CONF_COOKIE_USERNAME) or "").strip()
    controller_device = _get_scoped_device(
        device_registry,
        entry,
        (DOMAIN, f"{entry.entry_id}_stations"),
    )
    if controller_device and username:
        device_registry.async_update_device(
            controller_device.id,
            name=username,
        )


def _cleanup_legacy_use_history_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    for device_identifier in (
        f"{entry.entry_id}_use_history_week",
        f"{entry.entry_id}_use_history_month",
    ):
        device = _get_scoped_device(
            device_registry,
            entry,
            (DOMAIN, device_identifier),
        )
        if not device:
            continue
        for entity in list(entity_registry.entities.values()):
            if entity.config_entry_id != entry.entry_id:
                continue
            if entity.device_id == device.id:
                entity_registry.async_remove(entity.entity_id)
        device_registry.async_remove_device(device.id)
