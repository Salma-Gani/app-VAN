"""Données de marché internationales (Yahoo Finance) : indices, VIX, devises, matières premières.

Sert de complément au connecteur BVC : contexte macro, sentiment de volatilité et
comparaison de performance avec les marchés mondiaux.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from ..config import FX_TICKERS, GLOBAL_INDICES, TTL
from ..utils import cache
from .http import record_exception

NS = "market_global"

try:  # pragma: no cover - dépend de l'environnement
    import yfinance as yf

    _HAS_YF = True
except Exception:  # pragma: no cover
    yf = None  # type: ignore
    _HAS_YF = False


def _yahoo_available() -> bool:
    return _HAS_YF


# ═══════════════════════════ Cours globaux ═══════════════════════════

def _download(tickers: Sequence[str], period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Téléchargement groupé Yahoo Finance avec gestion d'erreur tolérante."""
    if not _HAS_YF:
        return pd.DataFrame()
    try:
        df = yf.download(
            list(tickers),
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=True,
            group_by="column",
        )
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception as exc:
        record_exception("Yahoo Finance", exc)
        return pd.DataFrame()


def _extract_close(df: pd.DataFrame, tickers: Sequence[str]) -> pd.DataFrame:
    """Normalise la sortie de yfinance en un DataFrame de clôtures (colonnes = tickers)."""
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        level0 = set(df.columns.get_level_values(0))
        level1 = set(df.columns.get_level_values(1))
        if "Close" in level0:
            out = df["Close"]
        elif "Close" in level1:
            out = df.xs("Close", axis=1, level=1)
        else:
            out = pd.DataFrame()
    else:
        if "Close" in df.columns:
            out = df[["Close"]]
            out.columns = [tickers[0]] if len(tickers) == 1 else out.columns
        else:
            out = df
    if out.empty:
        return out
    out = out.reindex(columns=[t for t in tickers if t in out.columns])
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def global_history(ticker: str, period: str = "1y", force: bool = False) -> pd.DataFrame:
    """Historique de clôture d'un instrument mondial."""
    key = cache.make_key("ghist", ticker, period)
    if not force:
        hit = cache.get(NS, key, TTL["global"])
        if hit is not None:
            return hit
    raw = _download([ticker], period=period)
    out = _extract_close(raw, [ticker])
    if not out.empty:
        out = out.dropna(how="all").reset_index().rename(columns={"Date": "date", "index": "date"})
        out.columns = ["date", "close"][: len(out.columns)]
        cache.set(NS, key, out)
    return out


def global_quotes(tickers: Optional[Sequence[str]] = None, force: bool = False) -> pd.DataFrame:
    """Cours, variation journalière et variation sur 1 an d'un panier d'instruments."""
    tickers = list(tickers or GLOBAL_INDICES.keys())
    key = cache.make_key("gquotes", tickers)
    if not force:
        hit = cache.get(NS, key, TTL["global"])
        if hit is not None and not hit.empty:
            return hit

    closes = _extract_close(_download(tickers, period="1y"), tickers)
    rows: List[Dict[str, Any]] = []
    for ticker in tickers:
        name = GLOBAL_INDICES.get(ticker, ticker)
        if closes.empty or ticker not in closes.columns:
            rows.append({"ticker": ticker, "name": name, "price": None,
                         "change_pct": None, "return_1y": None, "series": None})
            continue
        s = closes[ticker].dropna()
        if s.empty:
            rows.append({"ticker": ticker, "name": name, "price": None,
                         "change_pct": None, "return_1y": None, "series": None})
            continue
        price = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) > 1 else price
        first = float(s.iloc[0])
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "price": price,
                "change_pct": (price / prev - 1.0) if prev else None,
                "return_1y": (price / first - 1.0) if first else None,
                "series": s.tail(260).reset_index(drop=True),
            }
        )
    df = pd.DataFrame(rows)
    cache.set(NS, key, df)
    return df


def global_matrix(period: str = "1y", tickers: Optional[Sequence[str]] = None, force: bool = False) -> pd.DataFrame:
    """Matrice de clôtures (dates × instruments) pour les corrélations et graphiques."""
    tickers = list(tickers or GLOBAL_INDICES.keys())
    key = cache.make_key("gmatrix", tickers, period)
    if not force:
        hit = cache.get(NS, key, TTL["global"])
        if hit is not None and not hit.empty:
            return hit
    out = _extract_close(_download(tickers, period=period), tickers).dropna(how="all")
    if not out.empty:
        cache.set(NS, key, out)
    return out


# ═══════════════════════════ VIX & sentiment ═══════════════════════════

def vix_series(period: str = "1y", force: bool = False) -> pd.DataFrame:
    """Série du VIX (indice de volatilité implicite du S&P 500)."""
    return global_history("^VIX", period=period, force=force)


def vix_level(force: bool = False) -> Optional[float]:
    """Dernier niveau du VIX."""
    s = vix_series(period="6mo", force=force)
    if s.empty:
        return None
    try:
        return float(s["close"].dropna().iloc[-1])
    except (KeyError, IndexError):
        return None


def vix_regime(force: bool = False) -> Dict[str, Any]:
    """Interprétation du VIX : régime de volatilité et implication sur le momentum."""
    level = vix_level(force=force)
    if level is None:
        return {"level": None, "label": "Indisponible", "score": None, "advice": "",
                "color": "#64748B", "percentile": None}

    s = vix_series(period="3y", force=force)
    pct: Optional[float] = None
    if not s.empty:
        vals = s["close"].dropna()
        if len(vals) > 30:
            pct = float((vals < level).mean())

    if level < 12:
        label, score, color = "Complaisance extrême", -0.35, "#B45309"
        advice = ("Volatilité très basse : le marché est serein mais vulnérable à un choc. "
                  "Évitez les achats en euphorie ; privilégiez les renforcements progressifs.")
    elif level < 16:
        label, score, color = "Calme / risk-on", 0.65, "#0F766E"
        advice = ("Régime favorable aux actifs risqués. Momentum haussier généralement "
                  "fiable : les entrées sur cassure de résistance sont statistiquement payantes.")
    elif level < 22:
        label, score, color = "Normalisation", 0.15, "#123B6D"
        advice = ("Volatilité normale : sélectivité accrue. Privilégiez les valeurs à "
                  "fondamentaux solides et évitez le levier.")
    elif level < 30:
        label, score, color = "Nervosité", -0.45, "#B45309"
        advice = ("Marché nerveux : réduisez la taille des positions, échelonnez les entrées "
                  "et surveillez les supports clés.")
    else:
        label, score, color = "Panique / risk-off", -0.85, "#B42318"
        advice = ("Volatilité de crise : les marchés soldent en désordre. Opportunités "
                  "potentielles pour un investisseur patient, mais entrée fractionnée obligatoire.")
    return {
        "level": level, "label": label, "score": score, "advice": advice,
        "color": color, "percentile": pct,
        "mean": float(s["close"].mean()) if not s.empty else None,
    }


def strip_series(df: pd.DataFrame, column: str = "close") -> pd.DataFrame:
    """Réduit un historique à deux colonnes lisibles (date, valeur)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "value"])
    out = df.copy()
    if "date" not in out.columns:
        out = out.reset_index().rename(columns={"index": "date", "Date": "date"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"])
    val = column if column in out.columns else out.columns[-1]
    return out[["date", val]].rename(columns={val: "value"}).reset_index(drop=True)


# ═══════════════════════════ Devises ═══════════════════════════

def fx_rates(force: bool = False) -> Dict[str, float]:
    """Taux de change exprimés en MAD pour 1 unité de devise étrangère."""
    rates: Dict[str, float] = {"MAD": 1.0}
    key = "fx_rates"
    if not force:
        hit = cache.get(NS, key, TTL["global"])
        if hit:
            return hit

    tickers = list(FX_TICKERS.values())
    closes = _extract_close(_download(tickers, period="5d"), tickers)
    for cur, ticker in FX_TICKERS.items():
        try:
            s = closes[ticker].dropna()
        except (KeyError, IndexError):
            continue
        if not s.empty:
            rates[cur] = float(s.iloc[-1])
    # MAD = 1.0 est la seule valeur certaine ; aucune devise n'est estimée à
    # défaut. Une devise absente restera introuvable côté affichage.
    cache.set(NS, key, rates)
    return rates


def fx_history(currency: str, period: str = "1y", force: bool = False) -> pd.DataFrame:
    """Historique du taux de change MAD par unité de devise."""
    if currency == "MAD":
        return pd.DataFrame(columns=["date", "close"])
    ticker = FX_TICKERS.get(currency)
    if not ticker:
        return pd.DataFrame(columns=["date", "close"])
    return global_history(ticker, period=period, force=force)


# ═══════════════════════════ Contexte macro ═══════════════════════════

def macro_context(force: bool = False) -> Dict[str, Any]:
    """Synthèse macro : inflation implicite, taux US, pétrole, or, dollar."""
    quotes = global_quotes(force=force)
    if quotes.empty:
        return {}
    by_ticker = {row["ticker"]: row for _, row in quotes.iterrows()}

    def _val(t: str) -> Optional[float]:
        row = by_ticker.get(t)
        return None if row is None else row.get("price")

    def _chg(t: str) -> Optional[float]:
        row = by_ticker.get(t)
        return None if row is None else row.get("change_pct")

    out = {
        "us10y": _val("^TNX"),
        "us10y_change": _chg("^TNX"),
        "oil": _val("CL=F"),
        "oil_change": _chg("CL=F"),
        "gold": _val("GC=F"),
        "gold_change": _chg("GC=F"),
        "eurusd": _val("EURUSD=X"),
        "eurmad": _val("EURMAD=X"),
        "usdmad": _val("MAD=X"),
        "btc": _val("BTC-USD"),
    }
    if out["us10y"] and out["us10y"] > 4.5:
        out["rates_regime"] = "Taux élevés — pression sur les valorisations"
    elif out["us10y"] and out["us10y"] < 3.5:
        out["rates_regime"] = "Taux bas — environnement porteur pour les actions"
    else:
        out["rates_regime"] = "Taux modérés — contexte neutre"
    return out


def global_performance_table(period: str = "1y", force: bool = False) -> pd.DataFrame:
    """Performance comparée des grands indices sur la période demandée."""
    quotes = global_quotes(force=force)
    if quotes.empty:
        return pd.DataFrame(columns=["Indice", "Niveau", "1 an"])
    rows = []
    for _, r in quotes.iterrows():
        if r["ticker"] in ("^VIX",):
            continue
        rows.append(
            {
                "Indice": r["name"],
                "Code": r["ticker"],
                "Niveau": r["price"],
                "Variation jour": r["change_pct"],
                "1 an": r["return_1y"],
            }
        )
    return pd.DataFrame(rows)


def data_health(force: bool = False) -> Dict[str, Any]:
    """État des sources de données, affiché dans la barre latérale."""
    health: Dict[str, Any] = {
        "yahoo": _HAS_YF,
        "yahoo_live": False,
        "bvc_live": False,
        "last_global": None,
        "last_bvc": None,
    }
    try:
        from . import bvc

        _, age_bvc = cache.last_updated("bvc_api", "universe")
        health["last_bvc"] = age_bvc
        health["bvc_live"] = bvc.snapshot() is not None
    except Exception:
        health["bvc_live"] = False
    try:
        df = global_quotes(force=force)
        health["yahoo_live"] = not df.empty and df["price"].notna().any()
        _, age = cache.last_updated(NS, cache.make_key("gquotes", list(GLOBAL_INDICES.keys())))
        health["last_global"] = age
    except Exception:
        health["yahoo_live"] = False
    return health
