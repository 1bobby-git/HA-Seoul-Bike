from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "seoul_bike"
    / "rent_status.py"
)
SPEC = importlib.util.spec_from_file_location("seoul_bike_rent_status", MODULE_PATH)
rent_status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rent_status)


class RentStatusTests(unittest.TestCase):
    def test_normalizes_rent_bike_endpoint_fields(self) -> None:
        normalized = rent_status.normalize_rent_status(
            {
                "rentBikeYn": "Y",
                "rentStationName": "1001. 테스트 대여소",
                "rentBikeNo": "SPB-1234",
                "rentDttm": "2026-09-01 12:00:00",
            }
        )

        self.assertEqual("Y", normalized["rentYn"])
        self.assertEqual("1001. 테스트 대여소", normalized["stationName"])
        self.assertEqual("SPB-1234", normalized["bikeNo"])

    def test_preserves_existing_endpoint_fields_and_unknown_values(self) -> None:
        normalized = rent_status.normalize_rent_status(
            {
                "rentYn": "N",
                "stationName": "대여소",
                "bikeNo": "BIKE",
                "custom": 7,
            }
        )

        self.assertEqual("N", normalized["rentBikeYn"])
        self.assertEqual("대여소", normalized["rentStationName"])
        self.assertEqual("BIKE", normalized["rentBikeNo"])
        self.assertEqual(7, normalized["custom"])

    def test_invalid_payload_returns_empty_mapping(self) -> None:
        self.assertEqual({}, rent_status.normalize_rent_status(None))
        self.assertEqual({}, rent_status.normalize_rent_status([]))


if __name__ == "__main__":
    unittest.main()
