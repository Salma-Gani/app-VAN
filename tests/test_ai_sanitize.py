"""Tests du garde-fou éditorial appliqué aux réponses LLM."""
from __future__ import annotations

import unittest

from ecoinvest.ai.llm import sanitize_llm_text


class TestSanitizeLLMText(unittest.TestCase):
    def test_removes_broken_editorial_phrase(self) -> None:
        text = "La société a publié ses résultats. 10 classe est égale à EI. Le chiffre d'affaires progresse."
        cleaned = sanitize_llm_text(text)
        self.assertNotIn("classe est égale", cleaned)
        self.assertIn("chiffre d'affaires progresse", cleaned)
        self.assertIn("publié ses résultats", cleaned)

    def test_removes_snake_case_assignment_lines(self) -> None:
        text = "Analyse.\nnet_income = 844 millions\nLe résultat net progresse."
        cleaned = sanitize_llm_text(text)
        self.assertNotIn("net_income =", cleaned)
        self.assertIn("Le résultat net progresse", cleaned)

    def test_keeps_normal_financial_prose_and_ratios(self) -> None:
        text = "Le PER = 12,5 reste inférieur à la moyenne du secteur.\nLa marge nette s'améliore."
        cleaned = sanitize_llm_text(text)
        self.assertIn("PER = 12,5", cleaned)
        self.assertIn("marge nette", cleaned)

    def test_empty_or_only_technical_text(self) -> None:
        self.assertEqual(sanitize_llm_text(None), "")
        self.assertEqual(sanitize_llm_text(""), "")
        only_technical = "net_income = 10\noperating_cf = 20"
        self.assertIn("fragments techniques", sanitize_llm_text(only_technical))


if __name__ == "__main__":
    unittest.main()
