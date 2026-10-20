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
from .http import ProviderError, classify_status, record_error, record_exception, record_success

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
    "baisse des taux", "stimulus", "soutien", "florissant", "dynamisme",
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
            kind = classify_status(resp.status_code)
            record_error(source["name"], ProviderError(
                source["name"], resp.status_code, kind, f"HTTP {resp.status_code}",
                kind in {"rate_limit", "server", "timeout", "network"},
            ))
            return []
        items = parse_feed(resp.text, source["name"], source.get("scope", ""))
        if not items:
            record_error(source["name"], ProviderError(
                source["name"], 200, "empty", "flux sans article exploitable", False,
            ))
        else:
            record_success(source["name"], len(items), 200)
        return items
    except requests.RequestException as exc:
        record_error(source["name"], ProviderError(
            source["name"], None, "network", str(exc), True,
        ))
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
        futures = {pool.submit(_fetch_source, s): s for s in SOURCES}
        for fut in as_completed(futures):
            source = futures[fut]
            try:
                collected.extend(fut.result())
            except Exception as exc:
                record_exception(f"Actualités · {source.get('name') or source.get('url')}", exc)
                continue

    df = pd.DataFrame(collected)
    if df.empty:
        stale = cache.get(NS, key, None)
        return stale if stale is not None else df

    # Date de récupération distincte de la date de publication : une actualité
    # ancienne reste ancienne, même si elle vient d'être importée.
    df["fetched_at"] = pd.Timestamp.now(tz="UTC")

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    df = df[df["published"].isna() | (df["published"] >= cutoff)]
    df["dedup"] = df["title"].str.lower().str.replace(r"[^a-z0-9à-ÿ ]", "", regex=True).str.slice(0, 90)
    df = df.drop_duplicates(subset=["dedup"]).drop(columns=["dedup"])
    df["sentiment"] = df.apply(lambda r: score_text(f"{r['title']} {r['summary']}"), axis=1)
    df["sentiment_label"] = df["sentiment"].apply(sentiment_label)
    df = enrich_news(df)
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
        df["fetched_at"] = pd.Timestamp.now(tz="UTC")
        df["sentiment"] = df.apply(lambda r: score_text(f"{r['title']} {r['summary']}"), axis=1)
        df["sentiment_label"] = df["sentiment"].apply(sentiment_label)
        df = enrich_news(df)
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


# ═══════════════════════════ Catégories et impact ═══════════════════════════
# Sentiment (ton de l'article) et impact potentiel (matérialité estimée) sont DEUX
# dimensions distinctes. La classification ci-dessous est heuristique (mots-clés)
# et explicitement présentée comme indicative : elle ne remplace pas une lecture.

CATEGORY_RULES: List[tuple] = [
    ("Dividendes", ("dividende", "dividend", "coupon")),
    ("Résultats", ("résultat", "resultat", "bénéfice", "chiffre d'affaires",
                   "ebitda", "earnings", "profit", "revenus", "profit warning")),
    ("Opérations sur titres", ("augmentation de capital", "fusion", "acquisition", "opa",
                               "apport", "cession", "merger", "opération sur titres")),
    ("Politique monétaire", ("bank al-maghrib", "taux directeur", "banque centrale", "bce",
                             "fed", "taux d'intérêt", "monétaire", "policy rate")),
    ("Inflation & prix", ("inflation", "ipc", "prix à la consommation", "cpi")),
    ("Taux de change", ("dirham", "taux de change", "devise", "currency")),
    ("Réglementation", ("ammc", "réglement", "reglement", "sanction", "amende", "régulateur",
                        "regulation", "compliance")),
    ("Énergie & matières premières", ("pétrole", "cours du baril", "matières premières",
                                      "oil", "commodity")),
    ("Secteur", ("secteur", "banque", "immobilier", "tourisme", "agroalimentaire", "btp",
                 "télécom", "telecom", "assurance")),
]

_IMPACT_TOP = ("augmentation de capital", "fusion", "acquisition", "opa", "taux directeur",
               "sanction", "amende", "faillite", "profit warning",
               "avertissement sur résultats", "résultats annuels", "résultats semestriels")
_IMPACT_STRONG = ("résultat", "bénéfice", "perte", "dividende", "fusion", "acquisition",
                  "sanction", "amende", "faillite", "taux directeur", "augmentation de capital")


def classify_category(text: str) -> str:
    """Catégorie thématique (heuristique par mots-clés)."""
    low = (text or "").lower()
    for label, keywords in CATEGORY_RULES:
        if any(k in low for k in keywords):
            return label
    return "Général"


def impact_of(text: str, category: Optional[str] = None) -> Dict[str, Any]:
    """Impact potentiel estimé (Faible/Moyen/Élevé), distinct du sentiment.

    Renvoie le niveau et la **raison** (les mots-clés déclencheurs), pour que
    l'estimation soit vérifiable plutôt qu'opaque.
    """
    low = (text or "").lower()
    category = category or classify_category(text)
    hits = [k for k in _IMPACT_TOP if k in low]
    if hits:
        return {"level": "Élevé", "reason": f"mention de « {hits[0]} »"}
    strong = [k for k in _IMPACT_STRONG if k in low]
    if len(strong) >= 2:
        return {"level": "Élevé", "reason": f"{len(strong)} facteurs matériels : {', '.join(strong[:3])}"}
    if len(strong) == 1:
        return {"level": "Moyen", "reason": f"facteur matériel : {strong[0]}"}
    if category in ("Politique monétaire", "Réglementation"):
        return {"level": "Moyen", "reason": f"thème {category}"}
    return {"level": "Faible", "reason": "aucun facteur matériel explicite"}


def enrich_news(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute `category`, `impact_level` et `impact_reason` (indicatifs)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    title = out["title"].fillna("").astype(str) if "title" in out.columns else pd.Series([""] * len(out))
    summary = out["summary"].fillna("").astype(str) if "summary" in out.columns else pd.Series([""] * len(out))
    text = title + " " + summary
    out["category"] = text.apply(classify_category)
    impacts = text.apply(impact_of)
    out["impact_level"] = [i["level"] for i in impacts]
    out["impact_reason"] = [i["reason"] for i in impacts]
    return out


def holdings_relevance(df: pd.DataFrame, holdings: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """Marque les articles mentionnant une société détenue (symbole ou nom)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if not holdings:
        out["held"] = ""
        return out
    tags = []
    for _, row in out.iterrows():
        text = f"{row.get('title','')} {row.get('summary','')} {row.get('scope','')}".lower()
        hits = []
        for h in holdings:
            symbol = str(h.get("symbol") or "").strip()
            name = str(h.get("name") or "").strip()
            if symbol and len(symbol) >= 2 and re.search(rf"\b{re.escape(symbol.lower())}\b", text):
                hits.append(symbol.upper())
            elif name and len(name) >= 4 and name.lower() in text:
                hits.append(name)
        tags.append(" · ".join(hits[:3]))
    out["held"] = tags
    return out


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
