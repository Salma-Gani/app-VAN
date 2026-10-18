"""Agrégation d'actualités financières (flux RSS) et analyse de sentiment.

Aucune clé d'API requise : les flux RSS publics sont collectés en parallèle,
dédupliqués puis notés par un lexique financier français/anglais.
"""
from __future__ import annotations

import re
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import requests

from ..config import HTTP_HEADERS, HTTP_TIMEOUT, TTL
from ..utils import cache

NS = "news"

SOURCES: List[Dict[str, str]] = [
    {"name": "Medias24", "url": "https://medias24.com/feed/", "scope": "Maroc"},
    {"name": "Le360", "url": "https://le360.ma/rss", "scope": "Maroc"},
    {"name": "LesEco", "url": "https://leseco.ma/feed", "scope": "Maroc"},
    {"name": "Boursenews", "url": "https://www.boursenews.ma/feed", "scope": "BVC"},
    {"name": "Challenge", "url": "https://www.challenge.ma/feed/", "scope": "Maroc"},
    {"name": "Investing.com", "url": "https://www.investing.com/rss/news.rss", "scope": "International"},
    {"name": "Investing — Actions", "url": "https://www.investing.com/rss/news_25.rss", "scope": "International"},
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "scope": "International"},
    {"name": "Financial Afrik", "url": "https://www.financialafrik.com/feed/", "scope": "Afrique"},
    {"name": "Agence Ecofin", "url": "https://www.agenceecofin.com/rss", "scope": "Afrique"},
]

GOOGLE_NEWS = "https://news.google.com/rss/search"

_LOCAL = threading.local()

# ═══════════════════════════ Lexique de sentiment ═══════════════════════════
POSITIVE = {
    "hausse", "progress", "progression", "croissance", "bénéfice", "benefice", "profits",
    "record", "gains", "dividende", "surperformance", "surperforme", "rebond", "rebondit",
    "accélère", "accelere", "optimiste", "contrat", "extension", "investissement",
    "croît", "croit", "amélioration", "amelioration", "relève", "releve", "résultats solides",
    "acquisition", "partenariat", "développement", "developpement", "excellente", "surcote",
    "surperformance", "hausses", "rallye", "confiance", "solide", "inflation ralentit",
    "baisse des taux", "stimulus", "soutien", "florissant", "dinamisme", "dynamisme",
    "beats", "beat", "upgrade", "outperform", "growth", "profit", "rally", "surge",
    "jumps", "record high", "strong", "bullish", "raises", "expansion", "deal",
}
NEGATIVE = {
    "baisse", "chute", "recul", "perte", "pertes", "déficit", "deficit", "avertissement",
    "avertit", "alerte", "crise", "récession", "recession", "dégradation", "degradation",
    "amende", "sanction", "poursuite", "fraude", "scandale", "grève", "greve", "licenciement",
    "restructuration", "suspension", "retard", "inquiétude", "inquietude", "incertitude",
    "downgrade", "sous-performance", "sous performance", "chute", "plonge", "effondrement",
    "correction", "pression", "faillite", "liquidation", "prudence", "vigilance", "risque",
    "fall", "falls", "drop", "drops", "plunge", "slump", "loss", "losses", "warning",
    "downgrades", "bearish", "weak", "decline", "crash", "lawsuit", "fine", "default",
}

BULLISH_HINTS = {"bce", "fed", "taux", "inflation", "croissance", "emploi"}


def _session() -> requests.Session:
    s = getattr(_LOCAL, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({**HTTP_HEADERS, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        _LOCAL.session = s
    return s


def _text(node: Optional[ET.Element]) -> str:
    if node is None or node.text is None:
        return ""
    return re.sub(r"<[^>]+>", " ", node.text).strip()


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value[: len(fmt) + 6], fmt)
            return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def parse_feed(xml_text: str, source: str, scope: str) -> List[Dict[str, Any]]:
    """Parse un flux RSS/Atom en liste d'articles normalisés."""
    items: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}
    nodes = root.findall(".//item") or root.findall(".//atom:entry", ns)

    for node in nodes:
        title = _text(node.find("title")) or _text(node.find("atom:title", ns))
        link = _text(node.find("link")) or ""
        if not link:
            link_node = node.find("atom:link", ns)
            if link_node is not None:
                link = link_node.attrib.get("href", "")
        summary = (
            _text(node.find("description"))
            or _text(node.find("atom:summary", ns))
            or _text(node.find("content:encoded", ns))
        )
        published = _parse_date(
            _text(node.find("pubDate"))
            or _text(node.find("atom:updated", ns))
            or _text(node.find("atom:published", ns))
        )
        if not title:
            continue
        items.append(
            {
                "title": title,
                "summary": summary[:600],
                "link": link,
                "source": source,
                "scope": scope,
                "published": published,
                "date": published.date() if published else None,
            }
        )
    return items


def _fetch_source(source: Dict[str, str]) -> List[Dict[str, Any]]:
    try:
        resp = _session().get(source["url"], timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        return parse_feed(resp.text, source["name"], source.get("scope", ""))
    except requests.RequestException:
        return []


def fetch_all_news(max_age_days: int = 14, force: bool = False) -> pd.DataFrame:
    """Collecte l'ensemble des flux, déduplique et trie par date décroissante."""
    key = cache.make_key("all_news", max_age_days)
    if not force:
        hit = cache.get(NS, key, TTL["news"])
        if hit is not None and len(hit):
            return hit

    collected: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_fetch_source, s) for s in SOURCES]
        for fut in as_completed(futures):
            try:
                collected.extend(fut.result())
            except Exception:
                continue

    df = pd.DataFrame(collected)
    if df.empty:
        stale = cache.get(NS, key, None)
        return stale if stale is not None else df

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    df = df[df["published"].isna() | (df["published"] >= cutoff)]
    df["dedup"] = df["title"].str.lower().str.replace(r"[^a-z0-9à-ÿ ]", "", regex=True).str.slice(0, 90)
    df = df.drop_duplicates(subset=["dedup"]).drop(columns=["dedup"])
    df["sentiment"] = df.apply(lambda r: score_text(f"{r['title']} {r['summary']}"), axis=1)
    df["sentiment_label"] = df["sentiment"].apply(sentiment_label)
    df = df.sort_values("published", ascending=False, na_position="last").reset_index(drop=True)
    cache.set(NS, key, df)
    return df


def google_news_query(query: str, limit: int = 25, force: bool = False) -> pd.DataFrame:
    """Recherche d'actualités via Google News RSS (aucune clé requise)."""
    key = cache.make_key("gnews", query.lower(), limit)
    if not force:
        hit = cache.get(NS, key, TTL["news"])
        if hit is not None and len(hit):
            return hit
    params = {"q": query, "hl": "fr", "gl": "MA", "ceid": "MA:fr"}
    try:
        resp = _session().get(GOOGLE_NEWS, params=params, timeout=HTTP_TIMEOUT)
        items = parse_feed(resp.text, f"Google News — {query}", "Recherche") if resp.status_code == 200 else []
    except requests.RequestException:
        items = []
    df = pd.DataFrame(items[:limit])
    if not df.empty:
        df["sentiment"] = df.apply(lambda r: score_text(f"{r['title']} {r['summary']}"), axis=1)
        df["sentiment_label"] = df["sentiment"].apply(sentiment_label)
        cache.set(NS, key, df)
    return df


def company_news(company_name: str, symbol: str = "", limit: int = 20, force: bool = False) -> pd.DataFrame:
    """Actualités relatives à une entreprise (nom puis symbole en repli)."""
    query = f'"{company_name}"' if company_name else symbol
    df = google_news_query(query, limit=limit, force=force)
    if df.empty and symbol:
        df = google_news_query(symbol, limit=limit, force=force)
    return df


def sector_news(sector: str, limit: int = 20, force: bool = False) -> pd.DataFrame:
    """Actualités relatives à un secteur."""
    query = f"Bourse Casablanca {sector}"
    return google_news_query(query, limit=limit, force=force)


# ═══════════════════════════ Sentiment ═══════════════════════════

def score_text(text: str) -> float:
    """Score de sentiment dans [-1, 1] basé sur un lexique financier."""
    if not text:
        return 0.0
    low = text.lower()
    pos = sum(1 for w in POSITIVE if w in low)
    neg = sum(1 for w in NEGATIVE if w in low)
    total = pos + neg
    if total == 0:
        return 0.0
    raw = (pos - neg) / total
    # Atténue les scores extrêmes sur les textes courts
    confidence = min(1.0, total / 4.0)
    return float(max(-1.0, min(1.0, raw * (0.55 + 0.45 * confidence))))


def sentiment_label(score: Optional[float]) -> str:
    if score is None:
        return "Neutre"
    if score >= 0.35:
        return "Très positif"
    if score >= 0.12:
        return "Positif"
    if score <= -0.35:
        return "Très négatif"
    if score <= -0.12:
        return "Négatif"
    return "Neutre"


def aggregate_sentiment(df: pd.DataFrame, days: int = 7) -> Dict[str, Any]:
    """Sentiment agrégé (moyenne pondérée par fraîcheur) sur les N derniers jours."""
    if df is None or df.empty or "sentiment" not in df.columns:
        return {"score": 0.0, "label": "Neutre", "count": 0, "positive": 0, "negative": 0}
    sub = df.copy()
    if "published" in sub.columns and sub["published"].notna().any():
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        sub = sub[sub["published"].isna() | (sub["published"] >= cutoff)]
    if sub.empty:
        return {"score": 0.0, "label": "Neutre", "count": 0, "positive": 0, "negative": 0}
    now = datetime.now(timezone.utc)
    weights = []
    for _, row in sub.iterrows():
        pub = row.get("published")
        if pub is None or pd.isna(pub):
            weights.append(0.5)
        else:
            age_days = max((now - pub).days, 0)
            weights.append(1.0 / (1.0 + age_days))
    w = pd.Series(weights, index=sub.index, dtype=float).fillna(0.5)
    score = float((sub["sentiment"].fillna(0) * w).sum() / max(w.sum(), 1e-9))
    return {
        "score": score,
        "label": sentiment_label(score),
        "count": int(len(sub)),
        "positive": int((sub["sentiment"] > 0.12).sum()),
        "negative": int((sub["sentiment"] < -0.12).sum()),
    }


def news_by_sector(force: bool = False) -> pd.DataFrame:
    """Sentiment agrégé par secteur, à partir des titres d'actualité."""
    df = fetch_all_news(force=force)
    if df.empty:
        return pd.DataFrame(columns=["secteur", "score", "articles"])
    from ..config import SECTOR_RISK

    rows = []
    for sector in SECTOR_RISK:
        keywords = [w for w in re.split(r"[ ,'/]+", sector.lower()) if len(w) > 3]
        mask = df["title"].str.lower().apply(lambda t: any(k in t for k in keywords)) if keywords else pd.Series(False, index=df.index)
        sub = df[mask]
        if sub.empty:
            continue
        agg = aggregate_sentiment(sub, days=21)
        rows.append({"secteur": sector, "score": agg["score"], "articles": agg["count"]})
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def market_news_summary(force: bool = False) -> Dict[str, Any]:
    """Résumé de sentiment global du marché."""
    df = fetch_all_news(force=force)
    return aggregate_sentiment(df, days=5)
