"""Chargements de données partagés entre les pages (avec mise en cache Streamlit)."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd
import streamlit as st

from ...ai import agent as agent_mod
from ...analytics import scoring, technical
from ...data import bvc, fundamentals, market, news
from ...portfolio import optimize, profile as profile_mod, simulate

CACHE_KW = dict(show_spinner=False, max_entries=8)


@st.cache_data(ttl=900, **CACHE_KW)
def market_table(force: bool = False) -> pd.DataFrame:
    """Tableau de marché enrichi (scores, technique, risque, fondamentaux disponibles)."""
    return scoring.build_market_table(force=force)


@st.cache_data(ttl=900, **CACHE_KW)
def snapshot(force: bool = False) -> pd.DataFrame:
    """Photo de marché brute (cours, volumes, capitalisation, date de clôture)."""
    return bvc.snapshot(force=force)


@st.cache_data(ttl=900, **CACHE_KW)
def market_regime(force: bool = False) -> Dict[str, Any]:
    return scoring.market_regime(force=force)


@st.cache_data(ttl=1800, **CACHE_KW)
def universe() -> pd.DataFrame:
    return bvc.universe()


@st.cache_data(ttl=600, **CACHE_KW)
def indices() -> pd.DataFrame:
    return bvc.index_table()


@st.cache_data(ttl=600, **CACHE_KW)
def sector_indices() -> pd.DataFrame:
    return bvc.sector_indices()


@st.cache_data(ttl=600, **CACHE_KW)
def global_quotes(force: bool = False) -> pd.DataFrame:
    return market.global_quotes(force=force)


@st.cache_data(ttl=900, **CACHE_KW)
def market_news(force: bool = False) -> pd.DataFrame:
    try:
        return news.fetch_all_news(force=force)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, **CACHE_KW)
def asset_frame(force: bool = False) -> pd.DataFrame:
    return optimize.asset_frame(force=force)


@st.cache_data(ttl=1800, **CACHE_KW)
def index_history(code: str = "MASI", period: str = "1Y") -> pd.DataFrame:
    try:
        return bvc.index_history(code, period=period)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, **CACHE_KW)
def index_members(code: str) -> set:
    """Symboles composant un indice (composition officielle BVC), vide si indisponible."""
    if not code or code == "Tous":
        return set()
    try:
        frame = bvc.index_composition(code)
        if frame is None or frame.empty or "symbol" not in frame.columns:
            return set()
        return {str(s) for s in frame["symbol"].dropna()}
    except Exception:
        return set()


@st.cache_data(ttl=1800, **CACHE_KW)
def stock_history(symbol: str, days: int = 400) -> pd.DataFrame:
    try:
        return bvc.stock_history(symbol, days=days)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800, **CACHE_KW)
def technical_summary(symbol: str) -> Dict[str, Any]:
    """Résumé technique d'une valeur, calculé sur l'historique BVC en cache."""
    hist = stock_history(symbol, days=400)
    if hist is None or hist.empty:
        return {}
    try:
        return technical.technical_summary(hist)
    except Exception:
        return {}


def get_profile() -> profile_mod.InvestorProfile:
    """Profil de l'investisseur, persisté et synchronisé avec la session."""
    if "profile" not in st.session_state:
        st.session_state["profile"] = profile_mod.load_profile()
    return st.session_state["profile"]


def set_profile(profile: profile_mod.InvestorProfile, persist: bool = True) -> None:
    st.session_state["profile"] = profile
    if persist:
        profile_mod.save_profile(profile)


def enriched_holdings(profile: Optional[profile_mod.InvestorProfile] = None) -> pd.DataFrame:
    profile = profile or get_profile()
    if not profile.holdings:
        return pd.DataFrame()
    try:
        return profile_mod.enrich_holdings(profile, market_table())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900, **CACHE_KW)
def recommendation(amount: float = 0.0, years: int = 0, profile_key: str = "") -> Dict[str, Any]:
    """Recommandation complète (cache invalidé par `profile_key`)."""
    profile = profile_mod.load_profile()
    table = scoring.build_market_table()
    return simulate.recommend(
        profile, table,
        amount=amount if amount > 0 else None,
        years=years if years > 0 else None,
    )


def build_agent(provider: Optional[str] = None, share_amounts: bool = False):
    holdings = enriched_holdings()
    if holdings is None or holdings.empty:
        holdings = None
    rec = recommendation()
    return agent_mod.build_agent(
        market_df=market_table(),
        regime=market_regime(),
        profile=get_profile(),
        enriched_holdings=holdings,
        recommendation=rec,
        provider=provider,
        share_amounts=share_amounts,
    )


def fx_rates() -> Dict[str, float]:
    try:
        return market.fx_rates()
    except Exception:
        # Aucun taux inventé : seul MAD est certain.
        return {"MAD": 1.0}


@st.cache_data(ttl=600, **CACHE_KW)
def vix_regime() -> Dict[str, Any]:
    return market.vix_regime()


@st.cache_data(ttl=3600, **CACHE_KW)
def macro() -> Dict[str, Any]:
    return market.macro_context()


@st.cache_data(ttl=900, **CACHE_KW)
def coverage() -> pd.DataFrame:
    return fundamentals.coverage_report(scoring.build_market_table())


def last_market_date(df: Optional[pd.DataFrame] = None) -> str:
    """Date de clôture la plus récente des données de marché."""
    frame = df if df is not None else snapshot()
    if frame is None or frame.empty or "last_date" not in frame.columns:
        return "date indisponible"
    dates = pd.to_datetime(frame["last_date"], errors="coerce").dropna()
    if dates.empty:
        return "date indisponible"
    return dates.max().strftime("%d/%m/%Y")


def watchlist() -> list:
    import json

    from ...config import WATCHLIST_FILE

    try:
        with open(WATCHLIST_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return list(data) if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def toggle_watchlist(symbol: str) -> bool:
    """Ajoute/retire une valeur de la liste de suivi. Retourne l'état final."""
    import json

    from ...config import WATCHLIST_FILE

    items = watchlist()
    symbol = symbol.strip().upper()
    if symbol in items:
        items.remove(symbol)
        state = False
    else:
        items.append(symbol)
        state = True
    try:
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False)
    except OSError:
        pass
    return state


def clear_caches() -> None:
    """Purge les caches mémoire et disque."""
    from ...utils import cache

    cache.clear()
    st.cache_data.clear()
