# /config/custom_components/seoul_bike/device.py
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def controller_device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="따릉이(API)",
        manufacturer="@1bobby-git",
        model="Seoul Bike API",
        sw_version="1.0",
    )


def station_device_info(entry_id: str, station_id: str, name: str, hw_version: str | None = None) -> DeviceInfo:
    info = DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}:{station_id}")},
        name=name,
        manufacturer="@1bobby-git",
        model="Seoul Bike Station",
        via_device=(DOMAIN, entry_id),
        sw_version="1.0",
    )
    if hw_version:
        info["hw_version"] = hw_version
    return info
