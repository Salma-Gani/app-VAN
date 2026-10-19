from __future__ import annotations

import unittest

from ecoinvest.portfolio import simulate


class TestOptionFees(unittest.TestCase):
    def test_zero_return_zero_fee(self) -> None:
        res = simulate.simulate_option("Test", 1000, 1, 0.0, 0.0, tax=0.0, fee_rate=0.0)
        self.assertAlmostEqual(res["Valeur brute finale"], 1000.0)
        self.assertAlmostEqual(res["Valeur nette finale"], 1000.0)
        self.assertAlmostEqual(res["Frais estimés"], 0.0)

    def test_fees_reduce_net_value(self) -> None:
        res = simulate.simulate_option("Test", 1000, 1, 0.0, 0.0, tax=0.0, fee_rate=0.006)
        self.assertAlmostEqual(res["Frais estimés"], 6.0)
        self.assertAlmostEqual(res["Valeur nette finale"], 994.0)


if __name__ == "__main__":
    unittest.main()
