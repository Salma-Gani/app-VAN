"""Indicateurs techniques : tendance, momentum, volatilité, signaux.

Implémentation autonome (pandas/numpy) pour éviter toute dépendance externe.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ═══════════════════════════ Moyennes & enveloppes ═══════════════════════════


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.astype(float).rolling(window, min_periods=max(2, window // 2)).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False, min_periods=max(2, span // 2)).mean()


def bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, window)
    std = series.astype(float).rolling(window, min_periods=max(2, window // 2)).std()
    return pd.DataFrame(
        {"middle": mid, "upper": mid + num_std * std, "lower": mid - num_std * std}
    )


def donchian(high: pd.Series, low: pd.Series, window: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "upper": high.astype(float).rolling(window, min_periods=2).max(),
            "lower": low.astype(float).rolling(window, min_periods=2).min(),
        }
    )


# ═══════════════════════════ Oscillateurs ═══════════════════════════


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(100.0).where(avg_loss.notna(), np.nan)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(series, fast) - ema(series, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14, smooth: int = 3) -> pd.DataFrame:
    lowest = low.astype(float).rolling(window, min_periods=2).min()
    highest = high.astype(float).rolling(window, min_periods=2).max()
    k = 100 * (close.astype(float) - lowest) / (highest - lowest).replace(0, np.nan)
    d = k.rolling(smooth, min_periods=1).mean()
    return pd.DataFrame({"k": k, "d": d})


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev_close = close.astype(float).shift(1)
    tr = pd.concat(
        [(high.astype(float) - low.astype(float)).abs(),
         (high.astype(float) - prev_close).abs(),
         (low.astype(float) - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.astype(float).diff().fillna(0.0))
    return (direction * volume.astype(float).fillna(0.0)).cumsum()


# ═══════════════════════════ Agrégation ═══════════════════════════


def add_indicators(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
    """Ajoute l'ensemble des indicateurs à un historique OHLCV."""
    if df is None or df.empty or price_col not in df.columns:
        return df
    out = df.copy()
    close = out[price_col].astype(float)
    high = out["high"].astype(float) if "high" in out.columns else close
    low = out["low"].astype(float) if "low" in out.columns else close
    volume = out["volume"].astype(float) if "volume" in out.columns else pd.Series(0.0, index=out.index)

    for w in (20, 50, 100, 200):
        out[f"sma{w}"] = sma(close, w)
    out["ema12"] = ema(close, 12)
    out["ema26"] = ema(close, 26)
    out["rsi14"] = rsi(close, 14)
    out["rsi7"] = rsi(close, 7)
    m = macd(close)
    out["macd"] = m["macd"]
    out["macd_signal"] = m["signal"]
    out["macd_hist"] = m["hist"]
    bb = bollinger(close, 20, 2.0)
    out["bb_upper"], out["bb_middle"], out["bb_lower"] = bb["upper"], bb["middle"], bb["lower"]
    out["bb_width"] = (bb["upper"] - bb["lower"]) / bb["middle"].replace(0, np.nan)
    st = stochastic(high, low, close)
    out["stoch_k"], out["stoch_d"] = st["k"], st["d"]
    out["atr14"] = atr(high, low, close, 14)
    out["obv"] = obv(close, volume)
    out["vol_sma20"] = volume.rolling(20, min_periods=5).mean()
    out["volume_ratio"] = volume / out["vol_sma20"].replace(0, np.nan)
    out["returns"] = close.pct_change()
    out["volatility_20"] = out["returns"].rolling(20, min_periods=10).std() * np.sqrt(252)
    out["drawdown"] = close / close.cummax() - 1.0
    return out


# ═══════════════════════════ Lecture de tendance ═══════════════════════════


def trend_state(df: pd.DataFrame) -> Dict[str, Any]:
    """Qualifie la tendance à partir des moyennes mobiles et du prix."""
    if df is None or df.empty or "close" not in df.columns:
        return {"state": "Indéterminé", "score": 0.0, "notes": []}

    last = df.iloc[-1]
    close = float(last["close"])
    sma20, sma50, sma200 = last.get("sma20"), last.get("sma50"), last.get("sma200")
    notes: List[str] = []
    score = 0.0

    if pd.notna(sma20):
        if close > sma20:
            score += 0.25
            notes.append("Cours au-dessus de la moyenne 20 jours (court terme haussier)")
        else:
            score -= 0.25
            notes.append("Cours sous la moyenne 20 jours (court terme baissier)")
    if pd.notna(sma50):
        if close > sma50:
            score += 0.25
            notes.append("Cours au-dessus de la moyenne 50 jours (moyen terme haussier)")
        else:
            score -= 0.25
            notes.append("Cours sous la moyenne 50 jours (moyen terme baissier)")
    if pd.notna(sma200):
        if close > sma200:
            score += 0.3
            notes.append("Cours au-dessus de la moyenne 200 jours (tendance de fond haussière)")
        else:
            score -= 0.3
            notes.append("Cours sous la moyenne 200 jours (tendance de fond baissière)")
    if pd.notna(sma20) and pd.notna(sma50):
        if sma20 > sma50:
            score += 0.2
            notes.append("Moyenne 20 j > moyenne 50 j : configuration haussière alignée")
        else:
            score -= 0.2
            notes.append("Moyenne 20 j < moyenne 50 j : configuration baissière alignée")

    score = float(max(-1.0, min(1.0, score)))
    if score >= 0.6:
        state = "Haussière forte"
    elif score >= 0.25:
        state = "Haussière"
    elif score <= -0.6:
        state = "Baissière forte"
    elif score <= -0.25:
        state = "Baissière"
    else:
        state = "Neutre / indécise"
    return {"state": state, "score": score, "notes": notes}


def momentum_state(df: pd.DataFrame) -> Dict[str, Any]:
    """Qualifie le momentum à partir du RSI, du MACD et de la performance relative."""
    if df is None or df.empty:
        return {"state": "Indéterminé", "score": 0.0, "notes": [], "rsi": None}
    last = df.iloc[-1]
    notes: List[str] = []
    score = 0.0
    rsi_v = last.get("rsi14")
    if pd.notna(rsi_v):
        rsi_v = float(rsi_v)
        if rsi_v >= 70:
            score -= 0.25
            notes.append(f"RSI à {rsi_v:.0f} : zone de surachat, risque de consolidation")
        elif rsi_v >= 55:
            score += 0.4
            notes.append(f"RSI à {rsi_v:.0f} : momentum haussier sain")
        elif rsi_v >= 45:
            score += 0.05
            notes.append(f"RSI à {rsi_v:.0f} : momentum neutre")
        elif rsi_v >= 30:
            score -= 0.15
            notes.append(f"RSI à {rsi_v:.0f} : momentum affaibli")
        else:
            score += 0.15
            notes.append(f"RSI à {rsi_v:.0f} : zone de survente, potentiel de rebond technique")
    if pd.notna(last.get("macd")) and pd.notna(last.get("macd_signal")):
        if last["macd"] > last["macd_signal"]:
            score += 0.3
            notes.append("MACD au-dessus de sa ligne de signal (impulsion positive)")
        else:
            score -= 0.3
            notes.append("MACD sous sa ligne de signal (impulsion négative)")
    if pd.notna(last.get("macd_hist")) and len(df) > 2:
        prev_hist = df["macd_hist"].iloc[-2]
        if pd.notna(prev_hist):
            if last["macd_hist"] > prev_hist:
                score += 0.15
                notes.append("Histogramme MACD en amélioration (accélération)")
            else:
                score -= 0.15
                notes.append("Histogramme MACD en dégradation (ralentissement)")
    if pd.notna(last.get("stoch_k")):
        k = float(last["stoch_k"])
        if k > 80:
            score -= 0.1
            notes.append(f"Stochastique à {k:.0f} : excès acheteur")
        elif k < 20:
            score += 0.1
            notes.append(f"Stochastique à {k:.0f} : excès vendeur")

    score = float(max(-1.0, min(1.0, score)))
    if score >= 0.5:
        state = "Momentum fort"
    elif score >= 0.15:
        state = "Momentum positif"
    elif score <= -0.5:
        state = "Momentum négatif marqué"
    elif score <= -0.15:
        state = "Momentum faible"
    else:
        state = "Momentum neutre"
    return {"state": state, "score": score, "notes": notes, "rsi": rsi_v}


def volume_state(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty or "volume_ratio" not in df.columns:
        return {"state": "—", "score": 0.0, "note": "Volumes indisponibles"}
    ratio = df["volume_ratio"].iloc[-1]
    if pd.isna(ratio):
        return {"state": "—", "score": 0.0, "note": "Volumes indisponibles"}
    ratio = float(ratio)
    if ratio >= 2.0:
        return {"state": "Exceptionnel", "score": 0.3, "note": f"Volume {ratio:.1f}× la moyenne 20 j — intérêt marqué du marché"}
    if ratio >= 1.3:
        return {"state": "Au-dessus de la moyenne", "score": 0.15, "note": f"Volume {ratio:.1f}× la moyenne 20 jours"}
    if ratio <= 0.6:
        return {"state": "Faible", "score": -0.1, "note": f"Volume {ratio:.1f}× la moyenne — signal peu fiable"}
    return {"state": "Normal", "score": 0.0, "note": f"Volume {ratio:.1f}× la moyenne 20 jours"}


def support_resistance(df: pd.DataFrame, lookback: int = 120) -> Dict[str, Optional[float]]:
    """Détecte des niveaux de support/résistance par pivots locaux et extrêmes."""
    if df is None or df.empty:
        return {"support": None, "resistance": None, "pivot": None}
    sub = df.tail(lookback)
    close = float(sub["close"].iloc[-1])
    highs = sub["high"] if "high" in sub.columns else sub["close"]
    lows = sub["low"] if "low" in sub.columns else sub["close"]
    resistance = float(highs.max())
    support = float(lows.min())

    # Pivots classiques (Fibonacci) sur la dernière séance
    h, l, c = float(highs.iloc[-1]), float(lows.iloc[-1]), close
    pivot = (h + l + c) / 3
    return {
        "support": support,
        "resistance": resistance,
        "pivot": pivot,
        "r1": 2 * pivot - l,
        "s1": 2 * pivot - h,
        "r2": pivot + (h - l),
        "s2": pivot - (h - l),
        "distance_resistance": (resistance / close - 1) if close else None,
        "distance_support": (support / close - 1) if close else None,
    }


def generate_signals(df: pd.DataFrame) -> List[Dict[str, str]]:
    """Liste lisible des signaux techniques actifs."""
    if df is None or df.empty:
        return []
    out: List[Dict[str, str]] = []
    last = df.iloc[-1]

    if pd.notna(last.get("sma50")) and len(df) > 2:
        prev = df.iloc[-2]
        if pd.notna(prev.get("sma50")):
            if prev["close"] <= prev["sma50"] and last["close"] > last["sma50"]:
                out.append({"signal": "Croisement haussier de la MM50", "type": "achat",
                            "detail": "Le cours repasse au-dessus de sa moyenne 50 jours."})
            elif prev["close"] >= prev["sma50"] and last["close"] < last["sma50"]:
                out.append({"signal": "Croisement baissier de la MM50", "type": "vente",
                            "detail": "Le cours casse à la baisse sa moyenne 50 jours."})
    if pd.notna(last.get("macd")) and pd.notna(last.get("macd_signal")) and len(df) > 2:
        prev = df.iloc[-2]
        if pd.notna(prev.get("macd")) and pd.notna(prev.get("macd_signal")):
            if prev["macd"] <= prev["macd_signal"] and last["macd"] > last["macd_signal"]:
                out.append({"signal": "Croisement MACD haussier", "type": "achat",
                            "detail": "Passage au-dessus de la ligne de signal : accélération probable."})
            elif prev["macd"] >= prev["macd_signal"] and last["macd"] < last["macd_signal"]:
                out.append({"signal": "Croisement MACD baissier", "type": "vente",
                            "detail": "Passage sous la ligne de signal : perte de momentum."})
    rsi_v = last.get("rsi14")
    if pd.notna(rsi_v):
        if rsi_v < 30:
            out.append({"signal": "RSI en survente", "type": "achat",
                        "detail": f"RSI à {rsi_v:.0f} : rebond technique statistiquement fréquent."})
        elif rsi_v > 70:
            out.append({"signal": "RSI en surachat", "type": "vente",
                        "detail": f"RSI à {rsi_v:.0f} : prise de bénéfices envisageable."})
    if pd.notna(last.get("bb_lower")) and last["close"] < last["bb_lower"]:
        out.append({"signal": "Sortie basse des bandes de Bollinger", "type": "achat",
                    "detail": "Volatilité en expansion à la baisse : surveiller un retour vers la moyenne."})
    if pd.notna(last.get("bb_upper")) and last["close"] > last["bb_upper"]:
        out.append({"signal": "Sortie haute des bandes de Bollinger", "type": "vente",
                    "detail": "Extension haussière forte : risque de retour à la moyenne."})
    if pd.notna(last.get("volume_ratio")) and float(last["volume_ratio"]) > 2.0:
        direction = "achat" if last.get("returns", 0) and last["returns"] > 0 else "vente"
        out.append({"signal": "Volume anormal", "type": direction,
                    "detail": f"Volume {float(last['volume_ratio']):.1f}× la moyenne : mouvement soutenu par le marché."})
    return out


def technical_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """Synthèse complète : tendance, momentum, volumes, niveaux, signaux."""
    if df is None or df.empty:
        return {
            "trend": {"state": "Indéterminé", "score": 0.0, "notes": []},
            "momentum": {"state": "Indéterminé", "score": 0.0, "notes": [], "rsi": None},
            "volume": {"state": "—", "score": 0.0, "note": "—"},
            "levels": {"support": None, "resistance": None, "pivot": None},
            "signals": [],
            "score": 0.0,
        }
    enriched = add_indicators(df) if "rsi14" not in df.columns else df
    trend = trend_state(enriched)
    momentum = momentum_state(enriched)
    volume = volume_state(enriched)
    levels = support_resistance(enriched)
    signals = generate_signals(enriched)
    score = 0.5 * trend["score"] + 0.4 * momentum["score"] + 0.1 * volume["score"]
    return {
        "trend": trend,
        "momentum": momentum,
        "volume": volume,
        "levels": levels,
        "signals": signals,
        "score": float(max(-1.0, min(1.0, score))),
        "enriched": enriched,
    }
