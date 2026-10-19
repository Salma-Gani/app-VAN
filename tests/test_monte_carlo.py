from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ecoinvest.analytics import forecast


def _prices(n: int = 260, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    values = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)))
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=n, freq="B"), dtype=float)


class TestValuationMonteCarlo(unittest.TestCase):
    def _run(self, **kwargs):
        return forecast.monte_carlo_valuation(
            fcf_start=100_000_000.0,
            growth_mean=0.05,
            discount_rate=0.10,
            net_debt=50_000_000.0,
            shares=1_000_000.0,
            years=5,
            terminal_growth=0.02,
            n_sims=2000,
            price=120.0,
            **kwargs,
        )

    def test_percentiles_are_ordered(self) -> None:
        out = self._run()
        self.assertLessEqual(out["p5"], out["p25"])
        self.assertLessEqual(out["p25"], out["p50"])
        self.assertLessEqual(out["p50"], out["p75"])
        self.assertLessEqual(out["p75"], out["p95"])
        self.assertEqual(out["p50"], out["median"])

    def test_reproducible_with_seed(self) -> None:
        a, b = self._run(seed=42), self._run(seed=42)
        self.assertAlmostEqual(a["median"], b["median"], places=6)
        self.assertAlmostEqual(a["p5"], b["p5"], places=6)
        c = self._run(seed=43)
        self.assertNotAlmostEqual(a["median"], c["median"], places=6)

    def test_probability_is_a_fraction(self) -> None:
        out = self._run()
        self.assertGreaterEqual(out["prob_undervalued"], 0.0)
        self.assertLessEqual(out["prob_undervalued"], 1.0)
        self.assertEqual(len(out["values"]), 2000)

    def test_assumptions_are_exposed(self) -> None:
        out = self._run(seed=5)
        self.assertEqual(out["assumptions"]["seed"], 5)
        self.assertEqual(out["assumptions"]["n_sims"], 2000)


class TestPriceMonteCarlo(unittest.TestCase):
    def test_refuses_short_history(self) -> None:
        out = forecast.price_monte_carlo(_prices(30))
        self.assertFalse(out["available"])
        self.assertIn("insuffisant", out["reason"].lower())

    def test_paths_start_at_last_close_and_stay_positive(self) -> None:
        prices = _prices(260)
        out = forecast.price_monte_carlo(prices, horizon_days=126, n_sims=500, seed=3)
        self.assertTrue(out["available"])
        self.assertAlmostEqual(out["start"], float(prices.iloc[-1]), places=6)
        self.assertGreater(out["final"].min(), 0.0)
        self.assertEqual(out["sample"].shape[1], out["percentiles"]["p50"].shape[0])

    def test_percentiles_and_probabilities(self) -> None:
        out = forecast.price_monte_carlo(_prices(260), horizon_days=252, n_sims=1000, seed=9)
        pct = out["percentiles"]
        self.assertTrue(np.all(pct["p5"] <= pct["p25"]))
        self.assertTrue(np.all(pct["p25"] <= pct["p50"]))
        self.assertTrue(np.all(pct["p50"] <= pct["p75"]))
        self.assertTrue(np.all(pct["p75"] <= pct["p95"]))
        self.assertAlmostEqual(out["prob_above"] + out["prob_below"], 1.0, places=6)
        self.assertAlmostEqual(out["median_final"], float(np.median(out["final"])), places=6)

    def test_reproducible_with_seed(self) -> None:
        prices = _prices(200)
        a = forecast.price_monte_carlo(prices, n_sims=400, seed=11)
        b = forecast.price_monte_carlo(prices, n_sims=400, seed=11)
        self.assertAlmostEqual(a["median_final"], b["median_final"], places=6)
        c = forecast.price_monte_carlo(prices, n_sims=400, seed=12)
        self.assertNotAlmostEqual(a["median_final"], c["median_final"], places=6)

    def test_zero_volatility_stays_near_start(self) -> None:
        prices = _prices(150)
        out = forecast.price_monte_carlo(prices, horizon_days=63, n_sims=50, seed=1,
                                         drift=0.0, volatility=1e-6)
        self.assertAlmostEqual(out["median_final"], out["start"], delta=out["start"] * 1e-3)

    def test_user_parameters_are_flagged_as_such(self) -> None:
        out = forecast.price_monte_carlo(_prices(150), drift=0.08, volatility=0.30, n_sims=100)
        self.assertEqual(out["drift_source"], "paramètre utilisateur")
        self.assertEqual(out["volatility_source"], "paramètre utilisateur")


class TestPortfolioFan(unittest.TestCase):
    def test_has_tight_and_wide_bands(self) -> None:
        out = forecast.portfolio_fan_chart(100_000.0, 1000.0, 0.07, 0.15, years=5,
                                           n_sims=500, seed=2)
        self.assertIn("p5", out["percentiles"])
        self.assertIn("p95", out["percentiles"])
        self.assertLess(out["final_p5"], out["final_p95"])
        self.assertLessEqual(out["final_p5"], out["final_median"])
        self.assertLessEqual(out["final_median"], out["final_p95"])


if __name__ == "__main__":
    unittest.main()
