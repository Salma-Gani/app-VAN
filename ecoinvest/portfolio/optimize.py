"""Classes d'actifs, frontière efficiente et optimisation d'allocation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..config import (
    BROKERAGE_FEE,
    CAPITAL_GAINS_TAX,
    DIVIDEND_TAX,
    INFLATION_RATE,
    MASI_LONG_TERM_RETURN,
    MASI_LONG_TERM_VOL,
    RISK_FREE_RATE,
    TTL,
)
from ..data import bvc, market
from ..utils import cache
from ..utils.formatting import as_float, safe_div

NS = "optim"

# ═══════════════════════════ Classes d'actifs ═══════════════════════════

ASSUMPTIONS: Dict[str, Dict[str, Any]] = {
    "BVC_MASI": {
        "label": "Actions BVC — MASI",
        "expected_return": MASI_LONG_TERM_RETURN,
        "volatility": MASI_LONG_TERM_VOL,
        "liquidity": "Moyenne",
        "tax": CAPITAL_GAINS_TAX,
        "min_ticket": 10_000,
        "horizon_min": 5,
        "note": "Exposition large au marché marocain. Rendement historique MASI ~9-10 % brut sur longue période.",
        "source": "hypothèse(long terme) / série MASI",
    },
    "BVC_BLUECHIP": {
        "label": "Actions BVC — grandes capitalisations",
        "expected_return": 0.105,
        "volatility": 0.16,
        "liquidity": "Bonne",
        "tax": CAPITAL_GAINS_TAX,
        "min_ticket": 5_000,
        "horizon_min": 5,
        "note": "Valeurs les plus liquides (MASI 20) : meilleure exécution, volatilité un peu plus faible.",
        "source": "hypothèse dérivée du MASI 20",
    },
    "BVC_SELECT": {
        "label": "Sélection de valeurs BVC (score élevé)",
        "expected_return": 0.125,
        "volatility": 0.19,
        "liquidity": "Variable",
        "tax": CAPITAL_GAINS_TAX,
        "min_ticket": 5_000,
        "horizon_min": 5,
        "note": "Portefeuille concentré issu du screener. Rendement potentiel supérieur, risque spécifique accru.",
        "source": "hypothèse (sélection active)",
    },
    "GLOBAL_EQ": {
        "label": "Actions internationales (S&P 500)",
        "expected_return": 0.09,
        "volatility": 0.16,
        "liquidity": "Très bonne",
        "tax": CAPITAL_GAINS_TAX,
        "min_ticket": 1_000,
        "horizon_min": 7,
        "note": "Diversification géographique et devises. Risque de change EUR/USD.",
        "source": "série S&P 500 (Yahoo Finance)",
    },
    "GOLD": {
        "label": "Or (couverture)",
        "expected_return": 0.055,
        "volatility": 0.15,
        "liquidity": "Bonne",
        "tax": CAPITAL_GAINS_TAX,
        "min_ticket": 1_000,
        "horizon_min": 5,
        "note": "Décorrélé des actions : amortisseur en période de crise, rendement de long terme modéré.",
        "source": "série Or (Yahoo Finance)",
    },
    "BONDS": {
        "label": "Obligations / bons du Trésor",
        "expected_return": 0.035,
        "volatility": 0.03,
        "liquidity": "Moyenne",
        "tax": 0.20,
        "min_ticket": 100_000,
        "horizon_min": 2,
        "note": "Revenu régulier, capital peu volatil. Ticket d'entrée élevé sur le marché marocain.",
        "source": "hypothèse (courbe BDT marocaine)",
    },
    "DEPOSIT": {
        "label": "Dépôt bancaire rémunéré",
        "expected_return": 0.025,
        "volatility": 0.004,
        "liquidity": "Très bonne",
        "tax": 0.20,
        "min_ticket": 0,
        "horizon_min": 0,
        "note": "Sans risque de capital (dans la limite de la garantie), rendement souvent inférieur à l'inflation.",
        "source": "hypothèse (taux moyen rémunéré)",
    },
    "REAL_ESTATE": {
        "label": "Immobilier locatif",
        "expected_return": 0.055,
        "volatility": 0.09,
        "liquidity": "Très faible",
        "tax": 0.15,
        "min_ticket": 500_000,
        "horizon_min": 8,
        "note": "Rendement locatif net + valorisation. Illiquide, frais d'acquisition et de gestion, effet de levier possible.",
        "source": "hypothèse (rendement locatif net Maroc)",
    },
    "CASH": {
        "label": "Cash / monétaire",
        "expected_return": 0.012,
        "volatility": 0.001,
        "liquidity": "Immédiate",
        "tax": 0.0,
        "min_ticket": 0,
        "horizon_min": 0,
        "note": "Réserve de précaution et munitions pour saisir les opportunités.",
        "source": "hypothèse (cash courant)",
    },
}


@dataclass
class AssetClass:
    code: str
    label: str
    expected_return: float
    volatility: float
    liquidity: str
    tax: float
    min_ticket: float
    horizon_min: int
    note: str
    source: str
    real_stats: bool = False


def asset_classes(force: bool = False) -> List[AssetClass]:
    """Classes d'actifs disponibles, avec statistiques réelles quand elles existent."""
    key = "asset_classes"
    if not force:
        hit = cache.get(NS, key, TTL["history"])
        if hit is not None:
            return [AssetClass(**d) for d in hit]

    out: List[AssetClass] = []
    real: Dict[str, Tuple[Optional[float], Optional[float]]] = {}

    # Statistiques réelles : MASI (5 ans), S&P 500 et Or (10 ans)
    try:
        masi = bvc.index_history("MASI", period="5Y", force=force)
        if not masi.empty and len(masi) > 250:
            from ..analytics import risk as risk_mod

            series = masi.set_index("date")["value"]
            real["BVC_MASI"] = (risk_mod.annualized_return(series), risk_mod.annualized_volatility(series))
    except Exception:
        pass
    try:
        from ..analytics import risk as risk_mod

        for code, ticker in (("GLOBAL_EQ", "^GSPC"), ("GOLD", "GC=F")):
            hist = market.global_history(ticker, period="10y", force=force)
            if not hist.empty and len(hist) > 500:
                series = hist.set_index("date")["close"]
                real[code] = (risk_mod.annualized_return(series), risk_mod.annualized_volatility(series))
    except Exception:
        pass

    for code, cfg in ASSUMPTIONS.items():
        er = float(cfg["expected_return"])
        vol = float(cfg["volatility"])
        is_real = False
        if code in real:
            r_ret, r_vol = real[code]
            if r_ret is not None and r_vol is not None and np.isfinite(r_ret):
                # Ancrage : hypothèse long terme majoritaire, corrigée modérément par l'observé.
                # Évite le biais de récence (ex. flambée récente de l'or).
                blended = 0.65 * float(cfg["expected_return"]) + 0.35 * float(r_ret)
                er = float(np.clip(blended,
                                   float(cfg["expected_return"]) - 0.03,
                                   float(cfg["expected_return"]) + 0.03))
                vol = float(np.clip(r_vol, 0.005, 0.60))
                is_real = True
        out.append(
            AssetClass(
                code=code,
                label=cfg["label"],
                expected_return=er,
                volatility=vol,
                liquidity=cfg["liquidity"],
                tax=float(cfg["tax"]),
                min_ticket=float(cfg["min_ticket"]),
                horizon_min=int(cfg["horizon_min"]),
                note=cfg["note"],
                source=cfg["source"],
                real_stats=is_real,
            )
        )
    cache.set(NS, key, [a.__dict__ for a in out])
    return out


def asset_frame(force: bool = False) -> pd.DataFrame:
    rows = []
    for a in asset_classes(force=force):
        rows.append(
            {
                "code": a.code,
                "Classe d'actifs": a.label,
                "Rendement attendu": a.expected_return,
                "Volatilité": a.volatility,
                "Rendement réel": (1 + a.expected_return) / (1 + INFLATION_RATE) - 1,
                "Liquidité": a.liquidity,
                "Fiscalité": a.tax,
                "Ticket min. (MAD)": a.min_ticket,
                "Horizon min. (ans)": a.horizon_min,
                "Rendement net": a.expected_return * (1 - a.tax),
                "Ratio de Sharpe": safe_div(a.expected_return - RISK_FREE_RATE, a.volatility),
                "Source": a.source,
                "Statistiques réelles": a.real_stats,
                "Interprétation": a.note,
            }
        )
    return pd.DataFrame(rows)


# ═══════════════════════════ Optimisation ═══════════════════════════

def _stats_arrays(classes: Sequence[AssetClass]) -> Tuple[np.ndarray, np.ndarray]:
    mu = np.array([c.expected_return for c in classes], dtype=float)
    sigma = np.array([c.volatility for c in classes], dtype=float)
    return mu, sigma


def _correlation(classes: Sequence[AssetClass]) -> np.ndarray:
    """Matrice de corrélation forfaitaire, calibrée sur les grandes classes d'actifs."""
    codes = [c.code for c in classes]
    n = len(codes)
    corr = np.eye(n)
    pairs = {
        ("BVC_MASI", "BVC_BLUECHIP"): 0.94,
        ("BVC_MASI", "BVC_SELECT"): 0.82,
        ("BVC_BLUECHIP", "BVC_SELECT"): 0.86,
        ("BVC_MASI", "GLOBAL_EQ"): 0.35,
        ("BVC_BLUECHIP", "GLOBAL_EQ"): 0.34,
        ("BVC_SELECT", "GLOBAL_EQ"): 0.30,
        ("BVC_MASI", "GOLD"): 0.05,
        ("GLOBAL_EQ", "GOLD"): 0.02,
        ("BVC_MASI", "BONDS"): 0.10,
        ("GLOBAL_EQ", "BONDS"): -0.05,
        ("GOLD", "BONDS"): 0.15,
        ("BVC_MASI", "DEPOSIT"): 0.0,
        ("BVC_MASI", "CASH"): 0.0,
        ("BVC_MASI", "REAL_ESTATE"): 0.25,
        ("REAL_ESTATE", "BONDS"): 0.20,
        ("BONDS", "DEPOSIT"): 0.75,
        ("DEPOSIT", "CASH"): 0.85,
        ("BONDS", "CASH"): 0.65,
        ("GLOBAL_EQ", "REAL_ESTATE"): 0.10,
        ("GOLD", "REAL_ESTATE"): 0.05,
        ("GOLD", "DEPOSIT"): 0.0,
        ("GLOBAL_EQ", "DEPOSIT"): 0.0,
        ("BVC_SELECT", "GOLD"): 0.03,
        ("BVC_SELECT", "BONDS"): 0.08,
        ("BVC_SELECT", "REAL_ESTATE"): 0.24,
        ("BVC_BLUECHIP", "GOLD"): 0.04,
        ("BVC_BLUECHIP", "BONDS"): 0.10,
        ("BVC_BLUECHIP", "REAL_ESTATE"): 0.26,
    }
    for (a, b), value in pairs.items():
        if a in codes and b in codes:
            i, j = codes.index(a), codes.index(b)
            corr[i, j] = corr[j, i] = value
    # Rend la matrice définie positive
    eigvals, eigvecs = np.linalg.eigh(corr)
    eigvals = np.clip(eigvals, 1e-6, None)
    corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
    d = np.sqrt(np.diag(corr))
    corr = corr / np.outer(d, d)
    np.fill_diagonal(corr, 1.0)
    return corr


def portfolio_stats(w: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> Tuple[float, float]:
    ret = float(w @ mu)
    vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
    return ret, vol


def random_portfolios(
    classes: Sequence[AssetClass],
    n: int = 20000,
    max_weight: float = 0.55,
    seed: int = 42,
) -> pd.DataFrame:
    """Échantillonne l'univers des portefeuilles possibles (frontière efficiente)."""
    mu, sigma = _stats_arrays(classes)
    corr = _correlation(classes)
    cov = np.outer(sigma, sigma) * corr
    rng = np.random.default_rng(seed)
    k = len(classes)
    weights = rng.dirichlet(np.ones(k), size=n)
    # Applique une contrainte de concentration par rejet/renormalisation
    for _ in range(6):
        over = weights > max_weight
        if not over.any():
            break
        weights[over] = max_weight
        weights = weights / weights.sum(axis=1, keepdims=True)
    rets = weights @ mu
    vols = np.sqrt(np.einsum("ij,jk,ik->i", weights, cov, weights))
    sharpes = (rets - RISK_FREE_RATE) / np.maximum(vols, 1e-9)
    df = pd.DataFrame({"return": rets, "vol": vols, "sharpe": sharpes})
    for i, c in enumerate(classes):
        df[c.code] = weights[:, i]
    return df


def optimize(
    classes: Sequence[AssetClass],
    objective: str = "max_sharpe",
    max_weight: float = 0.55,
    n: int = 20000,
) -> Dict[str, Any]:
    """Résout l'allocation optimale (Sharpe maximal, variance minimale ou rendement cible)."""
    df = random_portfolios(classes, n=n, max_weight=max_weight)
    mu, sigma = _stats_arrays(classes)
    corr = _correlation(classes)
    cov = np.outer(sigma, sigma) * corr

    if objective == "min_variance":
        idx = df["vol"].idxmin()
    elif objective == "max_return":
        # Meilleur rendement sous contrainte de volatilité raisonnable
        sub = df[df["vol"] <= df["vol"].quantile(0.25)]
        idx = (sub if not sub.empty else df)["return"].idxmax()
    else:
        idx = df["sharpe"].idxmax()

    best = df.loc[idx]
    weights = {c.code: float(best[c.code]) for c in classes}
    ret, vol = portfolio_stats(np.array(list(weights.values())), mu, cov)
    return {
        "weights": weights,
        "expected_return": ret,
        "volatility": vol,
        "sharpe": safe_div(ret - RISK_FREE_RATE, vol),
        "objective": objective,
        "frontier": df,
    }


def efficient_frontier(df_portfolios: pd.DataFrame, n_points: int = 40) -> pd.DataFrame:
    """Enveloppe supérieure de l'univers échantillonné (frontière efficiente)."""
    if df_portfolios is None or df_portfolios.empty:
        return pd.DataFrame(columns=["vol", "return"])
    bins = np.linspace(df_portfolios["vol"].min(), df_portfolios["vol"].max(), n_points)
    labels = np.digitize(df_portfolios["vol"], bins)
    rows = []
    for b in np.unique(labels):
        sub = df_portfolios[labels == b]
        if sub.empty:
            continue
        best = sub.loc[sub["return"].idxmax()]
        rows.append({"vol": float(best["vol"]), "return": float(best["return"])})
    return pd.DataFrame(rows).sort_values("vol").reset_index(drop=True)


# ═══════════════════════════ Allocation personnalisée ═══════════════════════════

def target_allocation(profile: Any, classes: Optional[Sequence[AssetClass]] = None) -> Dict[str, float]:
    """Allocation cible personnalisée selon le profil de risque et l'horizon."""
    classes = list(classes or asset_classes())
    codes = {c.code for c in classes}
    risk = float(profile.overall_risk_score())
    horizon = max(1, int(profile.horizon_years))

    equity = float(np.clip(0.15 + 0.70 * risk, 0.05, 0.90))
    if horizon <= 3:
        equity = min(equity, 0.35)
    elif horizon <= 5:
        equity = min(equity, 0.60)
    non_equity = max(0.0, 1.0 - equity)

    gold = min(0.08, 0.25 * non_equity)
    rest = max(0.0, non_equity - gold)
    bonds = rest * 0.6 if horizon >= 3 else 0.0
    cash = max(0.0, rest - bonds)

    # Répartition interne de la poche actions
    bvc_share = 0.65 if risk >= 0.4 else 0.55
    bvc_equity = equity * bvc_share
    raw = {
        "BVC_BLUECHIP": bvc_equity * 0.50,
        "BVC_MASI": bvc_equity * 0.35,
        "BVC_SELECT": bvc_equity * 0.15,
        "GLOBAL_EQ": equity * (1 - bvc_share),
        "GOLD": gold,
        "BONDS": bonds,
        "CASH": cash,
        "REAL_ESTATE": 0.0,
        "DEPOSIT": 0.0,
    }
    total = sum(v for k, v in raw.items() if k in codes)
    if total <= 0:
        return {c.code: 1.0 / len(classes) for c in classes}
    return {k: (v / total if k in codes else 0.0) for k, v in raw.items() if k in codes}


def portfolio_risk(
    weights: Dict[str, float],
    classes: Sequence[AssetClass],
) -> Tuple[float, float, Optional[float]]:
    """(rendement attendu, volatilité, Sharpe) d'une allocation, via la matrice de covariance."""
    codes = [c.code for c in classes]
    mu = np.array([c.expected_return for c in classes], dtype=float)
    sigma = np.array([c.volatility for c in classes], dtype=float)
    corr = _correlation(classes)
    cov = np.outer(sigma, sigma) * corr
    w = np.array([float(weights.get(c, 0.0)) for c in codes], dtype=float)
    if w.sum() > 0:
        w = w / w.sum()
    ret, vol = portfolio_stats(w, mu, cov)
    return ret, vol, (safe_div(ret - RISK_FREE_RATE, vol) if vol else None)


def allocation_table(weights: Dict[str, float], classes: Optional[Sequence[AssetClass]] = None) -> pd.DataFrame:
    classes = list(classes or asset_classes())
    by_code = {c.code: c for c in classes}
    invested = sum(v for k, v in weights.items() if k != "CASH")
    rows = []
    for code, weight in sorted(weights.items(), key=lambda x: -x[1]):
        if weight <= 0:
            continue
        c = by_code.get(code)
        if c is None:
            continue
        rows.append(
            {
                "code": code,
                "Classe d'actifs": c.label,
                "Poids": weight,
                "Poids (hors cash)": (weight / invested if invested and code != "CASH" else 0.0),
                "Rendement attendu": c.expected_return,
                "Contribution rendement": weight * c.expected_return,
                "Volatilité": c.volatility,
                "Risque": c.volatility,
                "Liquidité": c.liquidity,
                "Source": c.source,
            }
        )
    return pd.DataFrame(rows)


def compare_allocations(
    current: Dict[str, float],
    recommended: Dict[str, float],
    classes: Optional[Sequence[AssetClass]] = None,
) -> pd.DataFrame:
    """Compare l'allocation actuelle à l'allocation recommandée, par classe d'actifs."""
    classes = list(classes or asset_classes())
    by_code = {c.code: c for c in classes}
    codes = sorted(set(current) | set(recommended))
    rows = []
    for code in codes:
        c = by_code.get(code)
        if c is None:
            continue
        cur, rec = float(current.get(code, 0.0)), float(recommended.get(code, 0.0))
        rows.append(
            {
                "code": code,
                "Classe d'actifs": c.label,
                "Actuel": cur,
                "Recommandé": rec,
                "Écart": rec - cur,
                "Action": "Renforcer" if rec - cur > 0.02 else "Alléger" if cur - rec > 0.02 else "Statu quo",
            }
        )
    return pd.DataFrame(rows).sort_values("Écart", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def rebalancing_plan(
    current_value: float,
    current: Dict[str, float],
    recommended: Dict[str, float],
    classes: Optional[Sequence[AssetClass]] = None,
) -> pd.DataFrame:
    """Montants à arbitrer pour rejoindre l'allocation cible."""
    df = compare_allocations(current, recommended, classes)
    if df.empty:
        return df
    for col in ("Actuel", "Recommandé", "Écart"):
        df[col + " (MAD)"] = df[col] * float(current_value) if col != "Écart" else df[col] * float(current_value)
    df = df.rename(columns={"Écart (MAD)": "À arbitrer (MAD)"})
    df["Frais estimés (MAD)"] = df["À arbitrer (MAD)"].abs() * BROKERAGE_FEE
    col_order = ["Classe d'actifs", "Actuel", "Recommandé", "Écart", "À arbitrer (MAD)", "Frais estimés (MAD)", "Action"]
    return df[[c for c in col_order if c in df.columns]]


def allocation_from_holdings(enriched: pd.DataFrame) -> Dict[str, float]:
    """Convertit un portefeuille détenu en allocation par classe d'actifs."""
    if enriched is None or enriched.empty:
        return {}
    total = float(enriched["value"].sum())
    if total <= 0:
        return {}
    out: Dict[str, float] = {}
    for _, row in enriched.iterrows():
        sector = str(row.get("sector") or "")
        if "Banque" in sector or "Assurance" in sector or "Financement" in sector:
            key = "BVC_BLUECHIP"
        elif "Télécom" in sector:
            key = "BVC_BLUECHIP"
        else:
            key = "BVC_SELECT"
        out[key] = out.get(key, 0.0) + float(row["value"]) / total
    return out
