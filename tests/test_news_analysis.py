from __future__ import annotations

import unittest

import pandas as pd

from ecoinvest.data import news


class TestCategory(unittest.TestCase):
    def test_results(self) -> None:
        self.assertEqual(news.classify_category("Résultats annuels : le bénéfice progresse"), "Résultats")

    def test_monetary_policy(self) -> None:
        self.assertEqual(
            news.classify_category("Bank Al-Maghrib relève le taux directeur"), "Politique monétaire"
        )

    def test_dividend(self) -> None:
        self.assertEqual(news.classify_category("Un dividende de 5 MAD par action"), "Dividendes")

    def test_fallback(self) -> None:
        self.assertEqual(news.classify_category("Une journée ensoleillée à Casablanca"), "Général")


class TestImpact(unittest.TestCase):
    def test_high_impact_factor(self) -> None:
        out = news.impact_of("Augmentation de capital de 1 milliard de dirhams")
        self.assertEqual(out["level"], "Élevé")
        self.assertIn("augmentation de capital", out["reason"])

    def test_low_impact_when_no_factor(self) -> None:
        out = news.impact_of("Le salon de l'automobile ouvre ses portes")
        self.assertEqual(out["level"], "Faible")

    def test_medium_for_regulation(self) -> None:
        out = news.impact_of("L'AMMC publie une nouvelle circulaire")
        self.assertIn(out["level"], {"Moyen", "Élevé"})

    def test_impact_is_independent_from_sentiment(self) -> None:
        # Ton neutre mais événement matériel : l'impact ne doit pas dépendre du sentiment.
        text = "Assemblée générale : projet d'augmentation de capital"
        self.assertEqual(news.impact_of(text)["level"], "Élevé")
        self.assertAlmostEqual(news.score_text(text), 0.0, places=2)


class TestEnrich(unittest.TestCase):
    def test_columns_added(self) -> None:
        df = pd.DataFrame(
            [
                {"title": "Résultats record", "summary": "Le bénéfice grimpe de 20 %"},
                {"title": "Séance calme", "summary": "Le marché évolue peu"},
            ]
        )
        out = news.enrich_news(df)
        for col in ("category", "impact_level", "impact_reason"):
            self.assertIn(col, out.columns)
        self.assertEqual(out.loc[0, "category"], "Résultats")

    def test_empty_is_safe(self) -> None:
        self.assertTrue(news.enrich_news(pd.DataFrame()).empty)


class TestHoldingsRelevance(unittest.TestCase):
    def _df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"title": "Attijariwafa Bank dévoile ses résultats", "summary": "", "scope": "BVC"},
                {"title": "ATW annonce un dividende", "summary": "", "scope": "BVC"},
                {"title": "Météo du week-end", "summary": "", "scope": ""},
            ]
        )

    def test_name_and_symbol_matches(self) -> None:
        holdings = [{"symbol": "ATW", "name": "Attijariwafa Bank"}]
        out = news.holdings_relevance(self._df(), holdings)
        self.assertIn("held", out.columns)
        self.assertTrue(out.loc[0, "held"])
        self.assertTrue(out.loc[1, "held"])
        self.assertEqual(out.loc[2, "held"], "")

    def test_no_holdings_is_safe(self) -> None:
        out = news.holdings_relevance(self._df(), [])
        self.assertEqual(set(out["held"].tolist()), {""})


if __name__ == "__main__":
    unittest.main()
