# 서울자전거 따릉이 (Seoul Public Bike)

이 커스텀 통합구성요소는 서울자전거 따릉이 정보를 Home Assistant에서 조회할 수 있도록 제공합니다.  
현재 버전은 **로그인 방식(아이디/패스워드)** 으로만 동작하며, 로그인 후 생성된 쿠키를 내부에 저장해 비공식 API를 호출합니다.

---

## 설치 (HACS)

[![Open your Home Assistant instance and show the HACS repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=1bobby-git&repository=HA-Seoul-Bike&category=integration)

1. HACS → **Integrations** → 오른쪽 상단 메뉴 → **Custom repositories**
2. Repository: `https://github.com/1bobby-git/HA-Seoul-Bike`
3. Category: **Integration**
4. 설치 후 Home Assistant 재시작

---

## 설정 (추가)

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=seoul_bike)

**필수 입력**
- **아이디**
- **패스워드**

**추가 설정 (선택)**
- **내 위치 엔티티 (entity_id)**: 주변 추천/거리 계산 기준 위치

---

## 동작 방식

- 아이디/패스워드로 로그인합니다.
- 로그인 성공 시 쿠키를 내부에 저장하고, 비공식 API로 데이터를 수집합니다.
- 세션이 만료되면 동일한 로그인 정보로 자동 재로그인해 쿠키를 갱신합니다.

---

## 주요 기능

- **이용 내역 센서**: 최근 대여/반납 기록, 이용 시간, 거리, 칼로리, 탄소 절감 효과 제공
- **이용권 유효 기간**: 이용권 만료일 센서 제공
- **즐겨찾는 대여소 센서**: 일반/새싹 자전거 잔여 수 자동 생성
- **대여소/주변 추천**: 실시간 대여소 현황 기반 주변 추천 센서
- **새로 고침 버튼**: 각 기기별 즉시 갱신

---

## 옵션 (수정)

옵션 화면에서도 **아이디/패스워드**와 **내 위치 엔티티**를 수정할 수 있습니다.

---

## 버전 히스토리 (큰 변경점)

- **1.1.4**: 기존 API 방식 + Cookie 방식 구성을 **아이디/패스워드 로그인 단일 방식**으로 통합. 쿠키 자동 저장/갱신 구조로 전환.
- **1.0.8**: API 방식과 Cookie 방식이 분리되어 동작하던 버전.
