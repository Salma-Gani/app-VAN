"""Indicateurs macroéconomiques marocains issus de sources publiques.

World Bank Open Data est utilisé pour les séries annuelles (PIB, inflation,
chômage). Ces données sont **annuelles, publiques et différées** : elles ne
remplacent pas les publications trimestrielles du HCP ou de Bank Al-Maghrib.
Aucune valeur n'est inventée ; si l'API est indisponible, le champ vaut ``None``
et un statut explicite est renvoyé.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from ..config import HTTP_TIMEOUT, TTL
from ..utils import cache

NS = "macro"
BASE = "https://api.worldbank.org/v2/country/MA/indicator"
INDICATORS = {
    "gdp_growth": {
        "code": "NY.GDP.MKTP.KD.ZG",
        "label": "Croissance du PIB",
        "unit": "%",
        "url": f"{BASE}/NY.GDP.MKTP.KD.ZG",
    },
    "inflation": {
        "code": "FP.CPI.TOTL.ZG",
        "label": "Inflation (IPC)",
        "unit": "%",
        "url": f"{BASE}/FP.CPI.TOTL.ZG",
    },
    "unemployment": {
        "code": "SL.UEM.TOTL.ZS",
        "label": "Taux de chômage",
        "unit": "%",
        "url": f"{BASE}/SL.UEM.TOTL.ZS",
    },
}


def _parse_indicator(payload: Any) -> Dict[str, Any]:
    """Extrait la dernière observation non nulle d'une réponse World Bank."""
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return {"value": None, "year": None, "updated": None}
    meta = payload[0] if isinstance(payload[0], dict) else {}
    for item in payload[1]:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if value is None:
            continue
        try:
            return {
                "value": float(value),
                "year": str(item.get("date") or ""),
                "updated": str(meta.get("lastupdated") or ""),
            }
        except (TypeError, ValueError):
            continue
    return {"value": None, "year": None, "updated": str(meta.get("lastupdated") or "")}


def _fetch(indicator: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    key = cache.make_key("worldbank", indicator["code"])
    if not force:
        hit = cache.get(NS, key, TTL.get("macro", 86400))
        if isinstance(hit, dict):
            return hit
    try:
        resp = requests.get(
            indicator["url"],
            params={"format": "json", "per_page": 8},
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "MarketMind/3.1 (research; contact: local)"},
        )
    except requests.RequestException as exc:
        return {"value": None, "year": None, "updated": None, "error": str(exc)}
    if resp.status_code != 200:
        return {"value": None, "year": None, "updated": None,
                "error": f"HTTP {resp.status_code}"}
    try:
        parsed = _parse_indicator(resp.json())
    except ValueError as exc:
        return {"value": None, "year": None, "updated": None, "error": f"JSON invalide : {exc}"}
    parsed["url"] = indicator["url"]
    parsed["source"] = "World Bank Open Data"
    cache.set(NS, key, parsed)
    return parsed


def morocco_indicators(force: bool = False) -> Dict[str, Any]:
    """Séries macro marocaines, avec année, source et statut de fraîcheur."""
    out: Dict[str, Any] = {
        "country": "Maroc",
        "source": "World Bank Open Data",
        "status": "annual_delayed",
        "url": "https://data.worldbank.org/country/morocco",
        "indicators": {},
    }
    errors: List[str] = []
    for key, meta in INDICATORS.items():
        data = _fetch(meta, force=force)
        if data.get("error"):
            errors.append(f"{meta['label']}: {data['error']}")
        out["indicators"][key] = {
            "label": meta["label"],
            "unit": meta["unit"],
            "value": data.get("value"),
            "year": data.get("year"),
            "updated": data.get("updated"),
            "url": meta["url"],
            "error": data.get("error"),
        }
    out["errors"] = errors
    out["available"] = any(v.get("value") is not None for v in out["indicators"].values())
    return out


def macro_context_text() -> str:
    """Bloc texte compact pour l'agent IA."""
    data = morocco_indicators()
    lines = ["### MACRO MAROC (World Bank Open Data, séries annuelles différées)"]
    for key in ("gdp_growth", "inflation", "unemployment"):
        item = data["indicators"].get(key) or {}
        value = item.get("value")
        if value is None:
            lines.append(f"- {item.get('label', key)} : donnée non disponible")
            continue
        lines.append(
            f"- {item.get('label')} : {value:.2f} {item.get('unit', '')} "
            f"({item.get('year') or 'année n.d.'})"
        )
    lines.append("- Source : https://data.worldbank.org/country/morocco — données annuelles, "
                 "ne pas confondre avec les taux BAM ou les publications trimestrielles du HCP.")
    return "\n".join(lines)
