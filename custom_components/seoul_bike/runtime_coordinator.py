"""Runtime coordinator extensions for stable Seoul Bike payload semantics."""

from __future__ import annotations

from typing import Any

from .coordinator import SeoulPublicBikeCoordinator as BaseCoordinator
from .rent_status import normalize_rent_status


class SeoulPublicBikeCoordinator(BaseCoordinator):
    """Normalize endpoint variants before entities and change detection consume them."""

    @staticmethod
    def _make_rent_key(rent_status: dict[str, Any]) -> str:
        normalized = normalize_rent_status(rent_status)
        if not normalized:
            return ""
        return "|".join(
            (
                str(normalized.get("rentYn") or ""),
                str(normalized.get("rentDttm") or ""),
                str(normalized.get("stationName") or ""),
                str(normalized.get("bikeNo") or ""),
            )
        )

    async def _ensure_login(self) -> tuple[bool | None, dict[str, Any]]:
        login_ok, rent_status = await super()._ensure_login()
        return login_ok, normalize_rent_status(rent_status)

    async def _async_update_data(self) -> dict[str, Any]:
        data = await super()._async_update_data()
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        normalized["rent_status"] = normalize_rent_status(
            normalized.get("rent_status")
        )
        return normalized
