"""Couche LLM multi-fournisseur avec détection automatique et repli local.

Fournisseurs supportés (le premier dont la clé est présente est utilisé) :
OpenAI, Anthropic, DeepSeek, Groq, Google Gemini, Mistral, Ollama (local).

Si aucune clé n'est disponible, ``get_client()`` renvoie ``None`` et l'agent
bascule sur l'**analyste local** : un moteur de règles qui répond en langage
naturel à partir des données réelles de l'application, sans aucune connexion.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..config import HTTP_TIMEOUT, USER_AI_FILE
from ..data.http import ProviderError, classify_status, record_error, record_success

# ═══════════════════════════ Garde-fou éditorial ═══════════════════════════

# Fragments techniques qui ne doivent jamais apparaître comme du texte
# éditorial : artefacts « clé = valeur » issus du contexte, ou tournures
# corrompues du type « 10 classe est égale à EI ».
_BROKEN_PHRASE = re.compile(r"[^.\n]*\bclasse\s+est\s+égale\s+à\b[^.\n]*\.?", re.IGNORECASE)
_TECH_ASSIGNMENT = re.compile(r"^\s*[a-z][a-z0-9]*(?:_[a-z0-9]+)+\s*=\s*.{0,60}$", re.MULTILINE)


def sanitize_llm_text(text: Optional[str]) -> str:
    """Retire les artefacts techniques d'une réponse LLM, sans la réécrire.

    Seules les tournures manifestement corrompues sont supprimées ; le contenu
    financier rédigé est conservé tel quel. Si le nettoyage vide la réponse,
    un message explicite remplace le texte plutôt que de laisser un blanc.
    """
    if not text:
        return ""
    cleaned = _BROKEN_PHRASE.sub("", text)
    cleaned = _TECH_ASSIGNMENT.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return "Réponse du fournisseur retirée : elle contenait uniquement des fragments techniques illisibles."
    return cleaned

# ═══════════════════════════ Définition des fournisseurs ═══════════════════════════


@dataclass
class Provider:
    key: str
    label: str
    env_var: str
    model_env: str
    default_model: str
    base_url: str
    style: str  # "openai" | "anthropic" | "gemini" | "ollama"
    docs: str


PROVIDERS: List[Provider] = [
    Provider("openai", "OpenAI", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini",
             "https://api.openai.com/v1", "openai", "https://platform.openai.com/api-keys"),
    Provider("anthropic", "Anthropic Claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-sonnet-4-5",
             "https://api.anthropic.com/v1", "anthropic", "https://console.anthropic.com/"),
    Provider("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-chat",
             "https://api.deepseek.com/v1", "openai", "https://platform.deepseek.com/"),
    Provider("groq", "Groq", "GROQ_API_KEY", "GROQ_MODEL", "llama-3.3-70b-versatile",
             "https://api.groq.com/openai/v1", "openai", "https://console.groq.com/keys"),
    # Les identifiants de modèles Gemini évoluent vite : ``gemini-2.0-flash`` a été
    # retiré (404 « no longer available to new users »). L'alias « latest » évite
    # de coder en dur une version qui sera retirée ; surchargez-le avec GEMINI_MODEL.
    # Vérifié le 20/10/2026 avec un briefing complet (réponse STOP, texte non vide).
    Provider("gemini", "Google Gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-flash-lite-latest",
             "https://generativelanguage.googleapis.com/v1beta", "gemini", "https://aistudio.google.com/apikey"),
    Provider("mistral", "Mistral AI", "MISTRAL_API_KEY", "MISTRAL_MODEL", "mistral-large-latest",
             "https://api.mistral.ai/v1", "openai", "https://console.mistral.ai/"),
    Provider("ollama", "Ollama (local)", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "llama3.1",
             "http://localhost:11434", "ollama", "https://ollama.com/download"),
]

PROVIDER_BY_KEY = {p.key: p for p in PROVIDERS}


def load_user_config() -> Dict[str, Any]:
    try:
        with open(USER_AI_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_user_config(config: Dict[str, Any]) -> None:
    try:
        with open(USER_AI_FILE, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _credential(provider: Provider) -> Optional[str]:
    """Clé/URL du fournisseur : session → fichier utilisateur → variables d'environnement."""
    cfg = load_user_config()
    for source in (cfg.get("session", {}) if isinstance(cfg.get("session"), dict) else {},
                   cfg, os.environ):
        val = source.get(provider.env_var) if hasattr(source, "get") else None
        if val:
            return str(val).strip()
    if provider.key == "ollama":
        return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return None


def _model(provider: Provider, override: Optional[str] = None) -> str:
    if override:
        return override
    cfg = load_user_config()
    return str(cfg.get(provider.model_env) or os.getenv(provider.model_env) or provider.default_model)


def available_providers() -> List[Dict[str, Any]]:
    """Liste des fournisseurs avec leur état de disponibilité."""
    forced = os.getenv("ECOINVEST_LLM_PROVIDER", "").strip()
    out = []
    for p in PROVIDERS:
        cred = _credential(p)
        available = bool(cred)
        if p.key == "ollama" and available:
            available = _ollama_alive(cred)
        out.append(
            {
                "key": p.key,
                "label": p.label,
                "available": available,
                "model": _model(p),
                "env_var": p.env_var,
                "docs": p.docs,
                "forced": (forced == p.key),
                "credential_set": bool(_credential(p)),
            }
        )
    return out


def _ollama_alive(base_url: str) -> bool:
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=2.5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def active_provider() -> Optional[Provider]:
    """Fournisseur actif : celui forcé, sinon le premier disponible."""
    forced = os.getenv("ECOINVEST_LLM_PROVIDER", "").strip().lower()
    if forced and forced in PROVIDER_BY_KEY:
        p = PROVIDER_BY_KEY[forced]
        return p if _credential(p) else None
    for p in PROVIDERS:
        cred = _credential(p)
        if not cred:
            continue
        if p.key == "ollama" and not _ollama_alive(cred):
            continue
        return p
    return None


# ═══════════════════════════ Client ═══════════════════════════


class LLMError(RuntimeError):
    pass


def _post(url: str, label: str, **kwargs: Any) -> requests.Response:
    """POST avec erreurs classifiées et message utilisateur sans secret ni corps brut."""
    try:
        response = requests.post(url, **kwargs)
    except requests.Timeout as exc:
        err = ProviderError(label, None, "timeout", str(exc), True)
        record_error(label, err)
        raise LLMError(err.user_message) from exc
    except requests.RequestException as exc:
        err = ProviderError(label, None, "network", str(exc), True)
        record_error(label, err)
        raise LLMError(err.user_message) from exc

    if response.status_code != 200:
        kind = classify_status(response.status_code)
        err = ProviderError(label, response.status_code, kind, f"HTTP {response.status_code}")
        record_error(label, err)
        raise LLMError(err.user_message)
    record_success(label, None, response.status_code)
    return response


class LLMClient:
    """Client unifié : ``client.chat(messages, system=...)``."""

    def __init__(self, provider: Provider, model: Optional[str] = None) -> None:
        self.provider = provider
        self.model = _model(provider, model)
        self.credential = _credential(provider)

    @property
    def label(self) -> str:
        return f"{self.provider.label} · {self.model}"

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1600,
    ) -> str:
        style = self.provider.style
        if style == "anthropic":
            text = self._anthropic(messages, system, temperature, max_tokens)
        elif style == "gemini":
            text = self._gemini(messages, system, temperature, max_tokens)
        elif style == "ollama":
            text = self._ollama(messages, system, temperature, max_tokens)
        else:
            text = self._openai_compatible(messages, system, temperature, max_tokens)
        return sanitize_llm_text(text)

    # ─── Implémentations ───
    def _openai_compatible(self, messages, system, temperature, max_tokens) -> str:
        payload_messages = ([{"role": "system", "content": system}] if system else []) + messages
        resp = _post(
            f"{self.provider.base_url.rstrip('/')}/chat/completions",
            self.provider.label,
            headers={
                "Authorization": f"Bearer {self.credential}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": payload_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=90,
        )
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Réponse inattendue de {self.provider.label} : {exc}") from exc

    def _anthropic(self, messages, system, temperature, max_tokens) -> str:
        resp = _post(
            f"{self.provider.base_url.rstrip('/')}/messages",
            self.provider.label,
            headers={
                "x-api-key": self.credential or "",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system or "",
                "messages": messages,
            },
            timeout=90,
        )
        data = resp.json()
        try:
            return "".join(b.get("text", "") for b in data["content"]).strip()
        except (KeyError, TypeError) as exc:
            raise LLMError(f"Réponse inattendue d'Anthropic : {exc}") from exc

    def _gemini(self, messages, system, temperature, max_tokens) -> str:
        contents = []
        for m in messages:
            role = "user" if m["role"] != "assistant" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            resp = _post(
                f"{self.provider.base_url.rstrip('/')}/models/{self.model}:generateContent",
                self.provider.label,
                params={"key": self.credential},
                json=body,
                timeout=90,
            )
        except LLMError as exc:
            raise LLMError(
                f"{exc} Modèle demandé : « {self.model} ». Si ce modèle a été retiré par "
                "Google, choisissez un modèle actif via GEMINI_MODEL (par exemple "
                "gemini-flash-lite-latest)."
            ) from exc
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            if blocked:
                raise LLMError(f"Gemini a bloqué la requête ({blocked}).")
            raise LLMError("Gemini n'a renvoyé aucun candidat exploitable.")
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        if not text.strip():
            reason = candidates[0].get("finishReason") or "sans texte"
            raise LLMError(f"Gemini n'a renvoyé aucun texte exploitable ({reason}).")
        return text.strip()

    def _ollama(self, messages, system, temperature, max_tokens) -> str:
        payload_messages = ([{"role": "system", "content": system}] if system else []) + messages
        resp = _post(
            f"{(self.credential or self.provider.base_url).rstrip('/')}/api/chat",
            self.provider.label,
            json={
                "model": self.model,
                "messages": payload_messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=180,
        )
        data = resp.json()
        try:
            return data["message"]["content"].strip()
        except (KeyError, TypeError) as exc:
            raise LLMError(f"Réponse inattendue d'Ollama : {exc}") from exc


def get_client(preferred: Optional[str] = None) -> Optional[LLMClient]:
    """Retourne un client LLM prêt à l'emploi, ou ``None`` si aucun fournisseur."""
    if preferred and preferred in PROVIDER_BY_KEY:
        p = PROVIDER_BY_KEY[preferred]
        if _credential(p):
            return LLMClient(p)
    p = active_provider()
    return LLMClient(p) if p else None


def provider_status() -> Dict[str, Any]:
    """Statut consolidé pour l'affichage dans l'interface."""
    client = get_client()
    providers = available_providers()
    return {
        "mode": "llm" if client else "local",
        "active": client.label if client else "Analyste local (hors-ligne)",
        "provider_key": client.provider.key if client else None,
        "model": client.model if client else None,
        "providers": providers,
    }


def test_connection(preferred: Optional[str] = None) -> Tuple[bool, str]:
    """Test rapide de la connexion au fournisseur sélectionné."""
    client = get_client(preferred)
    if client is None:
        return False, "Aucun fournisseur configuré."
    try:
        text = client.chat(
            [{"role": "user", "content": "Réponds uniquement par : OK"}],
            system="Tu es un test de connexion.",
            temperature=0.0,
            max_tokens=12,
        )
        return True, f"Connexion réussie ({client.label}) : {text[:60]}"
    except LLMError as exc:
        return False, str(exc)
    except requests.RequestException as exc:
        return False, f"Erreur réseau : {exc}"
