"""Non-régression du bug « exercices 2023 et 2024 affichent les mêmes montants ».

Deux niveaux sont testés :

1. **Données** : le seed vérifié ne doit contenir aucune ligne détaillée
   incohérente avec les agrégats de son exercice (``store_issues``), et chaque
   exercice doit restituer ses propres montants.
2. **Affichage** : les colonnes portent l'année réellement sélectionnée.
"""
from __future__ import annotations

import unittest

import pandas as pd

from ecoinvest.data import statements as stmt


class TestSeedIntegrity(unittest.TestCase):
    def test_no_inconsistent_detail_in_store(self) -> None:
        self.assertEqual(stmt.store_issues(), {}, "le magasin contient un détail rattaché au mauvais exercice")

    def test_tma_has_two_distinct_exercises(self) -> None:
        records = stmt.get_statements("TMA")
        years = sorted(int(r["fiscal_year"]) for r in records)
        self.assertEqual(years, [2023, 2024])


class TestExerciseValues(unittest.TestCase):
    """Le cœur du bug : chaque exercice doit montrer SES montants."""

    def _revenue(self, year: int) -> float:
        record = stmt.get_statement("TMA", fiscal_year=year)
        self.assertIsNotNone(record, f"exercice {year} absent")
        table = stmt.block_table(record, "income")
        row = table[table["Poste"].str.contains("affaires", case=False, na=False)].iloc[0]
        return float(row["Exercice"])

    def test_2023_and_2024_revenue_differ(self) -> None:
        rev_2023 = self._revenue(2023)
        rev_2024 = self._revenue(2024)
        self.assertNotAlmostEqual(rev_2023, rev_2024)
        self.assertAlmostEqual(rev_2023, 17_984_198_998.17, places=1)
        self.assertAlmostEqual(rev_2024, 18_348_026_022.08, places=1)

    def test_aggregates_follow_the_selected_year(self) -> None:
        rec_2023 = stmt.get_statement("TMA", fiscal_year=2023)
        rec_2024 = stmt.get_statement("TMA", fiscal_year=2024)
        self.assertNotEqual(rec_2023["income"]["net_income"], rec_2024["income"]["net_income"])
        self.assertNotEqual(rec_2023["balance"]["total_assets"], rec_2024["balance"]["total_assets"])

    def test_2023_falls_back_to_verified_aggregates(self) -> None:
        """Sans détail vérifié, le tableau ne montre pas de lignes inventées."""
        record = stmt.get_statement("TMA", fiscal_year=2023)
        self.assertFalse((record.get("lines") or {}).get("income"))
        table = stmt.block_table(record, "income")
        self.assertGreater(len(table), 0)
        # La colonne « exercice précédent » reste vide : aucune donnée 2022.
        self.assertTrue(table["Exercice précédent"].isna().all())

    def test_record_issues_detects_wrong_exercise_detail(self) -> None:
        record = stmt.get_statement("TMA", fiscal_year=2023)
        corrupted = dict(record)
        # On réinjecte le détail erroné (valeurs 2024) sur l'exercice 2023.
        rec_2024 = stmt.get_statement("TMA", fiscal_year=2024)
        corrupted["lines"] = rec_2024["lines"]
        issues = stmt.record_issues(corrupted)
        self.assertTrue(issues)


class TestExerciseColumnLabels(unittest.TestCase):
    def test_columns_carry_the_selected_year(self) -> None:
        from ecoinvest.ui.pages import statements_page as page

        frame = pd.DataFrame({"Poste": ["CA"], "Exercice": [1.0], "Exercice précédent": [0.5]})
        renamed = page._exercise_columns(frame, {"fiscal_year": 2023})
        self.assertIn("Exercice 2023", renamed.columns)
        self.assertIn("Exercice 2022", renamed.columns)
        self.assertNotIn("Exercice", renamed.columns)

    def test_rename_is_a_noop_without_year(self) -> None:
        from ecoinvest.ui.pages import statements_page as page

        frame = pd.DataFrame({"Exercice": [1.0]})
        renamed = page._exercise_columns(frame, {"fiscal_year": None})
        self.assertEqual(list(renamed.columns), ["Exercice"])


if __name__ == "__main__":
    unittest.main()
