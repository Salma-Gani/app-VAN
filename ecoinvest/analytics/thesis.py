"""Valuation & Trigger Engine — thèses de valorisation et conditions de suivi.

Transforme les hypothèses de l'utilisateur (multiple cible, marge de sécurité)
en une **thèse persistée**, puis surveille en continu les deux conditions qui
peuvent la rendre caduque :

1. le **prix** — le cours atteint-il le prix d'entrée calculé ?
2. la **métrique de référence** — le BPA, l'EBITDA, les fonds propres ou le
   dividende ont-ils changé depuis la création de la thèse ? Un prix cible se
   recalcule dès que le BPA bouge.

Une thèse n'est ni une recommandation, ni une prévision. C'est une condition de
surveillance explicite, rattachée à sa source et à son exercice comptable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from ..config import USER_THESES_FILE
from ..utils.formatting import as_float, safe_div

STATUS_LABELS = {
    "entry_reached": "Prix d'entrée atteint",
    "near": "Cours proche du prix d'entrée",
    "watch": "Sous surveillance",
    "stale": "Métrique à actualiser",
    "invalid": "Donnée manquante",
}

METRIC_BY_METHOD = {
    "per": ("eps", "BPA (résultat par action)", "MAD/action"),
    "ev_ebitda": ("ebitda", "EBITDA", "MAD"),
    "ev_ebit": ("ebit", "EBIT (résultat d'exploitation)", "MAD"),
    "pb": ("bvps", "Valeur comptable par action", "MAD/action"),
    "ps": ("sales_ps", "Ventes par action", "MAD/action"),
    "dividend": ("dps", "Dividende par action", "MAD/action"),
}


# ═══════════════════════════ Persistance ═══════════════════════════

def _read() -> Dict[str, List[Dict[str, Any]]]:
    try:
        with open(USER_THESES_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for symbol, records in data.items():
        if isinstance(records, dict):
            records = [records]
        out[str(symbol).strip().upper()] = [r for r in records or [] if isinstance(r, dict)]
    return out


def _write(store: Dict[str, List[Dict[str, Any]]]) -> None:
    tmp = USER_THESES_FILE.with_suffix(USER_THESES_FILE.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(store, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, USER_THESES_FILE)


def load_all() -> Dict[str, List[Dict[str, Any]]]:
    return _read()


def list_for(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    store = _read()
    if symbol:
        return list(store.get(symbol.strip().upper(), []))
    out: List[Dict[str, Any]] = []
    for records in store.values():
        out.extend(records)
    return out


def count() -> int:
    return len(list_for())


def save(thesis: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(thesis.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("Thèse sans symbole : enregistrement impossible.")
    thesis = dict(thesis)
    thesis["symbol"] = symbol
    thesis.setdefault("id", thesis_id(symbol, thesis.get("method"), thesis.get("fiscal_year")))
    thesis["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    store = _read()
    records = [r for r in store.get(symbol, []) if r.get("id") != thesis["id"]]
    records.append(thesis)
    records.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    store[symbol] = records
    _write(store)
    return thesis


def delete(thesis_id: str, symbol: Optional[str] = None) -> bool:
    store = _read()
    changed = False
    symbols = [symbol.strip().upper()] if symbol else list(store.keys())
    for key in symbols:
        records = store.get(key, [])
        kept = [r for r in records if r.get("id") != thesis_id]
        if len(kept) != len(records):
            changed = True
        if kept:
            store[key] = kept
        else:
            store.pop(key, None)
    if changed:
        _write(store)
    return changed


def thesis_id(symbol: str, method: Optional[str], fiscal_year: Any) -> str:
    return f"{str(symbol).strip().upper()}:{method or 'na'}:{fiscal_year or 'na'}"


# ═══════════════════════════ Construction ═══════════════════════════

def build(symbol: str, name: str, method: str, target: float, result: Dict[str, Any],
          required_margin: float, f: Dict[str, Any], price: Optional[float],
          method_label: str = "") -> Dict[str, Any]:
    """Construit une thèse à partir d'un résultat du Valuation Lab."""
    metric_key, metric_label, metric_unit = METRIC_BY_METHOD.get(
        method, ("eps", "Métrique", "")
    )
    return {
        "id": thesis_id(symbol, method, f.get("fiscal_year")),
        "symbol": str(symbol).strip().upper(),
        "name": name,
        "method": method,
        "method_label": method_label or method,
        "target": as_float(target),
        "metric_key": metric_key,
        "metric_label": metric_label,
        "metric_unit": metric_unit,
        "metric_value": as_float(result.get("metric_value")),
        "reference_price": as_float(price),
        "target_price": as_float(result.get("fair_value")),
        "required_margin": as_float(required_margin),
        "entry_price": as_float(result.get("entry_price")),
        "net_debt": as_float(result.get("net_debt")),
        "shares": as_float(result.get("shares")),
        "currency": f.get("statement_currency") or "MAD",
        "fiscal_year": f.get("fiscal_year"),
        "source": f.get("statement_source") or f.get("source"),
        "source_url": f.get("statement_url"),
        "as_of": f.get("as_of"),
        "status": "active",
        "notes": "",
        "alert_price": True,
        "alert_metric": True,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def current_metric(thesis: Dict[str, Any], f: Dict[str, Any]) -> Optional[float]:
    """Valeur actuelle de la métrique suivie, depuis la fiche fondamentale."""
    key = thesis.get("metric_key")
    if key == "sales_ps":
        shares = as_float(f.get("shares"))
        return safe_div(as_float(f.get("revenue")), shares) if shares else None
    if key == "bvps":
        shares = as_float(f.get("shares"))
        if f.get("bvps") is not None:
            return as_float(f.get("bvps"))
        return safe_div(as_float(f.get("equity")), shares) if shares else None
    return as_float(f.get(key))


def evaluate(thesis: Dict[str, Any], price: Optional[float],
             f: Dict[str, Any]) -> Dict[str, Any]:
    """Compare une thèse au cours et à la fiche fondamentale actuels."""
    price = as_float(price) or as_float(f.get("price"))
    entry = as_float(thesis.get("entry_price"))
    target_price = as_float(thesis.get("target_price"))
    metric = as_float(thesis.get("metric_value"))
    current = current_metric(thesis, f)

    flags: List[str] = []
    result: Dict[str, Any] = dict(thesis)
    result["current_price"] = price
    result["current_metric"] = current
    result["metric_change"] = None
    result["distance_entry"] = None
    result["distance_target"] = None

    if metric and current is not None:
        change = current / metric - 1.0
        result["metric_change"] = change
        if abs(change) > 0.01:
            flags.append("metric_changed")
    elif metric is None or current is None:
        flags.append("metric_missing")

    current_year = str(f.get("fiscal_year") or "")
    thesis_year = str(thesis.get("fiscal_year") or "")
    if thesis_year and current_year and thesis_year != current_year:
        flags.append("new_fiscal_year")

    if price and entry:
        result["distance_entry"] = price / entry - 1.0
    if price and target_price:
        result["distance_target"] = price / target_price - 1.0

    if entry is None or target_price is None:
        status = "invalid"
        flags.append("no_target")
    elif price is None:
        status = "invalid"
        flags.append("no_price")
    elif price <= entry:
        status = "entry_reached"
    elif price <= entry * 1.03:
        status = "near"
    elif {"metric_changed", "new_fiscal_year", "metric_missing"} & set(flags):
        status = "stale"
    else:
        status = "watch"

    result["status"] = status
    result["status_label"] = STATUS_LABELS.get(status, status)
    result["flags"] = flags
    result["needs_recalc"] = bool({"metric_changed", "new_fiscal_year"} & set(flags))
    return result


def evaluate_all(market_rows: Dict[str, Dict[str, Any]],
                 fundamentals_fn: Any) -> List[Dict[str, Any]]:
    """Évalue toutes les thèses à partir d'un accès ``{symbol: ligne marché}``."""
    out: List[Dict[str, Any]] = []
    for thesis in list_for():
        symbol = thesis.get("symbol")
        row = market_rows.get(symbol) or {}
        try:
            f = fundamentals_fn(symbol)
        except Exception:
            f = {}
        out.append(evaluate(thesis, row.get("close") if isinstance(row, dict) else None, f))
    return out


def to_frame(evaluated: List[Dict[str, Any]]) -> pd.DataFrame:
    if not evaluated:
        return pd.DataFrame(columns=[
            "Symbole", "Méthode", "Cible", "Prix théorique", "Prix d'entrée",
            "Cours actuel", "Statut", "Métrique", "Variation métrique",
        ])
    rows = []
    for item in evaluated:
        rows.append({
            "Symbole": item.get("symbol"),
            "Méthode": item.get("method_label"),
            "Cible": item.get("target"),
            "Prix théorique": item.get("target_price"),
            "Prix d'entrée": item.get("entry_price"),
            "Cours actuel": item.get("current_price"),
            "Statut": item.get("status_label"),
            "Métrique": item.get("metric_label"),
            "Variation métrique": item.get("metric_change"),
        })
    return pd.DataFrame(rows)
