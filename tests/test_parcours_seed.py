"""Tests des états AMMC ajoutés et des calculs du parcours guidé.

Les valeurs attendues sont celles des rapports 2024 :
- Maroc Telecom, comptes consolidés IFRS, pages 24-26 ;
- Attijariwafa bank, comptes consolidés, pages 95-96 ;
- Cosumar, comptes consolidés IFRS, pages 124-126.
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ecoinvest.data import fundamentals, statements as stmt
from ecoinvest.ui.pages import parcours_page, sector_page


class TestAmmcSeedRatios(unittest.TestCase):
    def test_iam_consolidated_ratios(self) -> None:
        f = stmt.fundamentals_for("IAM")
        self.assertAlmostEqual(f["revenue"], 36_699_000_000.0, places=2)
        self.assertAlmostEqual(f["net_income"], 1_801_000_000.0, places=2)
        # Part du groupe, et non total incluant les minoritaires (18,702 Md).
        self.assertAlmostEqual(f["equity"], 14_908_000_000.0, places=2)
        self.assertAlmostEqual(f["eps"], 2.05, places=4)
        self.assertAlmostEqual(f["interest_expense"], 1_074_000_000.0, places=2)

        f["dps"] = 4.0
        price = 40.0
        cap = price * f["shares"]
        ratios = fundamentals.compute_ratios(
            f, price=price, cap=cap, sector="Télécommunications"
        )
        self.assertAlmostEqual(ratios["per"], price / 2.05, places=6)
        self.assertAlmostEqual(ratios["pb"], price / (14_908_000_000.0 / f["shares"]), places=6)
        self.assertAlmostEqual(ratios["roe"], 1_801_000_000.0 / 14_908_000_000.0, places=6)
        self.assertAlmostEqual(ratios["net_margin"], 1_801_000_000.0 / 36_699_000_000.0, places=6)
        self.assertAlmostEqual(ratios["dividend_yield"], 0.1, places=6)
        self.assertAlmostEqual(ratios["interest_coverage"], 6_062_000_000.0 / 1_074_000_000.0, places=6)
        self.assertLess(ratios["fcf_yield"], 0)

    def test_atw_bank_ratios_exclude_corporate_multiples(self) -> None:
        f = stmt.fundamentals_for("ATW")
        price = 200.0
        cap = price * f["shares"]
        ratios = fundamentals.compute_ratios(f, price=price, cap=cap, sector="Banques")
        self.assertAlmostEqual(ratios["per"], price / 44.18, places=6)
        # Part du groupe, et non total incluant les minoritaires (72,503 Md).
        self.assertAlmostEqual(f["equity"], 62_456_132_000.0, places=2)
        self.assertAlmostEqual(ratios["roe"], 9_504_486_000.0 / 62_456_132_000.0, places=6)
        self.assertAlmostEqual(ratios["net_margin"], 9_504_486_000.0 / 34_507_117_000.0, places=6)
        for key in ("ev_ebitda", "ev_sales", "debt_to_equity", "current_ratio",
                    "interest_coverage", "net_debt_to_ebitda"):
            self.assertIsNone(ratios[key], key)

    def test_bcp_and_boa_bank_ratios(self) -> None:
        cases = {
            "BCP": (250.0, 20.39, 37_043_849_000.0 / 203_312_473),
            "BOA": (200.0, 15.88, 29_129_447_000.0 / 215_786_333),
        }
        for symbol, (price, eps, bvps) in cases.items():
            f = stmt.fundamentals_for(symbol)
            cap = price * f["shares"]
            ratios = fundamentals.compute_ratios(f, price=price, cap=cap, sector="Banques")
            self.assertAlmostEqual(ratios["per"], price / eps, places=5, msg=symbol)
            self.assertAlmostEqual(ratios["pb"], price / bvps, places=4, msg=symbol)
            self.assertGreater(ratios["roe"], 0.10, symbol)
            for key in ("ev_ebitda", "ev_sales", "debt_to_equity", "current_ratio",
                        "interest_coverage", "net_debt_to_ebitda"):
                self.assertIsNone(ratios[key], f"{symbol}:{key}")

    def test_csr_industrial_ratios(self) -> None:
        f = stmt.fundamentals_for("CSR")
        price = 175.0
        cap = price * f["shares"]
        ratios = fundamentals.compute_ratios(
            f, price=price, cap=cap, sector="Agroalimentaire et Production"
        )
        # Part du groupe (5 878,5 M), et non total incluant les minoritaires (5 885,6 M).
        self.assertAlmostEqual(f["equity"], 5_878_500_000.0, places=2)
        self.assertAlmostEqual(ratios["roe"], 850_400_000.0 / 5_878_500_000.0, places=6)
        self.assertAlmostEqual(ratios["net_margin"], 850_400_000.0 / 10_238_600_000.0, places=6)
        self.assertAlmostEqual(ratios["current_ratio"], 8_118_500_000.0 / 5_730_200_000.0, places=6)
        self.assertAlmostEqual(ratios["interest_coverage"], 1_332_600_000.0 / 35_300_000.0, places=6)
        self.assertGreater(ratios["fcf_yield"], 0)

    def test_bank_statement_ratios_mark_non_applicable_metrics(self) -> None:
        record = stmt.latest_statement("BCP")
        frame = stmt.ratios_for(
            record,
            {"close": 250.0, "cap": 250.0 * record["balance"]["shares"], "sector": "Banques"},
        )
        statuses = dict(zip(frame["Indicateur"], frame["Statut"]))
        for label in ("Marge brute", "Levier financier", "Liquidité générale",
                      "Couverture des intérêts", "FCF / chiffre d'affaires", "EV / EBITDA"):
            self.assertEqual(statuses[label], "Non pertinent", label)
        self.assertEqual(statuses["PER"], "Calculé")
        self.assertEqual(statuses["ROE"], "Calculé")

    def test_records_carry_page_level_evidence(self) -> None:
        record = stmt.latest_statement("IAM")
        lines = record.get("lines") or {}
        pages = {
            item.get("page")
            for block in lines.values()
            for item in block
            if isinstance(item, dict)
        }
        self.assertIn(24, pages)
        self.assertIn(25, pages)
        self.assertIn(26, pages)

    def test_source_units_are_explicit(self) -> None:
        expected = {
            "IAM": "millions MAD",
            "ATW": "milliers MAD",
            "CSR": "millions MAD",
            "BCP": "milliers MAD",
            "BOA": "milliers MAD",
        }
        for symbol, source_unit in expected.items():
            record = stmt.latest_statement(symbol)
            self.assertEqual(record.get("source_unit"), source_unit, symbol)
            self.assertEqual(record.get("unit"), "MAD", symbol)


class TestSectorDefault(unittest.TestCase):
    def test_default_sector_prefers_ratios_over_size(self) -> None:
        table = pd.DataFrame(
            {
                "symbol": ["A", "B", "C", "D", "E", "F", "G"],
                "sector": ["Peuplé"] * 5 + ["Couvert"] * 2,
                "cap": [100.0] * 7,
                "r_per": [np.nan] * 5 + [10.0, 12.0],
                "r_pb": [np.nan] * 5 + [1.0, 1.2],
                "r_roe": [np.nan] * 5 + [0.12, 0.14],
                "r_net_margin": [np.nan] * 5 + [0.08, 0.09],
                "r_revenue_growth": [np.nan] * 5 + [0.05, 0.06],
            }
        )
        sectors = ["Peuplé", "Couvert"]
        self.assertEqual(sector_page._default_sector_index(table, sectors), 1)

    def test_default_sector_falls_back_to_largest(self) -> None:
        table = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "sector": ["Petit", "Grand", "Grand"],
                "cap": [1.0, 2.0, 3.0],
                "r_per": [np.nan, np.nan, np.nan],
            }
        )
        self.assertEqual(sector_page._default_sector_index(table, ["Petit", "Grand"]), 1)


class TestParcoursHelpers(unittest.TestCase):
    def test_perimeter_labels(self) -> None:
        self.assertEqual(parcours_page._perimeter({"consolidated": True}), "comptes consolidés")
        self.assertEqual(parcours_page._perimeter({"consolidated": False}), "comptes sociaux")
        self.assertEqual(parcours_page._perimeter({"consolidated": None}), "périmètre non renseigné")
        self.assertEqual(parcours_page._perimeter(None), "non couvert")

    def test_gap_never_divides_by_zero(self) -> None:
        self.assertAlmostEqual(parcours_page._gap(11.0, 10.0), 0.1)
        self.assertIsNone(parcours_page._gap(None, 10.0))
        self.assertIsNone(parcours_page._gap(10.0, None))
        self.assertIsNone(parcours_page._gap(10.0, 0.0))

    def test_ratio_formatting(self) -> None:
        self.assertEqual(parcours_page._ratio_value("per", 12.345), "12,35x")
        self.assertEqual(parcours_page._ratio_value("roe", 0.1234), "12,3 %")
        self.assertEqual(parcours_page._ratio_value("per", None), "—")
        self.assertEqual(parcours_page._ratio_value("per", -3.0), "n.s.")

    def test_sector_median_ignores_missing_values(self) -> None:
        table = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "sector": ["S", "S", "T"],
                "r_per": [10.0, np.nan, 30.0],
            }
        )
        median, count = parcours_page._sector_median(table, "S", "per")
        self.assertEqual(median, 10.0)
        self.assertEqual(count, 1)
        missing, count_missing = parcours_page._sector_median(table, "S", "pb")
        self.assertIsNone(missing)
        self.assertEqual(count_missing, 0)


if __name__ == "__main__":
    unittest.main()
