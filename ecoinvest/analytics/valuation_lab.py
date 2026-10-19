"""Valuation Lab — moteur de prix théorique et de prix d'entrée.

Toutes les fonctions sont pures et testables. Elles ne fabriquent aucune donnée :
si la métrique de référence (BPA, EBITDA, capitaux propres, dividende) est absente
ou non pertinente, la fonction retourne ``available=False`` avec une raison explicite.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..utils.formatting import as_float, safe_div

# Méthodes et conventions d'affichage
METHODS: Dict[str, Dict[str, Any]] = {
    "per": {
        "label": "PER (P/E)",
        "metric": "BPA",
        "metric_unit": "MAD/action",
        "target_label": "PER cible (x)",
        "target_kind": "multiple",
        "default_target": 15.0,
    },
    "ev_ebitda": {
        "label": "EV/EBITDA",
        "metric": "EBITDA",
        "metric_unit": "MAD",
        "target_label": "EV/EBITDA cible (x)",
        "target_kind": "multiple",
        "default_target": 8.0,
    },
    "ev_ebit": {
        "label": "EV/EBIT",
        "metric": "EBIT",
        "metric_unit": "MAD",
        "target_label": "EV/EBIT cible (x)",
        "target_kind": "multiple",
        "default_target": 10.0,
    },
    "pb": {
        "label": "P/B (cours / actif net)",
        "metric": "Valeur comptable par action",
        "metric_unit": "MAD/action",
        "target_label": "P/B cible (x)",
        "target_kind": "multiple",
        "default_target": 1.5,
    },
    "ps": {
        "label": "P/S (cours / ventes)",
        "metric": "Ventes par action",
        "metric_unit": "MAD/action",
        "target_label": "P/S cible (x)",
        "target_kind": "multiple",
        "default_target": 1.5,
    },
    "dividend": {
        "label": "Rendement du dividende",
        "metric": "Dividende par action",
        "metric_unit": "MAD/action",
        "target_label": "Rendement exigé (%)",
        "target_kind": "yield",
        "default_target": 0.04,
    },
}


def target_per_price(target_per: float, eps: Optional[float]) -> Optional[float]:
    """Prix théorique = PER cible × BPA. Non calculé si le BPA est nul/négatif."""
    p = as_float(target_per)
    e = as_float(eps)
    if p is None or p <= 0 or e is None or e <= 0:
        return None
    return float(p * e)


def target_ev_ebitda_price(
    target_multiple: float,
    ebitda: Optional[float],
    net_debt: Optional[float] = None,
    shares: Optional[float] = None,
    adjustments: float = 0.0,
) -> Optional[float]:
    """Prix théorique via EV/EBITDA.

    EV = multiple × EBITDA ; capitaux propres = EV − dette nette + ajustements ;
    prix = capitaux propres / nombre d'actions.
    """
    m = as_float(target_multiple)
    e = as_float(ebitda)
    s = as_float(shares)
    if m is None or m <= 0 or e is None or e <= 0 or s is None or s <= 0:
        return None
    ev = m * e
    equity = ev - float(net_debt or 0.0) + float(adjustments or 0.0)
    if equity <= 0:
        return None
    return float(equity / s)


def target_ev_ebit_price(
    target_multiple: float,
    ebit: Optional[float],
    net_debt: Optional[float] = None,
    shares: Optional[float] = None,
    adjustments: float = 0.0,
) -> Optional[float]:
    """Prix théorique via EV/EBIT (même logique que EV/EBITDA)."""
    return target_ev_ebitda_price(target_multiple, ebit, net_debt, shares, adjustments)


def target_pb_price(target_pb: float, bvps: Optional[float]) -> Optional[float]:
    """Prix théorique = P/B cible × valeur comptable par action."""
    p = as_float(target_pb)
    b = as_float(bvps)
    if p is None or p <= 0 or b is None or b <= 0:
        return None
    return float(p * b)


def target_ps_price(target_ps: float, sales_per_share: Optional[float]) -> Optional[float]:
    """Prix théorique = P/S cible × ventes par action."""
    p = as_float(target_ps)
    s = as_float(sales_per_share)
    if p is None or p <= 0 or s is None or s <= 0:
        return None
    return float(p * s)


def target_dividend_price(dps: Optional[float], target_yield: float) -> Optional[float]:
    """Prix théorique = dividende par action / rendement exigé."""
    d = as_float(dps)
    y = as_float(target_yield)
    if d is None or d <= 0 or y is None or y <= 0:
        return None
    return float(d / y)


def implied_multiple(price: Optional[float], metric: Optional[float]) -> Optional[float]:
    """Multiple implicite = cours / métrique (métrique strictement positive)."""
    return safe_div(as_float(price), as_float(metric))


def margin_of_safety(fair_value: Optional[float], price: Optional[float]) -> Optional[float]:
    """Marge de sécurité = (valeur théorique − cours) / valeur théorique."""
    f = as_float(fair_value)
    p = as_float(price)
    if f is None or p is None or f <= 0:
        return None
    return float((f - p) / f)


def upside(fair_value: Optional[float], price: Optional[float]) -> Optional[float]:
    """Écart de prix = (valeur théorique − cours) / cours."""
    f = as_float(fair_value)
    p = as_float(price)
    if f is None or p is None or p <= 0:
        return None
    return float((f - p) / p)


def required_entry_price(fair_value: Optional[float], margin: float = 0.20) -> Optional[float]:
    """Prix d'entrée = valeur théorique × (1 − marge de sécurité exigée)."""
    f = as_float(fair_value)
    m = as_float(margin)
    if f is None or f <= 0 or m is None:
        return None
    m = max(0.0, min(0.90, float(m)))
    return float(f * (1.0 - m))


def price_zone(price: Optional[float], entry: Optional[float], fair: Optional[float]) -> Dict[str, str]:
    """Position du cours par rapport au prix d'entrée et à la valeur théorique."""
    p, e, f = as_float(price), as_float(entry), as_float(fair)
    if p is None or e is None or f is None:
        return {"key": "na", "label": "Indéterminé", "tone": "info",
                "text": "Données insuffisantes pour situer le cours."}
    if p <= e:
        return {
            "key": "below_entry", "label": "Sous le prix d'entrée", "tone": "up",
            "text": "Le cours est inférieur au prix d'entrée calculé avec votre marge de sécurité. "
                    "Cela ne constitue pas une recommandation : vérifiez les hypothèses et les risques.",
        }
    if p <= f:
        return {
            "key": "between", "label": "Entre l'entrée et la valeur théorique", "tone": "info",
            "text": "Le cours est au-dessus du prix d'entrée mais sous la valeur théorique. "
                    "La marge de sécurité exigée n'est pas atteinte.",
        }
    return {
        "key": "above_fair", "label": "Au-dessus de la valeur théorique", "tone": "down",
        "text": "Le cours dépasse la valeur théorique calculée avec vos hypothèses. "
                "Le marché valorise l'entreprise au-delà de votre scénario.",
    }


def method_catalog(f: Dict[str, Any], price: Optional[float] = None,
                   cap: Optional[float] = None) -> List[Dict[str, Any]]:
    """Liste les méthodes disponibles avec leur métrique et leur ratio actuel.

    Le catalogue ne calcule pas de prix : il expose les données nécessaires et la
    raison d'indisponibilité. L'interface peut ainsi demander une saisie vérifiée.
    """
    price = as_float(price) if price is not None else as_float(f.get("price"))
    cap = as_float(cap) if cap is not None else as_float(f.get("market_cap"))
    shares = as_float(f.get("shares"))
    net_income = as_float(f.get("net_income"))
    revenue = as_float(f.get("revenue"))
    ebitda = as_float(f.get("ebitda"))
    ebit = as_float(f.get("ebit"))
    equity = as_float(f.get("equity"))
    debt = as_float(f.get("total_debt")) or 0.0
    cash = as_float(f.get("cash")) or 0.0
    net_debt = float(debt) - float(cash)
    dps = as_float(f.get("dps"))
    eps = as_float(f.get("eps"))
    if eps is None and shares and net_income is not None:
        eps = net_income / shares
    bvps = as_float(f.get("bvps")) or (equity / shares if shares and equity is not None else None)
    sales_ps = revenue / shares if shares and revenue is not None else None
    ev = (cap + net_debt) if cap is not None else None

    out: List[Dict[str, Any]] = []

    def add(key: str, metric: Optional[float], current: Optional[float], reason: str) -> None:
        meta = dict(METHODS[key])
        available = metric is not None and metric > 0
        meta.update(
            {
                "key": key,
                "metric_value": float(metric) if metric is not None else None,
                "current_ratio": float(current) if current is not None else None,
                "available": bool(available),
                "reason": "" if available else reason,
                "default_target": float(current) if (current is not None and current > 0) else meta["default_target"],
                "source": f.get("source") or "",
                "fiscal_year": f.get("fiscal_year") or "",
                "as_of": f.get("as_of") or "",
            }
        )
        out.append(meta)

    add("per", eps, implied_multiple(price, eps),
        "BPA indisponible ou négatif : le PER n'est pas pertinent. Renseignez le résultat net "
        "et le nombre de titres, ou utilisez une autre méthode.")
    add("ev_ebitda", ebitda, implied_multiple(ev, ebitda),
        "EBITDA indisponible ou négatif. Renseignez l'EBITDA pour utiliser EV/EBITDA.")
    add("ev_ebit", ebit, implied_multiple(ev, ebit),
        "EBIT indisponible ou négatif. Renseignez le résultat d'exploitation pour EV/EBIT.")
    add("pb", bvps, implied_multiple(price, bvps),
        "Capitaux propres indisponibles : la valeur comptable par action ne peut pas être calculée.")
    add("ps", sales_ps, implied_multiple(price, sales_ps),
        "Chiffre d'affaires indisponible : le P/S ne peut pas être calculé.")
    add("dividend", dps, safe_div(dps, price),
        "Dividende par action indisponible. Le référentiel BVC ne publie pas de DPS pour cette valeur.")
    return out


def _metric_for_method(method: str, f: Dict[str, Any]) -> Optional[float]:
    shares = as_float(f.get("shares"))
    if method == "per":
        eps = as_float(f.get("eps"))
        if eps is None and shares and as_float(f.get("net_income")) is not None:
            eps = as_float(f.get("net_income")) / shares
        return eps
    if method == "ev_ebitda":
        return as_float(f.get("ebitda"))
    if method == "ev_ebit":
        return as_float(f.get("ebit"))
    if method == "pb":
        bvps = as_float(f.get("bvps"))
        if bvps is None and shares and as_float(f.get("equity")) is not None:
            bvps = as_float(f.get("equity")) / shares
        return bvps
    if method == "ps":
        return safe_div(as_float(f.get("revenue")), shares)
    if method == "dividend":
        return as_float(f.get("dps"))
    return None


def target_entry(
    method: str,
    target: float,
    f: Dict[str, Any],
    price: Optional[float] = None,
    net_debt: Optional[float] = None,
    shares: Optional[float] = None,
    adjustments: float = 0.0,
    required_margin: float = 0.20,
    metric_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Calcule la valeur théorique et le prix d'entrée pour une méthode donnée."""
    if method not in METHODS:
        return {"available": False, "reason": "Méthode inconnue."}
    price = as_float(price) if price is not None else as_float(f.get("price"))
    metric = as_float(metric_override) if metric_override is not None else _metric_for_method(method, f)
    shares = as_float(shares) if shares is not None else as_float(f.get("shares"))
    debt = as_float(f.get("total_debt")) or 0.0
    cash = as_float(f.get("cash")) or 0.0
    net_debt = as_float(net_debt) if net_debt is not None else (float(debt) - float(cash))
    meta = METHODS[method]

    fair: Optional[float]
    if method == "per":
        fair = target_per_price(target, metric)
    elif method == "ev_ebitda":
        fair = target_ev_ebitda_price(target, metric, net_debt, shares, adjustments)
    elif method == "ev_ebit":
        fair = target_ev_ebit_price(target, metric, net_debt, shares, adjustments)
    elif method == "pb":
        fair = target_pb_price(target, metric)
    elif method == "ps":
        fair = target_ps_price(target, metric)
    else:
        fair = target_dividend_price(metric, target)

    if fair is None or fair <= 0:
        reason = "Le calcul n'est pas possible avec ces données : métrique de référence absente, "
        reason += "nulle ou négative, ou nombre d'actions manquant."
        if method in ("ev_ebitda", "ev_ebit") and (shares is None or shares <= 0):
            reason += " Le nombre d'actions est nécessaire pour passer de la valeur d'entreprise "
            reason += "à la valeur par action."
        return {
            "available": False, "reason": reason, "method": method,
            "label": meta["label"], "metric_value": metric, "current_price": price,
        }

    entry = required_entry_price(fair, required_margin)
    mos = margin_of_safety(fair, price)
    up = upside(fair, price)
    zone = price_zone(price, entry, fair)
    current = None
    if method == "dividend":
        current = safe_div(metric, price)
    elif method in ("ev_ebitda", "ev_ebit"):
        cap = as_float(f.get("market_cap"))
        if cap is not None:
            current = safe_div(cap + net_debt, metric)
    elif method == "ps":
        current = safe_div(as_float(f.get("market_cap")), as_float(f.get("revenue")))
    else:
        current = implied_multiple(price, metric)

    return {
        "available": True,
        "method": method,
        "label": meta["label"],
        "metric_name": meta["metric"],
        "metric_unit": meta["metric_unit"],
        "metric_value": float(metric) if metric is not None else None,
        "current_ratio": current,
        "target_ratio": float(target),
        "current_price": price,
        "fair_value": fair,
        "entry_price": entry,
        "margin_required": float(required_margin),
        "margin_of_safety": mos,
        "upside": up,
        "zone": zone,
        "net_debt": net_debt,
        "shares": shares,
        "adjustments": float(adjustments or 0.0),
        "source": f.get("source") or "",
        "fiscal_year": f.get("fiscal_year") or "",
        "as_of": f.get("as_of") or "",
    }


def sensitivity(
    method: str,
    target: float,
    f: Dict[str, Any],
    price: Optional[float] = None,
    net_debt: Optional[float] = None,
    shares: Optional[float] = None,
    adjustments: float = 0.0,
    required_margin: float = 0.20,
    metric_override: Optional[float] = None,
    steps: int = 9,
    spread: float = 0.40,
) -> pd.DataFrame:
    """Table de sensibilité du prix théorique à l'hypothèse cible."""
    target = as_float(target)
    if target is None or target <= 0:
        return pd.DataFrame()
    factors = np.linspace(max(0.05, 1.0 - spread), 1.0 + spread, max(3, int(steps)))
    rows = []
    for factor in factors:
        t = float(target * factor)
        res = target_entry(method, t, f, price=price, net_debt=net_debt, shares=shares,
                           adjustments=adjustments, required_margin=required_margin,
                           metric_override=metric_override)
        rows.append(
            {
                "Hypothèse cible": t,
                "Prix théorique": res.get("fair_value"),
                "Prix d'entrée": res.get("entry_price"),
                "Écart vs cours": res.get("upside"),
                "Disponible": res.get("available"),
            }
        )
    return pd.DataFrame(rows)


def format_target_input(method: str, value: float) -> float:
    """Convertit une saisie utilisateur (%) en fraction pour le rendement exigé."""
    if METHODS.get(method, {}).get("target_kind") == "yield":
        return float(value) / 100.0
    return float(value)
