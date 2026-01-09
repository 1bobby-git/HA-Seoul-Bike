⚠️ 설치하지 마세요! ⚠️
---

# 따릉이 (Seoul Public Bike) – Home Assistant 커스텀 통합구성요소

하나의 통합구성요소 안에서 **2가지 수집 방식**을 선택해서 사용할 수 있습니다.

- **API 방식(OpenAPI Polling)**: 서울 열린데이터광장 OpenAPI로 실시간 대여소 데이터를 주기적으로 가져옵니다.
- **Cookie 방식(bikeseoul.com Pulling)**: bikeseoul.com의 로그인 쿠키로 **대여/반납 이력(이용내역)** 및 **즐겨찾는 대여소** 화면을 수집합니다.

> 버전 표기는 로컬 테스트 목적에 맞춰 항상 `1.0` 으로 유지합니다.

---

## 설치

1. `/config/custom_components/seoul_bike/` 경로에 이 폴더를 그대로 복사
2. Home Assistant 재시작
3. 설정 → 기기 및 서비스 → 통합 추가 → **따릉이 (Seoul Public Bike)**

---

## 설정(추가) 흐름

통합을 추가하면 **수집 방식**을 먼저 선택합니다.

### 1) API 방식(OpenAPI Polling)

입력 항목
- **OpenAPI 키**
- **내 위치 엔티티(entity_id)** (필수)
- **업데이트 주기(초)** (선택)
- **정류소 목록** (선택, 쉼표/줄바꿈)  
  예) `3685, ST-2697`

특징
- 주변 반경 내 대여가능 자전거 합계/추천 대여소(가장 가까운 1곳) 센서
- 지정한 정류소(대여소)별 기기/센서 생성
- 새로고침 버튼(전체/정류소)로 즉시 갱신
- 정류소 번호(예: 3685) 입력 시 내부에서 ST-xxxx 자동 변환 시도  
  (후보가 여러 개인 경우 ambiguous 처리 → ST-xxxx로 확정 입력 권장)

OpenAPI 키 발급
- 데이터셋: https://data.seoul.go.kr/dataList/OA-15493/A/1/datasetView.do
- 인증키 확인: https://data.seoul.go.kr/together/mypage/actkeyMng_ss.do

테스트 예시
```bash
curl -m 25 -v "http://openapi.seoul.go.kr:8088/내키/json/bikeList/1/5/"
```

### 2) Cookie 방식(bikeseoul.com Pulling)

입력 항목
- **bikeseoul.com 로그인 쿠키** (필수)

특징
- 대여/반납 이력(이용내역) 수집 센서
- 즐겨찾는 대여소 목록/잔여 수량(일반/새싹) 센서
- 새로고침 시 즐겨찾기 목록 변경분을 기기(엔티티)에도 반영
- 마지막 업데이트 시간 센서 포함

---

## 옵션(수정)

통합 추가 후에는 각 항목의 **옵션**에서 설정값을 변경할 수 있습니다.
- API 방식: 정류소 목록, 내 위치 엔티티, 업데이트 주기
- Cookie 방식: 쿠키

---

## 화면에서 함께 보이게 하기

API 방식과 Cookie 방식을 **둘 다** 사용하려면 통합을 **2번 추가**하면 됩니다.

- `따릉이(API)`
- `따릉이 (Cookie)`

각 항목은 서로 독립적으로 동작하며, 내부 구현 파일도 분리되어 충돌하지 않습니다.
