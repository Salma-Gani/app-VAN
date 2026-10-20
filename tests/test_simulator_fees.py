"""Tests des frais et de la référence de marché du simulateur."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ecoinvest.analytics import forecast


class TestFeesInMonteCarlo(unittest.TestCase):
    def test_fees_reduce_median_and_are_reported(self) -> None:
        gross = forecast.portfolio_fan_chart(100_000, 1_000, 0.08, 0.15, years=5, n_sims=500)
        net = forecast.portfolio_fan_chart(
            100_000, 1_000, 0.08, 0.15, years=5, n_sims=500,
            annual_fee=0.01, contribution_fee=0.006,
        )
        self.assertLess(net["final_median"], gross["final_median"])
        self.assertAlmostEqual(net["net_monthly"], 994.0)
        self.assertLess(net["net_annual_return"], 0.08)

    def test_zero_fees_leave_result_unchanged(self) -> None:
        base = forecast.portfolio_fan_chart(50_000, 500, 0.07, 0.12, years=3, n_sims=300)
        same = forecast.portfolio_fan_chart(
            50_000, 500, 0.07, 0.12, years=3, n_sims=300, annual_fee=0.0, contribution_fee=0.0
        )
        self.assertAlmostEqual(base["final_median"], same["final_median"])

    def test_projection_table_applies_fees(self) -> None:
        gross = forecast.projection_table(100_000, 1_000, 0.08, years=10)
        net = forecast.projection_table(
            100_000, 1_000, 0.08, years=10, annual_fee=0.01, contribution_fee=0.006
        )
        self.assertLess(float(net.iloc[-1]["Capital projeté"]), float(gross.iloc[-1]["Capital projeté"]))
        # Le capital versé reste le montant brut payé par l'investisseur.
        self.assertAlmostEqual(
            float(net.iloc[-1]["Versements cumulés"]), float(gross.iloc[-1]["Versements cumulés"])
        )


class TestAnnualizedStats(unittest.TestCase):
    def test_computes_cagr_from_real_dates(self) -> None:
        dates = pd.date_range("2020-01-01", periods=260, freq="B")
        values = 100 * (1.10 ** (np.arange(len(dates)) / 252.0))
        frame = pd.DataFrame({"date": dates, "value": values})
        stats = forecast.annualized_stats(frame)
        self.assertAlmostEqual(stats["cagr"], 0.10, delta=0.006)
        self.assertGreater(stats["volatility"], 0.0)
        self.assertEqual(stats["start"], "2020-01-01")

    def test_short_or_empty_history_returns_no_stats(self) -> None:
        self.assertEqual(forecast.annualized_stats(None), {})
        self.assertEqual(forecast.annualized_stats(pd.DataFrame()), {})
        short = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "value": [100, 101, 102, 103, 104],
        })
        self.assertEqual(forecast.annualized_stats(short), {})


if __name__ == "__main__":
    unittest.main()
