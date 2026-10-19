from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ecoinvest.analytics import backtest


def _series(values) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2025-01-01", periods=len(values), freq="B"),
                     dtype=float)


class TestSignals(unittest.TestCase):
    def test_ma_cross_returns_binary_positions(self) -> None:
        prices = _series(np.linspace(100, 200, 120))
        signal = backtest.ma_cross_signals(prices, 10, 30)
        self.assertEqual(len(signal), len(prices))
        self.assertTrue(set(signal.unique()).issubset({0.0, 1.0}))

    def test_rsi_reversion_toggles(self) -> None:
        values = list(np.linspace(100, 80, 40)) + list(np.linspace(80, 120, 40))
        signal = backtest.rsi_reversion_signals(_series(values), low=30, high=70)
        self.assertTrue(set(signal.unique()).issubset({0.0, 1.0}))
        self.assertEqual(signal.iloc[0], 0.0)


class TestRun(unittest.TestCase):
    def _prices(self) -> pd.Series:
        return _series(np.linspace(100, 160, 100))

    def test_insufficient_history_is_refused(self) -> None:
        result = backtest.run(_series([100, 101, 102]), [1, 1, 1])
        self.assertFalse(result["available"])
        self.assertIn("insuffisant", result["reason"])

    def test_buy_and_hold_matches_market_without_costs(self) -> None:
        prices = self._prices()
        result = backtest.run(prices, pd.Series(1.0, index=prices.index), cost_bps=0.0)
        strategy = result["metrics"]["total_return"]
        market = result["buy_hold"]["total_return"]
        self.assertAlmostEqual(strategy, market, places=6)

    def test_costs_reduce_performance(self) -> None:
        prices = self._prices()
        # Alternating position forces many round trips.
        signals = pd.Series([1.0 if i % 2 == 0 else 0.0 for i in range(len(prices))],
                            index=prices.index)
        free = backtest.run(prices, signals, cost_bps=0.0)["metrics"]["total_return"]
        charged = backtest.run(prices, signals, cost_bps=50.0)["metrics"]["total_return"]
        self.assertLess(charged, free)

    def test_no_look_ahead_on_signal_day(self) -> None:
        values = [100.0] * 90
        values[70] = 200.0  # saut brutal un seul jour
        prices = _series(values)
        signals = pd.Series(0.0, index=prices.index)
        signals.iloc[70] = 1.0  # signal connu le jour même du saut
        result = backtest.run(prices, signals, cost_bps=0.0)
        # La position est décalée d'un rang : le saut du jour 70 n'est pas capté.
        self.assertEqual(result["position"].iloc[70], 0.0)
        self.assertAlmostEqual(result["returns"].iloc[70], 0.0, places=9)

    def test_signal_captures_next_day_move(self) -> None:
        values = [100.0] * 90
        values[71] = 200.0
        prices = _series(values)
        signals = pd.Series(0.0, index=prices.index)
        signals.iloc[70] = 1.0  # décidé en clôture du jour 70
        result = backtest.run(prices, signals, cost_bps=0.0)
        self.assertGreater(result["returns"].iloc[71], 0.5)

    def test_metrics_are_bounded(self) -> None:
        prices = self._prices()
        result = backtest.run(prices, backtest.ma_cross_signals(prices, 10, 30))
        metrics = result["metrics"]
        self.assertIsNotNone(metrics["max_drawdown"])
        self.assertLessEqual(metrics["max_drawdown"], 0.0)
        self.assertGreaterEqual(metrics["exposure"], 0.0)
        self.assertLessEqual(metrics["exposure"], 1.0)


class TestWalkForward(unittest.TestCase):
    def test_walk_forward_splits_and_selects(self) -> None:
        rng = np.random.default_rng(42)
        values = 100 + np.cumsum(rng.normal(0.2, 1.5, 300))
        values = np.maximum(values, 5.0)
        result = backtest.walk_forward(_series(values), "ma_cross", train_frac=0.6, cost_bps=25.0)
        self.assertTrue(result["available"])
        self.assertIn("fast", result["best_params"])
        self.assertGreater(result["in_sample"]["sessions"], result["out_of_sample"]["sessions"])
        self.assertAlmostEqual(result["in_sample"]["sessions"] + result["out_of_sample"]["sessions"],
                               len(values), delta=1)

    def test_walk_forward_refuses_short_history(self) -> None:
        result = backtest.walk_forward(_series(np.linspace(100, 110, 50)))
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
