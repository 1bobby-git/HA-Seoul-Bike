# custom_components/seoul_bike/modes/cookie/const.py

DOMAIN = "seoul_bike"

CONF_COOKIE = "cookie"
CONF_COOKIE_USERNAME = "cookie_username"
CONF_COOKIE_PASSWORD = "cookie_password"
CONF_COOKIE_UPDATE_INTERVAL = "cookie_update_interval_seconds"
CONF_STATION_IDS = "station_ids"
CONF_LOCATION_ENTITY = "location_entity"
CONF_RADIUS_M = "radius_m"
CONF_MAX_RESULTS = "max_results"
CONF_MIN_BIKES = "min_bikes"
DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS = 120
DEFAULT_RADIUS_M = 500
DEFAULT_MAX_RESULTS = 5
DEFAULT_MIN_BIKES = 1

MANUFACTURER = "@1bobby-git"
INTEGRATION_NAME = "따릉이 (비공식 API)"
DEVICE_NAME_ROOT = "따릉이"
MODEL_USE_HISTORY = "이용내역 (대여 반납 이력)"
MODEL_FAVORITE_STATION = "즐겨찾는 대여소"
MODEL_STATION = "대여소"
MODEL_CONTROLLER = "비공식 API"
MODEL_MY_PAGE = "마이페이지"

DEVICE_NAME_USE_HISTORY = "따릉이"
DEVICE_NAME_MY_PAGE = "따릉이"

# 즐겨찾는 대여소 기기 prefix
FAVORITE_DEVICE_PREFIX = "favorite_station"
