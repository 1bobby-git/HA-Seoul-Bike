"""1.4.0 regressions: sessions, login failures, preserved favorites, nearby sensors.

Fixtures are synthetic; no test contacts a real Seoul Bike account.
"""
from __future__ import annotations

import ast
import importlib
import json
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from test_parser_regressions import api, coordinator

runtime = importlib.import_module("custom_components.seoul_bike.runtime_coordinator")
const = importlib.import_module("custom_components.seoul_bike.const")
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "seoul_bike"

LOGIN_HTML = '<form action="/j_spring_security_check"><input type="password"></form>'
HISTORY_HTML = '<div class="kcal_box"></div>'
OK_STATUS = {"loginYn": "Y", "memberYn": "Y", "rentYn": "N"}


def favorite_html(number: str = "101", name: str = "City Hall") -> str:
    return (f'<ul id="favoriteList"><li><div class="place"><strong>{number}. {name}'
            '</strong></div><div class="bike"><p>3 / 1</p></div></li></ul>')


def make_coordinator(*, options=None, data=None, rent=None):
    hass = types.SimpleNamespace(
        config=types.SimpleNamespace(latitude=37.5, longitude=127.0),
        states=types.SimpleNamespace(get=lambda entity_id: None),
        config_entries=types.SimpleNamespace(async_update_entry=Mock()),
    )
    entry = types.SimpleNamespace(
        entry_id="account",
        data={"cookie": "session", "cookie_username": "user", "cookie_password": "pw", **(data or {})},
        options=dict(options or {}),
    )
    instance = runtime.SeoulPublicBikeCoordinator(hass, entry)
    instance.data = {}
    instance._api = types.SimpleNamespace(
        set_cookie=Mock(), last_meta=None, last_error=None,
        fetch_rent_status=AsyncMock(return_value=dict(rent or OK_STATUS)),
        fetch_user_status=AsyncMock(return_value={}),
        fetch_reconsent_status=AsyncMock(return_value={}),
        fetch_use_history_html=AsyncMock(return_value=HISTORY_HTML),
        fetch_favorites_html=AsyncMock(return_value=favorite_html()),
        fetch_station_realtime_all=AsyncMock(return_value=[]),
        fetch_voucher_info=AsyncMock(return_value={"voucherEndDttm": "2027-01-01 00:00"}),
        fetch_left_page_html=AsyncMock(return_value="2027-01-01 10:00"),
        login=AsyncMock(return_value="fresh=1"),
    )

    async def refresh():
        instance.data = await instance._async_update_data()

    instance.async_refresh = refresh
    return instance


class TierTwoLoginPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_page_in_use_history_keeps_favorites_for_later_polls(self) -> None:
        c = make_coordinator()
        await c.async_refresh()
        favorite_status = c.data["favorite_status"]

        c._api.fetch_use_history_html.return_value = LOGIN_HTML
        await c.async_refresh_web()
        self.assertEqual("login_page", c.data["validation_status"])
        self.assertEqual("101", c.data["favorites"][0]["station_id"])
        self.assertEqual(favorite_status, c.data["favorite_status"])

        # The next poll skips Tier 2 and must not publish an empty favorite list.
        c._api.fetch_use_history_html.return_value = HISTORY_HTML
        c._last_tier2_update = time.monotonic()
        await c.async_refresh()
        self.assertEqual("ok", c.data["validation_status"])
        self.assertEqual("101", c.data["favorites"][0]["station_id"])


class ReloginTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_password_is_tried_only_once(self) -> None:
        c = make_coordinator(rent={"loginYn": "N"})
        c._api.login.side_effect = ValueError("login_failed")

        for _ in range(3):
            await c.async_refresh()

        c._api.login.assert_awaited_once()
        self.assertEqual("login_page", c.data["validation_status"])

    async def test_connection_error_during_relogin_is_not_a_rejection(self) -> None:
        c = make_coordinator()
        await c.async_refresh()
        c._api.fetch_rent_status.return_value = {"loginYn": "N"}
        c._api.login.side_effect = ConnectionResetError("reset")

        await c.async_refresh()

        self.assertEqual("error", c.data["validation_status"])
        self.assertNotIn("로그인", c.data["error"])
        self.assertEqual("101", c.data["favorites"][0]["station_id"])
        await c.async_refresh()
        self.assertEqual(2, c._api.login.await_count)

    async def test_relogin_updates_a_legacy_options_cookie(self) -> None:
        c = make_coordinator(options={"cookie": "old"})
        c._api.fetch_rent_status.side_effect = [{"loginYn": "N"}, dict(OK_STATUS), dict(OK_STATUS)]

        await c.async_refresh()

        kwargs = c.hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual("fresh=1", kwargs["data"]["cookie"])
        self.assertEqual("fresh=1", kwargs["options"]["cookie"])
        self.assertEqual("ok", c.data["validation_status"])

    async def test_rent_status_redirected_to_login_triggers_relogin(self) -> None:
        c = make_coordinator()
        calls = 0

        async def rent_status():
            nonlocal calls
            calls += 1
            if calls == 1:
                c._api.last_meta = {"url": "https://www.bikeseoul.com/login.do", "status": 200}
                raise ValueError("non_json_response")
            return dict(OK_STATUS)

        c._api.fetch_rent_status = AsyncMock(side_effect=rent_status)

        await c.async_refresh()

        c._api.login.assert_awaited_once()
        self.assertEqual("ok", c.data["validation_status"])

    async def test_button_relogin_errors_are_temporary(self) -> None:
        c = make_coordinator(rent={"loginYn": "N"})
        c._api.login.side_effect = TimeoutError()

        login_ok, _status = await c._ensure_login()
        self.assertIs(False, login_ok)
        self.assertEqual("error", c.validation_status)
        await c._ensure_login()
        self.assertEqual(2, c._api.login.await_count)

    async def test_button_refresh_respects_a_rejected_password(self) -> None:
        c = make_coordinator(rent={"loginYn": "N"})
        c._api.login.side_effect = ValueError("login_failed")

        await c._ensure_login()
        await c._ensure_login()

        c._api.login.assert_awaited_once()
        self.assertEqual("login_page", c.validation_status)


class TemporaryPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_use_history_is_a_temporary_error(self) -> None:
        c = make_coordinator()
        await c.async_refresh()
        c._api.fetch_use_history_html.return_value = ""

        with self.assertRaises(coordinator.UpdateFailed):
            await c.async_refresh_web()

        self.assertEqual("error", c.validation_status)

    async def test_left_page_failure_keeps_the_previous_ticket_expiry(self) -> None:
        c = make_coordinator()
        c._api.fetch_voucher_info.return_value = {}
        await c.async_refresh()
        expiry = c.data["ticket_expiry"]
        self.assertTrue(expiry)

        c._api.fetch_left_page_html.side_effect = ConnectionResetError("reset")
        await c.async_refresh_web()

        self.assertEqual(expiry, c.data["ticket_expiry"])
        self.assertEqual("ok", c.data["validation_status"])


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_entry_gets_its_own_cookie_jar(self) -> None:
        def create(_hass, **kwargs):
            return types.SimpleNamespace(cookie_jar=kwargs["cookie_jar"])

        hass = types.SimpleNamespace(config=None, states=None)
        with patch.object(coordinator, "async_create_clientsession", Mock(side_effect=create)) as factory:
            first = runtime.SeoulPublicBikeCoordinator(
                hass, types.SimpleNamespace(entry_id="a", data={"cookie": "a=1"}, options={})
            )
            second = runtime.SeoulPublicBikeCoordinator(
                hass, types.SimpleNamespace(entry_id="b", data={"cookie": "b=1"}, options={})
            )

        self.assertEqual(2, factory.call_count)
        jar_a = factory.call_args_list[0].kwargs["cookie_jar"]
        jar_b = factory.call_args_list[1].kwargs["cookie_jar"]
        self.assertIsNot(jar_a, jar_b)
        self.assertEqual("CookieJar", type(jar_a).__name__)
        self.assertIs(jar_a, first._api._session.cookie_jar)
        self.assertIs(jar_b, second._api._session.cookie_jar)

    def test_cookie_header_reads_the_jar_with_a_url(self) -> None:
        jar = types.SimpleNamespace(
            filter_cookies=Mock(return_value={"A": types.SimpleNamespace(value="1")})
        )
        client = api.SeoulPublicBikeSiteApi(types.SimpleNamespace(cookie_jar=jar), "")

        self.assertEqual("A=1", client._cookie_header_from_session())
        self.assertEqual("URL", type(jar.filter_cookies.call_args.args[0]).__name__)


class NearbyTests(unittest.IsolatedAsyncioTestCase):
    async def test_nearby_sensors_follow_a_location_entity_or_legacy_stations(self) -> None:
        with_location = make_coordinator(data={"location_entity": "person.me"})
        plain = make_coordinator()
        legacy = make_coordinator(options={const.CONF_STATION_IDS: ["ST-1"]})
        for instance in (with_location, plain, legacy):
            await instance.async_refresh()

        self.assertTrue(with_location.nearby_enabled)
        self.assertFalse(plain.nearby_enabled)
        self.assertTrue(legacy.nearby_enabled)

    def test_sensor_platform_creates_and_removes_nearby_sensors_by_nearby_enabled(self) -> None:
        tree = ast.parse((PACKAGE / "sensor.py").read_text(encoding="utf-8"))
        functions = {
            node.name: ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("nearby_enabled", functions["async_setup_entry"])
        self.assertIn("nearby_enabled", functions["_async_sync_stations"])
        self.assertNotIn("if not prev and curr", functions["_async_sync_stations"])


class PlatformContractTests(unittest.TestCase):
    def test_registry_removals_are_never_awaited(self) -> None:
        for filename in ("sensor.py", "button.py", "binary_sensor.py", "__init__.py", "favorites.py"):
            tree = ast.parse((PACKAGE / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                    function = node.value.func
                    with self.subTest(filename=filename, line=node.lineno):
                        self.assertFalse(
                            isinstance(function, ast.Attribute)
                            and function.attr == "async_remove"
                            and isinstance(function.value, ast.Name)
                            and "reg" in function.value.id
                        )

    def test_route_coordinates_are_not_recorded(self) -> None:
        tree = ast.parse((PACKAGE / "sensor.py").read_text(encoding="utf-8"))
        sensor = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "MoveRouteDistanceSensor"
        )
        assignments = [
            ast.unparse(item) for item in sensor.body
            if isinstance(item, ast.Assign)
            and any(getattr(t, "id", "") == "_unrecorded_attributes" for t in item.targets)
        ]
        self.assertTrue(assignments)
        self.assertIn("경로 좌표", assignments[0])


class ConfigFlowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def _schema_keys(self, constant: str) -> list[ast.Call]:
        return [
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("Required", "Optional")
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == constant
        ]

    def test_password_is_never_sent_to_the_form(self) -> None:
        keys = self._schema_keys("CONF_COOKIE_PASSWORD")
        self.assertTrue(keys)
        for key in keys:
            self.assertNotIn("default", {keyword.arg for keyword in key.keywords})

    def test_location_can_be_cleared(self) -> None:
        keys = self._schema_keys("CONF_LOCATION_ENTITY")
        self.assertTrue(keys)
        for key in keys:
            self.assertNotIn("default", {keyword.arg for keyword in key.keywords})
        self.assertIn("suggested_value", self.source)

    def test_blank_password_keeps_the_stored_password(self) -> None:
        self.assertEqual("stored", const.entered_or_stored_password("", "stored"))
        self.assertEqual("stored", const.entered_or_stored_password("  ", "stored"))
        self.assertEqual("new", const.entered_or_stored_password(" new ", "stored"))
        self.assertEqual("", const.entered_or_stored_password(None, None))
        self.assertIn("entered_or_stored_password", self.source)

    def test_reauth_reloads_only_an_entry_that_is_not_loaded(self) -> None:
        self.assertIn("ConfigEntryState.LOADED", self.source)

    def test_reauth_abort_reasons_are_translated(self) -> None:
        for path in (
            PACKAGE / "strings.json",
            PACKAGE / "translations" / "en.json",
            PACKAGE / "translations" / "ko.json",
        ):
            with self.subTest(path=path.name):
                abort = json.loads(path.read_text(encoding="utf-8"))["config"]["abort"]
                self.assertIn("reauth_successful", abort)
                self.assertIn("reauth_failed", abort)


if __name__ == "__main__":
    unittest.main()
