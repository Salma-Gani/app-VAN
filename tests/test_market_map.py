"""Carte thermique, largeur de marché et couleurs d'actualités.

Ces tests vérifient la **structure** du treemap (nœuds sectoriels explicites,
valeurs manquantes en gris) sans dépendre d'un rendu navigateur.
"""
from __future__ import annotations

import unittest

import pandas as pd

from ecoinvest.ui import charts
from ecoinvest.ui.pages import news_page


def _frame():
    return pd.DataFrame({
        "symbol": ["AAA", "BBB", "CCC", "DDD"],
        "name": ["Alpha", "Beta", "Gamma", "Delta"],
        "sector": ["Banques", "Banques", "Mines", "Mines"],
        "cap": [100.0, 50.0, 30.0, 20.0],
        "close": [10.0, 20.0, 30.0, 40.0],
        "change_pct": [0.02, -0.01, None, 0.0],
        "volume": [1000, 2000, 0, 500],
        "return_12m": [0.10, None, 0.05, -0.03],
        "ytd_pct": [0.05, -0.02, 0.01, None],
    })


class TestTreemap(unittest.TestCase):
    def test_sector_nodes_are_explicit_parents(self) -> None:
        fig = charts.sector_treemap(_frame(), height=300)
        trace = fig.data[0]
        self.assertEqual(len(trace.labels), 6)  # 2 secteurs + 4 valeurs
        self.assertEqual(list(trace.parents[:2]), ["", ""])
        self.assertTrue(all(p in {"Banques", "Mines"} for p in trace.parents[2:]))
        # branchvalues total exige que les secteurs portent la somme de leurs enfants.
        self.assertEqual(trace.branchvalues, "total")

    def test_sector_value_equals_sum_of_members(self) -> None:
        fig = charts.sector_treemap(_frame(), height=300)
        trace = fig.data[0]
        values = dict(zip(trace.labels, trace.values))
        self.assertAlmostEqual(values["Banques"], 150.0)
        self.assertAlmostEqual(values["Mines"], 50.0)

    def test_missing_performance_is_grey_not_zero(self) -> None:
        fig = charts.sector_treemap(_frame(), height=300)
        colors = list(fig.data[0].marker.colors)
        labels = list(fig.data[0].labels)
        idx = labels.index("CCC · Gamma")
        from ecoinvest.config import COLORS

        self.assertEqual(colors[idx], COLORS["muted"])

    def test_zero_change_is_neutral_grey_family(self) -> None:
        fig = charts.sector_treemap(_frame(), height=300)
        labels = list(fig.data[0].labels)
        colors = list(fig.data[0].marker.colors)
        from ecoinvest.config import COLORS

        self.assertNotIn(colors[labels.index("DDD · Delta")], {COLORS["up"], COLORS["down"]})

    def test_rows_without_cap_are_dropped(self) -> None:
        frame = _frame()
        frame.loc[0, "cap"] = None
        fig = charts.sector_treemap(frame, height=300)
        self.assertNotIn("AAA · Alpha", list(fig.data[0].labels))

    def test_empty_frame_shows_explicit_state(self) -> None:
        fig = charts.sector_treemap(pd.DataFrame(), height=300)
        self.assertIn("Aucune", str(fig.layout.title.text or ""))


class TestNewsColors(unittest.TestCase):
    def test_five_levels_map_to_green_grey_red(self) -> None:
        style = news_page._SENTIMENT_STYLE
        self.assertEqual(set(style), {"Très positif", "Positif", "Neutre", "Négatif", "Très négatif"})
        self.assertIn("very-pos", style["Très positif"][0])
        self.assertIn("pos", style["Positif"][0])
        self.assertIn("neu", style["Neutre"][0])
        self.assertIn("neg", style["Négatif"][0])
        self.assertIn("very-neg", style["Très négatif"][0])
        # Vert pour les positifs, rouge pour les négatifs.
        self.assertEqual(style["Très positif"][1], "#04543C".replace("C", "c"))
        self.assertEqual(style["Négatif"][1], "#B42318")
        self.assertEqual(style["Très négatif"][1], "#7F1D14")


class TestFreshness(unittest.TestCase):
    def test_missing_date_stays_missing(self) -> None:
        self.assertIsNone(news_page._fmt_datetime(None))
        self.assertIsNone(news_page._fmt_datetime(float("nan")))

    def test_naive_timestamp_is_marked_utc(self) -> None:
        out = news_page._fmt_datetime(pd.Timestamp("2026-10-16 14:30:00"))
        self.assertIn("16/10/2026", str(out))
        self.assertIn("UTC", str(out))


if __name__ == "__main__":
    unittest.main()
