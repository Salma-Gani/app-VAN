from __future__ import annotations

import unittest

from ecoinvest.ai import report


class TestReport(unittest.TestCase):
    def setUp(self) -> None:
        self.result = {
            "symbol": "ATW",
            "provider": "Test",
            "generated_at": "19/10/2026 10:00",
            "text": (
                "## Tendance & niveaux clés\n"
                "- Cours **670 MAD**, support **661 MAD**.\n\n"
                "### Conclusion\n**Prudence** — confiance moyenne.\n\n"
                "> Les performances passées ne préjugent pas des performances futures."
            ),
            "payload": {
                "symbol": "ATW",
                "row": {"symbol": "ATW", "name": "Attijariwafa Bank", "close": 670.0,
                        "change_pct": -0.0001, "volume": 14_280_000, "cap": 140_000_000_000,
                        "volatility": 0.18, "max_drawdown": -0.12, "beta": 0.9,
                        "last_date": "2026-10-16"},
                "technical": {
                    "trend": {"state": "Baissière"},
                    "momentum": {"state": "Momentum positif", "rsi": 37.6},
                    "levels": {"support": 661.0, "resistance": 723.0},
                },
                "ratios": {"dividend_yield": {"value": 0.0328}, "per": {"value": 12.4}},
                "news": [{"title": "Résultats semestriels", "source": "Test", "published": "2026-10-18"}],
                "macro": {"indicators": {"gdp_growth": {"label": "Croissance du PIB", "value": 4.6,
                                                          "unit": "%", "year": "2025"}}},
                "sources": ["Bourse de Casablanca", "World Bank Open Data"],
            },
        }

    def test_pdf_starts_with_header(self) -> None:
        pdf = report.build_analysis_pdf(self.result, "ATW")
        if not report.reportlab_available():
            self.skipTest("reportlab absent")
        self.assertIsNotNone(pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 3000)

    def test_markdown_fallback(self) -> None:
        md = report.build_markdown_report(self.result, "ATW")
        self.assertIn("Market Mind", md)
        self.assertIn("ATW", md)
        self.assertIn("Tendance", md)
        self.assertIn("Bourse de Casablanca", md)
        self.assertIn("conseil en investissement", md)


if __name__ == "__main__":
    unittest.main()
