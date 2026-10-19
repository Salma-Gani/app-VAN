from __future__ import annotations

import unittest

from ecoinvest.analytics import valuation_lab as lab


class TestTargetPrices(unittest.TestCase):
    def test_per_target_price(self) -> None:
        self.assertAlmostEqual(lab.target_per_price(20, 12), 240.0)

    def test_per_rejects_negative_eps(self) -> None:
        self.assertIsNone(lab.target_per_price(20, -3))
        self.assertIsNone(lab.target_per_price(0, 12))
        self.assertIsNone(lab.target_per_price(20, None))

    def test_ev_ebitda_bridges_enterprise_to_equity(self) -> None:
        # EV = 8 × 1 000 = 8 000 ; equity = 8 000 − 200 = 7 800 ; /100 actions = 78
        self.assertAlmostEqual(lab.target_ev_ebitda_price(8, 1000, net_debt=200, shares=100), 78.0)

    def test_ev_ebitda_requires_shares(self) -> None:
        self.assertIsNone(lab.target_ev_ebitda_price(8, 1000, net_debt=200, shares=0))

    def test_ev_ebit_same_bridge(self) -> None:
        self.assertAlmostEqual(lab.target_ev_ebit_price(10, 500, net_debt=100, shares=50), 98.0)

    def test_pb_and_ps(self) -> None:
        self.assertAlmostEqual(lab.target_pb_price(2, 50), 100.0)
        self.assertAlmostEqual(lab.target_ps_price(1.5, 80), 120.0)

    def test_dividend_target(self) -> None:
        # 4 MAD de dividende pour un rendement exigé de 5 % => 80 MAD
        self.assertAlmostEqual(lab.target_dividend_price(4, 0.05), 80.0)

    def test_implied_multiple_and_margin(self) -> None:
        self.assertAlmostEqual(lab.implied_multiple(240, 12), 20.0)
        self.assertAlmostEqual(lab.margin_of_safety(240, 180), 0.25)
        self.assertAlmostEqual(lab.upside(240, 180), 1 / 3)
        self.assertAlmostEqual(lab.required_entry_price(240, 0.20), 192.0)

    def test_price_zone_does_not_issue_advice(self) -> None:
        zone = lab.price_zone(180, 192, 240)
        self.assertEqual(zone["key"], "below_entry")
        self.assertIn("ne constitue pas une recommandation", zone["text"])
        self.assertEqual(lab.price_zone(250, 192, 240)["key"], "above_fair")


class TestMethodCatalog(unittest.TestCase):
    def setUp(self) -> None:
        self.f = {
            "price": 20.0,
            "market_cap": 2000.0,
            "shares": 10.0,
            "net_income": 100.0,
            "eps": 10.0,
            "revenue": 1000.0,
            "ebitda": 200.0,
            "ebit": 150.0,
            "equity": 500.0,
            "total_debt": 200.0,
            "cash": 50.0,
            "dps": 2.0,
            "source": "Rapport annuel 2025",
            "fiscal_year": "2025",
            "as_of": "2026-03-31",
        }

    def test_catalog_marks_available_methods(self) -> None:
        catalog = {m["key"]: m for m in lab.method_catalog(self.f)}
        self.assertTrue(catalog["per"]["available"])
        self.assertTrue(catalog["ev_ebitda"]["available"])
        self.assertTrue(catalog["dividend"]["available"])
        self.assertAlmostEqual(catalog["per"]["current_ratio"], 2.0)
        self.assertAlmostEqual(catalog["ev_ebitda"]["current_ratio"], 10.75)
        self.assertAlmostEqual(catalog["dividend"]["current_ratio"], 0.10)
        self.assertEqual(catalog["per"]["source"], "Rapport annuel 2025")

    def test_missing_eps_is_explicit(self) -> None:
        catalog = {m["key"]: m for m in lab.method_catalog({"price": 20, "shares": 10})}
        self.assertFalse(catalog["per"]["available"])
        self.assertIn("BPA indisponible", catalog["per"]["reason"])


class TestTargetEntry(unittest.TestCase):
    def setUp(self) -> None:
        self.f = {
            "price": 180.0,
            "market_cap": 1800.0,
            "shares": 10.0,
            "net_income": 120.0,
            "eps": 12.0,
            "equity": 500.0,
            "dps": 4.0,
            "source": "États financiers 2025",
        }

    def test_per_entry_price(self) -> None:
        res = lab.target_entry("per", 20, self.f, required_margin=0.20)
        self.assertTrue(res["available"])
        self.assertAlmostEqual(res["fair_value"], 240.0)
        self.assertAlmostEqual(res["entry_price"], 192.0)
        self.assertEqual(res["zone"]["key"], "below_entry")
        self.assertAlmostEqual(res["upside"], 240 / 180 - 1)

    def test_dividend_entry_price(self) -> None:
        res = lab.target_entry("dividend", 0.05, self.f, required_margin=0.10)
        self.assertTrue(res["available"])
        self.assertAlmostEqual(res["fair_value"], 80.0)
        self.assertAlmostEqual(res["entry_price"], 72.0)

    def test_manual_override(self) -> None:
        res = lab.target_entry("per", 20, {"price": 100, "shares": 10},
                               metric_override=12, required_margin=0.0)
        self.assertTrue(res["available"])
        self.assertAlmostEqual(res["fair_value"], 240.0)

    def test_sensitivity_rows(self) -> None:
        table = lab.sensitivity("per", 20, self.f, steps=9, required_margin=0.20)
        self.assertEqual(len(table), 9)
        self.assertTrue(table["Disponible"].all())
        # La colonne doit rester croissante avec le multiple cible.
        values = table["Prix théorique"].tolist()
        self.assertTrue(all(b > a for a, b in zip(values, values[1:])))

    def test_format_yield_input(self) -> None:
        self.assertAlmostEqual(lab.format_target_input("dividend", 5.0), 0.05)
        self.assertAlmostEqual(lab.format_target_input("per", 20.0), 20.0)


if __name__ == "__main__":
    unittest.main()
