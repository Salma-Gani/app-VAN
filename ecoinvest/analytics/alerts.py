"""Moteur d'alertes locales et explicables.

Les alertes sont des **observations conditionnelles** calculées à partir des
cours, volumes et indicateurs disponibles. Elles ne sont ni des ordres, ni des
recommandations d'achat ou de vente. Aucune notification push n'est envoyée :
l'utilisateur consulte le centre d'alertes dans l'application.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from ..utils.formatting import as_float, fmt_num, fmt_pct

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "rsi_low": 30.0,
    "rsi_high": 70.0,
    "drawdown": -0.20,
    "proximity": 0.015,
    "daily_move": 0.05,
    "volume_ratio": 2.0,
    "vix_high": 25.0,
}

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Alert:
    symbol: str
    name: str
    kind: str
    severity: str
    title: str
    detail: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    as_of: str = ""
    source: str = "BVC (cours et volumes)"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def thresholds(**overrides: float) -> Dict[str, float]:
    """Fusionne les seuils par défaut avec des valeurs validées."""
    out = dict(DEFAULT_THRESHOLDS)
    for key, value in overrides.items():
        if key not in out:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v != v:
            continue
        out[key] = v
    if out["rsi_low"] >= out["rsi_high"]:
        out["rsi_low"], out["rsi_high"] = 30.0, 70.0
    if out["drawdown"] > 0:
        out["drawdown"] = -abs(out["drawdown"])
    if out["proximity"] < 0:
        out["proximity"] = 0.0
    return out


def _date(value: Any) -> str:
    if value is None:
        return ""
    try:
        ts = pd.Timestamp(value)
        return "" if pd.isna(ts) else ts.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)


def _alert(row: Any, kind: str, severity: str, title: str, detail: str,
           value: Optional[float] = None, threshold: Optional[float] = None,
           source: str = "BVC (cours et volumes)") -> Alert:
    return Alert(
        symbol=str(row.get("symbol") or ""),
        name=str(row.get("name") or row.get("symbol") or ""),
        kind=kind,
        severity=severity,
        title=title,
        detail=detail,
        value=value,
        threshold=threshold,
        as_of=_date(row.get("last_date")),
        source=source,
    )


def evaluate_row(row: Any, summary: Optional[Dict[str, Any]] = None,
                 th: Optional[Dict[str, float]] = None) -> List[Alert]:
    """Évalue les règles d'alerte pour une valeur.

    ``row`` peut provenir de ``scoring.build_market_table`` ou du snapshot BVC.
    ``summary`` est la sortie de ``technical.technical_summary`` lorsqu'un
    historique est disponible (niveaux de support/résistance, signaux).
    """
    if row is None:
        return []
    try:
        data = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    except (TypeError, ValueError):
        return []
    th = thresholds(**(th or {}))
    close = as_float(data.get("close"))
    if close is None or close <= 0:
        return []

    out: List[Alert] = []
    low52 = as_float(data.get("low_52w"))
    high52 = as_float(data.get("high_52w"))
    prox = th["proximity"]

    if low52 is not None and low52 > 0 and close <= low52 * (1.0 + prox):
        gap = close / low52 - 1.0
        out.append(_alert(
            data, "low_52w", "warning", "Cours proche du plus bas 52 semaines",
            f"Cours {fmt_num(close, 2)} MAD, plus bas 52 semaines {fmt_num(low52, 2)} MAD "
            f"({fmt_pct(gap, 1, signed=True)}). Zone de vigilance : la liquidité peut se réduire.",
            close, low52,
        ))
    if high52 is not None and high52 > 0 and close >= high52 * (1.0 - prox):
        gap = close / high52 - 1.0
        out.append(_alert(
            data, "high_52w", "info", "Cours proche du plus haut 52 semaines",
            f"Cours {fmt_num(close, 2)} MAD, plus haut 52 semaines {fmt_num(high52, 2)} MAD "
            f"({fmt_pct(gap, 1, signed=True)}). Test de résistance possible, à confirmer par le volume.",
            close, high52,
        ))

    rsi = as_float(data.get("rsi14"))
    if rsi is None and summary:
        rsi = as_float((summary.get("momentum") or {}).get("rsi"))
    if rsi is not None:
        if rsi <= th["rsi_low"]:
            out.append(_alert(
                data, "rsi", "warning", "RSI en zone de survente",
                f"RSI(14) à {rsi:.0f} (seuil {th['rsi_low']:.0f}). Une survente n'est pas un signal "
                "d'achat automatique : vérifiez la tendance et les fondamentaux.", rsi, th["rsi_low"],
                "Indicateur calculé sur l'historique BVC",
            ))
        elif rsi >= th["rsi_high"]:
            out.append(_alert(
                data, "rsi", "warning", "RSI en zone de surachat",
                f"RSI(14) à {rsi:.0f} (seuil {th['rsi_high']:.0f}). Risque de consolidation ; "
                "surveillez le volume et les niveaux de support.", rsi, th["rsi_high"],
                "Indicateur calculé sur l'historique BVC",
            ))

    mdd = as_float(data.get("max_drawdown"))
    if mdd is not None and mdd <= th["drawdown"]:
        out.append(_alert(
            data, "drawdown", "critical", "Correction profonde depuis le plus haut",
            f"Drawdown maximal observé {fmt_pct(mdd, 1, signed=True)} (seuil "
            f"{fmt_pct(th['drawdown'], 0, signed=True)}). Vérifiez la thèse d'investissement et la liquidité.",
            mdd, th["drawdown"], "Calcul sur l'historique BVC",
        ))

    change = as_float(data.get("change_pct"))
    if change is not None and abs(change) >= th["daily_move"]:
        out.append(_alert(
            data, "daily_move", "warning", "Variation journalière inhabituelle",
            f"Variation de {fmt_pct(change, 2, signed=True)} sur la séance. "
            "Recherchez une actualité ou une opération sur titre avant d'agir.",
            change, th["daily_move"],
        ))

    if summary:
        levels = summary.get("levels") or {}
        support = as_float(levels.get("support"))
        resistance = as_float(levels.get("resistance"))
        if support is not None and support > 0 and close <= support * (1.0 + prox):
            out.append(_alert(
                data, "support", "warning", "Test du support technique",
                f"Cours {fmt_num(close, 2)} MAD à proximité du support 120 jours "
                f"{fmt_num(support, 2)} MAD. Une cassure invaliderait le scénario de rebond.",
                close, support, "Niveaux calculés sur l'historique BVC",
            ))
        if resistance is not None and resistance > 0 and close >= resistance * (1.0 - prox):
            out.append(_alert(
                data, "resistance", "info", "Test de la résistance technique",
                f"Cours {fmt_num(close, 2)} MAD à proximité de la résistance 120 jours "
                f"{fmt_num(resistance, 2)} MAD. Une cassure confirmée par le volume changerait le régime.",
                close, resistance, "Niveaux calculés sur l'historique BVC",
            ))
        for sig in summary.get("signals") or []:
            title = str(sig.get("signal") or "Signal technique")
            detail = str(sig.get("detail") or "")
            tone = "warning" if str(sig.get("type")) == "vente" else "info"
            out.append(_alert(
                data, "technical", tone, title, detail or "Signal détecté sur la dernière séance.",
                None, None, "Indicateurs calculés sur l'historique BVC",
            ))

    # Déduplication par (type, titre), conservation de l'alerte la plus sévère.
    dedup: Dict[Any, Alert] = {}
    for item in out:
        key = (item.kind, item.title)
        previous = dedup.get(key)
        if previous is None or _SEVERITY_ORDER.get(item.severity, 9) < _SEVERITY_ORDER.get(previous.severity, 9):
            dedup[key] = item
    return sorted(dedup.values(), key=lambda a: (_SEVERITY_ORDER.get(a.severity, 9), a.symbol, a.title))


def scan_market(table: pd.DataFrame, symbols: Optional[Sequence[str]] = None,
                th: Optional[Dict[str, float]] = None) -> List[Alert]:
    """Scanne le tableau de marché (sans historique détaillé)."""
    if table is None or table.empty:
        return []
    frame = table
    if symbols:
        wanted = {str(s).upper() for s in symbols}
        frame = table[table["symbol"].astype(str).str.upper().isin(wanted)]
    alerts: List[Alert] = []
    for _, row in frame.iterrows():
        alerts.extend(evaluate_row(row, th=th))
    return sorted(alerts, key=lambda a: (_SEVERITY_ORDER.get(a.severity, 9), a.symbol, a.title))


def scan_with_histories(table: pd.DataFrame, symbols: Sequence[str],
                        summaries: Dict[str, Dict[str, Any]],
                        th: Optional[Dict[str, float]] = None) -> List[Alert]:
    """Scanne une liste de valeurs en utilisant les résumés techniques fournis."""
    if table is None or table.empty or not symbols:
        return []
    wanted = {str(s).upper() for s in symbols}
    frame = table[table["symbol"].astype(str).str.upper().isin(wanted)]
    alerts: List[Alert] = []
    for _, row in frame.iterrows():
        sym = str(row.get("symbol") or "").upper()
        alerts.extend(evaluate_row(row, summary=summaries.get(sym), th=th))
    return sorted(alerts, key=lambda a: (_SEVERITY_ORDER.get(a.severity, 9), a.symbol, a.title))


def vix_alert(regime: Optional[Dict[str, Any]], th: Optional[Dict[str, float]] = None) -> Optional[Alert]:
    """Alerte de volatilité internationale (VIX, options S&P 500 — pas le MASI)."""
    th = thresholds(**(th or {}))
    if not regime:
        return None
    level = as_float(regime.get("level"))
    if level is None or level < th["vix_high"]:
        return None
    return Alert(
        symbol="^VIX",
        name="VIX — volatilité implicite S&P 500",
        kind="vix",
        severity="warning" if level < 30 else "critical",
        title="Volatilité internationale élevée",
        detail=(
            f"VIX à {level:.1f} (seuil {th['vix_high']:.0f}), régime « {regime.get('label')} ». "
            "Le VIX mesure la volatilité implicite des options sur le S&P 500 ; ce n'est pas une "
            "mesure directe de la volatilité du MASI."
        ),
        value=level,
        threshold=th["vix_high"],
        source="Yahoo Finance (^VIX)",
    )


def counts(alerts: Iterable[Alert]) -> Dict[str, int]:
    out = {"critical": 0, "warning": 0, "info": 0, "total": 0}
    for alert in alerts:
        out["total"] += 1
        if alert.severity in out:
            out[alert.severity] += 1
    return out


def to_frame(alerts: Iterable[Alert]) -> pd.DataFrame:
    rows = [a.to_dict() for a in alerts]
    if not rows:
        return pd.DataFrame(columns=["symbol", "name", "severity", "kind", "title", "detail", "as_of", "source"])
    return pd.DataFrame(rows)
