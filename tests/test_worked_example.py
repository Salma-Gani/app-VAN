"""Régression sur le cas vérifiable documenté (docs/cas_verifiable.md)."""
from __future__ import annotations

import unittest

from ecoinvest.analytics import valuation_lab as lab
from ecoinvest.data import statements as stmt


class TestTmaWorkedExample(unittest.TestCase):
    def setUp(self) -> None:
        record = stmt.get_statement("TMA", fiscal_year=2024) or stmt.latest_statement("TMA")
        self.assertIsNotNone(record)
        self.f = stmt.to_fundamentals(record)

    def test_published_figures(self) -> None:
        self.assertAlmostEqual(self.f["net_income"], 844_618_182.50, places=2)
        self.assertAlmostEqual(self.f["shares"], 8_960_000.0, places=0)

    def test_eps_and_per_target(self) -> None:
        eps = self.f["net_income"] / self.f["shares"]
        self.assertAlmostEqual(eps, 94.2654, places=4)
        out = lab.target_entry("per", target=12.0, f=self.f, price=1345.0, required_margin=0.20)
        self.assertTrue(out["available"])
        self.assertAlmostEqual(out["fair_value"], 1_131.19, places=1)
        self.assertAlmostEqual(out["entry_price"], 904.95, places=1)

    def test_ev_ebitda_target(self) -> None:
        out = lab.target_entry("ev_ebitda", target=8.0, f=self.f, price=1345.0, required_margin=0.20)
        self.assertTrue(out["available"])
        # Calcul manuel (voir docs) : 1 551,21 MAD par action.
        self.assertAlmostEqual(out["fair_value"], 1_551.21, delta=1.0)


if __name__ == "__main__":
    unittest.main()
