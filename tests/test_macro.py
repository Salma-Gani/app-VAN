from __future__ import annotations

import unittest

from ecoinvest.data import macro


class TestMacroParsing(unittest.TestCase):
    def test_latest_non_null_is_selected(self) -> None:
        payload = [
            {"lastupdated": "2026-10-08"},
            [
                {"date": "2025", "value": 4.6},
                {"date": "2024", "value": 3.8},
                {"date": "2023", "value": None},
            ],
        ]
        parsed = macro._parse_indicator(payload)
        self.assertAlmostEqual(parsed["value"], 4.6)
        self.assertEqual(parsed["year"], "2025")
        self.assertEqual(parsed["updated"], "2026-10-08")

    def test_invalid_payload_is_safe(self) -> None:
        parsed = macro._parse_indicator({"unexpected": True})
        self.assertIsNone(parsed["value"])
        self.assertIsNone(parsed["year"])


if __name__ == "__main__":
    unittest.main()
