"""Couche HTTP commune : classification des erreurs, réessais et diagnostic.

Principes :

* **Distinguer** les causes : authentification (401), autorisation (403), ressource
  absente (404), limite de débit (429), panne serveur (5xx), délai, réseau, réponse
  vide ou illisible.
* **Réessayer** uniquement ce qui est réessayable (429, 5xx, réseau, délai), avec
  un délai exponentiel borné.
* **Ne jamais exposer** une clé, un token ou un en-tête d'authentification dans un
  message utilisateur ou dans le journal de diagnostic.
* **Ne pas masquer** : l'erreur est levée et enregistrée ; l'appelant décide d'un
  repli explicite (cache daté) ou d'un état « indisponible ».
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from ..config import HTTP_HEADERS, HTTP_RETRIES, HTTP_TIMEOUT

_SECRET_QUERY_KEYS = {
    "api_token", "apikey", "api_key", "key", "token", "access_token",
    "auth", "password", "secret", "client_secret",
}

KIND_LABELS = {
    "auth": "Authentification requise (401)",
    "forbidden": "Accès refusé (403)",
    "not_found": "Ressource introuvable (404)",
    "rate_limit": "Limite de débit atteinte (429)",
    "server": "Défaillance côté serveur (5xx)",
    "timeout": "Délai d'attente dépassé",
    "network": "Erreur réseau",
    "empty": "Réponse vide",
    "malformed": "Réponse illisible",
    "unknown": "Erreur inconnue",
}

USER_MESSAGES = {
    "auth": "Clé ou authentification invalide : vérifiez la configuration du fournisseur.",
    "forbidden": "Accès refusé par le fournisseur (droits ou abonnement insuffisants).",
    "not_found": "La ressource demandée n'existe pas, ou l'identifiant de l'instrument est incorrect.",
    "rate_limit": "Trop de requêtes : le fournisseur limite le débit. Réessayez dans quelques minutes.",
    "server": "Le fournisseur rencontre une panne. Les données en cache, si elles existent, restent affichées.",
    "timeout": "Le fournisseur ne répond pas assez vite. Réessayez plus tard.",
    "network": "Connexion au fournisseur impossible. Vérifiez votre réseau.",
    "empty": "Le fournisseur a répondu sans données pour cette requête.",
    "malformed": "Le fournisseur a renvoyé une réponse illisible.",
    "unknown": "Erreur inattendue lors de l'appel au fournisseur.",
}

_RETRYABLE = {"rate_limit", "server", "timeout", "network"}


def redact_url(url: str) -> str:
    """Retire toute valeur de secret d'une URL avant journalisation."""
    try:
        parts = urlsplit(url)
        query = [
            (k, "***" if k.lower() in _SECRET_QUERY_KEYS else v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return "<url>"


def classify_status(status: Optional[int]) -> str:
    if status is None:
        return "network"
    if status == 401:
        return "auth"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limit"
    if 500 <= status <= 599:
        return "server"
    if 400 <= status <= 499:
        return "unknown"
    return "unknown"


class ProviderError(RuntimeError):
    """Erreur d'un fournisseur, classifiée et sûre à afficher."""

    def __init__(self, provider: str, status: Optional[int] = None,
                 kind: str = "unknown", message: str = "",
                 retryable: bool = False, attempts: int = 1) -> None:
        self.provider = provider
        self.status = status
        self.kind = kind
        self.message = message
        self.retryable = retryable
        self.attempts = attempts
        super().__init__(self.user_message)

    @property
    def user_message(self) -> str:
        base = USER_MESSAGES.get(self.kind, USER_MESSAGES["unknown"])
        prefix = f"{self.provider} : " if self.provider else ""
        return prefix + base

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, KIND_LABELS["unknown"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "kind": self.kind,
            "label": self.label,
            "message": self.message,
            "retryable": self.retryable,
        }


# ─────────────────────────── Registre de diagnostic ───────────────────────────
# En mémoire, par processus. Aucun secret : les URLs sont expurgées.

_LOCK = threading.Lock()
_STATE: Dict[str, Dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_success(provider: str, count: Optional[int] = None, status: int = 200,
                   elapsed_ms: Optional[float] = None) -> None:
    with _LOCK:
        state = _STATE.setdefault(provider, {})
        state.update({
            "provider": provider,
            "status": "ok",
            "http_status": status,
            "last_success": _now(),
            "records": int(count) if count is not None else state.get("records"),
            "elapsed_ms": round(elapsed_ms, 1) if elapsed_ms is not None else None,
        })
        state.pop("last_error", None)


def record_error(provider: str, error: ProviderError) -> None:
    with _LOCK:
        state = _STATE.setdefault(provider, {})
        state.update({
            "provider": provider,
            "status": "error",
            "http_status": error.status,
            "kind": error.kind,
            "label": error.label,
            "last_error": error.message,
            "last_error_at": _now(),
        })


def state_for(provider: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        item = _STATE.get(provider)
        return dict(item) if item else None


def record_exception(provider: str, error: BaseException) -> ProviderError:
    """Enregistre une exception silencieuse sans la masquer au diagnostic.

    Utilisé par les connecteurs qui préfèrent renvoyer une valeur vide plutôt
    que d'interrompre la page. L'erreur reste consultable dans ``diagnostics()``.
    """
    if isinstance(error, ProviderError):
        wrapped = error
    else:
        kind = "timeout" if isinstance(error, TimeoutError) else "network"
        message = f"{error.__class__.__name__}: {error}"
        wrapped = ProviderError(provider, kind=kind, message=message)
    record_error(provider, wrapped)
    return wrapped


def diagnostics() -> List[Dict[str, Any]]:
    with _LOCK:
        return [dict(v) for v in sorted(_STATE.values(), key=lambda d: d.get("provider", ""))]


def clear() -> None:
    with _LOCK:
        _STATE.clear()


# ─────────────────────────────── Appel HTTP ───────────────────────────────


def _count(data: Any) -> Optional[int]:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("data", "results", "financials", "items", "values"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
        return 1
    return None


def _snippet(response: requests.Response) -> str:
    try:
        text = response.text or ""
    except Exception:
        return ""
    text = " ".join(text.split())
    return text[:180]


def request_json(
    url: str,
    provider: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    retries: Optional[int] = None,
    backoff: float = 0.5,
    allow_empty: bool = True,
) -> Any:
    """GET JSON avec classification, réessais ciblés et diagnostic.

    Lève ``ProviderError`` après épuisement des tentatives réessayables.
    """
    attempts = max(int(retries if retries is not None else HTTP_RETRIES), 1)
    request_headers = dict(HTTP_HEADERS)
    if headers:
        request_headers.update(headers)
    last: Optional[ProviderError] = None

    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            response = requests.get(
                url, params=params or {}, headers=request_headers,
                timeout=timeout or HTTP_TIMEOUT,
            )
        except requests.Timeout as exc:
            last = ProviderError(provider, None, "timeout", str(exc), True, attempt)
        except requests.RequestException as exc:
            last = ProviderError(provider, None, "network", str(exc), True, attempt)
        else:
            status = response.status_code
            kind = classify_status(status)
            if status == 200:
                if not (response.content or b"").strip():
                    if allow_empty:
                        record_success(provider, 0, status, (time.time() - started) * 1000)
                        return None
                    last = ProviderError(provider, status, "empty", "corps vide", False, attempt)
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        last = ProviderError(provider, status, "malformed", "JSON invalide", False, attempt)
                    else:
                        record_success(provider, _count(data), status, (time.time() - started) * 1000)
                        return data
            else:
                last = ProviderError(
                    provider, status, kind, f"HTTP {status} — {_snippet(response)}",
                    kind in _RETRYABLE, attempt,
                )

        assert last is not None
        record_error(provider, last)
        if not last.retryable or attempt >= attempts:
            break
        time.sleep(backoff * (2 ** (attempt - 1)))

    assert last is not None
    raise last
