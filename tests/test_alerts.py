from __future__ import annotations

import unittest

import pandas as pd

from ecoinvest.analytics import alerts


class TestAlertRules(unittest.TestCase):
    def setUp(self) -> None:
        self.row = pd.Series({
            "symbol": "ATW", "name": "Attijariwafa Bank", "close": 100.0,
            "change_pct": -0.06, "low_52w": 99.0, "high_52w": 150.0,
            "rsi14": 25.0, "max_drawdown": -0.25, "last_date": "2026-10-16",
            "volume": 1_000_000,
        })

    def test_multiple_rules_are_detected(self) -> None:
        found = alerts.evaluate_row(self.row)
        kinds = {a.kind for a in found}
        self.assertIn("low_52w", kinds)
        self.assertIn("rsi", kinds)
        self.assertIn("drawdown", kinds)
        self.assertIn("daily_move", kinds)
        self.assertTrue(all(a.symbol == "ATW" for a in found))
        self.assertTrue(all(a.source for a in found))

    def test_summary_support_and_signals(self) -> None:
        summary = {
            "levels": {"support": 99.0, "resistance": 101.0, "pivot": 100.0},
            "signals": [{"signal": "Croisement MACD haussier", "type": "achat",
                         "detail": "Passage au-dessus de la ligne de signal."}],
        }
        found = alerts.evaluate_row(self.row, summary=summary)
        kinds = {a.kind for a in found}
        self.assertIn("support", kinds)
        self.assertIn("technical", kinds)

    def test_resistance_alert(self) -> None:
        row = self.row.copy()
        row["close"] = 149.0
        row["rsi14"] = 74.0
        row["change_pct"] = 0.01
        row["low_52w"] = 90.0
        row["max_drawdown"] = -0.05
        found = alerts.evaluate_row(row)
        kinds = {a.kind for a in found}
        self.assertIn("high_52w", kinds)
        self.assertIn("rsi", kinds)
        self.assertNotIn("drawdown", kinds)

    def test_missing_price_is_safe(self) -> None:
        self.assertEqual(alerts.evaluate_row(pd.Series({"symbol": "X"})), [])

    def test_scan_filters_watchlist(self) -> None:
        table = pd.DataFrame([
            self.row.to_dict(),
            dict(self.row.to_dict(), symbol="IAM", name="Maroc Telecom", close=59.5,
                 low_52w=40.0, high_52w=60.0, rsi14=75.0, max_drawdown=-0.05,
                 change_pct=0.0),
        ])
        found = alerts.scan_market(table, symbols=["IAM"])
        self.assertTrue(found)
        self.assertTrue(all(a.symbol == "IAM" for a in found))

    def test_vix_alert(self) -> None:
        self.assertIsNone(alerts.vix_alert({"level": 18.0}))
        found = alerts.vix_alert({"level": 28.0, "label": "Nervosité"})
        self.assertIsNotNone(found)
        self.assertEqual(found.kind, "vix")
        self.assertIn("S&P 500", found.detail)

    def test_threshold_validation(self) -> None:
        th = alerts.thresholds(rsi_low=80, rsi_high=20, drawdown=0.2, proximity=-1)
        self.assertLess(th["rsi_low"], th["rsi_high"])
        self.assertLess(th["drawdown"], 0)
        self.assertEqual(th["proximity"], 0.0)


if __name__ == "__main__":
    unittest.main()
