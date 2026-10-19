"""Backtest honnête : coûts de transaction, absence de look-ahead, hors échantillon.

Trois principes non négociables :

1. **Aucun look-ahead.** Un signal calculé à la clôture du jour *t* ne s'applique
   qu'à la performance du jour *t+1* (décalage d'un rang).
2. **Coûts inclus.** Chaque changement de position paie des frais de courtage et,
   si on le souhaite, une slippage. Les frais sont facturés à l'aller et au retour.
3. **Hors échantillon.** Les paramètres sont choisis sur une première période
   (« apprentissage ») puis évalués une seule fois sur la période suivante, jamais
   vue. Un backtest n'est pas une preuve de performance future.

Aucune donnée n'est inventée : tout part de l'historique réel des cours fourni.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import technical

TRADING_DAYS = 252
MIN_OBSERVATIONS = 60
MIN_OBSERVATIONS_WF = 120

STRATEGIES: Dict[str, Dict[str, Any]] = {
    "ma_cross": {
        "label": "Croisement de moyennes mobiles",
        "note": "Position longue quand la moyenne rapide dépasse la moyenne lente.",
        "params": [("fast", "Moyenne rapide", 20), ("slow", "Moyenne lente", 50)],
        "grid": [(10, 30), (20, 50), (20, 100), (50, 150)],
    },
    "rsi_reversion": {
        "label": "Retour à la moyenne (RSI)",
        "note": "Achat sous le seuil bas, sortie au-dessus du seuil haut.",
        "params": [("low", "RSI bas (achat)", 30), ("high", "RSI haut (sortie)", 70)],
        "grid": [(25, 60), (30, 70), (35, 75)],
    },
}


def _clean_prices(prices: Any) -> pd.Series:
    series = pd.Series(prices).astype(float)
    series = series[~series.isna()]
    series = series[series > 0]
    return series


def ma_cross_signals(prices: pd.Series, fast: int = 20, slow: int = 50) -> pd.Series:
    """Position souhaitée (0/1) d'une règle de croisement de moyennes."""
    fast_ma = technical.sma(prices, int(fast))
    slow_ma = technical.sma(prices, int(slow))
    return (fast_ma > slow_ma).astype(float).fillna(0.0)


def rsi_reversion_signals(prices: pd.Series, low: float = 30.0, high: float = 70.0,
                          window: int = 14) -> pd.Series:
    """Position (0/1) d'une règle de retour à la moyenne fondée sur le RSI."""
    rsi = technical.rsi(prices, int(window))
    position = pd.Series(0.0, index=prices.index)
    state = 0.0
    for i in range(len(prices)):
        value = rsi.iloc[i]
        if state == 0.0 and pd.notna(value) and value < low:
            state = 1.0
        elif state == 1.0 and pd.notna(value) and value > high:
            state = 0.0
        position.iloc[i] = state
    return position


def _strategy_signals(strategy: str, prices: pd.Series, params: Dict[str, Any]) -> pd.Series:
    if strategy == "rsi_reversion":
        return rsi_reversion_signals(prices, params.get("low", 30.0), params.get("high", 70.0))
    return ma_cross_signals(prices, params.get("fast", 20), params.get("slow", 50))


def _metrics(net: pd.Series, position: pd.Series) -> Dict[str, Any]:
    """Indicateurs calculés sur une suite de rendements nets (base 1,0)."""
    net = net.fillna(0.0)
    if net.empty:
        return {"total_return": None, "cagr": None, "volatility": None, "sharpe": None,
                "max_drawdown": None, "exposure": None, "hit_rate": None, "entries": 0,
                "sessions": 0}
    equity = (1.0 + net).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    years = max(len(net) / TRADING_DAYS, 1e-9)
    growth = max(float(equity.iloc[-1]), 1e-9)
    cagr = growth ** (1.0 / years) - 1.0
    std = float(net.std(ddof=1)) if len(net) > 1 else 0.0
    volatility = std * math.sqrt(TRADING_DAYS)
    mean_annual = float(net.mean()) * TRADING_DAYS
    sharpe = (mean_annual / volatility) if volatility > 0 else None
    drawdown = equity / equity.cummax() - 1.0
    invested = position.reindex(net.index).fillna(0.0) > 0
    hit_rate = float((net[invested] > 0).mean()) if invested.any() else None
    changes = position.diff()
    entries = int((changes > 0).sum())
    return {
        "total_return": total_return,
        "cagr": cagr,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()) if not drawdown.empty else None,
        "exposure": float(invested.mean()),
        "hit_rate": hit_rate,
        "entries": entries,
        "sessions": int(len(net)),
    }


def run(prices: Any, signals: Any, cost_bps: float = 20.0, slippage_bps: float = 0.0,
        initial: float = 100_000.0) -> Dict[str, Any]:
    """Exécute une stratégie longue/cash sur un historique de cours.

    ``signals`` décrit la position souhaitée **connue en clôture** ; elle est
    décalée d'un rang pour éviter tout look-ahead. Les frais s'appliquent à
    chaque variation de position (entrée et sortie).
    """
    series = _clean_prices(prices)
    if len(series) < MIN_OBSERVATIONS:
        return {"available": False,
                "reason": f"Historique insuffisant ({len(series)} séances, minimum {MIN_OBSERVATIONS})."}

    desired = pd.Series(signals).reindex(series.index).fillna(0.0).clip(0.0, 1.0)
    position = desired.shift(1).fillna(0.0)
    returns = series.pct_change().fillna(0.0)
    gross = position * returns
    turnover = position.diff().abs()
    if not turnover.empty:
        turnover.iloc[0] = position.iloc[0]
    cost_rate = (max(cost_bps, 0.0) + max(slippage_bps, 0.0)) / 10_000.0
    net = gross - turnover * cost_rate

    equity = initial * (1.0 + net).cumprod()
    buy_hold = initial * (1.0 + returns).cumprod()
    return {
        "available": True,
        "initial": float(initial),
        "cost_bps": float(cost_bps),
        "slippage_bps": float(slippage_bps),
        "metrics": _metrics(net, position),
        "buy_hold": _metrics(returns, pd.Series(1.0, index=series.index)),
        "equity": equity,
        "buy_hold_equity": buy_hold,
        "returns": net,
        "position": position,
        "prices": series,
    }


def walk_forward(prices: Any, strategy: str = "ma_cross",
                 grid: Optional[Sequence[Tuple[float, float]]] = None,
                 train_frac: float = 0.6, cost_bps: float = 20.0,
                 slippage_bps: float = 0.0, initial: float = 100_000.0) -> Dict[str, Any]:
    """Choisit les paramètres sur l'apprentissage, puis évalue hors échantillon.

    Le choix se fait uniquement sur la première fraction de l'historique. La
    seconde fraction n'intervient jamais dans la sélection : c'est la seule
    mesure honnête d'un paramétrage.
    """
    series = _clean_prices(prices)
    if len(series) < MIN_OBSERVATIONS_WF:
        return {"available": False,
                "reason": f"Historique insuffisant pour une validation hors échantillon "
                          f"({len(series)} séances, minimum {MIN_OBSERVATIONS_WF})."}

    split = int(len(series) * min(max(train_frac, 0.3), 0.8))
    train_index = series.index[:split]
    test_index = series.index[split:]
    if len(test_index) < 20:
        return {"available": False, "reason": "Période de test trop courte."}

    meta = STRATEGIES.get(strategy, STRATEGIES["ma_cross"])
    combos = list(grid or meta.get("grid") or [])

    def params_for(combo: Tuple[float, float]) -> Dict[str, Any]:
        if strategy == "rsi_reversion":
            return {"low": float(combo[0]), "high": float(combo[1])}
        return {"fast": int(combo[0]), "slow": int(combo[1])}

    best: Optional[Tuple[float, Dict[str, Any], Dict[str, Any]]] = None
    for combo in combos:
        params = params_for(combo)
        if strategy == "ma_cross" and params["slow"] >= split:
            continue
        result = run(series, _strategy_signals(strategy, series, params),
                     cost_bps=cost_bps, slippage_bps=slippage_bps, initial=initial)
        if not result["available"]:
            continue
        segment = _metrics(result["returns"].reindex(train_index),
                           result["position"].reindex(train_index))
        score = segment.get("sharpe")
        score = float(score) if score is not None else -99.0
        if best is None or score > best[0]:
            best = (score, params, result)
    if best is None:
        return {"available": False, "reason": "Aucun paramètre exploitable sur la période d'apprentissage."}

    _, params, result = best
    in_sample = _metrics(result["returns"].reindex(train_index),
                         result["position"].reindex(train_index))
    out_sample = _metrics(result["returns"].reindex(test_index),
                          result["position"].reindex(test_index))
    return {
        "available": True,
        "strategy": strategy,
        "strategy_label": meta["label"],
        "best_params": params,
        "train_frac": float(train_frac),
        "in_sample": in_sample,
        "out_of_sample": out_sample,
        "equity": result["equity"],
        "buy_hold_equity": result["buy_hold_equity"],
        "train_index": train_index,
        "test_index": test_index,
        "cost_bps": float(cost_bps),
        "slippage_bps": float(slippage_bps),
    }
