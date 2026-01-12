# custom_components/seoul_bike/modes/api/const.py

from __future__ import annotations

DOMAIN = "seoul_bike"
PLATFORMS: list[str] = ["sensor", "button"]

INTEGRATION_NAME = "따릉이 (Seoul Bike)"
DEFAULT_NAME = INTEGRATION_NAME

# URLs (UI 안내용)
OPEN_DATA_URL = "https://data.seoul.go.kr/dataList/OA-15493/A/1/datasetView.do"
OPEN_API_KEY_URL = "https://data.seoul.go.kr/together/mypage/actkeyMng_ss.do"

# Defaults
DEFAULT_UPDATE_INTERVAL_SECONDS = 60
DEFAULT_RADIUS_M = 500
DEFAULT_MAX_RESULTS = 5
DEFAULT_MIN_BIKES = 1

# Config keys
CONF_API_KEY = "api_key"
CONF_STATION_IDS = "station_ids"
CONF_LOCATION_ENTITY = "location_entity"
CONF_RADIUS_M = "radius_m"
CONF_MAX_RESULTS = "max_results"
CONF_MIN_BIKES = "min_bikes"
CONF_UPDATE_INTERVAL = "update_interval_seconds"

# Device info
MANUFACTURER = "@1bobby-git"
MODEL_CONTROLLER = "Open API"
MODEL_STATION = "대여소"
