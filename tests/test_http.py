from __future__ import annotations

import unittest
from unittest.mock import patch

from ecoinvest.data import http


class _Response:
    def __init__(self, status: int, payload=None, content: bytes = b"{}", text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = text or (str(payload) if payload is not None else "")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _call(*responses, **kwargs):
    """Exécute request_json avec une séquence de réponses simulées."""
    seq = list(responses)
    calls = {"n": 0}

    def fake_get(*_args, **_kwargs):
        idx = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        item = seq[idx]
        if isinstance(item, Exception):
            raise item
        return item

    with patch.object(http.requests, "get", side_effect=fake_get), \
            patch.object(http.time, "sleep", lambda *_: None):
        try:
            return http.request_json("https://example.test/data?api_token=SECRET",
                                     provider="Test", retries=kwargs.pop("retries", 3), **kwargs)
        finally:
            calls["attempts"] = calls["n"]


class TestClassification(unittest.TestCase):
    def setUp(self) -> None:
        http.clear()

    def test_status_mapping(self) -> None:
        self.assertEqual(http.classify_status(401), "auth")
        self.assertEqual(http.classify_status(403), "forbidden")
        self.assertEqual(http.classify_status(404), "not_found")
        self.assertEqual(http.classify_status(429), "rate_limit")
        self.assertEqual(http.classify_status(500), "server")
        self.assertEqual(http.classify_status(503), "server")

    def test_redaction(self) -> None:
        url = "https://api.test/v1/x?symbol=IAM&api_token=abc123&apikey=xyz"
        safe = http.redact_url(url)
        self.assertNotIn("abc123", safe)
        self.assertNotIn("xyz", safe)
        self.assertIn("symbol=IAM", safe)


class TestRequestJson(unittest.TestCase):
    def setUp(self) -> None:
        http.clear()

    def test_success_records_state(self) -> None:
        data = _call(_Response(200, [{"a": 1}, {"a": 2}]))
        self.assertEqual(len(data), 2)
        state = http.state_for("Test")
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["records"], 2)

    def test_401_is_not_retried(self) -> None:
        with self.assertRaises(http.ProviderError) as ctx:
            _call(_Response(401, {"error": "invalid key"}))
        err = ctx.exception
        self.assertEqual(err.kind, "auth")
        self.assertFalse(err.retryable)
        self.assertIn("authentification", err.user_message.lower())

    def test_403(self) -> None:
        with self.assertRaises(http.ProviderError) as ctx:
            _call(_Response(403))
        self.assertEqual(ctx.exception.kind, "forbidden")

    def test_404(self) -> None:
        with self.assertRaises(http.ProviderError) as ctx:
            _call(_Response(404))
        self.assertEqual(ctx.exception.kind, "not_found")

    def test_429_retries_then_succeeds(self) -> None:
        data = _call(_Response(429), _Response(200, {"ok": True}))
        self.assertEqual(data, {"ok": True})
        self.assertEqual(http.state_for("Test")["status"], "ok")

    def test_500_exhausts_retries(self) -> None:
        with self.assertRaises(http.ProviderError) as ctx:
            _call(_Response(500), _Response(500), _Response(500), retries=3)
        err = ctx.exception
        self.assertEqual(err.kind, "server")
        self.assertTrue(err.retryable)
        self.assertEqual(err.attempts, 3)

    def test_timeout(self) -> None:
        import requests
        with self.assertRaises(http.ProviderError) as ctx:
            _call(requests.Timeout("slow"), requests.Timeout("slow"), requests.Timeout("slow"))
        self.assertEqual(ctx.exception.kind, "timeout")

    def test_network(self) -> None:
        import requests
        with self.assertRaises(http.ProviderError) as ctx:
            _call(requests.ConnectionError("down"), requests.ConnectionError("down"),
                  requests.ConnectionError("down"))
        self.assertEqual(ctx.exception.kind, "network")

    def test_empty_body(self) -> None:
        self.assertIsNone(_call(_Response(200, content=b""), allow_empty=True))
        with self.assertRaises(http.ProviderError) as ctx:
            _call(_Response(200, content=b""), allow_empty=False)
        self.assertEqual(ctx.exception.kind, "empty")

    def test_malformed_json(self) -> None:
        with self.assertRaises(http.ProviderError) as ctx:
            _call(_Response(200, ValueError("bad json"), content=b"<html>"))
        self.assertEqual(ctx.exception.kind, "malformed")

    def test_diagnostics_never_contain_secret(self) -> None:
        with self.assertRaises(http.ProviderError):
            _call(_Response(401, {"error": "bad"}))
        blob = str(http.diagnostics()) + str(http.state_for("Test"))
        self.assertNotIn("SECRET", blob)


if __name__ == "__main__":
    unittest.main()
