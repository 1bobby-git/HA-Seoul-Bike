# custom_components/seoul_bike/modes/cookie/const.py

DOMAIN = "seoul_bike"

CONF_COOKIE = "cookie"
CONF_COOKIE_USERNAME = "cookie_username"
CONF_COOKIE_PASSWORD = "cookie_password"
CONF_USE_HISTORY_WEEK = "use_history_week"
CONF_USE_HISTORY_MONTH = "use_history_month"
CONF_COOKIE_UPDATE_INTERVAL = "cookie_update_interval_seconds"
CONF_STATION_IDS = "station_ids"
CONF_LOCATION_ENTITY = "location_entity"
CONF_RADIUS_M = "radius_m"
CONF_MAX_RESULTS = "max_results"
CONF_MIN_BIKES = "min_bikes"
DEFAULT_USE_HISTORY_WEEK = True
DEFAULT_USE_HISTORY_MONTH = True
DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS = 120
DEFAULT_RADIUS_M = 500
DEFAULT_MAX_RESULTS = 5
DEFAULT_MIN_BIKES = 1

MANUFACTURER = "@1bobby-git"
INTEGRATION_NAME = "따릉이 (비공식 API)"
MODEL_USE_HISTORY = "이용 내역"
MODEL_FAVORITE_STATION = "즐겨찾는 대여소"
MODEL_STATION = "대여소"
MODEL_CONTROLLER = "비공식 API"

DEVICE_NAME_USE_HISTORY_WEEK = "이용 내역 (1주일)"
DEVICE_NAME_USE_HISTORY_MONTH = "이용 내역 (1개월)"

# 즐겨찾는 대여소 기기 prefix
FAVORITE_DEVICE_PREFIX = "favorite_station"
