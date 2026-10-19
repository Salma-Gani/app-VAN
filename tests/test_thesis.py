from __future__ import annotations

import unittest

from ecoinvest.analytics import thesis


def _fundamentals(**overrides):
    base = {
        "eps": 10.0, "ebitda": 100.0, "ebit": 80.0, "bvps": 50.0,
        "revenue": 1_000.0, "shares": 100.0, "dps": 4.0,
        "fiscal_year": "2024", "source": "AMMC", "as_of": "2025-04-30",
        "statement_currency": "MAD",
    }
    base.update(overrides)
    return base


class TestThesisBuild(unittest.TestCase):
    def test_build_captures_assumptions_and_metadata(self) -> None:
        result = {"metric_value": 10.0, "fair_value": 300.0, "entry_price": 240.0,
                  "net_debt": 0.0, "shares": 100.0}
        built = thesis.build("tma", "Total", "per", 30.0, result, 0.20,
                             _fundamentals(), 200.0, "PER (P/E)")
        self.assertEqual(built["symbol"], "TMA")
        self.assertEqual(built["metric_key"], "eps")
        self.assertAlmostEqual(built["target_price"], 300.0)
        self.assertAlmostEqual(built["entry_price"], 240.0)
        self.assertEqual(built["fiscal_year"], "2024")
        self.assertEqual(built["source"], "AMMC")
        self.assertEqual(built["id"], "TMA:per:2024")


class TestThesisEvaluation(unittest.TestCase):
    def setUp(self) -> None:
        self.result = {"metric_value": 10.0, "fair_value": 300.0, "entry_price": 240.0}
        self.thesis = thesis.build("TMA", "Total", "per", 30.0, self.result, 0.20,
                                   _fundamentals(), 400.0, "PER (P/E)")

    def test_entry_reached_when_price_below_entry(self) -> None:
        out = thesis.evaluate(self.thesis, 230.0, _fundamentals())
        self.assertEqual(out["status"], "entry_reached")
        self.assertLess(out["distance_entry"], 0)

    def test_watch_when_price_far_from_entry(self) -> None:
        out = thesis.evaluate(self.thesis, 400.0, _fundamentals())
        self.assertEqual(out["status"], "watch")

    def test_metric_change_flags_recalculation(self) -> None:
        out = thesis.evaluate(self.thesis, 400.0, _fundamentals(eps=12.0))
        self.assertAlmostEqual(out["metric_change"], 0.2, places=6)
        self.assertTrue(out["needs_recalc"])
        self.assertEqual(out["status"], "stale")

    def test_new_fiscal_year_flags_recalculation(self) -> None:
        out = thesis.evaluate(self.thesis, 400.0, _fundamentals(fiscal_year="2025"))
        self.assertIn("new_fiscal_year", out["flags"])
        self.assertTrue(out["needs_recalc"])

    def test_missing_metric_flags_stale(self) -> None:
        out = thesis.evaluate(self.thesis, 400.0, _fundamentals(eps=None))
        self.assertEqual(out["status"], "stale")
        self.assertIn("metric_missing", out["flags"])

    def test_dividend_metric_uses_dps(self) -> None:
        result = {"metric_value": 4.0, "fair_value": 80.0, "entry_price": 64.0}
        div = thesis.build("ATW", "Bank", "dividend", 0.05, result, 0.20,
                           _fundamentals(), 90.0, "Rendement")
        out = thesis.evaluate(div, 90.0, _fundamentals(dps=5.0))
        self.assertEqual(out["current_metric"], 5.0)
        self.assertAlmostEqual(out["metric_change"], 0.25, places=6)


class TestThesisFrame(unittest.TestCase):
    def test_frame_has_readable_columns(self) -> None:
        result = {"metric_value": 10.0, "fair_value": 300.0, "entry_price": 240.0}
        built = thesis.build("TMA", "Total", "per", 30.0, result, 0.20,
                             _fundamentals(), 400.0, "PER (P/E)")
        frame = thesis.to_frame([thesis.evaluate(built, 250.0, _fundamentals())])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["Symbole"], "TMA")


if __name__ == "__main__":
    unittest.main()
