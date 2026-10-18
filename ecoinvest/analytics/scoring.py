"""Scoring multifactoriel et construction du tableau de screening du marché.

Le score composite combine cinq dimensions, chacune normalisée dans [-1, 1] :

* **Momentum technique** — RSI, MACD, stochastique, volumes
* **Tendance** — position vs moyennes mobiles 20/50/200
* **Valorisation** — P/E, rendement du dividende vs médiane sectorielle
* **Qualité** — ROE, marge nette, levier financier
* **Risque** — volatilité, drawdown maximal, bêta

Le tout est modulé par le **régime de marché** (VIX, largeur, tendance du MASI).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..config import SECTOR_RISK, TTL
from ..data import bvc, fundamentals, market, news
from ..utils import cache
from ..utils.formatting import as_float, safe_div
from . import risk as risk_mod
from . import technical as tech

NS = "screener"

DIMENSION_WEIGHTS = {
    "momentum": 0.30,
    "trend": 0.18,
    "valuation": 0.20,
    "quality": 0.17,
    "risk": 0.15,
}

DIMENSION_LABELS = {
    "momentum": "Momentum technique",
    "trend": "Tendance",
    "valuation": "Valorisation",
    "quality": "Qualité fondamentale",
    "risk": "Profil de risque",
}


# ═══════════════════════════ Construction du tableau ═══════════════════════════

def build_market_table(
    force: bool = False,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    include_fundamentals: bool = True,
) -> pd.DataFrame:
    """Tableau enrichi de toutes les valeurs cotées à la BVC.

    Fusionne : snapshot BVC (réel) → indicateurs techniques → mesures de risque
    → ratios fondamentaux disponibles → scores et signal d'entrée.
    """
    key = cache.make_key("market_table", include_fundamentals)
    if not force:
        hit = cache.get(NS, key, TTL["snapshot"])
        if hit is not None and not hit.empty:
            return hit

    snap = bvc.snapshot(force=force, progress_cb=progress_cb)
    if snap.empty:
        return snap

    histories = bvc.load_histories(snap["symbol"].tolist(), days=400, force=force)
    benchmark = bvc.index_history("MASI", period="2Y", force=force)
    bench_series = (
        benchmark.set_index("date")["value"].astype(float)
        if not benchmark.empty and "date" in benchmark.columns
        else None
    )
    store = fundamentals.load_store() if include_fundamentals else {}

    rows: List[Dict[str, Any]] = []
    for _, row in snap.iterrows():
        symbol = str(row["symbol"])
        hist = histories.get(symbol)
        rec: Dict[str, Any] = {}

        trend = {"state": "Indéterminé", "score": 0.0}
        momentum = {"state": "Indéterminé", "score": 0.0, "rsi": None}
        tech_score = None
        vol_1y = as_float(row.get("volatility"))
        beta = alpha = sharpe = mdd = None

        if hist is not None and not hist.empty:
            enriched = tech.add_indicators(hist)
            summary = tech.technical_summary(enriched)
            trend = summary["trend"]
            momentum = summary["momentum"]
            tech_score = summary["score"]
            rsi_v = momentum.get("rsi")
            if pd.isna(rsi_v) if rsi_v is not None else True:
                rsi_v = None
            macd_hist = enriched["macd_hist"].iloc[-1] if "macd_hist" in enriched else None
            macd_v = enriched["macd"].iloc[-1] if "macd" in enriched else None
            close_series = (
                enriched.set_index("date")["close"].astype(float)
                if "date" in enriched.columns
                else enriched["close"].astype(float)
            )
            prof = risk_mod.risk_profile(close_series, bench_series)
            vol_1y = prof.get("volatility") or vol_1y
            beta, alpha = prof.get("beta"), prof.get("alpha")
            sharpe, mdd = prof.get("sharpe"), prof.get("max_drawdown")
        else:
            rsi_v, macd_hist, macd_v = None, None, None

        f = fundamentals.get_fundamentals(symbol, row) if include_fundamentals else {}
        ratios = fundamentals.compute_ratios(f, price=as_float(row.get("close")), cap=as_float(row.get("cap"))) if include_fundamentals else {}

        rows.append(
            {
                **{k: row.get(k) for k in ("symbol", "name", "sector", "close", "change_pct",
                                           "volume", "transactions", "cap", "high_52w", "low_52w",
                                           "open", "high", "low", "prev_close", "last_date",
                                           "return_1m", "return_3m", "return_6m", "return_12m",
                                           "ytd_pct", "sma20", "sma50", "sma200")},
                "volatility": vol_1y,
                "beta": beta,
                "alpha": alpha,
                "sharpe": sharpe,
                "max_drawdown": mdd,
                "rsi14": as_float(rsi_v),
                "macd": as_float(macd_v),
                "macd_hist": as_float(macd_hist),
                "trend_state": trend.get("state"),
                "trend_score": trend.get("score"),
                "momentum_state": momentum.get("state"),
                "momentum_score": momentum.get("score"),
                "tech_score": tech_score,
                **{f"r_{k}": v for k, v in ratios.items()},
                "has_fundamentals": bool(f.get("_bvc") or store.get(symbol)),
                "sector_risk": SECTOR_RISK.get(str(row.get("sector")), 3),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = _add_valuation_and_quality(df, store)
    df = _add_composite(df)
    df = _add_signal(df)
    cache.set(NS, key, df)
    return df


def _sector_medians(df: pd.DataFrame, column: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if column not in df.columns:
        return out
    for sector, sub in df.groupby("sector"):
        vals = pd.to_numeric(sub[column], errors="coerce").dropna()
        vals = vals[vals > 0]
        if len(vals) >= 2:
            out[str(sector)] = float(vals.median())
    return out


def _linear_score(value: Optional[float], lo: float, hi: float, higher_better: bool = True) -> Optional[float]:
    """Mappe une valeur de [lo, hi] vers [-1, 1]."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    if hi == lo:
        return 0.0
    t = (v - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    return float((t * 2 - 1) if higher_better else (1 - t * 2))


def _add_valuation_and_quality(df: pd.DataFrame, store: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """Scores de valorisation et de qualité, avec référence sectorielle."""
    out = df.copy()
    per_med = _sector_medians(out, "r_per")
    pb_med = _sector_medians(out, "r_pb")

    val_scores, q_scores = [], []
    for _, row in out.iterrows():
        sector = str(row.get("sector"))
        per = as_float(row.get("r_per"))
        pb = as_float(row.get("r_pb"))
        dy = as_float(row.get("r_dividend_yield"))
        roe = as_float(row.get("r_roe"))
        margin = as_float(row.get("r_net_margin"))
        de = as_float(row.get("r_debt_to_equity"))
        fcf_y = as_float(row.get("r_fcf_yield"))
        growth = as_float(row.get("r_revenue_growth"))

        parts: List[Tuple[float, float]] = []
        if per is not None and per > 0:
            ref = per_med.get(sector, 15.0)
            # Un P/E inférieur à la médiane sectorielle est valorisant
            relative = per / ref if ref else 1.0
            parts.append((_linear_score(relative, 2.0, 0.5, higher_better=False) or 0.0, 0.45))
        if pb is not None and pb > 0:
            ref = pb_med.get(sector, 2.0)
            relative = pb / ref if ref else 1.0
            parts.append((_linear_score(relative, 2.5, 0.5, higher_better=False) or 0.0, 0.2))
        if dy is not None:
            parts.append((_linear_score(dy, 0.0, 0.08, higher_better=True) or 0.0, 0.35))
        val = float(sum(p * w for p, w in parts) / sum(w for _, w in parts)) if parts else None
        val_scores.append(val)

        qparts: List[Tuple[float, float]] = []
        if roe is not None:
            qparts.append((_linear_score(roe, 0.0, 0.30, higher_better=True) or 0.0, 0.4))
        if margin is not None:
            qparts.append((_linear_score(margin, -0.02, 0.25, higher_better=True) or 0.0, 0.3))
        if de is not None:
            qparts.append((_linear_score(de, 3.0, 0.0, higher_better=True) or 0.0, 0.2))
        if fcf_y is not None:
            qparts.append((_linear_score(fcf_y, 0.0, 0.12, higher_better=True) or 0.0, 0.1))
        if growth is not None:
            qparts.append((_linear_score(growth, -0.1, 0.25, higher_better=True) or 0.0, 0.2))
        q = float(sum(p * w for p, w in qparts) / sum(w for _, w in qparts)) if qparts else None
        q_scores.append(q)

    out["valuation_score"] = val_scores
    out["quality_score"] = q_scores
    out["per_sector_median"] = out["sector"].map(per_med)
    out["pb_sector_median"] = out["sector"].map(pb_med)
    out["data_completeness"] = out.apply(
        lambda r: sum(
            1 for k in ("r_per", "r_pb", "r_roe", "r_net_margin", "r_dividend_yield", "r_debt_to_equity")
            if as_float(r.get(k)) is not None
        ) / 6.0,
        axis=1,
    )
    return out


def _add_composite(df: pd.DataFrame) -> pd.DataFrame:
    """Score composite (0–100) par moyenne pondérée adaptative."""
    out = df.copy()
    cols = {
        "momentum": "momentum_score",
        "trend": "trend_score",
        "valuation": "valuation_score",
        "quality": "quality_score",
    }
    composites, detail = [], []
    for _, row in out.iterrows():
        acc, wsum, components = 0.0, 0.0, {}
        for dim, col in cols.items():
            v = as_float(row.get(col))
            if v is None:
                components[dim] = None
                continue
            components[dim] = float(v)
            acc += v * DIMENSION_WEIGHTS[dim]
            wsum += DIMENSION_WEIGHTS[dim]
        vol = as_float(row.get("volatility"))
        mdd = as_float(row.get("max_drawdown"))
        beta = as_float(row.get("beta"))
        rparts, rw = [], []
        if vol is not None:
            rparts.append(_linear_score(vol, 0.55, 0.08, higher_better=False) or 0.0)
            rw.append(0.5)
        if mdd is not None:
            rparts.append(_linear_score(abs(mdd), 0.65, 0.05, higher_better=False) or 0.0)
            rw.append(0.35)
        if beta is not None:
            rparts.append(_linear_score(beta, 2.0, 0.2, higher_better=False) or 0.0)
            rw.append(0.15)
        if rparts:
            risk_component = float(sum(rparts) / len(rparts))
            components["risk"] = risk_component
            acc += risk_component * DIMENSION_WEIGHTS["risk"]
            wsum += DIMENSION_WEIGHTS["risk"]
        else:
            components["risk"] = None
        composites.append(100.0 * (acc / wsum) / 2.0 + 50.0 if wsum > 0 else None)
        detail.append(components)

    out["composite_score"] = composites
    for dim in ("momentum", "trend", "valuation", "quality", "risk"):
        out[f"score_{dim}"] = [d.get(dim) for d in detail]
    return out


def _add_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Signal d'entrée consolidé (analyse fondamentale × technique × régime)."""
    out = df.copy()
    regime = market_regime()
    gate = regime.get("entry_gate", 0.0)

    signals, colors, plans, scores = [], [], [], []
    for _, row in out.iterrows():
        comp = as_float(row.get("composite_score"))
        mom = as_float(row.get("momentum_score")) or 0.0
        trend = as_float(row.get("trend_score")) or 0.0
        val = as_float(row.get("valuation_score"))
        q = as_float(row.get("quality_score"))
        completeness = as_float(row.get("data_completeness")) or 0.0

        if comp is None:
            signals.append("Données insuffisantes")
            colors.append("#8DA2C0")
            plans.append(None)
            scores.append(None)
            continue

        gated = comp + gate * 12.0
        if gated >= 72 and mom >= 0.15 and trend >= 0:
            sig, col = "🟢 Achat fort", "#22D3A6"
        elif gated >= 62 and trend >= -0.1:
            sig, col = "🟢 Achat", "#22D3A6"
        elif gated >= 52:
            sig, col = "🔵 Consolider / conserver", "#5B8DEF"
        elif gated >= 42:
            sig, col = "🟡 Attendre", "#F5B547"
        elif gated >= 32:
            sig, col = "🟠 Alléger", "#F5B547"
        else:
            sig, col = "🔴 Éviter / vendre", "#F45B69"

        if completeness < 0.34:
            sig = sig + " (technique seul)"

        signals.append(sig)
        colors.append(col)

        close = as_float(row.get("close"))
        atr_like = as_float(row.get("volatility"))
        low_52 = as_float(row.get("low_52w"))
        high_52 = as_float(row.get("high_52w"))
        plan = None
        if close:
            stop = close * (1 - min(max((atr_like or 0.25) / np.sqrt(252) * 2.5, 0.05), 0.20))
            target = high_52 if (high_52 and high_52 > close) else close * 1.15
            plan = {
                "prix": close,
                "entree_zone_basse": close * 0.98,
                "entree_zone_haute": close * 1.01,
                "stop": stop,
                "objectif": target,
                "risque": close - stop,
                "gain_potentiel": target - close,
                "ratio_rr": safe_div(target - close, close - stop) if close > stop else None,
            }
        plans.append(plan)
        scores.append(gated)

    out["signal"] = signals
    out["signal_color"] = colors
    out["gated_score"] = scores
    out["entry_plan"] = plans
    out["market_gate"] = gate
    out["market_regime"] = regime.get("label")
    return out


# ═══════════════════════════ Régime de marché ═══════════════════════════

def market_regime(force: bool = False) -> Dict[str, Any]:
    """Régime de marché consolidé : VIX, largeur de marché, tendance du MASI, news.

    ``entry_gate`` ∈ [-1, 1] : > 0 favorable aux entrées, < 0 défavorable.
    """
    key = "market_regime"
    if not force:
        hit = cache.get(NS, key, TTL["snapshot"])
        if hit is not None:
            return hit

    vix = market.vix_regime(force=force)
    breadth = bvc.market_breadth(force=force)

    try:
        masi = bvc.index_history("MASI", period="6M", force=force)
        enriched = tech.add_indicators(masi.rename(columns={"value": "close"})) if not masi.empty else pd.DataFrame()
        masi_trend = tech.trend_state(enriched) if not enriched.empty else {"state": "Indéterminé", "score": 0.0}
        masi_last = float(masi["value"].iloc[-1]) if not masi.empty else None
        masi_var = float(masi["variation"].dropna().iloc[-1]) if not masi.empty and masi["variation"].notna().any() else None
        masi_ytd = float(masi["ytd"].dropna().iloc[-1]) if not masi.empty and masi["ytd"].notna().any() else None
    except Exception:
        masi_trend = {"state": "Indéterminé", "score": 0.0}
        masi_last = masi_var = masi_ytd = None

    try:
        news_summary = news.market_news_summary(force=force)
    except Exception:
        news_summary = {"score": 0.0, "label": "Neutre", "count": 0}

    vix_score = vix.get("score") or 0.0
    breadth_score = float(breadth.get("breadth") or 0.0)
    trend_score = float(masi_trend.get("score") or 0.0)
    news_score = float(news_summary.get("score") or 0.0)

    gate = 0.30 * vix_score + 0.25 * breadth_score + 0.30 * trend_score + 0.15 * news_score
    gate = float(max(-1.0, min(1.0, gate)))

    if gate >= 0.35:
        label, color = "Risk-on — conditions favorables", "#22D3A6"
        advice = ("Le régime de marché soutient la prise de risque : les entrées sur valeurs "
                  "de qualité en tendance haussière sont statistiquement favorisées.")
    elif gate >= 0.1:
        label, color = "Légèrement favorable", "#5B8DEF"
        advice = "Contexte porteur mais sans excès : privilégiez les renforcements progressifs."
    elif gate >= -0.1:
        label, color = "Neutre — sélectivité requise", "#8DA2C0"
        advice = "Marché sans direction claire : concentrez-vous sur les meilleurs fondamentaux et fractionnez les entrées."
    elif gate >= -0.35:
        label, color = "Prudence — risk-off modéré", "#F5B547"
        advice = "Conditions dégradées : réduisez la taille des positions et privilégiez les valeurs défensives."
    else:
        label, color = "Risk-off — éviter les entrées", "#F45B69"
        advice = "Régime hostile : privilégiez le cash et les valeurs à faible bêta ; n'entrez pas en force."

    out = {
        "entry_gate": gate,
        "label": label,
        "color": color,
        "advice": advice,
        "vix": vix,
        "breadth": breadth,
        "masi_trend": masi_trend,
        "masi_last": masi_last,
        "masi_var": masi_var,
        "masi_ytd": masi_ytd,
        "news": news_summary,
        "components": {
            "Volatilité (VIX)": vix_score,
            "Largeur de marché": breadth_score,
            "Tendance MASI": trend_score,
            "Sentiment des news": news_score,
        },
    }
    cache.set(NS, key, out)
    return out


# ═══════════════════════════ Filtres de screening ═══════════════════════════

def filter_market(
    df: pd.DataFrame,
    sectors: Optional[List[str]] = None,
    signal_filter: Optional[List[str]] = None,
    min_cap: Optional[float] = None,
    max_cap: Optional[float] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    min_volume: Optional[float] = None,
    max_per: Optional[float] = None,
    min_dividend: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    max_volatility: Optional[float] = None,
    min_return_1y: Optional[float] = None,
    only_with_fundamentals: bool = False,
    search: str = "",
) -> pd.DataFrame:
    """Applique la batterie de filtres du screener."""
    out = df.copy()
    if sectors:
        out = out[out["sector"].isin(sectors)]
    if signal_filter:
        prefixes = [s.split(" ")[0] for s in signal_filter]
        out = out[out["signal"].apply(lambda s: any(s.startswith(p) for p in prefixes))]
    if min_cap is not None:
        out = out[out["cap"].fillna(0) >= min_cap]
    if max_cap is not None:
        out = out[out["cap"].fillna(np.inf) <= max_cap]
    if min_score is not None:
        out = out[out["composite_score"].fillna(-1) >= min_score]
    if max_score is not None:
        out = out[out["composite_score"].fillna(101) <= max_score]
    if min_volume is not None:
        out = out[out["volume"].fillna(0) >= min_volume]
    if max_per is not None:
        per = pd.to_numeric(out.get("r_per"), errors="coerce")
        out = out[per.notna() & (per > 0) & (per <= max_per)]
    if min_dividend is not None:
        dy = pd.to_numeric(out.get("r_dividend_yield"), errors="coerce")
        out = out[dy.fillna(-1) >= min_dividend]
    if min_sharpe is not None:
        out = out[out["sharpe"].fillna(-99) >= min_sharpe]
    if max_volatility is not None:
        out = out[out["volatility"].fillna(99) <= max_volatility]
    if min_return_1y is not None:
        out = out[out["return_12m"].fillna(-99) >= min_return_1y]
    if only_with_fundamentals:
        out = out[out["data_completeness"].fillna(0) >= 0.34]
    if search:
        needle = search.strip().lower()
        out = out[
            out["name"].str.lower().str.contains(needle, na=False)
            | out["symbol"].str.lower().str.contains(needle, na=False)
        ]
    return out.reset_index(drop=True)


def sector_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Agrégat par secteur : nombre de valeurs, performance, score moyen, volatilité."""
    if df is None or df.empty:
        return pd.DataFrame()
    g = df.groupby("sector")
    out = pd.DataFrame(
        {
            "Valeurs": g.size(),
            "Perf. jour": g["change_pct"].mean(),
            "Perf. 1 an": g["return_12m"].mean(),
            "Perf. YTD": g["ytd_pct"].mean(),
            "Score moyen": g["composite_score"].mean(),
            "Volatilité moy.": g["volatility"].mean(),
            "Capitalisation": g["cap"].sum(),
            "Volume": g["volume"].sum(),
        }
    ).reset_index()
    return out.sort_values("Score moyen", ascending=False).reset_index(drop=True)


def top_opportunities(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Meilleures opportunités : score élevé et momentum positif confirmé."""
    if df is None or df.empty:
        return pd.DataFrame()
    sub = df[df["composite_score"].notna()].copy()
    sub = sub[(sub["momentum_score"].fillna(-1) > 0)]
    return sub.nlargest(n, "gated_score")[
        ["symbol", "name", "sector", "close", "change_pct", "composite_score", "signal",
         "momentum_score", "valuation_score", "quality_score", "sharpe"]
    ].reset_index(drop=True)


def explain_score(row: pd.Series) -> Dict[str, Any]:
    """Décompose le score composite pour l'affichage pédagogique."""
    dims = {}
    for dim, col in (("momentum", "score_momentum"), ("trend", "score_trend"),
                     ("valuation", "score_valuation"), ("quality", "score_quality"),
                     ("risk", "score_risk")):
        v = as_float(row.get(col))
        dims[dim] = {
            "label": DIMENSION_LABELS[dim],
            "raw": v,
            "points": None if v is None else (v / 2.0 + 0.5) * 100.0,
            "weight": DIMENSION_WEIGHTS[dim],
        }
    return {
        "composite": as_float(row.get("composite_score")),
        "dimensions": dims,
        "signal": row.get("signal"),
        "signal_color": row.get("signal_color"),
    }
