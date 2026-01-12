# custom_components/seoul_bike/modes/api/coordinator.py

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SeoulBikeApi, SeoulBikeApiAuthError, SeoulBikeApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_STATION_NO_RE = re.compile(r"^\s*(\d+)\s*(?:[\.．\)\-]|번|\s)")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return r * c


@dataclass(slots=True)
class Station:
    station_id: str
    station_no: str
    station_title: str
    lat: float
    lon: float
    bikes_total: int
    bikes_general: int
    bikes_teen: int
    bikes_repair: int


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return float(default)


class SeoulBikeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api_key: str,
        update_interval_s: int = 60,
        **kwargs: Any,
    ) -> None:
        if "update_interval_seconds" in kwargs:
            try:
                update_interval_s = int(kwargs["update_interval_seconds"])
            except Exception:
                pass

        self.hass = hass
        self._api = SeoulBikeApi(async_get_clientsession(hass), str(api_key).strip())
        self.api = self._api

        # ✅ UI에서 안 받는 값들은 __init__/__init__.py에서 고정 주입
        self.location_entity_id: str = ""
        self.radius_m: int = 500
        self.max_results: int = 0   # 0 = 무제한
        self.min_bikes: int = 1     # 1로 고정

        self.center_source: str = "homeassistant_home"
        self.center_lat: float | None = None
        self.center_lon: float | None = None
        self.nearby_status: str = "unknown"
        self.nearby: list[dict[str, Any]] = []
        self.nearby_total_bikes: int = 0
        self.nearby_recommended_bikes: int = 0

        self.stations_by_id: dict[str, Station] = {}

        self.station_ids: list[str] = []
        self.configured_station_inputs: list[str] = []
        self.resolved_stations: list[dict[str, Any]] = []
        self.unresolved_stations: list[dict[str, Any]] = []

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=int(update_interval_s)),
        )

    def _compute_center(self) -> None:
        self.center_source = "homeassistant_home"
        self.center_lat = self.hass.config.latitude
        self.center_lon = self.hass.config.longitude

        ent_id = (self.location_entity_id or "").strip()
        if not ent_id:
            self.nearby_status = "ok"
            return

        st = self.hass.states.get(ent_id)
        if not st:
            self.nearby_status = "location_entity_not_found"
            return

        lat = st.attributes.get("latitude")
        lon = st.attributes.get("longitude")

        if lat is None or lon is None:
            self.nearby_status = "location_no_coords"
            return

        try:
            self.center_lat = float(lat)
            self.center_lon = float(lon)
            self.center_source = ent_id
            self.nearby_status = "ok"
        except Exception:
            self.nearby_status = "location_invalid_coords"

    def get_station_device_name(self, station_id: str) -> str:
        s = self.stations_by_id.get(station_id)
        if not s:
            return station_id
        if s.station_no:
            return f"{s.station_no} {s.station_title}".strip()
        return s.station_title or s.station_id

    def _row_to_station(self, r: dict[str, Any]) -> Station | None:
        sid = str(r.get("stationId", "")).strip()
        if not sid:
            return None

        raw_name = str(r.get("stationName", "")).strip()
        station_no = ""
        station_title = raw_name

        m = _STATION_NO_RE.match(raw_name)
        if m:
            station_no = m.group(1)
            station_title = raw_name[m.end() :].strip(" .-")

        lat = _to_float(r.get("stationLatitude"))
        lon = _to_float(r.get("stationLongitude"))

        bikes_total = _to_int(r.get("parkingBikeTotCnt"))
        bikes_general = _to_int(r.get("parkingBikeTotCntGeneral"), bikes_total)
        bikes_teen = _to_int(r.get("parkingBikeTotCntTeen"), 0)
        bikes_repair = _to_int(r.get("parkingBikeTotCntRepair"), 0)

        return Station(
            station_id=sid,
            station_no=station_no,
            station_title=station_title or raw_name,
            lat=lat,
            lon=lon,
            bikes_total=bikes_total,
            bikes_general=bikes_general,
            bikes_teen=bikes_teen,
            bikes_repair=bikes_repair,
        )

    def _compute_nearby(self) -> None:
        self._compute_center()

        self.nearby = []
        self.nearby_total_bikes = 0
        self.nearby_recommended_bikes = 0

        if self.center_lat is None or self.center_lon is None:
            return

        radius = max(1, int(self.radius_m or 500))
        min_bikes = 1  # ✅ 고정
        max_results = int(self.max_results or 0)  # ✅ 0이면 무제한

        candidates: list[dict[str, Any]] = []
        total = 0

        for s in self.stations_by_id.values():
            dist = haversine_m(self.center_lat, self.center_lon, s.lat, s.lon)
            if dist > radius:
                continue
            if s.bikes_total < min_bikes:
                continue

            total += s.bikes_total
            candidates.append(
                {
                    "station_id": s.station_id,
                    "station_no": s.station_no,
                    "station_name": f"{s.station_no} {s.station_title}".strip() if s.station_no else s.station_title,
                    "bikes_total": s.bikes_total,
                    "distance_m": round(dist, 1),
                }
            )

        candidates.sort(key=lambda x: (-int(x.get("bikes_total") or 0), float(x.get("distance_m") or 0.0)))

        self.nearby_total_bikes = total

        if max_results > 0:
            self.nearby = candidates[:max_results]
        else:
            self.nearby = candidates  # ✅ 무제한

        self.nearby_recommended_bikes = sum(int(x.get("bikes_total") or 0) for x in self.nearby)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            rows = await self._api.fetch_all(page_size=1000, max_pages=10, retries=2)
            if not isinstance(rows, list):
                raise UpdateFailed("API returned non-list rows")

            by_id: dict[str, dict[str, Any]] = {}
            stations_by_id: dict[str, Station] = {}
            nonzero_count = 0

            for r in rows:
                if not isinstance(r, dict):
                    continue

                sid = str(r.get("stationId", "")).strip()
                if not sid:
                    continue

                by_id[sid] = r

                st = self._row_to_station(r)
                if st:
                    stations_by_id[st.station_id] = st

                try:
                    if int(r.get("parkingBikeTotCnt") or 0) > 0:
                        nonzero_count += 1
                except Exception:
                    pass

            self.stations_by_id = stations_by_id
            self._compute_nearby()

            fetch_meta = self._api.last_meta or {}

            return {
                "rows": rows,
                "by_id": by_id,
                "total_rows": len(rows),
                "nonzero_station_count": nonzero_count,
                "fetch_meta": fetch_meta,
                "configured_station_inputs": list(self.configured_station_inputs),
                "resolved": list(self.resolved_stations),
                "unresolved": list(self.unresolved_stations),
                "nearby_count": len(self.nearby),
            }

        except SeoulBikeApiAuthError as err:
            raise UpdateFailed(f"auth_failed: {err}") from err
        except SeoulBikeApiError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(str(err)) from err
