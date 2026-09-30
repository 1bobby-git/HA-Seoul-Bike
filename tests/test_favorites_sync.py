"""Favorites reload regressions; fixtures do not contact a real Seoul Bike account."""
from __future__ import annotations

import ast
import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from test_parser_regressions import api, coordinator

favorites_module = importlib.import_module('custom_components.seoul_bike.favorites')
runtime = importlib.import_module('custom_components.seoul_bike.runtime_coordinator')
ROOT = Path(__file__).resolve().parents[1]


def favorite_html(number='102', name='City Hall'):
    return (f'<ul id="favoriteList"><li><div class="place"><strong>{number}. {name}'
            '</strong></div><div class="bike"><p>3 / 1</p></div></li></ul>')


class FavoritePageTests(unittest.TestCase):
    def test_nonempty_snapshot_preserves_existing_parser_identity(self):
        html = favorite_html()
        parsed = coordinator._extract_favorites_with_counts(html)
        favorites_module.validate_favorites_html(html, parsed)
        self.assertEqual(parsed[0]['station_id'], '102')
        self.assertEqual(parsed[0]['normal'], 3)

    def test_recognized_empty_list_is_valid(self):
        for html in ('<ul id="favoriteList"></ul>', '<div id="favoriteList"><ul></ul></div>',
                     '<ul id="favoriteList"><li>등록된 즐겨찾기가 없습니다.</li></ul>'):
            with self.subTest(html=html):
                favorites_module.validate_favorites_html(html, [])

    def test_error_login_incomplete_or_changed_markup_cannot_delete_all(self):
        for html in ('', '<h1>Service unavailable</h1>', '<input type="password">',
                     '<ul id="favoriteList">', '<ul id="favoriteList"><li>서버 오류</li></ul>',
                     '<ul id="favoriteList"><li><div class="place">changed markup</div></li></ul>',
                     '<ul id><li>missing id value</li></ul>'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                favorites_module.validate_favorites_html(html, [])


class FavoriteRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_favorite_requests_use_distinct_cache_keys_and_existing_transport(self):
        client = api.SeoulPublicBikeSiteApi(object(), 'a=1')
        client._get_text = AsyncMock(return_value=favorite_html())
        with patch('custom_components.seoul_bike.api.time_ns', side_effect=[100, 101]):
            await client.fetch_favorites_html()
            await client.fetch_favorites_html()
        calls = client._get_text.await_args_list
        self.assertEqual(calls[0].kwargs['params'], {'_': '100'})
        self.assertEqual(calls[1].kwargs['params'], {'_': '101'})
        self.assertEqual(calls[0].args[0], '/app/mybike/favoriteStation.do')
        headers = client._headers()
        self.assertEqual(headers['Cookie'], 'a=1')
        self.assertEqual(headers['Connection'], 'close')
        self.assertIn('no-cache', headers['Cache-Control'])
        self.assertEqual(headers['Pragma'], 'no-cache')


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.entry = types.SimpleNamespace(entry_id='account')
        self.er = types.SimpleNamespace(entities={})
        self.dr = types.SimpleNamespace(devices={})
        self.er.async_remove = Mock(side_effect=lambda key: self.er.entities.pop(key))
        self.dr.async_remove_device = Mock(side_effect=lambda key: self.dr.devices.pop(key))
        self.dr.async_update_device = Mock()
        er_mod = types.ModuleType('homeassistant.helpers.entity_registry')
        dr_mod = types.ModuleType('homeassistant.helpers.device_registry')
        er_mod.async_get = lambda hass: self.er
        dr_mod.async_get = lambda hass: self.dr
        self.modules = patch.dict(sys.modules, {er_mod.__name__: er_mod, dr_mod.__name__: dr_mod})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        helpers = sys.modules['homeassistant.helpers']
        self.attrs = patch.multiple(helpers, entity_registry=er_mod, device_registry=dr_mod, create=True)
        self.attrs.start()
        self.addCleanup(self.attrs.stop)

    def entity(self, key, uid, account='account', device_id=None, platform='seoul_bike'):
        self.er.entities[key] = types.SimpleNamespace(
            entity_id=key, unique_id=uid, config_entry_id=account,
            device_id=device_id, platform=platform)

    def device(self, key, station, accounts=('account',)):
        self.dr.devices[key] = types.SimpleNamespace(
            id=key, name='old name', identifiers={('seoul_bike', f'favorite_station_account_{station}')},
            config_entries=set(accounts))

    def sync(self, favorites, **extra):
        data = {'favorites': favorites, 'error': None, 'validation_status': 'ok', **extra}
        favorites_module.sync_favorite_registry(object(), self.entry, data)

    def test_reload_removes_persisted_deleted_favorites_before_platform_setup(self):
        self.entity('sensor.old', 'account_fav_101_normal', device_id='old')
        self.entity('button.old', 'account_fav_101_refresh', device_id='old')
        self.entity('sensor.keep', 'account_fav_102_normal', device_id='keep')
        self.device('old', '101')
        self.device('keep', '102')
        self.sync([{'station_id': '102', 'station_name': 'New name'}])
        self.assertEqual(set(self.er.entities), {'sensor.keep'})
        self.assertEqual(set(self.dr.devices), {'keep'})
        self.dr.async_update_device.assert_called_once_with('keep', name='New name')

    def test_valid_empty_snapshot_removes_all_and_handles_zero_entities(self):
        self.entity('sensor.old', 'account_fav_101_normal', device_id='old')
        self.device('old', '101')
        self.device('orphan', '999')
        self.sync([])
        self.assertEqual(self.er.entities, {})
        self.assertEqual(self.dr.devices, {})

    def test_unrelated_station_other_account_and_shared_device_are_preserved(self):
        self.entity('sensor.station', 'account_ST-1_bikes_total')
        self.entity('sensor.other', 'other_fav_101_normal', account='other', device_id='shared')
        self.entity('sensor.other_platform', 'account_fav_101_normal', platform='other')
        self.device('shared', '101', accounts=('account', 'other'))
        self.sync([])
        self.assertEqual(len(self.er.entities), 3)
        self.assertIn('shared', self.dr.devices)

    def test_failed_or_missing_snapshot_never_removes_previous_favorites(self):
        self.entity('sensor.old', 'account_fav_101_normal')
        self.sync([], error='login_page')
        self.sync([], validation_status='login_page')
        self.sync(None)
        self.sync([{}])
        self.er.async_remove.assert_not_called()

    def test_repeated_refresh_is_idempotent_and_keeps_identity(self):
        self.entity('sensor.custom', 'account_fav_102_normal')
        original = self.er.entities['sensor.custom']
        for _ in range(2):
            self.sync([{'station_id': '102', 'station_name': 'City Hall'}])
        self.assertIs(self.er.entities['sensor.custom'], original)
        self.er.async_remove.assert_not_called()


class CoordinatorRefreshTests(unittest.IsolatedAsyncioTestCase):
    def make_coordinator(self, html):
        hass = types.SimpleNamespace(
            config=types.SimpleNamespace(latitude=37.5, longitude=127.0),
            states=types.SimpleNamespace(get=lambda entity_id: None))
        entry = types.SimpleNamespace(entry_id='account', data={'cookie': 'session'}, options={})
        instance = runtime.SeoulPublicBikeCoordinator(hass, entry)
        instance.data = {}
        instance._api = types.SimpleNamespace(
            set_cookie=Mock(), last_meta=None, last_error=None,
            fetch_rent_status=AsyncMock(return_value={'loginYn': 'Y', 'memberYn': 'Y', 'rentYn': 'N'}),
            fetch_user_status=AsyncMock(return_value={}),
            fetch_reconsent_status=AsyncMock(return_value={}),
            fetch_use_history_html=AsyncMock(return_value='<div class="kcal_box"></div>'),
            fetch_favorites_html=AsyncMock(return_value=html),
            fetch_station_realtime_all=AsyncMock(return_value=[]),
            fetch_voucher_info=AsyncMock(return_value={'voucherEndDttm': '2027-01-01 00:00'}),
            fetch_left_page_html=AsyncMock(return_value='2027-01-01'))
        async def refresh():
            instance.data = await instance._async_update_data()
        instance.async_refresh = refresh
        return instance

    async def test_reload_fetches_new_list_and_drops_previous_counts(self):
        old = self.make_coordinator(favorite_html('101'))
        await old.async_refresh()
        reloaded = self.make_coordinator(favorite_html('102'))
        await reloaded.async_refresh()
        self.assertEqual(old.data['favorites'][0]['station_id'], '101')
        self.assertEqual(reloaded.data['favorites'][0]['station_id'], '102')
        self.assertEqual(set(reloaded.data['favorite_status']), {'102'})
        reloaded._api.fetch_favorites_html.assert_awaited_once()

    async def test_manual_web_refresh_bypasses_tier_wait_ordinary_poll_does_not(self):
        instance = self.make_coordinator(favorite_html('101'))
        await instance.async_refresh()
        instance._api.fetch_favorites_html.return_value = favorite_html('102')
        await instance.async_refresh()
        self.assertEqual(instance._api.fetch_favorites_html.await_count, 1)
        await instance.async_refresh_web()
        self.assertEqual(instance._api.fetch_favorites_html.await_count, 2)
        self.assertEqual(instance.data['favorites'][0]['station_id'], '102')
        self.assertEqual(instance._api.fetch_voucher_info.await_count, 2)

    async def test_valid_empty_and_failure_are_distinct(self):
        instance = self.make_coordinator(favorite_html('101'))
        await instance.async_refresh()
        previous = instance.data
        for response in ('<h1>Service unavailable</h1>', '<form action="/login"><input type="password"></form>'):
            instance._api.fetch_favorites_html.return_value = response
            with self.assertRaises(coordinator.UpdateFailed):
                await instance.async_refresh_web()
            self.assertIs(instance.data, previous)
        instance._api.fetch_favorites_html.return_value = '<ul id="favoriteList"></ul>'
        await instance.async_refresh_web()
        self.assertEqual(instance.data['favorites'], [])
        self.assertEqual(instance.data['favorite_status'], {})

    async def test_periodic_update_uses_existing_refresh_lock(self):
        instance = self.make_coordinator(favorite_html())
        await instance._refresh_lock.acquire()
        task = asyncio.create_task(instance._async_update_data())
        await asyncio.sleep(0)
        instance._api.fetch_rent_status.assert_not_awaited()
        instance._refresh_lock.release()
        await task
        instance._api.fetch_rent_status.assert_awaited_once()


class PlatformContractTests(unittest.TestCase):
    def test_registry_callbacks_are_not_awaited_and_listeners_are_unloaded(self):
        for filename in ('sensor.py', 'button.py'):
            text = (ROOT / 'custom_components/seoul_bike' / filename).read_text(encoding='utf-8')
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                    function = node.value.func
                    self.assertFalse(isinstance(function, ast.Attribute) and function.attr == 'async_remove'
                                     and isinstance(function.value, ast.Name) and function.value.id == 'ent_reg')
            self.assertIn('entry.async_on_unload(coordinator.async_add_listener(_on_coordinator_update))', text)

    def test_reload_reconciles_before_entity_platforms_are_created(self):
        text = (ROOT / 'custom_components/seoul_bike/__init__.py').read_text(encoding='utf-8')
        self.assertLess(text.index('sync_favorite_registry(hass, entry, data)'),
                        text.index('await hass.config_entries.async_forward_entry_setups'))


if __name__ == '__main__':
    unittest.main()
