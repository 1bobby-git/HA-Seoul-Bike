"""1.4.0 regressions: sessions, login failures, preserved favorites, nearby sensors.

Fixtures are synthetic; no test contacts a real Seoul Bike account.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

# Import the real aiohttp first so the shared stubs never replace it; the
# real-socket tests below need it.
import aiohttp
from aiohttp import web

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
                raise ValueError("non_json_response")
            return dict(OK_STATUS)

        c._api.fetch_rent_status = AsyncMock(side_effect=rent_status)
        c._api.rent_status_redirected_to_login = Mock(return_value=True)

        await c.async_refresh()

        c._api.login.assert_awaited_once()
        self.assertEqual("ok", c.data["validation_status"])

    async def test_non_json_rent_status_without_redirect_stays_temporary(self) -> None:
        c = make_coordinator()
        await c.async_refresh()
        c._api.fetch_rent_status = AsyncMock(side_effect=ValueError("non_json_response"))
        c._api.rent_status_redirected_to_login = Mock(return_value=False)

        await c.async_refresh()

        c._api.login.assert_not_awaited()
        self.assertNotEqual("login_page", c.data["validation_status"])

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

    async def test_empty_use_history_from_the_button_is_not_a_sign_out(self) -> None:
        c = make_coordinator()
        await c.async_refresh()
        before = c.data
        c._api.fetch_use_history_html.return_value = ""
        c.async_set_updated_data = Mock()

        await c.async_refresh_use_history("history")

        self.assertEqual("error", c.validation_status)
        c.async_set_updated_data.assert_not_called()
        self.assertIs(before, c.data)

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
        self.assertIsInstance(jar_a, coordinator.aiohttp.CookieJar)
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

    @staticmethod
    def _locate(instance, state: str = "home", **attributes) -> None:
        located = types.SimpleNamespace(state=state, attributes=attributes)
        instance.hass.states = types.SimpleNamespace(
            get=lambda entity_id: located if entity_id == "person.me" else None
        )

    async def test_failed_station_list_keeps_the_previous_nearby_result(self) -> None:
        c = make_coordinator(data={"location_entity": "person.me"})
        self._locate(c, latitude=37.5665, longitude=126.978)
        c._api.fetch_station_realtime_all.return_value = [
            {
                "stationId": "ST-9",
                "stationName": "102. City Hall",
                "stationLatitude": "37.5666",
                "stationLongitude": "126.978",
                "parkingBikeTotCnt": "7",
            }
        ]
        await c.async_refresh()
        self.assertEqual(7, c.nearby_total_bikes)
        self.assertEqual(1, len(c.nearby))

        c._api.fetch_station_realtime_all.side_effect = ConnectionResetError("reset")
        await c.async_refresh()

        self.assertEqual(7, c.nearby_total_bikes)
        self.assertEqual(1, len(c.nearby))
        self.assertTrue(c.nearby_ready)
        self.assertEqual("station_list_unavailable", c.nearby_status)
        self.assertEqual("ok", c.data["validation_status"])

    async def test_nearby_stays_unknown_until_a_station_list_arrives(self) -> None:
        c = make_coordinator(data={"location_entity": "person.me"})
        self._locate(c, latitude=37.5665, longitude=126.978)
        c._api.fetch_station_realtime_all.side_effect = ConnectionResetError("reset")

        await c.async_refresh()

        self.assertFalse(c.nearby_ready)
        self.assertEqual("station_list_unavailable", c.nearby_status)

    async def test_legacy_entries_still_compute_nearby_from_their_stations(self) -> None:
        c = make_coordinator(options={const.CONF_STATION_IDS: ["ST-1"]})
        c._api.fetch_station_realtime_all.side_effect = ConnectionResetError("reset")

        await c.async_refresh()

        self.assertTrue(c.nearby_ready)
        self.assertNotEqual("station_list_unavailable", c.nearby_status)

    async def test_location_state_in_lat_lon_form_is_the_center(self) -> None:
        c = make_coordinator(data={"location_entity": "person.me"})
        self._locate(c, state="37.5665,126.978")
        c._api.fetch_station_realtime_all.return_value = [
            {
                "stationId": "ST-9",
                "stationName": "102. City Hall",
                "stationLatitude": "37.5666",
                "stationLongitude": "126.978",
                "parkingBikeTotCnt": "3",
            }
        ]

        await c.async_refresh()

        self.assertEqual("person.me", c.center_source)
        self.assertEqual((37.5665, 126.978), (c.center_lat, c.center_lon))
        self.assertEqual("ok", c.nearby_status)
        self.assertEqual(3, c.nearby_total_bikes)

    def test_platforms_seed_station_tracking_at_setup(self) -> None:
        """Legacy station sensors and buttons are not re-added on the first poll."""
        for filename, attribute in (
            ("sensor.py", "_spb_station_ids"),
            ("button.py", "_spb_station_ids_btn"),
        ):
            tree = ast.parse((PACKAGE / filename).read_text(encoding="utf-8"))
            setup = next(
                node for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
            )
            seeded = [
                node for node in setup.body
                if isinstance(node, ast.Assign)
                and any(getattr(t, "attr", "") == attribute for t in node.targets)
            ]
            with self.subTest(filename=filename):
                self.assertTrue(seeded)

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


class LoginRedirectRealSocketTests(unittest.IsolatedAsyncioTestCase):
    """A local site that answers like a Spring login: JSON when signed in, a
    redirect to /login.do otherwise. Exercises the real site_api, transport
    and aiohttp code."""

    async def asyncSetUp(self) -> None:
        # Switches for site variants: an accepted login whose check is still
        # redirected, and an alternate rent status path that answers 404.
        self.redirect_signed_in = False
        self.alternate_status: int | None = None

        async def rent_status(request):
            if request.path == const.API_PATH_RENT_STATUS_ALT and self.alternate_status:
                return web.Response(status=self.alternate_status, text="missing")
            if request.cookies.get("JSESSIONID") == "signed-in" and not self.redirect_signed_in:
                return web.json_response({"loginYn": "Y", "memberYn": "Y", "rentYn": "N"})
            raise web.HTTPFound("/login.do")

        async def login_page(_request):
            return web.Response(
                text=(
                    '<form action="/j_spring_security_check" method="post">'
                    '<input type="text" name="j_username">'
                    '<input type="password" name="j_password"></form>'
                ),
                content_type="text/html",
            )

        async def login_post(request):
            form = await request.post()
            if form.get("j_password") == "right":
                response = web.HTTPFound("/main.do")
                response.set_cookie("JSESSIONID", "signed-in", path="/")
                raise response
            raise web.HTTPFound("/login.do?error=1")

        async def home(_request):
            return web.Response(text="<html>home</html>", content_type="text/html")

        app = web.Application()
        app.router.add_get(const.API_PATH_RENT_STATUS, rent_status)
        app.router.add_get(const.API_PATH_RENT_STATUS_ALT, rent_status)
        app.router.add_get(const.API_PATH_LOGIN, login_page)
        app.router.add_post("/j_spring_security_check", login_post)
        app.router.add_get("/main.do", home)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        # IP addresses need an unsafe jar; production talks to www.bikeseoul.com.
        self.session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        self.client = api.SeoulPublicBikeSiteApi(self.session, "")
        self.client.BASE = f"http://127.0.0.1:{port}"

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.runner.cleanup()

    async def test_redirect_to_login_is_detected_after_rent_status_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "non_json_response"):
            await self.client.fetch_rent_status()
        self.assertTrue(self.client.rent_status_redirected_to_login())
        # site_api's error path still reports the requested address.
        self.assertNotIn("/login.do", str(self.client.last_meta["url"]))

    async def test_wrong_password_redirect_is_a_rejection(self) -> None:
        with self.assertRaisesRegex(ValueError, "login_failed"):
            await self.client.login("me", "wrong")

    async def test_accepted_login_with_a_redirected_check_stays_temporary(self) -> None:
        """A signed-in session that the check still redirects is not a wrong password."""
        self.redirect_signed_in = True
        with self.assertRaises(ValueError) as caught:
            await self.client.login("me", "right")
        self.assertEqual("non_json_response", str(caught.exception))

    async def test_redirect_on_the_primary_path_counts_when_the_alternate_fails(self) -> None:
        self.alternate_status = 404
        with self.assertRaises(aiohttp.ClientResponseError):
            await self.client.fetch_rent_status()
        self.assertTrue(self.client.rent_status_redirected_to_login())

        with self.assertRaisesRegex(ValueError, "login_failed"):
            await self.client.login("me", "wrong")

    async def test_right_password_logs_in_and_json_is_not_a_redirect(self) -> None:
        cookie = await self.client.login("me", "right")
        self.assertIn("JSESSIONID=signed-in", cookie)

        status = await self.client.fetch_rent_status()

        self.assertEqual("Y", status["loginYn"])
        self.assertFalse(self.client.rent_status_redirected_to_login())

    async def test_unreachable_site_is_not_a_redirect(self) -> None:
        await self.runner.cleanup()
        transport = importlib.import_module("custom_components.seoul_bike.transport")
        with patch.object(transport, "RETRY_DELAYS", (0.0, 0.0)):
            with self.assertRaises(Exception) as caught:
                await self.client.fetch_rent_status()
        self.assertNotIsInstance(caught.exception, ValueError)
        self.assertFalse(self.client.rent_status_redirected_to_login())


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
        keep = const.entered_or_stored_password
        self.assertEqual("stored", keep("", "stored", username="me", stored_username="me"))
        self.assertEqual("stored", keep("  ", "stored", username=" me ", stored_username="me"))
        self.assertEqual("new", keep(" new ", "stored", username="me", stored_username="me"))
        self.assertEqual("new", keep("new", "stored", username="other", stored_username="me"))
        # Never send one account's password for another username.
        self.assertEqual("", keep("", "stored", username="other", stored_username="me"))
        self.assertEqual("", keep(None, None))
        self.assertIn("entered_or_stored_password", self.source)
        self.assertIn("stored_username=", self.source)

    def test_reauth_keeps_an_options_location_in_step(self) -> None:
        tree = ast.parse(self.source)
        flow = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "ConfigFlow"
        )
        updates = [
            node for node in ast.walk(flow)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "async_update_entry"
        ]
        self.assertTrue(updates)
        self.assertTrue(all("options" in {k.arg for k in call.keywords} for call in updates))

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
