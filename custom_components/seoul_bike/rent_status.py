"""Normalize rental status fields returned by Seoul Bike endpoints."""

from __future__ import annotations

from typing import Any


def _first_text(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def normalize_rent_status(status: Any) -> dict[str, Any]:
    """Return a stable schema while retaining unrecognized source fields."""
    if not isinstance(status, dict):
        return {}

    normalized = dict(status)
    rent_yn = _first_text(status, "rentYn", "rentBikeYn", "rentalYn")
    station_name = _first_text(
        status,
        "stationName",
        "rentStationName",
        "rentStationNm",
    )
    bike_number = _first_text(
        status,
        "bikeNo",
        "rentBikeNo",
        "bikeNumber",
    )
    rent_datetime = _first_text(
        status,
        "rentDttm",
        "rentDateTime",
        "rentDt",
    )

    if rent_yn is not None:
        normalized["rentYn"] = rent_yn
        normalized["rentBikeYn"] = rent_yn
    if station_name is not None:
        normalized["stationName"] = station_name
        normalized["rentStationName"] = station_name
    if bike_number is not None:
        normalized["bikeNo"] = bike_number
        normalized["rentBikeNo"] = bike_number
    if rent_datetime is not None:
        normalized["rentDttm"] = rent_datetime

    return normalized
