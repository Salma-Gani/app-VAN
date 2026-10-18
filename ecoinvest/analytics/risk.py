"""Mesures de risque : volatilité, bêta, ratio de Sharpe, drawdown, VaR, corrélations."""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd

from ..config import RISK_FREE_RATE


_MAX_DAILY_MOVE = 0.45


def clean_returns(series: pd.Series, clip: float = _MAX_DAILY_MOVE) -> pd.Series:
    """Rendements journaliers écrêtés.

    Les variations journalières au-delà de ±45 % sur la Bourse de Casablanca
    correspondent presque toujours à une opération sur titre (fractionnement,
    attribution) mal ajustée ou à une erreur de cotation. Les écrêter évite de
    biaiser fortement la volatilité et le bêta.
    """
    r = series.astype(float).pct_change().dropna()
    return r.clip(lower=-clip, upper=clip)


def daily_returns(prices: pd.Series) -> pd.Series:
    return prices.astype(float).pct_change().dropna()


def annualized_return(prices: pd.Series, periods: int = 252) -> Optional[float]:
    p = prices.astype(float).dropna()
    if len(p) < 2 or p.iloc[0] <= 0:
        return None
    years = len(p) / periods
    if years <= 0:
        return None
    total = p.iloc[-1] / p.iloc[0]
    if total <= 0:
        return None
    return float(total ** (1.0 / years) - 1.0)


def annualized_volatility(prices: pd.Series, periods: int = 252) -> Optional[float]:
    r = clean_returns(prices)
    if len(r) < 10:
        return None
    return float(r.std() * np.sqrt(periods))


def downside_deviation(prices: pd.Series, mar: float = 0.0, periods: int = 252) -> Optional[float]:
    r = clean_returns(prices)
    if len(r) < 10:
        return None
    downside = r[r < mar]
    if downside.empty:
        return None
    return float(np.sqrt((downside ** 2).mean()) * np.sqrt(periods))


def sharpe_ratio(prices: pd.Series, risk_free: float = RISK_FREE_RATE, periods: int = 252) -> Optional[float]:
    ret = annualized_return(prices, periods)
    vol = annualized_volatility(prices, periods)
    if ret is None or not vol:
        return None
    return float((ret - risk_free) / vol)


def sortino_ratio(prices: pd.Series, risk_free: float = RISK_FREE_RATE, periods: int = 252) -> Optional[float]:
    ret = annualized_return(prices, periods)
    dd = downside_deviation(prices, periods=periods)
    if ret is None or not dd:
        return None
    return float((ret - risk_free) / dd)


def calmar_ratio(prices: pd.Series, periods: int = 252) -> Optional[float]:
    ret = annualized_return(prices, periods)
    mdd = max_drawdown(prices)
    if ret is None or not mdd:
        return None
    return float(ret / abs(mdd))


def max_drawdown(prices: pd.Series) -> Optional[float]:
    p = prices.astype(float).dropna()
    if len(p) < 2:
        return None
    dd = p / p.cummax() - 1.0
    return float(dd.min())


def drawdown_series(prices: pd.Series) -> pd.Series:
    p = prices.astype(float).dropna()
    return p / p.cummax() - 1.0


def value_at_risk(prices: pd.Series, level: float = 0.95, horizon: int = 1) -> Dict[str, Optional[float]]:
    """VaR et CVaR historiques (en fraction du capital)."""
    r = clean_returns(prices)
    if len(r) < 30:
        return {"var": None, "cvar": None, "level": level, "horizon": horizon}
    scaled = r * np.sqrt(horizon)
    var = float(np.percentile(scaled, (1 - level) * 100))
    tail = scaled[scaled <= var]
    cvar = float(tail.mean()) if len(tail) else var
    return {"var": var, "cvar": cvar, "level": level, "horizon": horizon}


def beta_alpha(asset_prices: pd.Series, benchmark_prices: pd.Series, periods: int = 252) -> Dict[str, Optional[float]]:
    """Bêta, alpha de Jensen et R² face à un indice de référence."""
    try:
        a = clean_returns(asset_prices)
        b = clean_returns(benchmark_prices)
        df = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
        if len(df) < 30:
            return {"beta": None, "alpha": None, "r2": None, "correlation": None, "n": len(df)}
        cov = float(np.cov(df["a"], df["b"])[0, 1])
        var_b = float(np.var(df["b"]))
        if var_b == 0:
            return {"beta": None, "alpha": None, "r2": None, "correlation": None, "n": len(df)}
        beta = cov / var_b
        ra = float((1 + df["a"].mean()) ** periods - 1)
        rb = float((1 + df["b"].mean()) ** periods - 1)
        alpha = ra - (RISK_FREE_RATE + beta * (rb - RISK_FREE_RATE))
        corr = float(df["a"].corr(df["b"]))
        return {"beta": float(beta), "alpha": float(alpha), "r2": float(corr ** 2), "correlation": corr, "n": int(len(df))}
    except (ValueError, TypeError):
        return {"beta": None, "alpha": None, "r2": None, "correlation": None, "n": 0}


def risk_profile(prices: pd.Series, benchmark: Optional[pd.Series] = None) -> Dict[str, Any]:
    """Profil de risque complet d'une série de prix."""
    out: Dict[str, Any] = {
        "return_annualized": annualized_return(prices),
        "volatility": annualized_volatility(prices),
        "sharpe": sharpe_ratio(prices),
        "sortino": sortino_ratio(prices),
        "calmar": calmar_ratio(prices),
        "max_drawdown": max_drawdown(prices),
        "downside_deviation": downside_deviation(prices),
    }
    out.update(value_at_risk(prices))
    if benchmark is not None and len(benchmark) > 30:
        out.update(beta_alpha(prices, benchmark))
    else:
        out.update({"beta": None, "alpha": None, "r2": None, "correlation": None, "n": 0})
    out["risk_score"] = risk_score(out)
    return out


def risk_score(profile: Dict[str, Any]) -> Optional[float]:
    """Score de risque composite dans [0, 1] (0 = très faible, 1 = très élevé)."""
    vol = profile.get("volatility")
    mdd = profile.get("max_drawdown")
    beta = profile.get("beta")
    parts, weights = [], []
    if vol is not None:
        parts.append(min(float(vol) / 0.60, 1.0))
        weights.append(0.5)
    if mdd is not None:
        parts.append(min(abs(float(mdd)) / 0.70, 1.0))
        weights.append(0.35)
    if beta is not None:
        parts.append(min(max(float(beta), 0.0) / 2.0, 1.0))
        weights.append(0.15)
    if not parts:
        return None
    return float(sum(p * w for p, w in zip(parts, weights)) / sum(weights))


def correlation_matrix(price_frame: pd.DataFrame) -> pd.DataFrame:
    """Matrice de corrélation des rendements."""
    if price_frame is None or price_frame.empty:
        return pd.DataFrame()
    rets = price_frame.astype(float).pct_change().dropna(how="all")
    return rets.corr()


def portfolio_metrics(weights: Dict[str, float], price_frame: pd.DataFrame) -> Dict[str, Any]:
    """Rendement/volatilité/Sharpe d'un portefeuille pondéré."""
    if price_frame is None or price_frame.empty or not weights:
        return {}
    cols = [c for c in weights if c in price_frame.columns]
    if not cols:
        return {}
    rets = price_frame[cols].astype(float).pct_change().dropna()
    if rets.empty:
        return {}
    w = np.array([weights[c] for c in cols], dtype=float)
    total = w.sum()
    if total == 0:
        return {}
    w = w / total
    port_ret = rets.mul(w, axis=1).sum(axis=1)
    ann_ret = float((1 + port_ret.mean()) ** 252 - 1)
    ann_vol = float(port_ret.std() * np.sqrt(252))
    dd = float((port_ret.cumsum().apply(np.exp) / port_ret.cumsum().apply(np.exp).cummax() - 1).min())
    return {
        "expected_return": ann_ret,
        "volatility": ann_vol,
        "sharpe": (ann_ret - RISK_FREE_RATE) / ann_vol if ann_vol else None,
        "max_drawdown": dd,
        "weights": dict(zip(cols, w.tolist())),
    }


def stress_test(prices: pd.Series, shocks: Sequence[float] = (-0.10, -0.20, -0.30)) -> pd.DataFrame:
    """Impact d'un choc de marché instantané sur une position."""
    if prices is None or len(prices) == 0:
        return pd.DataFrame()
    last = float(prices.iloc[-1])
    rows = []
    for shock in shocks:
        rows.append(
            {
                "Choc": shock,
                "Nouveau cours": last * (1 + shock),
                "Impact": shock,
            }
        )
    return pd.DataFrame(rows)


def liquidity_score(avg_volume_value: Optional[float], cap: Optional[float]) -> Dict[str, Any]:
    """Facilité à entrer/sortir d'une position sur le marché marocain."""
    if not avg_volume_value or avg_volume_value <= 0:
        return {"score": None, "label": "Indisponible", "detail": "Volumes non renseignés."}
    if avg_volume_value >= 20e6:
        return {"score": 1.0, "label": "Très liquide", "detail": "Volume quotidien > 20 M MAD : exécution quasi immédiate."}
    if avg_volume_value >= 5e6:
        return {"score": 0.75, "label": "Liquide", "detail": "Volume quotidien 5–20 M MAD : ordres absorbés sans impact notable."}
    if avg_volume_value >= 1e6:
        return {"score": 0.5, "label": "Moyennement liquide", "detail": "Volume quotidien 1–5 M MAD : fractionnez les ordres importants."}
    if avg_volume_value >= 200_000:
        return {"score": 0.25, "label": "Peu liquide", "detail": "Volume quotidien < 1 M MAD : prévoyez plusieurs séances."}
    return {"score": 0.1, "label": "Très peu liquide", "detail": "Marché très étroit : risque d'exécution et de spread élevé."}
