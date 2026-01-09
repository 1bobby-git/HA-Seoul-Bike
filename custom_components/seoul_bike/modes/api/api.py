"""Seoul Bike OpenAPI client (Seoul Open Data Plaza)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_HOST = "http://openapi.seoul.go.kr:8088"
RESOURCE = "bikeList"


class SeoulBikeApiError(Exception):
    """Base API error."""


class SeoulBikeApiAuthError(SeoulBikeApiError):
    """Auth/key error."""


class SeoulBikeApi:
    """OpenAPI client.

    NOTE)
    - 서울시 bikeList 응답의 list_total_count 값이 '전체 개수'가 아니라
      '이번 요청에서 내려준 row 개수'처럼 보이는 케이스가 있어,
      전체 수를 믿지 않고 'row가 page_size보다 작아지는 시점'까지 paging 합니다.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        host: str = DEFAULT_HOST,
        timeout_s: int = 25,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._host = host.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=int(timeout_s))

        # 마지막 호출/전체 수집 메타 (diagnostic 용도)
        self.last_meta: dict[str, Any] | None = None

    # ---- backward compatible accessors (예전 코드 보호) ----
    @property
    def session(self) -> aiohttp.ClientSession:
        return self._session

    @property
    def timeout(self) -> aiohttp.ClientTimeout:
        return self._timeout

    def _make_url(self, start: int, end: int) -> str:
        return f"{self._host}/{self._api_key}/json/{RESOURCE}/{start}/{end}/"

    async def validate_key(self) -> None:
        """Validate API key by calling a small sample."""
        _ = await self.fetch_page(1, 1)
        # fetch_page에서 RESULT code 검증을 수행하므로 여기선 OK면 통과

    async def fetch_page(self, start: int, end: int) -> dict[str, Any]:
        url = self._make_url(start, end)
        http_status: int | None = None

        try:
            async with self._session.get(url, timeout=self._timeout) as resp:
                http_status = resp.status
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise SeoulBikeApiError(f"request_failed: {err}") from err

        root = payload.get("rentBikeStatus") or {}
        if not isinstance(root, dict):
            raise SeoulBikeApiError("invalid_payload")

        result = root.get("RESULT") or {}
        code = (result.get("CODE") or "").strip()
        msg = (result.get("MESSAGE") or "").strip()

        rows = list(root.get("row") or [])
        # list_total_count가 전체가 아닐 수 있음(페이지 크기처럼 내려오는 케이스)
        list_total_count = root.get("list_total_count")

        # 메타 저장
        self.last_meta = {
            "url": url,
            "start": start,
            "end": end,
            "http_status": http_status,
            "result_code": code,
            "result_message": msg,
            "row_count": len(rows),
            "list_total_count": list_total_count,
        }

        if code != "INFO-000":
            # 키 오류로 보이는 메시지는 auth로 처리
            if "인증" in msg or "KEY" in msg.upper():
                raise SeoulBikeApiAuthError(msg or "invalid_api_key")
            raise SeoulBikeApiError(msg or f"api_error:{code}")

        return root

    async def _fetch_page_with_retry(
        self,
        start: int,
        end: int,
        retries: int = 2,
        base_delay_s: float = 0.8,
    ) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await self.fetch_page(start, end)
            except (SeoulBikeApiError, SeoulBikeApiAuthError) as err:
                last_err = err
                # auth는 재시도 의미가 거의 없음
                if isinstance(err, SeoulBikeApiAuthError):
                    raise
            except Exception as err:
                last_err = err

            if attempt < retries:
                await asyncio.sleep(base_delay_s * (attempt + 1))

        raise SeoulBikeApiError(f"page_fetch_failed: {last_err}")

    async def fetch_all(
        self,
        page_size: int = 1000,
        max_pages: int = 10,
        retries: int = 2,
    ) -> list[dict[str, Any]]:
        """Fetch all stations by paging.

        - 1..1000, 1001..2000 ... 순차 조회
        - 각 페이지는 실패 시 재시도
        - 'row 길이 < page_size'인 페이지가 나오면 종료
        """
        page_size = min(int(page_size), 1000)
        max_pages = max(1, int(max_pages))

        all_rows: list[dict[str, Any]] = []
        pages_meta: list[dict[str, Any]] = []
        errors: list[str] = []

        start = 1

        for _ in range(max_pages):
            end = start + page_size - 1

            try:
                root = await self._fetch_page_with_retry(start, end, retries=retries)
                rows = list(root.get("row") or [])
                all_rows.extend(rows)

                # 페이지 메타 기록(진단용)
                if self.last_meta:
                    pages_meta.append(dict(self.last_meta))

                # 더 이상 페이지가 없으면 종료 (핵심: list_total_count 신뢰하지 않음)
                if len(rows) < page_size:
                    break

                start += page_size

            except SeoulBikeApiAuthError:
                raise
            except Exception as err:
                errors.append(f"{start}-{end}: {err}")
                # 페이지 하나가 완전히 죽어도 다음 페이지로 넘어가면
                # stationId 누락 가능성이 커서 여기서는 '중단'이 더 안전함
                raise SeoulBikeApiError(f"paging_failed at {start}-{end}: {err}") from err

        # 전체 수집 메타(진단용)
        self.last_meta = {
            "pages": pages_meta,
            "page_count": len(pages_meta),
            "row_count": len(all_rows),
            "errors": errors,
        }

        return all_rows
