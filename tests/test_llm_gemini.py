"""Tests du connecteur Gemini : modèle par défaut et parsing des réponses.

Ces tests ne font aucun appel réseau : ``_post`` est remplacé par une réponse
factice. Ils verrouillent les deux causes de panne observées le 20/10/2026 :
un modèle retiré (404) et une réponse 200 sans bloc ``parts`` exploitable.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from ecoinvest.ai.llm import LLMClient, LLMError, PROVIDER_BY_KEY


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class TestGeminiParsing(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PROVIDER_BY_KEY["gemini"]
        self.client = LLMClient(self.provider, model="gemini-test")

    def _run(self, payload):
        with patch("ecoinvest.ai.llm._post", return_value=_FakeResponse(payload)):
            return self.client._gemini(
                [{"role": "user", "content": "Bonjour"}], None, 0.0, 100
            )

    def test_concatenates_all_text_parts(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Bonjour "}, {"text": "monde"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        self.assertEqual(self._run(payload), "Bonjour monde")

    def test_ignores_parts_without_text(self) -> None:
        payload = {
            "candidates": [
                {"content": {"parts": [{"thought": True}, {"text": "OK"}]}}
            ]
        }
        self.assertEqual(self._run(payload), "OK")

    def test_reports_blocked_prompt(self) -> None:
        payload = {"promptFeedback": {"blockReason": "SAFETY"}}
        with self.assertRaises(LLMError) as ctx:
            self._run(payload)
        self.assertIn("bloqué", str(ctx.exception))

    def test_reports_empty_candidate_without_parts(self) -> None:
        payload = {"candidates": [{"finishReason": "MAX_TOKENS"}]}
        with self.assertRaises(LLMError) as ctx:
            self._run(payload)
        self.assertIn("aucun texte exploitable", str(ctx.exception))
        self.assertIn("MAX_TOKENS", str(ctx.exception))

    def test_404_adds_actionable_model_hint(self) -> None:
        with patch(
            "ecoinvest.ai.llm._post",
            side_effect=LLMError("Google Gemini : ressource introuvable (404)"),
        ):
            with self.assertRaises(LLMError) as ctx:
                self.client._gemini(
                    [{"role": "user", "content": "Bonjour"}], None, 0.0, 100
                )
        message = str(ctx.exception)
        self.assertIn("gemini-test", message)
        self.assertIn("GEMINI_MODEL", message)

    def test_default_model_is_not_the_retired_one(self) -> None:
        model = self.provider.default_model
        self.assertNotEqual(model, "gemini-2.0-flash")
        self.assertTrue(model)


if __name__ == "__main__":
    unittest.main()
