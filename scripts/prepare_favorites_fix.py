"""One-shot, exact-context patch; removed from the final change."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / 'custom_components/seoul_bike'


def replace(path, before, after, count=1):
    text = path.read_text(encoding='utf-8')
    if text.count(before) != count:
        raise RuntimeError(f'Patch context changed: {path}: expected {count}, got {text.count(before)}')
    path.write_text(text.replace(before, after), encoding='utf-8')


replace(COMP / 'api.py', 'from __future__ import annotations\n', 'from __future__ import annotations\n\nfrom time import time_ns\n\nfrom .const import API_PATH_FAVORITES\n')
replace(COMP / 'api.py', '        headers["Connection"] = "close"\n', '        headers["Connection"] = "close"\n        headers["Cache-Control"] = "no-cache, no-store, max-age=0"\n        headers["Pragma"] = "no-cache"\n')
replace(COMP / 'api.py', '    _get_text = site_request("GET")(_SiteApi._get_text)\n', '''    async def fetch_favorites_html(self) -> str:
        """Read a fresh account snapshot, not a cached favorite page."""
        return await self._get_text(
            API_PATH_FAVORITES,
            params={"_": str(time_ns())},
            referer_path=API_PATH_FAVORITES,
        )

    _get_text = site_request("GET")(_SiteApi._get_text)
''')
replace(COMP / 'coordinator.py', 'from .api import SeoulPublicBikeSiteApi\n', 'from .api import SeoulPublicBikeSiteApi\nfrom .favorites import validate_favorites_html\n')
replace(COMP / 'coordinator.py', '                favorites = [] if _looks_like_login(fav_html) else _extract_favorites_with_counts(fav_html)\n', '''                if _looks_like_login(fav_html):
                    raise ValueError("즐겨찾기 페이지 인증 실패: 기존 즐겨찾기를 유지합니다.")
                favorites = _extract_favorites_with_counts(fav_html)
                validate_favorites_html(fav_html, favorites)
''')
replace(COMP / 'runtime_coordinator.py', '    async def _async_update_data(self) -> dict[str, Any]:\n        data = await super()._async_update_data()\n', '''    async def async_refresh_web(self) -> None:
        """Refresh all website tiers immediately, including the favorite list."""
        self._force_web_refresh = True
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        # Serialize periodic refresh with the existing per-page refresh methods.
        async with self._refresh_lock:
            if getattr(self, "_force_web_refresh", False):
                self._force_web_refresh = False
                self._last_tier2_update = float("-inf")
                self._last_tier3_update = float("-inf")
            data = await super()._async_update_data()
''')
replace(COMP / '__init__.py', 'from .runtime_coordinator import SeoulPublicBikeCoordinator\n', 'from .runtime_coordinator import SeoulPublicBikeCoordinator\nfrom .favorites import sync_favorite_registry\n')
replace(COMP / '__init__.py', '        if validation_status == "ok":\n            reauth_started = False\n', '''        if validation_status == "ok":
            reauth_started = False
            if coordinator.last_update_success:
                sync_favorite_registry(hass, entry, current_data)
''')
replace(COMP / '__init__.py', '    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)\n', '''    # A reload resets the in-memory previous list, not the persistent registries.
    sync_favorite_registry(hass, entry, data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
''')
for filename in ('sensor.py', 'button.py'):
    path = COMP / filename
    text = path.read_text(encoding='utf-8')
    assert 'await ent_reg.async_remove(' in text
    path.write_text(text.replace('await ent_reg.async_remove(', 'ent_reg.async_remove('), encoding='utf-8')
    replace(path, '    coordinator.async_add_listener(_on_coordinator_update)\n', '    entry.async_on_unload(coordinator.async_add_listener(_on_coordinator_update))\n')
    replace(path, '    async def _async_sync_favorites() -> None:\n', '''    async def _async_sync_favorites() -> None:
        if not coordinator.last_update_success or (coordinator.data or {}).get("error"):
            return
''')
replace(COMP / 'button.py', 'await self.coordinator.async_refresh_my_page()', 'await self.coordinator.async_refresh_web()')
manifest = COMP / 'manifest.json'
payload = json.loads(manifest.read_text(encoding='utf-8'))
assert payload['version'] == '1.3.4', 'A newer version landed; rebase before release.'
payload['version'] = '1.3.5'
manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
notes = '''## 1.3.5 — 즐겨찾기 웹 상태 재동기화 (2026-09-08)

- 통합 다시 로드 시 웹에서 새로 조회한 목록을 기준으로 저장된 즐겨찾기 센서·버튼·빈 기기를 정리합니다.
- 즐겨찾기 조회에 고유 요청값과 캐시 재사용 방지 헤더를 적용합니다. 기존 네트워크 재시도·시간 제한은 유지합니다.
- 마이페이지의 새로 고침 버튼도 5분/30분 갱신 대기 없이 즐겨찾기·이용 내역·이용권을 다시 가져옵니다.
- 센서/버튼 삭제 중 잘못된 await로 동기화가 중단되는 문제와 재로드 후 남는 구독을 수정합니다.
- 로그인·통신·알 수 없는 HTML 응답은 빈 즐겨찾기로 취급하지 않습니다. 정상적인 빈 목록일 때만 전체 삭제를 반영합니다.
- 유지되는 대여소의 unique_id, 사용자 지정 이름, 별도 등록 대여소와 다른 계정의 기기는 보존합니다.

업데이트 후 Home Assistant를 한 번 재시작하세요. 이후 앱에서 즐겨찾기를 수정하면 통합의 **다시 로드** 또는 **마이페이지 → 새로 고침**으로 반영할 수 있습니다.
자동 갱신의 기존 주기는 유지합니다. 실제 계정·운영 HA에서의 확인은 별도이며, 앱의 변경 사항이 따릉이 웹 계정에도 저장되어 있어야 조회할 수 있습니다.
'''
readme = ROOT / 'README.md'
readme.write_text(readme.read_text(encoding='utf-8') + '\n' + notes, encoding='utf-8')
changelog = ROOT / 'CHANGELOG.md'
text = changelog.read_text(encoding='utf-8')
first, separator, rest = text.partition('\n')
changelog.write_text(first + '\n\n' + notes + '\n' + rest, encoding='utf-8')
release = ROOT / 'docs/releases/v1.3.5.md'
release.write_text('# Seoul Bike v1.3.5\n\n' + notes, encoding='utf-8')
print('Applied favorites reload fix; existing core parsing and identifiers retained.')
