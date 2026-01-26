# custom_components/seoul_bike/const.py

from typing import Final

DOMAIN: Final = "seoul_bike"

# ----------------------------
# API URLs and Paths
# ----------------------------
BIKESEOUL_BASE_URL: Final = "https://www.bikeseoul.com"

# API endpoints
API_PATH_LOGIN: Final = "/login.do"
API_PATH_RENT_STATUS: Final = "/app/rentCheck/isChkRentStatus.do"
API_PATH_RENT_STATUS_ALT: Final = "/app/rent/isChkRentStatus.do"
API_PATH_USER_STATUS: Final = "/app/rent/chkUserSataus.do"
API_PATH_RECONSENT: Final = "/checkReconsentAjax.do"
API_PATH_USE_HISTORY: Final = "/app/mybike/getMemberUseHistory.do"
API_PATH_MOVE_ROUTE: Final = "/app/mybike/getHistoryMoveRoute.do"
API_PATH_VOUCHER_INFO: Final = "/app/mybike/coupon/validChkVoucherAjax.do"
API_PATH_LEFT_PAGE: Final = "/myLeftPage.do"
API_PATH_FAVORITES: Final = "/app/mybike/favoriteStation.do"
API_PATH_STATION_REALTIME: Final = "/app/station/moveStationRealtimeStatus.do"
API_PATH_STATION_REALTIME_ALL: Final = "/app/station/getStationRealtimeStatus.do"

# ----------------------------
# Timing constants (seconds)
# ----------------------------
DEFAULT_SCAN_INTERVAL_SECONDS: Final = 60

# 3-Tier 업데이트 전략 간격
TIER2_INTERVAL_SECONDS: Final = 300     # 5분 - 이용내역, 즐겨찾기
TIER3_INTERVAL_SECONDS: Final = 1800    # 30분 - 이용권, 사용자 상태

CONF_COOKIE = "cookie"
CONF_COOKIE_USERNAME = "cookie_username"
CONF_COOKIE_PASSWORD = "cookie_password"
CONF_COOKIE_UPDATE_INTERVAL = "cookie_update_interval_seconds"
CONF_STATION_IDS = "station_ids"
CONF_LOCATION_ENTITY = "location_entity"
CONF_RADIUS_M = "radius_m"
CONF_MAX_RESULTS = "max_results"
CONF_MIN_BIKES = "min_bikes"
DEFAULT_COOKIE_UPDATE_INTERVAL_SECONDS = 60
DEFAULT_RADIUS_M = 500
DEFAULT_MAX_RESULTS = 5
DEFAULT_MIN_BIKES = 1

MANUFACTURER = "@1bobby-git"
INTEGRATION_NAME = "따릉이 (비공식 API)"
DEVICE_NAME_ROOT = "따릉이"
MODEL_USE_HISTORY = "따릉이"
MODEL_FAVORITE_STATION = "즐겨찾는 대여소"
MODEL_STATION = "대여소"
MODEL_CONTROLLER = "비공식 API"
MODEL_MY_PAGE = "따릉이"

DEVICE_NAME_USE_HISTORY = "이용내역 (대여 반납 이력)"
DEVICE_NAME_MY_PAGE = "마이페이지"

# 즐겨찾는 대여소 기기 prefix
FAVORITE_DEVICE_PREFIX: Final = "favorite_station"


# ----------------------------
# Common Utility Functions
# ----------------------------
def make_object_id(mode: str, identifier: str, name: str) -> str:
    """Generate a slugified object_id for entity registration."""
    from homeassistant.util import slugify
    return slugify(f"seoul_bike_{mode}_{identifier}_{name}")


def station_display_name(station: object | None, fallback: str) -> str:
    """Format station display name from station object."""
    if not station:
        return fallback
    station_no = str(getattr(station, "station_no", "") or "").strip()
    title = str(getattr(station, "station_title", "") or "").strip()
    if station_no and title:
        return f"{station_no}. {title}"
    return title or station_no or fallback
