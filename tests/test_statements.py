from __future__ import annotations

import unittest

import pandas as pd

from ecoinvest.data import statements as stmt


class TestStatementsSeed(unittest.TestCase):
    def test_seed_loads_official_records(self) -> None:
        tma = stmt.get_statements("TMA")
        self.assertEqual([r["fiscal_year"] for r in tma], [2024, 2023])
        mox = stmt.get_statements("MOX")
        self.assertEqual(len(mox), 1)
        self.assertEqual(mox[0]["status"], "official")
        self.assertIn("ammc.ma", mox[0]["source_url"])

    def test_latest_and_previous(self) -> None:
        latest = stmt.latest_statement("TMA")
        self.assertEqual(latest["fiscal_year"], 2024)
        previous = stmt.previous_statement("TMA", latest)
        self.assertEqual(previous["fiscal_year"], 2023)

    def test_fundamentals_derivation(self) -> None:
        f = stmt.fundamentals_for("TMA")
        self.assertAlmostEqual(f["revenue"], 18_348_026_022.08, places=2)
        self.assertAlmostEqual(f["net_income"], 844_618_182.50, places=2)
        self.assertAlmostEqual(f["eps"], round(844_618_182.50 / 8_960_000, 4), places=4)
        self.assertAlmostEqual(f["fcf"], 1_150_009_167.83 - 198_879_934.60, places=2)
        # variation vs 2023
        self.assertAlmostEqual(f["revenue_growth"],
                               18_348_026_022.08 / 17_984_198_998.17 - 1, places=6)

    def test_net_debt_and_fcf_are_derived_when_absent(self) -> None:
        record = stmt._sanitize({
            "symbol": "XYZ", "fiscal_year": 2024,
            "balance": {"total_debt": 300.0, "cash": 100.0},
            "cashflow": {"operating_cf": 90.0, "capex": 40.0},
        })
        self.assertAlmostEqual(record["balance"]["net_debt"], 200.0)
        self.assertAlmostEqual(record["cashflow"]["free_cash_flow"], 50.0)

    def test_block_table_exposes_lines(self) -> None:
        record = stmt.latest_statement("TMA")
        income = stmt.block_table(record, "income")
        self.assertFalse(income.empty)
        self.assertIn("Poste", income.columns)
        assets = stmt.block_table(record, "balance_assets")
        self.assertTrue((assets["Exercice"] > 0).any())

    def test_coverage_reports_status(self) -> None:
        market = pd.DataFrame({"symbol": ["TMA", "MOX", "ZZZ"], "name": ["T", "M", "Z"]})
        coverage = stmt.coverage(market)
        self.assertEqual(len(coverage), 3)
        row = coverage[coverage["Symbole"] == "TMA"].iloc[0]
        self.assertEqual(row["Dernier exercice"], 2024)
        missing = coverage[coverage["Symbole"] == "ZZZ"].iloc[0]
        self.assertEqual(missing["Statut"], "non couvert")

    def test_provider_status_never_leaks_keys(self) -> None:
        for item in stmt.provider_status():
            self.assertIn("configured", item)
            self.assertNotIn("sk-", str(item))


class TestCsvTemplate(unittest.TestCase):
    def test_template_has_all_blocks(self) -> None:
        text = stmt.template_csv()
        self.assertIn("income_revenue", text)
        self.assertIn("balance_total_assets", text)
        self.assertIn("cashflow_operating_cf", text)


class TestPdfHelpers(unittest.TestCase):
    def test_key_lines_extracts_raw_evidence(self) -> None:
        text = ("RÉSULTAT D'EXPLOITATION (I-II)  1 332 671 876,68  929 808 736,67\n"
                "TOTAL GENERAL I+II+III  7 823 328 116,20  8 785 016 442,20\n")
        lines = stmt.key_lines(text)
        fields = {(item["block"], item["field"]) for item in lines}
        self.assertIn(("income", "operating_income"), fields)
        self.assertIn(("balance", "total_assets"), fields)


class TestAmmcSearch(unittest.TestCase):
    """La recherche AMMC ne doit pas s'arrêter à la première page sans correspondance."""

    def setUp(self) -> None:
        from ecoinvest.utils import cache as cache_mod
        cache_mod.clear(stmt.NS)

    def test_finds_issuer_on_a_later_page(self) -> None:
        target = ("<table><tr><td>"
                  "<a href=\"/fr/espace-emetteurs/etats-financiers/acme-rfa-2025\">"
                  "ACME 2025 Rapports annuels</a></td></tr></table>")
        empty = "<table><tr><td>OTHER COMPANY 2026 Rapports 1er semestre</td></tr></table>"

        def fake_fetch(url: str) -> str:
            if url == stmt.AMMC_LIST:
                return empty
            if url.endswith("page=1"):
                return target
            return "<table></table>"

        original = stmt._fetch_html
        stmt._fetch_html = fake_fetch
        try:
            docs = stmt.ammc_documents("ACME", max_pages=2, limit=4, with_pdf=False)
        finally:
            stmt._fetch_html = original
            from ecoinvest.utils import cache as cache_mod
            cache_mod.clear(stmt.NS)

        self.assertEqual(len(docs), 1)
        self.assertIn("acme-rfa-2025", docs[0]["url"])
        self.assertEqual(docs[0]["year"], "2025")


if __name__ == "__main__":
    unittest.main()
