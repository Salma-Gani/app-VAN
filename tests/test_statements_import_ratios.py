"""Tests d'import, d'unités, de ratios et de résolution AMMC.

Ces tests couvrent les causes réelles du bloc « États financiers » vide :

* import CSV/Excel et validation des lignes ;
* repli du bilan pour les enregistrements sans lignes détaillées ;
* calcul des ratios avec formule et raison d'impossibilité ;
* conversion d'unités (MAD, milliers, millions, milliards) ;
* résolution du filtre émetteur AMMC (IAM → MAROC TELECOM).
"""
from __future__ import annotations

import io
import pathlib
import tempfile
import unittest
from typing import Any, Dict

import pandas as pd

from ecoinvest.data import statements as stmt


class _TempStore(unittest.TestCase):
    """Isole les écritures dans un fichier utilisateur temporaire."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._original = stmt.USER_STATEMENTS_FILE
        stmt.USER_STATEMENTS_FILE = pathlib.Path(self._tmp.name) / "statements.json"

    def tearDown(self) -> None:
        stmt.USER_STATEMENTS_FILE = self._original
        self._tmp.cleanup()


class TestImportTable(_TempStore):
    def test_csv_template_imports_one_record(self) -> None:
        content = stmt.template_csv().replace("EXEMPLE", "ZZTEST").encode("utf-8")
        result = stmt.import_table(content, "modele.csv")
        self.assertEqual(result["imported"], 1)
        records = stmt.get_statements("ZZTEST")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["fiscal_year"], 2024)
        self.assertEqual(records[0]["provider"], "import CSV")

    def test_invalid_header_is_rejected_with_a_clear_message(self) -> None:
        with self.assertRaises(stmt.StatementError) as ctx:
            stmt.import_table(b"foo,bar\n1,2\n", "bad.csv")
        self.assertIn("symbol", str(ctx.exception))

    def test_missing_fiscal_year_is_reported_not_saved(self) -> None:
        content = (
            "symbol,issuer,fiscal_year,income_revenue\n"
            "NODATE,Test,,1000\n"
        ).encode("utf-8")
        result = stmt.import_table(content, "nodate.csv")
        self.assertEqual(result["imported"], 0)
        self.assertTrue(any("exercice" in error.lower() for error in result["errors"]))
        self.assertEqual(stmt.get_statements("NODATE"), [])

    def test_row_without_number_is_reported(self) -> None:
        content = (
            "symbol,issuer,fiscal_year,income_revenue\n"
            "EMPTY,Test,2024,\n"
        ).encode("utf-8")
        result = stmt.import_table(content, "empty.csv")
        self.assertEqual(result["imported"], 0)
        self.assertTrue(any("aucun montant" in error.lower() for error in result["errors"]))

    def test_xlsx_import_uses_the_same_validator(self) -> None:
        row: Dict[str, Any] = {column: "" for column in stmt.CSV_COLUMNS}
        row.update({
            "symbol": "XLSX1", "issuer": "Test Excel", "fiscal_year": "2024",
            "period": "FY", "currency": "MAD", "unit": "MAD",
            "income_revenue": "1000", "balance_total_assets": "2500",
        })
        buffer = io.BytesIO()
        pd.DataFrame([row], columns=stmt.CSV_COLUMNS).to_excel(buffer, index=False)
        result = stmt.import_table(buffer.getvalue(), "etats.xlsx")
        self.assertEqual(result["imported"], 1)
        records = stmt.get_statements("XLSX1")
        self.assertEqual(records[0]["income"]["revenue"], 1000.0)
        self.assertEqual(records[0]["balance"]["total_assets"], 2500.0)

    def test_corrupted_xlsx_is_rejected(self) -> None:
        with self.assertRaises(stmt.StatementError) as ctx:
            stmt.import_table(b"not an excel file", "broken.xlsx")
        self.assertIn("illisible", str(ctx.exception).lower())

    def test_imported_balance_is_visible_in_asset_and_liability_tables(self) -> None:
        """Sans lignes détaillées, le bilan doit quand même s'afficher."""
        row: Dict[str, Any] = {column: "" for column in stmt.CSV_COLUMNS}
        row.update({
            "symbol": "BILAN", "fiscal_year": "2024", "period": "FY",
            "currency": "MAD", "unit": "MAD",
            "balance_non_current_assets": "400",
            "balance_current_assets": "200",
            "balance_cash": "100",
            "balance_total_assets": "700",
            "balance_equity": "300",
            "balance_total_debt": "150",
            "balance_current_liabilities": "250",
        })
        content = pd.DataFrame([row], columns=stmt.CSV_COLUMNS).to_csv(index=False).encode("utf-8")
        stmt.import_table(content, "bilan.csv")
        record = stmt.get_statements("BILAN")[0]
        assets = stmt.block_table(record, "balance_assets")
        liabilities = stmt.block_table(record, "balance_liabilities")
        self.assertIn("Actif immobilisé", set(assets["Poste"]))
        self.assertIn("Capitaux propres", set(liabilities["Poste"]))
        self.assertTrue((assets["Exercice"] > 0).any())


class TestUnits(unittest.TestCase):
    def test_unit_multiplier(self) -> None:
        self.assertEqual(stmt.unit_multiplier("MAD"), 1.0)
        self.assertEqual(stmt.unit_multiplier("milliers MAD"), 1e3)
        self.assertEqual(stmt.unit_multiplier("MDH"), 1e6)
        self.assertEqual(stmt.unit_multiplier("millions de dirhams"), 1e6)
        self.assertEqual(stmt.unit_multiplier("milliards MAD"), 1e9)
        self.assertEqual(stmt.unit_multiplier("unité inconnue"), 1.0)

    def test_detect_unit(self) -> None:
        self.assertEqual(stmt.detect_unit("Les montants sont en millions de dirhams."), "millions MAD")
        self.assertEqual(stmt.detect_unit("Montants en milliers de dirhams."), "milliers MAD")
        self.assertEqual(stmt.detect_unit("Montants en dirhams."), "MAD")


def _complete_record() -> Dict[str, Any]:
    return stmt._sanitize({
        "symbol": "TEST", "fiscal_year": 2024, "period": "FY",
        "currency": "MAD", "unit": "MAD", "status": "manual",
        "income": {
            "revenue": 1000.0, "operating_income": 200.0, "ebitda": 150.0,
            "interest_expense": 20.0, "net_income": 100.0, "eps": 10.0,
        },
        "balance": {
            "total_assets": 2000.0, "equity": 500.0, "total_debt": 300.0,
            "cash": 100.0, "current_assets": 400.0, "current_liabilities": 200.0,
            "shares": 10.0,
        },
        "cashflow": {
            "operating_cf": 120.0, "capex": 70.0, "free_cash_flow": 50.0,
            "dividends_paid": 40.0,
        },
    })


class TestRatios(unittest.TestCase):
    def _values(self, market: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        table = stmt.ratios_for(_complete_record(), market)
        return {row["Indicateur"]: row for _, row in table.iterrows()}

    def test_ratios_are_computed_from_available_data(self) -> None:
        rows = self._values({"close": 100.0, "cap": 1000.0, "sector": "Industrie"})
        expected = {
            "Marge d'exploitation": 20.0,
            "Marge nette": 10.0,
            "ROE": 20.0,
            "ROA": 5.0,
            "Levier financier": 0.6,
            "Liquidité générale": 2.0,
            "Couverture des intérêts": 10.0,
            "FCF / chiffre d'affaires": 5.0,
            "Distribution (payout)": 40.0,
            "PER": 10.0,
            "P/B": 2.0,
            "EV / EBITDA": 8.0,
        }
        for label, value in expected.items():
            self.assertEqual(rows[label]["Statut"], "Calculé", label)
            self.assertAlmostEqual(float(rows[label]["Valeur"]), value, places=6, msg=label)
            self.assertTrue(rows[label]["Formule"], label)

    def test_missing_equity_makes_roe_impossible_with_reason(self) -> None:
        record = _complete_record()
        record["balance"]["equity"] = None
        rows = {
            row["Indicateur"]: row
            for _, row in stmt.ratios_for(record, {"close": 100.0, "cap": 1000.0,
                                                  "sector": "Industrie"}).iterrows()
        }
        self.assertEqual(rows["ROE"]["Statut"], "Impossible")
        self.assertIn("capitaux propres", rows["ROE"]["Note"])
        self.assertTrue(pd.isna(rows["ROE"]["Valeur"]))

    def test_bank_excludes_ev_ebitda_but_keeps_per(self) -> None:
        rows = self._values({"close": 100.0, "cap": 1000.0, "sector": "Banques"})
        self.assertEqual(rows["EV / EBITDA"]["Statut"], "Non pertinent")
        self.assertIn("secteur", rows["EV / EBITDA"]["Note"])
        self.assertEqual(rows["PER"]["Statut"], "Calculé")
        self.assertEqual(rows["P/B"]["Statut"], "Calculé")

    def test_negative_net_income_disables_per(self) -> None:
        record = _complete_record()
        record["income"]["net_income"] = -50.0
        record["income"]["eps"] = -5.0
        rows = {
            row["Indicateur"]: row
            for _, row in stmt.ratios_for(record, {"close": 100.0, "cap": 1000.0,
                                                  "sector": "Industrie"}).iterrows()
        }
        self.assertEqual(rows["PER"]["Statut"], "Impossible")
        self.assertIn("négatif", rows["PER"]["Note"])

    def test_market_ratio_converts_statement_units(self) -> None:
        record = _complete_record()
        record["unit"] = "millions MAD"
        rows = {
            row["Indicateur"]: row
            for _, row in stmt.ratios_for(record, {"close": 100.0, "cap": 1_000_000_000.0,
                                                  "sector": "Industrie"}).iterrows()
        }
        # Capitalisation 1 000 000 000 MAD convertie en 1 000 millions MAD :
        # PER = 1 000 / 100 = 10, P/B = 1 000 / 500 = 2.
        self.assertAlmostEqual(float(rows["PER"]["Valeur"]), 10.0, places=6)
        self.assertAlmostEqual(float(rows["P/B"]["Valeur"]), 2.0, places=6)


class TestAmmcResolution(unittest.TestCase):
    def test_alias_resolves_iam_to_maroc_telecom(self) -> None:
        original = stmt._issuer_options
        stmt._issuer_options = lambda force=False: [("2798", "MAROC TELECOM"),
                                                    ("2734", "ATTIJARIWAFA BANK")]
        try:
            resolved = stmt.resolve_issuer("ITISSALAT AL-MAGHRIB", "IAM")
        finally:
            stmt._issuer_options = original
        self.assertEqual(resolved, ("2798", "MAROC TELECOM"))

    def test_unknown_issuer_returns_none(self) -> None:
        original = stmt._issuer_options
        stmt._issuer_options = lambda force=False: [("2798", "MAROC TELECOM")]
        try:
            resolved = stmt.resolve_issuer("SOCIETE INCONNUE", "ZZZ")
        finally:
            stmt._issuer_options = original
        self.assertIsNone(resolved)

    def test_unknown_provider_raises_statement_error(self) -> None:
        with self.assertRaises(stmt.StatementError) as ctx:
            stmt.fetch_provider("inconnu", "ATW")
        self.assertIn("Fournisseur inconnu", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
