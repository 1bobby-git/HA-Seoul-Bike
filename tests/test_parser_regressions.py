from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "custom_components" / "seoul_bike"


def _install_homeassistant_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")

    class _ConfigEntry:
        pass

    class _HomeAssistant:
        pass

    class _DataUpdateCoordinator:
        def __init__(self, *args, **kwargs):
            pass

        def __class_getitem__(cls, item):
            return cls

    class _UpdateFailed(Exception):
        pass

    config_entries.ConfigEntry = _ConfigEntry
    core.HomeAssistant = _HomeAssistant
    aiohttp_client.async_get_clientsession = lambda hass: None
    update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
    update_coordinator.UpdateFailed = _UpdateFailed
    dt.DEFAULT_TIME_ZONE = timezone.utc
    dt.as_utc = lambda value: value.astimezone(timezone.utc)
    util.dt = dt
    helpers.aiohttp_client = aiohttp_client
    helpers.update_coordinator = update_coordinator

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.config_entries", config_entries)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    sys.modules.setdefault("homeassistant.helpers.update_coordinator", update_coordinator)
    sys.modules.setdefault("homeassistant.util", util)
    sys.modules.setdefault("homeassistant.util.dt", dt)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_seoul_bike_modules():
    _install_homeassistant_stubs()

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.seoul_bike")
    package.__path__ = [str(PACKAGE_ROOT)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.seoul_bike", package)

    _load_module("custom_components.seoul_bike.const", PACKAGE_ROOT / "const.py")
    api = _load_module("custom_components.seoul_bike.api", PACKAGE_ROOT / "api.py")
    coordinator = _load_module("custom_components.seoul_bike.coordinator", PACKAGE_ROOT / "coordinator.py")
    return api, coordinator


api, coordinator = _load_seoul_bike_modules()


class ParserRegressionTests(unittest.TestCase):
    def test_favorites_counts_preserve_station_identity_and_counts(self) -> None:
        html = """
        <ul id="favoriteList">
          <li>
            <div class="place"><strong>3690. Gangil 4 Exit</strong></div>
            <div class="bike">general / sprout<p>11 / 0</p></div>
          </li>
          <li>
            <div class="place">102. City Hall</div>
            <div class="bike"><p>2 / 4</p></div>
          </li>
          <li>
            <div class="place"><strong>3690. Duplicate</strong></div>
            <div class="bike"><p>99 / 99</p></div>
          </li>
        </ul>
        """

        self.assertEqual(
            coordinator._extract_favorites_with_counts(html),
            [
                {
                    "station_id": "3690",
                    "station_name": "3690. Gangil 4 Exit",
                    "station_no": "3690",
                    "normal": 11,
                    "sprout": 0,
                },
                {
                    "station_id": "102",
                    "station_name": "102. City Hall",
                    "station_no": "102",
                    "normal": 2,
                    "sprout": 4,
                },
            ],
        )

    def test_use_history_combines_period_kcal_payment_history_and_last_row(self) -> None:
        html = """
        <input name="searchStartDate" value="2026.07.01">
        <input name="searchEndDate" value="2026.07.31">
        <div class="kcal_box">
          <img alt="distance"> 5.2 km
          <img alt="calorie"> 123 kcal
        </div>
        <div class="payment_box">
          <table>
            <tr><th>bike</th><th>rent</th><th>from</th><th>return</th><th>to</th><th>id</th><th>km</th></tr>
            <tr>
              <td>SPB-001</td><td>2026-07-31 08:00</td><td>3690. Gangil</td>
              <td>2026-07-31 08:12</td><td>102. City Hall</td><td>HIST-1</td><td>2.7 km</td>
            </tr>
          </table>
        </div>
        """

        parsed = coordinator._parse_use_history(html)

        self.assertEqual(parsed["period_start"], "2026-07-01")
        self.assertEqual(parsed["period_end"], "2026-07-31")
        self.assertEqual(parsed["kcal"], {"distance": "5.2 km", "calorie": "123 kcal"})
        self.assertEqual(parsed["history"][0]["bike"], "SPB-001")
        self.assertEqual(parsed["history"][0]["history_id"], "HIST-1")
        self.assertEqual(parsed["history"][0]["distance_km"], 2.7)
        self.assertEqual(parsed["last"], parsed["history"][0])

    def test_payment_history_falls_back_to_full_html_table(self) -> None:
        html = """
        <section>
          <table>
            <tr>
              <td>SPB-002</td><td>2026-08-01 09:00</td><td>Start</td>
              <td>2026-08-01 09:30</td><td>End</td><td>HIST-2</td><td>4</td>
            </tr>
          </table>
        </section>
        """

        self.assertEqual(
            coordinator._extract_payment_history(html),
            [
                {
                    "bike": "SPB-002",
                    "rent_datetime": "2026-08-01 09:00",
                    "rent_station": "Start",
                    "return_datetime": "2026-08-01 09:30",
                    "return_station": "End",
                    "history_id": "HIST-2",
                    "distance_km": 4.0,
                }
            ],
        )

    def test_login_page_detection_distinguishes_data_pages(self) -> None:
        self.assertTrue(
            coordinator._looks_like_login(
                '<form action="/j_spring_security_check"><input type="password" name="pw"></form>'
            )
        )
        self.assertFalse(coordinator._looks_like_login('<div class="kcal_box">authenticated data</div>'))
        self.assertFalse(coordinator._looks_like_login('<a href="/logout.do">logout</a>'))
        self.assertTrue(coordinator._looks_like_login(""))

    def test_station_list_trims_deduplicates_and_preserves_order(self) -> None:
        self.assertEqual(coordinator._parse_station_list(" ST-1, 102\nST-1\r103 "), ["ST-1", "102", "103"])
        self.assertEqual(coordinator._parse_station_list([" 102 ", "", "103", "102"]), ["102", "103"])

    def test_voucher_end_uses_first_parseable_realtime_key(self) -> None:
        realtime = [
            {"stationId": "ST-1", "voucherEndDttm": "null"},
            {"stationId": "ST-2", "ticketEndDttm": "2026.08.31 23:59"},
        ]

        self.assertEqual(coordinator._extract_voucher_end_from_realtime(realtime), "2026-08-31T23:59:00+00:00")

    def test_api_helpers_normalize_cookie_and_extract_login_form(self) -> None:
        self.assertEqual(api._normalize_cookie('Cookie: a=1; b=2\r\nAccept: text/html'), "a=1; b=2")

        client = api.SeoulPublicBikeSiteApi(session=object(), cookie="")
        action, inputs, user_field, pass_field = client._extract_login_form(
            """
            <form action="/j_spring_security_check">
              <input type="hidden" name="csrf" value="token">
              <input type="text" name="loginId" value="">
              <input type="password" name="loginPassword" value="">
            </form>
            """
        )

        self.assertEqual(action, "/j_spring_security_check")
        self.assertEqual(inputs["csrf"], "token")
        self.assertEqual(user_field, "loginId")
        self.assertEqual(pass_field, "loginPassword")


if __name__ == "__main__":
    unittest.main()
