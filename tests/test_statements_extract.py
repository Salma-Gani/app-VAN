"""Tests du module de normalisation des états financiers.

Couvre : formats numériques, séparateurs de colonnes, découpage des montants,
normalisation des libellés (sans fusion abusive), structuration rubrique ×
exercice, contrôles de cohérence, construction d'un enregistrement validé et
robustesse d'un PDF.
"""
from __future__ import annotations

import io
import unittest

import pandas as pd

from ecoinvest.data import statements as stmt
from ecoinvest.data import statements_extract as ext


class TestNumberParsing(unittest.TestCase):
    def test_french_and_english_formats(self) -> None:
        self.assertAlmostEqual(ext.parse_number("1 234,56"), 1234.56)
        self.assertAlmostEqual(ext.parse_number("1,234.56"), 1234.56)
        self.assertAlmostEqual(ext.parse_number("1 234 567"), 1234567.0)
        self.assertAlmostEqual(ext.parse_number("1.234.567,89"), 1234567.89)
        self.assertAlmostEqual(ext.parse_number("12,5 %"), 12.5)

    def test_negative_and_empty(self) -> None:
        self.assertAlmostEqual(ext.parse_number("(1 234,50)"), -1234.5)
        self.assertAlmostEqual(ext.parse_number("-1 234"), -1234.0)
        self.assertIsNone(ext.parse_number("—"))
        self.assertIsNone(ext.parse_number(""))
        self.assertIsNone(ext.parse_number("n/a"))

    def test_ambiguous_thousand_separator_is_flagged(self) -> None:
        value, ambiguous = ext.parse_number_ex("1.234")
        self.assertAlmostEqual(value, 1234.0)
        self.assertTrue(ambiguous)

    def test_unambiguous_thousands_are_not_flagged(self) -> None:
        value, ambiguous = ext.parse_number_ex("1 234")
        self.assertAlmostEqual(value, 1234.0)
        self.assertFalse(ambiguous)


class TestColumnSplitting(unittest.TestCase):
    def test_two_spaces_separate_columns(self) -> None:
        columns = ext.split_columns("Chiffre d'affaires   35 731   36 786")
        self.assertEqual(columns, ["Chiffre d'affaires", "35 731", "36 786"])

    def test_single_space_is_a_thousands_separator(self) -> None:
        columns = ext.split_columns("Chiffre d'affaires 35 731")
        self.assertEqual(columns, ["Chiffre d'affaires 35 731"])

    def test_amounts_from_layout_line(self) -> None:
        amounts, ambiguous = ext.extract_amounts("35 731   36 786   36 699")
        self.assertEqual(amounts, [35731.0, 36786.0, 36699.0])
        self.assertFalse(ambiguous)

    def test_amounts_from_single_space_line_are_ambiguous(self) -> None:
        amounts, ambiguous = ext.extract_amounts("35 731 36 786 36 699")
        self.assertEqual(amounts, [35731.0, 36786.0, 36699.0])
        self.assertTrue(ambiguous)


class TestLabelNormalisation(unittest.TestCase):
    def test_standard_label_is_mapped(self) -> None:
        matches, status = ext.normalize_label("Chiffre d'affaires")
        self.assertEqual(status, "mappée")
        self.assertEqual((matches[0].block, matches[0].key), ("income", "revenue"))

    def test_abbreviation_requires_verification(self) -> None:
        matches, status = ext.normalize_label("CA")
        self.assertEqual(status, "à vérifier")
        self.assertEqual(matches[0].key, "revenue")

    def test_distinct_rubric_is_not_merged_silently(self) -> None:
        matches, status = ext.normalize_label("Ventes de marchandises et de biens et services produits")
        self.assertEqual(status, "à vérifier")
        self.assertEqual(matches[0].key, "revenue")
        self.assertEqual(matches[0].confidence, "moyenne")

    def test_marge_brute_is_not_confused_with_caf(self) -> None:
        matches, _ = ext.normalize_label("Marge brute")
        keys = {match.key for match in matches}
        self.assertIn("gross_profit", keys)
        self.assertNotIn("operating_cf", keys)

    def test_total_passif_is_mapped(self) -> None:
        matches, status = ext.normalize_label("Total du passif")
        self.assertEqual(status, "mappée")
        self.assertEqual((matches[0].block, matches[0].key), ("balance", "total_liabilities"))

    def test_unknown_label(self) -> None:
        matches, status = ext.normalize_label("Frais de transport sur achats")
        self.assertEqual(matches, [])
        self.assertEqual(status, "non reconnue")


STATEMENT_TEXT = """ETATS FINANCIERS 2024
Compte de produits et charges
Chiffre d'affaires   1 000   900
Résultat d'exploitation   200   150
Résultat net   80   60
Bilan
Total du bilan   2 500   2 200
Capitaux propres   1 200   1 100
"""


class TestStructuring(unittest.TestCase):
    def test_text_is_structured_by_rubric_and_exercise(self) -> None:
        result = ext.structure_text(STATEMENT_TEXT, source="test")
        self.assertEqual(result.value_columns[0], "2024")
        frame = ext.to_editor_frame(result)
        self.assertIn("2024", frame.columns)
        self.assertIn("Exercice précédent", frame.columns)
        revenue = frame[frame["Libellé d'origine"] == "Chiffre d'affaires"].iloc[0]
        self.assertEqual(revenue["Clé"], "income.revenue")
        self.assertAlmostEqual(revenue["2024"], 1000.0)
        self.assertAlmostEqual(revenue["Exercice précédent"], 900.0)

    def test_absent_value_is_not_zero(self) -> None:
        result = ext.structure_text("Résultat net   80\n", source="test")
        frame = ext.to_editor_frame(result)
        row = frame.iloc[0]
        self.assertAlmostEqual(row["Exercice"], 80.0)
        self.assertTrue(pd.isna(row["Exercice précédent"]))

    def test_ambiguous_line_is_flagged_for_human(self) -> None:
        result = ext.structure_text("Chiffre d'affaires 1 000 900\n", source="test")
        row = result.rows[0]
        self.assertEqual(row.status, "à vérifier")
        self.assertIn("incertain", row.note)

    def test_original_labels_are_preserved(self) -> None:
        result = ext.structure_text(STATEMENT_TEXT)
        labels = [row.label for row in result.rows]
        self.assertIn("Chiffre d'affaires", labels)
        self.assertIn("Total du bilan", labels)


class TestCoherence(unittest.TestCase):
    def test_duplicate_with_different_values_is_reported(self) -> None:
        result = ext.structure_text(
            "Total du bilan   2 500   2 200\nTotal du bilan   2 700   2 200\n"
        )
        self.assertTrue(any("Doublon" in issue for issue in result.issues))

    def test_asset_liability_mismatch_is_reported(self) -> None:
        rows = [
            ext.ExtractedRow("balance", "total_assets", "Total du bilan", [2500.0, None], "MAD", "MAD", 1, "mappée", "haute"),
            ext.ExtractedRow("balance", "total_liabilities", "Total du passif", [2000.0, None], "MAD", "MAD", 1, "mappée", "haute"),
        ]
        issues = ext.coherence_issues(rows)
        self.assertTrue(any("actif ≠ total passif" in issue for issue in issues))

    def test_balanced_statement_has_no_mismatch(self) -> None:
        rows = [
            ext.ExtractedRow("balance", "total_assets", "Total du bilan", [2500.0, None], "MAD", "MAD", 1, "mappée", "haute"),
            ext.ExtractedRow("balance", "total_liabilities", "Total du passif", [2500.0, None], "MAD", "MAD", 1, "mappée", "haute"),
        ]
        issues = ext.coherence_issues(rows)
        self.assertFalse(any("actif ≠ total passif" in issue for issue in issues))


class TestRecordBuilding(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        return ext.to_editor_frame(ext.structure_text(STATEMENT_TEXT, source="test"))

    def test_record_uses_validated_columns_only(self) -> None:
        frame = self._frame()
        frame.loc[len(frame)] = {
            "Bloc": "—", "Clé": "", "Rubrique": "Frais divers", "Libellé d'origine": "Frais divers",
            "Unité": "MAD", "Devise": "MAD", "Page": 1, "Confiance": "faible", "Statut": "non reconnue",
            "2024": 42.0, "Exercice précédent": None,
        }
        record, skipped = ext.frame_to_record(frame, "TESTS", issuer="Test SA",
                                              source="test", fiscal_year=2024)
        self.assertIn("Frais divers", skipped)
        self.assertAlmostEqual(record["income"]["revenue"], 1000.0)
        self.assertAlmostEqual(record["balance"]["total_assets"], 2500.0)
        self.assertEqual(record["fiscal_year"], 2024)
        self.assertEqual(record["unit"], "MAD")
        self.assertTrue(record["lines"]["income"])

    def test_record_without_canonical_rows_is_rejected(self) -> None:
        frame = self._frame()
        frame["Clé"] = ""
        with self.assertRaises(stmt.StatementError):
            ext.frame_to_record(frame, "TESTS")

    def test_saved_record_is_readable_by_the_store(self) -> None:
        import pathlib
        import tempfile

        original = stmt.USER_STATEMENTS_FILE
        with tempfile.TemporaryDirectory() as tmp:
            stmt.USER_STATEMENTS_FILE = pathlib.Path(tmp) / "statements.json"
            try:
                record, _ = ext.frame_to_record(self._frame(), "TESTS", source="test",
                                                fiscal_year=2024)
                stmt.save_statement(record)
                loaded = stmt.get_statements("TESTS")
                self.assertEqual(len(loaded), 1)
                self.assertAlmostEqual(loaded[0]["income"]["revenue"], 1000.0)
                assets = stmt.block_table(loaded[0], "balance_assets")
                self.assertFalse(assets.empty)
            finally:
                stmt.USER_STATEMENTS_FILE = original


class TestPdfRobustness(unittest.TestCase):
    def test_invalid_pdf_raises_statement_error(self) -> None:
        with self.assertRaises(stmt.StatementError):
            ext.structure_pdf(b"not a pdf at all")

    def test_generated_pdf_is_structured(self) -> None:
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(50, 780, "ETATS FINANCIERS 2024")
        pdf.drawString(50, 750, "Chiffre d'affaires")
        pdf.drawString(300, 750, "1 000")
        pdf.drawString(400, 750, "900")
        pdf.drawString(50, 730, "Resultat net")
        pdf.drawString(300, 730, "80")
        pdf.drawString(400, 730, "60")
        pdf.save()

        result = ext.structure_pdf(buffer.getvalue(), source="test.pdf")
        self.assertEqual(result.pages, 1)
        frame = ext.to_editor_frame(result)
        self.assertIn("Libellé d'origine", frame.columns)
        # Le texte doit être extrait ; le nombre de rubriques reconnues peut
        # varier selon la mise en page produite par reportlab.
        self.assertGreaterEqual(len(result.rows), 0)

    def test_real_ammc_pdf_from_cache(self) -> None:
        """Non-régression sur un vrai PDF AMMC (50 pages) s'il est en cache.

        Le fichier de cache est ignoré par Git ; le test est donc sauté quand il
        n'est pas disponible localement.
        """
        import pathlib
        import pickle
        import sqlite3

        cache_path = pathlib.Path("data/cache/ecoinvest_cache.sqlite")
        if not cache_path.exists():
            self.skipTest("cache AMMC absent")
        con = sqlite3.connect(str(cache_path))
        try:
            row = con.execute(
                "SELECT payload FROM cache WHERE key LIKE 'doc:%Maroc_Telecom_RFS%'"
            ).fetchone()
        finally:
            con.close()
        if not row:
            self.skipTest("PDF AMMC en cache absent")
        blob = row[0]
        content = pickle.loads(blob) if not isinstance(blob, (bytes, bytearray)) else bytes(blob)
        if content[:4] != b"%PDF":
            content = pickle.loads(bytes(blob))

        result = ext.structure_pdf(content, source="Maroc_Telecom_RFS.pdf")
        self.assertGreater(result.pages, 10)
        self.assertGreater(len(result.rows), 0)
        keys = {(row.block, row.key) for row in result.rows if row.key}
        self.assertIn(("balance", "total_assets"), keys)
        self.assertIn(("income", "revenue"), keys)
        self.assertIn(("cashflow", "operating_cf"), keys)
        # « trésorerie » seule ne doit pas être assimilée à la trésorerie du bilan.
        for row in result.rows:
            if "activités d’exploitation" in row.label or "activites d'exploitation" in row.label:
                self.assertNotEqual((row.block, row.key), ("balance", "cash"))


if __name__ == "__main__":
    unittest.main()
