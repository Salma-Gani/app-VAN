"""Comparaison sectorielle rigoureuse des valeurs de la Bourse de Casablanca.

Principes :

- **Aucune valeur inventée** : une donnée absente reste ``NaN`` / ``None`` et
  s'affiche « — ». Aucun zéro de remplissage.
- **Métriques de marché** disponibles pour toutes les valeurs (cours,
  capitalisation, performance 12 mois, volatilité, drawdown, rendement).
- **Métriques fondamentales** uniquement lorsque les états financiers sont
  renseignés (PER, P/B, EV/EBITDA, ROE, marge nette, dette, croissance).
- **Banques et assurances** : les multiples d'entreprise (EV/EBITDA) et le
  levier dette/fonds propres ne sont pas applicables ; ils sont neutralisés et
  signalés comme tels, jamais calculés de force.
- Chaque statistique expose le **nombre de valeurs réellement utilisées**.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..data import statements
from ..data.fundamentals import is_financial_sector

# ═══════════════════════════ Définition des métriques ═══════════════════════════

SECTOR_METRICS: Tuple[Dict[str, Any], ...] = (
    {"key": "cap", "label": "Capitalisation", "unit": "MAD", "kind": "marché",
     "better": None, "financial_excluded": False,
     "formula": "Cours de clôture × nombre de titres en circulation."},
    {"key": "close", "label": "Cours", "unit": "MAD", "kind": "marché",
     "better": None, "financial_excluded": False,
     "formula": "Dernier cours de clôture publié par la Bourse de Casablanca."},
    {"key": "return_12m", "label": "Performance 12 mois", "unit": "%", "kind": "marché",
     "better": "higher", "financial_excluded": False,
     "formula": "Variation du cours sur 12 mois glissants."},
    {"key": "volatility", "label": "Volatilité annualisée", "unit": "%", "kind": "marché",
     "better": "lower", "financial_excluded": False,
     "formula": "Écart-type des rendements quotidiens × √252."},
    {"key": "max_drawdown", "label": "Drawdown maximal", "unit": "%", "kind": "marché",
     "better": "higher", "financial_excluded": False,
     "formula": "Baisse maximale depuis un plus haut, sur l'historique disponible."},
    {"key": "r_dividend_yield", "label": "Rendement du dividende", "unit": "%", "kind": "marché",
     "better": "higher", "financial_excluded": False,
     "formula": "Dividende par action / cours. Le DPA provient du référentiel BVC ou des états."},
    {"key": "r_per", "label": "P/E", "unit": "x", "kind": "états financiers",
     "better": "lower", "financial_excluded": False,
     "formula": "Capitalisation / résultat net (ou cours / BPA). Non calculé si le résultat est négatif."},
    {"key": "r_pb", "label": "P/B", "unit": "x", "kind": "états financiers",
     "better": "lower", "financial_excluded": False,
     "formula": "Capitalisation / fonds propres (ou cours / actif net par action)."},
    {"key": "r_ev_ebitda", "label": "EV/EBITDA", "unit": "x", "kind": "états financiers",
     "better": "lower", "financial_excluded": True,
     "formula": "(Capitalisation + dette nette) / EBITDA. Non applicable aux banques et assurances."},
    {"key": "r_roe", "label": "ROE", "unit": "%", "kind": "états financiers",
     "better": "higher", "financial_excluded": False,
     "formula": "Résultat net / fonds propres."},
    {"key": "r_net_margin", "label": "Marge nette", "unit": "%", "kind": "états financiers",
     "better": "higher", "financial_excluded": False,
     "formula": "Résultat net / chiffre d'affaires."},
    {"key": "r_debt_to_equity", "label": "Dette / fonds propres", "unit": "x",
     "kind": "états financiers", "better": "lower", "financial_excluded": True,
     "formula": "Dette financière / fonds propres. Non pertinent pour les banques et assurances."},
    {"key": "r_revenue_growth", "label": "Croissance du CA", "unit": "%",
     "kind": "états financiers", "better": "higher", "financial_excluded": False,
     "formula": "(CA exercice N − CA exercice N−1) / CA exercice N−1."},
)

METRIC_BY_KEY: Dict[str, Dict[str, Any]] = {m["key"]: m for m in SECTOR_METRICS}

# Colonnes numériques utilisées pour les statistiques de secteur.
NUMERIC_KEYS = tuple(m["key"] for m in SECTOR_METRICS)


def applicable_metrics(sector: Optional[str]) -> List[Dict[str, Any]]:
    """Métriques pertinentes pour le secteur (exclut EV/EBITDA et levier si financier)."""
    financial = is_financial_sector(sector)
    return [
        metric for metric in SECTOR_METRICS
        if not (financial and metric["financial_excluded"])
    ]


def _latest_records(store: Optional[Dict[str, List[Dict[str, Any]]]]) -> Dict[str, Dict[str, Any]]:
    if store is None:
        store = statements.load_store()
    latest: Dict[str, Dict[str, Any]] = {}
    for symbol, records in (store or {}).items():
        if records:
            latest[str(symbol).upper()] = records[0]
    return latest


def _statement_metadata(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not record:
        return {
            "has_statement": False, "fiscal_year": None, "period": None,
            "consolidated": None, "source": None, "source_url": None,
            "currency": None, "unit": None, "source_unit": None,
        }
    return {
        "has_statement": True,
        "fiscal_year": record.get("fiscal_year"),
        "period": record.get("period") or "FY",
        # Ne jamais supposer le périmètre : None = non renseigné.
        "consolidated": record.get("consolidated"),
        "source": record.get("source") or record.get("provider"),
        "source_url": record.get("source_url"),
        "currency": record.get("currency"),
        "unit": record.get("unit"),
        "source_unit": record.get("source_unit") or record.get("unit"),
    }


def comparison_frame(
    market_df: pd.DataFrame,
    sector: str,
    store: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Dict[str, Any]]]:
    """Tableau brut des valeurs d'un secteur + métadonnées par société.

    Les valeurs restent numériques (``NaN`` si absentes) : la mise en forme et
    les « — » sont la responsabilité de l'interface.
    """
    if market_df is None or market_df.empty or "sector" not in market_df.columns:
        return pd.DataFrame(columns=["symbol", "name"] + list(NUMERIC_KEYS)), {}

    subset = market_df[market_df["sector"].astype(str) == str(sector)].copy()
    latest = _latest_records(store)
    rows: List[Dict[str, Any]] = []
    metadata: Dict[str, Dict[str, Any]] = {}
    financial = is_financial_sector(sector)

    for _, row in subset.iterrows():
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        item: Dict[str, Any] = {
            "symbol": symbol,
            "name": row.get("name") or symbol,
            "sector": row.get("sector"),
        }
        for key in NUMERIC_KEYS:
            value = pd.to_numeric(pd.Series([row.get(key)]), errors="coerce").iloc[0]
            if financial and METRIC_BY_KEY[key]["financial_excluded"]:
                value = np.nan
            item[key] = value
        meta = _statement_metadata(latest.get(symbol))
        meta["symbol"] = symbol
        meta["name"] = item["name"]
        metadata[symbol] = meta
        item["has_statement"] = meta["has_statement"]
        raw_fund = row.get("has_fundamentals")
        item["has_fundamentals"] = bool(raw_fund) if pd.notna(raw_fund) else False
        item["fiscal_year"] = meta["fiscal_year"]
        item["statement_source"] = meta["source"]
        # Champs saisis à la main : les rendre visibles dans le détail société
        # pour ne pas les confondre avec un chiffre extrait d'un document.
        item["fundamentals_source"] = (
            None if pd.isna(row.get("fundamentals_source")) else row.get("fundamentals_source")
        )
        manual_fields = row.get("manual_fields")
        item["manual_fields"] = "" if pd.isna(manual_fields) else str(manual_fields)
        rows.append(item)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "name"] + list(NUMERIC_KEYS)), {}
    frame = frame.sort_values("cap", ascending=False, na_position="last").reset_index(drop=True)
    return frame, metadata


def sector_medians(
    frame: pd.DataFrame,
    sector: str,
) -> Dict[str, Dict[str, Any]]:
    """Médiane de chaque métrique, avec le nombre de valeurs réellement utilisées."""
    total = 0 if frame is None else len(frame)
    out: Dict[str, Dict[str, Any]] = {}
    for metric in SECTOR_METRICS:
        key = metric["key"]
        applicable = not (is_financial_sector(sector) and metric["financial_excluded"])
        values = pd.Series(dtype=float)
        if frame is not None and not frame.empty and key in frame.columns:
            values = pd.to_numeric(frame[key], errors="coerce").dropna()
        out[key] = {
            "value": float(values.median()) if len(values) else None,
            "count": int(len(values)),
            "total": int(total),
            "applicable": bool(applicable),
        }
    return out


def sector_overview(market_df: pd.DataFrame) -> pd.DataFrame:
    """Synthèse de tous les secteurs : taille, performance, valorisation, couverture."""
    columns = [
        "Secteur", "Valeurs", "Capitalisation médiane", "Perf. 12 mois médiane",
        "Volatilité médiane", "Rendement du dividende médian", "P/E médian",
        "ROE médian", "Valeurs avec ratios",
    ]
    if market_df is None or market_df.empty or "sector" not in market_df.columns:
        return pd.DataFrame(columns=columns)

    df = market_df.copy()
    for key in NUMERIC_KEYS:
        if key in df.columns:
            df[key] = pd.to_numeric(df[key], errors="coerce")
    fund_columns = [c for c in ("r_per", "r_pb", "r_roe", "r_net_margin", "r_ev_ebitda")
                    if c in df.columns]

    rows: List[Dict[str, Any]] = []
    for sector, sub in df.groupby(df["sector"].fillna("Non renseigné"), dropna=False):
        covered = int(sub[fund_columns].notna().any(axis=1).sum()) if fund_columns else 0
        rows.append({
            "Secteur": sector,
            "Valeurs": int(len(sub)),
            "Capitalisation médiane": sub["cap"].median() if "cap" in sub else np.nan,
            "Perf. 12 mois médiane": sub["return_12m"].median() if "return_12m" in sub else np.nan,
            "Volatilité médiane": sub["volatility"].median() if "volatility" in sub else np.nan,
            "Rendement du dividende médian": (
                sub["r_dividend_yield"].median() if "r_dividend_yield" in sub else np.nan
            ),
            "P/E médian": sub["r_per"].median() if "r_per" in sub else np.nan,
            "ROE médian": sub["r_roe"].median() if "r_roe" in sub else np.nan,
            "Valeurs avec ratios": covered,
        })
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame
    return frame.sort_values("Capitalisation médiane", ascending=False, na_position="last").reset_index(drop=True)


def rank_position(
    value: Optional[float],
    series: pd.Series,
    better: Optional[str],
) -> Optional[float]:
    """Rang relatif 0–100 (100 = meilleur) parmi les valeurs disponibles.

    ``better="lower"`` inverse le classement (P/E bas = meilleur). Retourne
    ``None`` si la valeur ou la série est indisponible.
    """
    if value is None or (isinstance(value, float) and value != value):
        return None
    clean = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    if clean.empty:
        return None
    ascending = better != "lower"
    ranks = clean.rank(method="average", ascending=ascending)
    # Rang de la valeur (première occurrence en cas d'égalité).
    matches = clean[clean == value]
    if matches.empty:
        return None
    position = float(ranks.loc[matches.index[0]])
    if len(clean) == 1:
        return 100.0
    return float((position - 1) / (len(clean) - 1) * 100.0)


def comparability_notes(
    metadata: Dict[str, Dict[str, Any]],
    sector: str,
) -> List[str]:
    """Signale ce qui empêche une comparaison parfaitement homogène."""
    notes: List[str] = []
    with_statement = {s: m for s, m in metadata.items() if m.get("has_statement")}
    if not with_statement:
        notes.append(
            "Aucune société de ce secteur ne dispose d'états financiers vérifiés : "
            "seules les métriques de marché sont comparables. Importez les états "
            "dans « États financiers » pour activer PER, P/B, ROE et marges."
        )
    else:
        years = sorted({m.get("fiscal_year") for m in with_statement.values()
                        if m.get("fiscal_year")})
        if len(years) > 1:
            notes.append(
                "Exercices différents selon les sociétés : "
                + ", ".join(str(y) for y in years)
                + ". Les multiples ne sont pas strictement comparables ; vérifiez l'exercice "
                  "de chaque ligne avant de conclure."
            )
        # Un périmètre inconnu n'est ni social ni consolidé : on ne le compare pas.
        consolidations = {m.get("consolidated") for m in with_statement.values()
                          if m.get("consolidated") is not None}
        if len(consolidations) > 1:
            notes.append(
                "Comptes sociaux et consolidés mélangés : le périmètre comptable diffère "
                "d'une société à l'autre, les ratios peuvent ne pas être homogènes."
            )
    if is_financial_sector(sector):
        notes.append(
            "Secteur financier : EV/EBITDA et dette/fonds propres sont masqués car "
            "non pertinents pour les banques et assurances."
        )
    return notes


def coverage_summary(frame: pd.DataFrame) -> Dict[str, int]:
    """Répartition des sociétés selon la disponibilité des données.

    - ``with_statement`` : au moins un état financier vérifié enregistré ;
    - ``with_ratios`` : au moins un ratio fondamental réellement calculable ;
    - ``market_only`` : aucune donnée fondamentale exploitable.
    """
    if frame is None or frame.empty:
        return {"total": 0, "with_statement": 0, "with_ratios": 0, "market_only": 0}
    with_statement = int(frame.get("has_statement", pd.Series(dtype=bool)).fillna(False).sum())
    ratio_columns = [c for c in ("r_per", "r_pb", "r_roe", "r_net_margin", "r_ev_ebitda")
                     if c in frame.columns]
    with_ratios = int(frame[ratio_columns].notna().any(axis=1).sum()) if ratio_columns else 0
    total = int(len(frame))
    return {
        "total": total,
        "with_statement": with_statement,
        "with_ratios": with_ratios,
        "market_only": total - with_ratios,
    }


__all__ = [
    "SECTOR_METRICS", "METRIC_BY_KEY", "NUMERIC_KEYS", "applicable_metrics",
    "comparability_notes", "comparison_frame", "coverage_summary",
    "is_financial_sector", "rank_position", "sector_medians", "sector_overview",
]
