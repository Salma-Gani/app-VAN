from __future__ import annotations

import unittest

from ecoinvest.utils import finance


class TestDiscounting(unittest.TestCase):
    def test_npv_known_value(self) -> None:
        # -100 + 60/1,10 + 60/1,21 = 4,1322...
        self.assertAlmostEqual(finance.npv(0.10, [60, 60], invest=100), 4.1322314, places=6)

    def test_irr_zero_npv(self) -> None:
        irr = finance.tri(100, [60, 60])
        self.assertIsNotNone(irr)
        self.assertAlmostEqual(finance.npv(irr, [60, 60], invest=100), 0.0, places=6)

    def test_payback(self) -> None:
        years, _ = finance.payback(100, [60, 60])
        self.assertAlmostEqual(years, 1 + 40 / 60, places=6)


class TestDCF(unittest.TestCase):
    def test_single_year_no_growth(self) -> None:
        # FCF 100, r 10 %, g terminal 0 %, sans dette nette, 10 actions.
        res = finance.dcf([100], 0.10, terminal_growth=0.0, net_debt=0, shares=10, mid_year=False)
        self.assertAlmostEqual(res["enterprise_value"], 1000.0)
        self.assertAlmostEqual(res["price_per_share"], 100.0)

    def test_net_debt_reduces_equity(self) -> None:
        res = finance.dcf([100], 0.10, terminal_growth=0.0, net_debt=200, shares=10, mid_year=False)
        self.assertAlmostEqual(res["equity_value"], 800.0)
        self.assertAlmostEqual(res["price_per_share"], 80.0)

    def test_discount_above_terminal_growth_is_invalid(self) -> None:
        res = finance.dcf([100], 0.02, terminal_growth=0.03, net_debt=0, shares=10, mid_year=False)
        self.assertIsNone(res["terminal_value"])
        self.assertAlmostEqual(res["price_per_share"], 100 / 1.02 / 10, places=6)


class TestCostOfCapital(unittest.TestCase):
    def test_capm(self) -> None:
        self.assertAlmostEqual(finance.capm_cost_of_equity(0.03, 1.2, 0.06), 0.102)

    def test_wacc(self) -> None:
        w = finance.wacc(600, 400, 0.10, 0.05, tax_rate=0.20)
        self.assertAlmostEqual(w, 0.076)


if __name__ == "__main__":
    unittest.main()
