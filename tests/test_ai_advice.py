"""Tests de non-conseil : l'IA décrit, elle ne recommande pas d'acheter ou de vendre."""
from __future__ import annotations

import unittest

from ecoinvest.ai import prompts
from ecoinvest.ai.agent import _verdict_from


class TestNoBuySellAdvice(unittest.TestCase):
    def test_verdict_labels_are_descriptive(self) -> None:
        cases = {
            80: "Signaux très favorables",
            65: "Signaux favorables",
            55: "Signaux mitigés",
            45: "Signaux insuffisants",
            35: "Signaux défavorables",
            20: "Signaux très défavorables",
        }
        for score, expected in cases.items():
            label = _verdict_from(score, 0.0)
            self.assertEqual(label, expected)
            self.assertNotIn("Achat", label)
            self.assertNotIn("Éviter", label)
            self.assertNotIn("vendre", label.lower())
            self.assertNotIn("Alléger", label)

    def test_prompts_do_not_request_action_labels(self) -> None:
        for text in (prompts.SYSTEM_DIRECT_ANALYST, prompts.SYSTEM_MARKET_ANALYST):
            lowered = text.lower()
            self.assertTrue(
                "consigne d'achat ou de vente" in lowered or "consigne d'action" in lowered,
                text,
            )
            self.assertNotIn("Achat progressif", text)
            self.assertNotIn("Plan d'exécution", text)
            self.assertNotIn("Achat fort", text)
        self.assertNotIn("actionnables", prompts.SYSTEM_BRIEFING)

    def test_base_rules_forbid_advice(self) -> None:
        self.assertIn("ni de consigne d'achat ou de vente", prompts.BASE_RULES)


if __name__ == "__main__":
    unittest.main()
