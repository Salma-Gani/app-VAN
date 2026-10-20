"""Tests du moteur de comparaison sectorielle.

Vérifient notamment l'absence de zéro de remplissage, l'exclusion des multiples
d'entreprise pour les banques/assurances et le calcul des médianes.
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ecoinvest.analytics import sector_compare


def sample_market() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "symbol": "AAA", "name": "Alpha", "sector": "Banques",
            "cap": 1000.0, "close": 10.0, "return_12m": 0.10, "volatility": 0.20,
            "max_drawdown": -0.15, "r_dividend_yield": 0.04,
            "r_per": 8.0, "r_pb": 1.2, "r_ev_ebitda": 5.0, "r_roe": 0.14,
            "r_net_margin": 0.20, "r_debt_to_equity": 3.0, "r_revenue_growth": 0.05,
            "has_fundamentals": True,
        },
        {
            "symbol": "BBB", "name": "Beta", "sector": "Banques",
            "cap": 500.0, "close": 5.0, "return_12m": np.nan, "volatility": 0.30,
            "max_drawdown": -0.25, "r_dividend_yield": np.nan,
            "r_per": 12.0, "r_pb": np.nan, "r_ev_ebitda": np.nan, "r_roe": np.nan,
            "r_net_margin": np.nan, "r_debt_to_equity": np.nan, "r_revenue_growth": np.nan,
            "has_fundamentals": False,
        },
        {
            "symbol": "CCC", "name": "Gamma", "sector": "Industrie",
            "cap": 2000.0, "close": 20.0, "return_12m": 0.25, "volatility": 0.18,
            "max_drawdown": -0.10, "r_dividend_yield": 0.02,
            "r_per": 15.0, "r_pb": 2.0, "r_ev_ebitda": 9.0, "r_roe": 0.18,
            "r_net_margin": 0.12, "r_debt_to_equity": 0.8, "r_revenue_growth": 0.10,
            "has_fundamentals": True,
        },
    ])


def sample_store():
    return {
        "AAA": [{
            "fiscal_year": 2024, "period": "FY", "consolidated": False,
            "source": "AMMC — RFA 2024", "source_url": "https://example.test/a.pdf",
            "currency": "MAD", "unit": "MAD",
        }],
        "BBB": [{
            "fiscal_year": 2023, "period": "FY", "consolidated": True,
            "source": "AMMC — RFA 2023", "source_url": "https://example.test/b.pdf",
            "currency": "MAD", "unit": "MILLIONS",
        }],
    }


class TestSectorDetection(unittest.TestCase):
    def test_financial_sectors(self) -> None:
        for sector in ("Banques", "Assurances", "Sociétés de financement et Autres Activités Financières"):
            self.assertTrue(sector_compare.is_financial_sector(sector))
        for sector in ("Mines", "Agroalimentaire et Production", "Télécommunications"):
            self.assertFalse(sector_compare.is_financial_sector(sector))

    def test_applicable_metrics_exclude_enterprise_multiples(self) -> None:
        keys = {m["key"] for m in sector_compare.applicable_metrics("Banques")}
        self.assertNotIn("r_ev_ebitda", keys)
        self.assertNotIn("r_debt_to_equity", keys)
        self.assertIn("r_per", keys)
        self.assertIn("r_roe", keys)
        keys_ind = {m["key"] for m in sector_compare.applicable_metrics("Mines")}
        self.assertIn("r_ev_ebitda", keys_ind)
        self.assertIn("r_debt_to_equity", keys_ind)


class TestComparisonFrame(unittest.TestCase):
    def test_missing_values_stay_nan_and_never_zero(self) -> None:
        frame, _ = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        beta = frame[frame["symbol"] == "BBB"].iloc[0]
        self.assertTrue(np.isnan(beta["r_pb"]))
        self.assertTrue(np.isnan(beta["r_roe"]))
        self.assertTrue(np.isnan(beta["return_12m"]))
        self.assertNotEqual(beta["r_pb"], 0)

    def test_financial_sector_neutralises_ev_and_leverage(self) -> None:
        frame, _ = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        alpha = frame[frame["symbol"] == "AAA"].iloc[0]
        self.assertTrue(np.isnan(alpha["r_ev_ebitda"]))
        self.assertTrue(np.isnan(alpha["r_debt_to_equity"]))
        self.assertAlmostEqual(float(alpha["r_per"]), 8.0)

    def test_industrial_sector_keeps_ev_and_leverage(self) -> None:
        frame, _ = sector_compare.comparison_frame(sample_market(), "Industrie", store=sample_store())
        gamma = frame[frame["symbol"] == "CCC"].iloc[0]
        self.assertAlmostEqual(float(gamma["r_ev_ebitda"]), 9.0)
        self.assertAlmostEqual(float(gamma["r_debt_to_equity"]), 0.8)

    def test_metadata_follows_latest_statement(self) -> None:
        _, metadata = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        self.assertEqual(metadata["AAA"]["fiscal_year"], 2024)
        self.assertFalse(metadata["AAA"]["consolidated"])
        self.assertEqual(metadata["BBB"]["fiscal_year"], 2023)
        self.assertTrue(metadata["BBB"]["consolidated"])
        self.assertEqual(metadata["BBB"]["unit"], "MILLIONS")

    def test_sorted_by_market_cap(self) -> None:
        frame, _ = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        self.assertEqual(frame["symbol"].tolist(), ["AAA", "BBB"])

    def test_unknown_sector_returns_empty_frame(self) -> None:
        frame, metadata = sector_compare.comparison_frame(sample_market(), "Inexistant", store={})
        self.assertTrue(frame.empty)
        self.assertEqual(metadata, {})


class TestMedians(unittest.TestCase):
    def test_median_ignores_missing_and_reports_count(self) -> None:
        frame, _ = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        medians = sector_compare.sector_medians(frame, "Banques")
        self.assertAlmostEqual(medians["r_per"]["value"], 10.0)  # (8 + 12) / 2
        self.assertEqual(medians["r_per"]["count"], 2)
        self.assertEqual(medians["r_roe"]["count"], 1)
        self.assertAlmostEqual(medians["r_roe"]["value"], 0.14)
        self.assertTrue(medians["r_ev_ebitda"]["applicable"] is False)
        self.assertIsNone(medians["r_ev_ebitda"]["value"])

    def test_no_median_when_no_value(self) -> None:
        frame, _ = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        medians = sector_compare.sector_medians(frame, "Banques")
        self.assertIsNone(medians["r_ev_ebitda"]["value"])
        self.assertEqual(medians["r_ev_ebitda"]["count"], 0)
        self.assertAlmostEqual(medians["r_net_margin"]["value"], 0.20)
        self.assertEqual(medians["r_net_margin"]["count"], 1)


class TestOverview(unittest.TestCase):
    def test_overview_counts_and_coverage(self) -> None:
        overview = sector_compare.sector_overview(sample_market())
        banks = overview[overview["Secteur"] == "Banques"].iloc[0]
        self.assertEqual(int(banks["Valeurs"]), 2)
        self.assertEqual(int(banks["Valeurs avec ratios"]), 2)
        self.assertAlmostEqual(float(banks["P/E médian"]), 10.0)
        self.assertAlmostEqual(float(banks["Capitalisation médiane"]), 750.0)

    def test_overview_without_sector_column(self) -> None:
        self.assertTrue(sector_compare.sector_overview(pd.DataFrame({"x": [1]})).empty)

    def test_overview_metric_columns_exist(self) -> None:
        from ecoinvest.ui.pages import sector_page

        overview = sector_compare.sector_overview(sample_market())
        for column, metric_key in sector_page.OVERVIEW_METRICS.values():
            self.assertIn(column, overview.columns)
            self.assertIn(metric_key, sector_compare.METRIC_BY_KEY)


class TestRanking(unittest.TestCase):
    def test_higher_is_better(self) -> None:
        series = pd.Series([1.0, 2.0, 3.0])
        self.assertEqual(sector_compare.rank_position(3.0, series, "higher"), 100.0)
        self.assertEqual(sector_compare.rank_position(1.0, series, "higher"), 0.0)

    def test_lower_is_better(self) -> None:
        series = pd.Series([10.0, 20.0, 30.0])
        self.assertEqual(sector_compare.rank_position(10.0, series, "lower"), 100.0)
        self.assertEqual(sector_compare.rank_position(30.0, series, "lower"), 0.0)

    def test_single_value_and_missing(self) -> None:
        self.assertEqual(sector_compare.rank_position(5.0, pd.Series([5.0]), "higher"), 100.0)
        self.assertIsNone(sector_compare.rank_position(None, pd.Series([1.0]), "higher"))
        self.assertIsNone(sector_compare.rank_position(np.nan, pd.Series([1.0]), "higher"))


class TestComparability(unittest.TestCase):
    def test_no_statement_message(self) -> None:
        notes = sector_compare.comparability_notes({"AAA": {"has_statement": False}}, "Mines")
        self.assertTrue(notes)
        self.assertIn("Aucune société", notes[0])

    def test_different_years_and_consolidation(self) -> None:
        _, metadata = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        notes = " ".join(sector_compare.comparability_notes(metadata, "Banques"))
        self.assertIn("Exercices différents", notes)
        self.assertIn("sociaux et consolidés", notes)
        self.assertIn("Secteur financier", notes)

    def test_coverage_summary(self) -> None:
        frame, _ = sector_compare.comparison_frame(sample_market(), "Banques", store=sample_store())
        coverage = sector_compare.coverage_summary(frame)
        self.assertEqual(coverage["total"], 2)
        self.assertEqual(coverage["with_statement"], 2)
        self.assertEqual(coverage["with_ratios"], 2)
        self.assertEqual(coverage["market_only"], 0)

    def test_unknown_perimeter_is_not_assumed_social(self) -> None:
        store = {"AAA": [{"fiscal_year": 2024, "source": "AMMC"}]}
        _, metadata = sector_compare.comparison_frame(sample_market(), "Banques", store=store)
        self.assertIsNone(metadata["AAA"]["consolidated"])
        self.assertIsNone(metadata["AAA"]["currency"])
        self.assertIsNone(metadata["AAA"]["unit"])

    def test_unknown_perimeter_not_treated_as_social(self) -> None:
        metadata = {
            "A": {"has_statement": True, "consolidated": True, "fiscal_year": 2024},
            "B": {"has_statement": True, "consolidated": None, "fiscal_year": 2024},
        }
        text = " ".join(sector_compare.comparability_notes(metadata, "Mines"))
        self.assertNotIn("sociaux et consolidés", text)

    def test_financial_note_even_without_statements(self) -> None:
        notes = sector_compare.comparability_notes({"AAA": {"has_statement": False}}, "Banques")
        text = " ".join(notes)
        self.assertIn("Aucune société", text)
        self.assertIn("Secteur financier", text)


if __name__ == "__main__":
    unittest.main()
