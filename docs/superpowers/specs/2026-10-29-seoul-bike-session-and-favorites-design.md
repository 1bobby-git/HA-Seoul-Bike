# Seoul Bike 다음 릴리스: 세션 분리·로그인 실패 처리·즐겨찾기 보존 설계

- 작성일: 2026-10-29
- 기준: `main` 1.3.6 (`7e1ee1c`)
- 범위: 코드와 aiohttp 동작으로 확인한 결함만 고칩니다. bikeseoul.com 실측은 하지 않았습니다.

## 1. 목표와 제약

목표: 여러 계정·일시 장애·세션 만료에서도 계정이 섞이거나 즐겨찾기 엔티티가 지워지거나 계정이 잠기지 않게 합니다.

제약: 엔티티와 unique_id, 엔티티 ID, 폴링 주기(60초·5분·30분), 설정 화면의 입력 항목, 즐겨찾기 실패 시 `UpdateFailed`(1.3.5 정책), `_looks_like_login("")` 동작, `site_api.py` 무변경 원칙을 유지합니다.

## 2. 확인된 결함

| # | 결함 | 근거 |
|---|---|---|
| F1 | Tier 2 이용내역이 로그인 페이지로 오면 반환값의 `favorites`·`favorite_status`·`periods`·`my_page`를 비웁니다. 다음 주기에 Tier 2를 건너뛰면 빈 즐겨찾기가 정상 데이터로 전달되어 즐겨찾기 엔티티·기기가 삭제되고 다음 Tier 2에서 다시 생깁니다(사용자 설정 손실 가능). Tier 1 분기는 이전 값을 유지합니다. | `coordinator.py` 1272-1297 vs 1201-1225, `__init__.py` 104-106, `favorites.py` |
| F2 | 여러 계정이 Home Assistant 공용 세션(`async_get_clientsession`)의 쿠키 jar를 같이 씁니다. aiohttp는 jar 쿠키로 같은 이름의 Cookie 헤더 값을 덮어쓰므로, 한 계정이 다시 로그인하면 다른 계정 요청에 그 계정의 `JSESSIONID`가 실립니다. 다른 계정의 대여 상태·이용내역·즐겨찾기가 보이고 즐겨찾기 엔티티가 바뀝니다(서버 데이터는 바뀌지 않음). | `coordinator.py` 605, `site_api.py` 90, 101-112, aiohttp `ClientRequest.update_cookies` |
| F3 | 거부된 비밀번호로 60초마다 다시 로그인합니다(재인증을 기다리는 동안에도). 계정 잠금 위험이 있습니다. | `coordinator.py` 1188-1199 |
| F4 | 재로그인 중 연결 오류·시간 초과도 비밀번호 거부와 같이 처리합니다. 시작 시 한 번의 연결 오류로 `ConfigEntryAuthFailed`가 나서 사용자가 재인증할 때까지 통합이 로드되지 않습니다. | `coordinator.py` 1198, `__init__.py` 80-85, `transport.py` 84-88(로그인 POST 1회) |
| F5 | `_async_update_data`에서 `/myLeftPage.do` 호출을 보호하지 않습니다. 이용권 만료일이 없는 사용자에게 이 페이지가 계속 실패하면 매 주기가 실패하고, 시작 시에는 `ConfigEntryNotReady`가 반복됩니다. 버튼 경로(`async_refresh_my_page`)는 보호합니다. | `coordinator.py` 1378-1388 vs 926-932 |
| F6 | 이용내역 응답이 빈 본문이면 로그인 페이지로 판단해 재인증을 요청합니다. 대여 상태 API가 `/login.do`로 리디렉트되어 HTML을 주면 `login_ok`가 None이 되어 자동 재로그인을 하지 않습니다. | `coordinator.py` 256-257, 1274, 1180-1186, `site_api.py` 146-155 |
| F7 | 실시간 대여소 값에서 새싹 수가 0이면 전기자전거 수(`parkingELECBikeCnt`)로 대체하고, 일반 수가 없으면 전체 수로 대체합니다. 즐겨찾기의 HTML 값(일반/새싹)을 실시간 값으로 덮어써 새싹 수가 틀립니다. | `coordinator.py` 683-747, 1031-1046, 1407-1424 |
| F8 | 재인증·옵션 화면이 저장된 비밀번호를 기본값으로 브라우저에 보냅니다. 위치 엔티티를 지울 수 없습니다(기본값이 다시 들어감). `reauth_successful` 문구가 없습니다. 로드된 항목을 재인증하면 두 번 다시 불러옵니다. | `config_flow.py` 72-84, 146, 168, 207-210, `strings.json` 21-23 |
| F9 | 레거시 바이너리 센서 정리에서 동기 함수 `entity_registry.async_remove`를 `await`해 `TypeError`가 나고 바이너리 센서 2개가 생성되지 않습니다(레거시 항목만). | `binary_sensor.py` 117 |
| F10 | 이동 경로 센서의 `경로 좌표`(routeList 전체)가 기록기에 저장됩니다. | `sensor.py` 666-676 |
| F11 | `filter_cookies`에 문자열을 넘겨 aiohttp가 4.x에서 동작하지 않는다고 경고합니다. | `site_api.py` 103 |
| F12 | 재로그인이 새 쿠키를 `data`에만 써서, 옵션에 쿠키가 남은 레거시 항목은 재시작 때 오래된 쿠키를 먼저 씁니다. | `coordinator.py` 1139, 1191-1194, `_ensure_login` 859-868 |
| F13 | README의 "주변 추천" 센서는 `station_ids`가 있는 레거시 항목에서만 생깁니다. 현재 설정 화면은 이 값을 쓰지 않아 새 항목에는 생기지 않습니다. 대여소 목록은 매 주기 받아 계산만 합니다. | `coordinator.py` 1143-1145, 1463-1473, `sensor.py` 226, 406, README 55-62 |

## 3. 설계

### 3.1 즐겨찾기 보존 (F1)
Tier 2 로그인 페이지 분기도 Tier 1 분기처럼 이전 `periods`·`ticket_expiry`·`my_page`·`favorites`·`favorite_status`를 그대로 돌려줍니다.

### 3.2 계정별 세션 (F2)
런타임 코디네이터가 항목마다 `async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())`로 만든 세션을 씁니다. 항목 설정 중에 만들므로 HA가 언로드 때 닫습니다. 한 계정만 쓰는 경우 시작 시 jar가 비어 있는 것은 지금과 같고, 요청은 저장된 Cookie 헤더로 시작합니다.

### 3.3 로그인 실패 구분 (F3, F4, F6)
- 비밀번호 거부(`login_failed`): 지금처럼 `login_page` 결과로 재인증을 요청하고, 이 코디네이터에서는 더 로그인하지 않습니다. 재인증·옵션 저장은 항목을 다시 불러와 새 코디네이터가 다시 시도합니다.
- 연결 오류·시간 초과·서버 오류: 인증 실패로 보지 않습니다. 이전 값을 유지한 일시 오류 결과를 돌려주고(문구에 "로그인" 없음), 시작 시에는 `ConfigEntryNotReady`로 재시도합니다.
- 대여 상태 응답이 JSON이 아니고 마지막 요청 주소가 `/login.do`이면 로그아웃으로 보고 재로그인합니다.
- 이용내역 본문이 비어 있으면 로그인 페이지가 아닌 일시 오류로 처리합니다. `_looks_like_login`은 바꾸지 않습니다.

### 3.4 그 밖의 수정
- F5: `/myLeftPage.do` 호출을 `async_refresh_my_page`와 같이 보호합니다.
- F7: 보류(3.6절).
- F8: 재인증·옵션의 비밀번호 칸은 비워 두면 저장된 값을 유지하고 기본값을 보내지 않습니다. 위치는 `suggested_value`로 바꿔 지울 수 있게 합니다. `reauth_successful`·`reauth_failed` 문구를 추가합니다. 로드되지 않은 항목만 직접 다시 불러옵니다.
- F9: `await`를 지우고 AST 검사를 `binary_sensor.py`·`__init__.py`까지 넓힙니다.
- F10: `_unrecorded_attributes = frozenset({"경로 좌표"})`.
- F11: `api.py`에서 `filter_cookies(URL(BASE))`로 덮어씁니다(`site_api.py` 무변경).
- F12: 재로그인 쿠키 저장을 `_ensure_login`과 같이 옵션 쿠키까지 갱신합니다.

### 3.5 주변 추천 (F13): A안으로 결정 (2026-10-29)
- A안(채택): 위치 엔티티가 설정된 항목에 기존 주변 추천 센서 3개(`{entry_id}_nearby_total_bikes`, `_nearby_recommended_bikes`, `_nearby_station_list`)를 만듭니다. 대여소별 센서·버튼은 지금처럼 레거시 `station_ids` 항목에만 있습니다. 새 엔티티가 생기므로 버전은 1.4.0입니다. 위치 엔티티를 지우면 센서와 `{entry_id}_stations` 기기를 정리합니다.
- B안(미채택): 동작은 그대로 두고 README를 "레거시 항목 전용"으로 고칩니다.

### 3.6 보류 (F7)
`parkingELECBikeCnt`가 전기자전거 수인지 새싹 수인지 코드로 확인할 수 없습니다(원 작성자 주석은 "새싹(전기)"). 실제 응답 확인 전까지 자전거 수 계산은 바꾸지 않습니다.

## 4. 바꾸지 않는 것
엔티티·unique_id·엔티티 ID, 폴링 주기와 Tier 간격, 설정 입력 항목, 즐겨찾기 실패 시 `UpdateFailed`, 효과가 있는 요청이 없는 점(로그인 POST와 조회 POST만), `site_api.py`, 재시도 정책(`transport.py`).

## 5. 테스트
저장소 방식(`unittest` + HA 스텁)을 따르고 스텁에 `homeassistant.exceptions`, `async_create_clientsession`을 추가합니다.
- F1: Tier 2 로그인 페이지 뒤 Tier 2를 건너뛴 주기에도 즐겨찾기가 유지됨
- F2: 두 코디네이터가 서로 다른 jar를 쓰고, 한쪽 재로그인 쿠키가 다른 쪽 요청에 실리지 않음(실제 aiohttp 로컬 서버)
- F3·F4: 비밀번호 거부 뒤 로그인 1회만, 연결 오류는 `login_page`가 아님
- F5·F6·F7·F9·F10·F11·F12: 각 경로 단위 테스트
- Linux(Python 3.13): `python -m unittest discover -s tests -p "test_*.py"`, `compileall`, `scripts/build_release.py`

## 6. 배포
`fix/1.3.7-session-and-favorites`에서 작업해 CI(단위 테스트·HACS·hassfest)를 확인하고 `main`에 병합·push합니다. `publish-release`가 `docs/releases/vX.md`로 Release와 zip을 만듭니다. 실제 계정·운영 HA 확인은 하지 않습니다.
