from __future__ import annotations

import unittest

from ecoinvest.data import fundamentals


class TestRatios(unittest.TestCase):
    def setUp(self) -> None:
        self.f = {
            "revenue": 1000.0,
            "ebitda": 200.0,
            "ebit": 150.0,
            "net_income": 100.0,
            "eps": 10.0,
            "fcf": 80.0,
            "equity": 500.0,
            "total_debt": 200.0,
            "cash": 50.0,
            "dps": 2.0,
            "shares": 10.0,
            "total_assets": 1500.0,
            "current_assets": 400.0,
            "current_liabilities": 200.0,
            "market_cap": 2000.0,
        }

    def test_core_ratios(self) -> None:
        r = fundamentals.compute_ratios(self.f, price=20.0)
        self.assertAlmostEqual(r["per"], 2.0)
        self.assertAlmostEqual(r["pb"], 0.4)
        self.assertAlmostEqual(r["ps"], 2.0)
        self.assertAlmostEqual(r["ev_ebitda"], 10.75)
        self.assertAlmostEqual(r["dividend_yield"], 0.10)
        self.assertAlmostEqual(r["roe"], 0.20)
        self.assertAlmostEqual(r["roa"], 100 / 1500)
        self.assertAlmostEqual(r["net_margin"], 0.10)
        self.assertAlmostEqual(r["operating_margin"], 0.15)
        self.assertAlmostEqual(r["debt_to_equity"], 0.40)
        self.assertAlmostEqual(r["net_debt_to_ebitda"], 0.75)
        self.assertAlmostEqual(r["current_ratio"], 2.0)
        self.assertAlmostEqual(r["fcf_yield"], 0.04)
        self.assertAlmostEqual(r["earnings_yield"], 0.50)
        self.assertAlmostEqual(r["payout"], 0.20)

    def test_negative_eps_is_not_meaningful(self) -> None:
        f = dict(self.f, eps=-5.0)
        r = fundamentals.compute_ratios(f, price=20.0)
        self.assertIsNone(r["per"])
        self.assertIsNone(fundamentals.interpret_ratio("per", r["per"])["value"])


if __name__ == "__main__":
    unittest.main()
