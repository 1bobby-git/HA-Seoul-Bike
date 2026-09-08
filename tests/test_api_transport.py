"""Network regression tests use synthetic data, never a real bike account."""
from __future__ import annotations

import asyncio
import errno
import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
from yarl import URL

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "seoul_bike_transport_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components" / "seoul_bike")]
sys.modules.setdefault(PACKAGE, package)
transport = importlib.import_module(f"{PACKAGE}.transport")


def http_error(status, headers=None):
    info = aiohttp.RequestInfo(URL("https://example.invalid/test"), "GET", {}, URL("https://example.invalid/test"))
    return aiohttp.ClientResponseError(info, (), status=status, headers=headers or {})


class Client:
    BASE = "https://example.invalid"
    last_meta = None
    last_error = None

    def _record_meta(self, method, url, status, error=None):
        self.last_meta = {"method": method, "url": url, "status": status}
        if error:
            self.last_meta["error"] = error
        self.last_error = error


class RetryPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = Client()
        self.sleep = AsyncMock()
        patcher = patch.object(transport.asyncio, "sleep", self.sleep)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def invoke(self, effects, method="GET", path="/read"):
        self.operation = AsyncMock(side_effect=effects)
        wrapped = transport.site_request(method)(self.operation)
        return await wrapped(self.client, path)

    async def test_raw_connection_reset_recovers(self):
        self.assertEqual(await self.invoke([ConnectionResetError(104, "reset"), "ok"]), "ok")
        self.assertEqual(self.operation.await_count, 2)
        self.sleep.assert_awaited_once_with(0.5)

    async def test_connection_and_payload_errors_recover(self):
        for error in (aiohttp.ServerDisconnectedError(), aiohttp.ClientOSError(104, "reset"), aiohttp.ClientPayloadError("truncated"), TimeoutError(), OSError(errno.ENETUNREACH, "offline")):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(await self.invoke([error, "ok"]), "ok")
                self.assertEqual(self.operation.await_count, 2)

    async def test_exhaustion_raises_original_exception(self):
        error = ConnectionResetError(104, "reset")
        with self.assertRaises(ConnectionResetError) as raised:
            await self.invoke([error, error, error])
        self.assertIs(raised.exception, error)
        self.assertEqual(self.operation.await_count, 3)
        self.assertEqual([call.args for call in self.sleep.await_args_list], [(0.5,), (1.0,)])
        self.assertEqual(self.client.last_meta["attempts"], 3)
        self.assertIsNone(self.client.last_meta["status"])

    async def test_only_allowlisted_query_posts_retry(self):
        for path in transport._READ_ONLY_POST_PATHS:
            with self.subTest(path=path):
                self.assertEqual(await self.invoke([ConnectionResetError(104, "reset"), {}], "POST", path), {})
                self.assertEqual(self.operation.await_count, 2)

    async def test_login_and_unknown_posts_are_never_replayed(self):
        for path in ("/j_spring_security_check", "/login.do", "/new-action"):
            with self.subTest(path=path), self.assertRaises(ConnectionResetError):
                await self.invoke([ConnectionResetError(104, "reset")], "POST", path)
            self.assertEqual(self.operation.await_count, 1)
        self.sleep.assert_not_awaited()

    async def test_auth_and_client_errors_are_not_retried(self):
        for status in (400, 401, 403, 404, 405, 429):
            with self.subTest(status=status), self.assertRaises(aiohttp.ClientResponseError):
                await self.invoke([http_error(status)])
            self.assertEqual(self.operation.await_count, 1)

    async def test_transient_http_errors_are_retried(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertEqual(await self.invoke([http_error(status), "ok"]), "ok")

    async def test_retry_after_is_respected(self):
        self.assertEqual(await self.invoke([http_error(503, {"Retry-After": "2"}), "ok"]), "ok")
        self.sleep.assert_awaited_once_with(2.0)

    async def test_long_or_invalid_retry_after_defers_to_next_poll(self):
        for value in ("120", "invalid", "-1"):
            with self.subTest(value=value), self.assertRaises(aiohttp.ClientResponseError):
                await self.invoke([http_error(503, {"Retry-After": value})])
            self.assertEqual(self.operation.await_count, 1)
        self.sleep.assert_not_awaited()

    async def test_retry_after_http_date(self):
        past = format_datetime(datetime.now(timezone.utc) - timedelta(seconds=10), usegmt=True)
        future = format_datetime(datetime.now(timezone.utc) + timedelta(hours=1), usegmt=True)
        self.assertEqual(transport._retry_delay(http_error(503, {"Retry-After": past}), 0.5), 0.5)
        self.assertIsNone(transport._retry_delay(http_error(503, {"Retry-After": future}), 0.5))

    async def test_parse_and_unrelated_os_errors_are_not_retried(self):
        for error in (ValueError("non_json_response"), OSError(errno.EACCES, "denied"), TypeError("bad call")):
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                await self.invoke([error])
            self.assertEqual(self.operation.await_count, 1)

    async def test_tls_validation_error_is_not_retried(self):
        error = aiohttp.ServerFingerprintMismatch(b"expected", b"actual", "example.invalid", 443)
        with self.assertRaises(aiohttp.ServerFingerprintMismatch):
            await self.invoke([error])
        self.assertEqual(self.operation.await_count, 1)

    async def test_cancellation_propagates_without_retry(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.invoke([asyncio.CancelledError()])
        self.assertEqual(self.operation.await_count, 1)
        self.sleep.assert_not_awaited()

    async def test_timeout_bounds_hanging_read(self):
        calls = 0
        async def hang(client, path):
            nonlocal calls
            calls += 1
            await asyncio.Event().wait()
        with patch.object(transport, "REQUEST_TIMEOUT_SECONDS", 0.005):
            with self.assertRaises(TimeoutError):
                await transport.site_request("GET")(hang)(self.client, "/read")
        self.assertEqual(calls, 3)
        self.assertEqual(self.client.last_error, "TimeoutError")

    async def test_timeout_does_not_replay_login(self):
        operation = AsyncMock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            await transport.site_request("POST")(operation)(self.client, "/login.do")
        self.assertEqual(operation.await_count, 1)

    async def test_previous_success_cannot_mask_transport_failure(self):
        self.client._record_meta("GET", self.client.BASE + "/read", 200)
        with self.assertRaises(ConnectionResetError):
            await self.invoke([ConnectionResetError(104, "secret_cookie")] * 3)
        self.assertIsNone(self.client.last_meta["status"])
        self.assertNotIn("secret_cookie", str(self.client.last_meta))

    async def test_keyword_path_and_url_are_forwarded_unchanged(self):
        for keyword in ("path", "url"):
            operation = AsyncMock(return_value="ok")
            args = {keyword: "/read", "params": {"q": "test"}}
            self.assertEqual(await transport.site_request("GET")(operation)(self.client, **args), "ok")
            operation.assert_awaited_once_with(self.client, **args)


class Response:
    def __init__(self, text='{"ok": true}', status=200, error=None):
        self.body, self.status, self.error = text, status, error
        self.url = "https://example.invalid/read"
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def text(self, **kwargs):
        if self.error:
            raise self.error
        return self.body

    def raise_for_status(self):
        if self.status >= 400:
            raise http_error(self.status)


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.close = AsyncMock()

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


class SiteApiRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = importlib.import_module(f"{PACKAGE}.api")
        patcher = patch.object(transport.asyncio, "sleep", AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_all_get_helpers_recover_and_clear_error(self):
        for name in ("_get_text", "_get_json", "_get_text_url"):
            with self.subTest(method=name):
                failed = Response(error=ConnectionResetError(104, "reset"))
                session = Session([failed, Response()])
                client = self.api.SeoulPublicBikeSiteApi(session, "Cookie: test=synthetic")
                result = await getattr(client, name)("/read")
                self.assertTrue(result)
                self.assertEqual(len(session.calls), 2)
                self.assertTrue(failed.closed)
                self.assertEqual(client.last_meta["attempts"], 2)
                self.assertEqual(client.last_meta["status"], 200)
                self.assertIsNone(client.last_error)
                for _, _, kwargs in session.calls:
                    self.assertEqual(kwargs["headers"]["Connection"], "close")
                    self.assertEqual(kwargs["headers"]["Cookie"], "test=synthetic")
                session.close.assert_not_called()

    async def test_query_posts_preserve_request_payload(self):
        for path in transport._READ_ONLY_POST_PATHS:
            with self.subTest(path=path):
                session = Session([Response(error=aiohttp.ClientPayloadError("truncated")), Response()])
                client = self.api.SeoulPublicBikeSiteApi(session, "test=synthetic")
                result = await client._post_json(path, data={"stationGrpSeq": "ALL"})
                self.assertEqual(result, {"ok": True})
                self.assertEqual(len(session.calls), 2)
                self.assertEqual(session.calls[0], session.calls[1])

    async def test_login_post_is_single_attempt(self):
        session = Session([Response(error=ConnectionResetError(104, "reset"))])
        client = self.api.SeoulPublicBikeSiteApi(session, "")
        with self.assertRaises(ConnectionResetError):
            await client._post_text("/j_spring_security_check", {"j_username": "synthetic"})
        self.assertEqual(len(session.calls), 1)

    async def test_invalid_json_is_not_retried(self):
        session = Session([Response("<html>login page</html>")])
        client = self.api.SeoulPublicBikeSiteApi(session, "")
        with self.assertRaisesRegex(ValueError, "non_json_response"):
            await client._get_json("/read")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(client.last_error, "non_json_response")

    async def test_permanent_failure_is_not_returned_as_fresh_data(self):
        session = Session([Response(error=ConnectionResetError(104, "reset")) for _ in range(3)])
        client = self.api.SeoulPublicBikeSiteApi(session, "")
        with self.assertRaises(ConnectionResetError):
            await client.fetch_use_history_html()
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(client.last_meta["attempts"], 3)
        self.assertIsNone(client.last_meta["status"])


class RealSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_aiohttp_post_recovers_from_tcp_reset(self):
        api = importlib.import_module(f"{PACKAGE}.api")
        calls = 0
        async def handler(reader, writer):
            nonlocal calls
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                length = next((int(line.split(b":", 1)[1]) for line in header.split(b"\r\n") if line.lower().startswith(b"content-length:")), 0)
                if length:
                    await reader.readexactly(length)
                calls += 1
                if calls == 1:
                    writer.transport.abort()
                    return
                body = b'{"realtimeList": [{"stationId": "ST-TEST"}]}'
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        async with server, aiohttp.ClientSession() as session:
            client = api.SeoulPublicBikeSiteApi(session, "")
            client.BASE = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            with patch.object(transport, "RETRY_DELAYS", (0.0, 0.0)):
                result = await client.fetch_station_realtime_all()
            self.assertEqual(result, [{"stationId": "ST-TEST"}])
            self.assertEqual(calls, 2)
            self.assertEqual(client.last_meta["attempts"], 2)
            self.assertFalse(session.closed)


if __name__ == "__main__":
    unittest.main()
