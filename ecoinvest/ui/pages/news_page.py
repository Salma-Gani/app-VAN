"""Veille d'actualités : sentiment du marché, secteurs et flux par source."""
from __future__ import annotations

import html as html_mod
from typing import Any, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...config import COLORS
from ...data import news
from ...utils.formatting import fmt_num, fmt_pct
from .. import components as ui
from . import shared


def render() -> None:
    ui.hero(
        "Actualités & sentiment",
        "Flux RSS publics (BVC, presse économique marocaine et internationale), dédupliqués et "
        "analysés par un lexique financier.",
        badge=ui.badge("Sources publiques · sans clé API", "info"),
    )

    ui.source_note(
        ["Flux RSS publics"],
        detail="Chaque article renvoie à sa source d'origine ; le sentiment est un indicateur lexical, pas une opinion.",
    )

    df = shared.market_news()
    if df.empty:
        ui.empty_state(
            "Aucune actualité n'a pu être chargée. Les flux RSS sont peut-être momentanément "
            "inaccessibles — réessayez dans quelques minutes.",
            "📰",
        )
        return

    df = _with_holdings(df)
    _summary(df)
    st.divider()
    filtered = _filters(df)
    st.divider()
    _feed(filtered)
    ui.disclaimer()


def _with_holdings(df: pd.DataFrame) -> pd.DataFrame:
    try:
        holdings = shared.get_profile().holdings or []
    except Exception:
        holdings = []
    return news.holdings_relevance(df, holdings)


# ═══════════════════════════ Synthèse ═══════════════════════════


def _summary(df: pd.DataFrame) -> None:
    agg = news.aggregate_sentiment(df, days=7)
    by_sector = news.news_by_sector()
    sources = df["source"].nunique() if "source" in df.columns else 0

    tone = "up" if agg["score"] > 0.12 else "down" if agg["score"] < -0.12 else "warn"
    impact_high = int((df["impact_level"] == "Élevé").sum()) if "impact_level" in df.columns else 0
    held = df["held"].astype(str) if "held" in df.columns else pd.Series([""] * len(df))
    held_count = int((held.str.len() > 0).sum())
    ui.kpi_row(
        [
            {"label": "Sentiment 7 jours", "value": str(agg["label"]),
             "sub": f"score {fmt_num(agg['score'], 2)} · {agg['count']} articles", "tone": tone},
            {"label": "Articles positifs", "value": str(agg["positive"]),
             "sub": "tonalité favorable", "tone": "up"},
            {"label": "Articles négatifs", "value": str(agg["negative"]),
             "sub": "tonalité défavorable", "tone": "down"},
            {"label": "Impact potentiel élevé", "value": str(impact_high),
             "sub": "matérialité estimée (heuristique)", "tone": "warn"},
            {"label": "Liés au portefeuille", "value": str(held_count),
             "sub": "mentionnent une position détenue", "tone": "accent"},
            {"label": "Sources actives", "value": str(sources),
             "sub": f"{len(df)} articles au total", "tone": "blue"},
        ],
        per_row=3,
    )

    left, right = st.columns([1.3, 1], gap="medium")
    with left:
        ui.section("Sentiment par secteur", "Analyse des titres d'actualité, pondérée par fraîcheur.")
        if by_sector.empty:
            ui.empty_state("Sentiment sectoriel indisponible.", "🗂️")
        else:
            sub = by_sector.head(12).sort_values("score")
            fig = go.Figure(
                go.Bar(
                    x=sub["score"], y=sub["secteur"], orientation="h",
                    marker_color=[COLORS["up"] if v >= 0 else COLORS["down"] for v in sub["score"]],
                    opacity=0.85,
                    customdata=sub["articles"],
                    hovertemplate="<b>%{y}</b><br>Score %{x:.2f}<br>%{customdata} articles<extra></extra>",
                )
            )
            fig.update_layout(height=380, xaxis_title="Score de sentiment (−1 à +1)", showlegend=False,
                              margin=dict(l=10, r=20, t=10, b=10))
            ui.plot(fig, key="news_sector")
    with right:
        ui.section("Répartition par source")
        counts = df["source"].value_counts().head(10)
        display = counts.rename_axis("Source").reset_index(name="Articles")
        ui.table(display, height=380, key="news_sources")

        with st.expander("ℹ️ Méthodologie du sentiment et de l'impact", expanded=False):
            st.markdown(
                "**Sentiment (ton de l'article).** Score calculé par un lexique de mots financiers "
                "positifs et négatifs (hausse, bénéfice, dividende… / baisse, perte, sanction…). "
                "Il est **atténué** lorsque peu de mots-clés sont détectés, afin d'éviter les scores "
                "extrêmes sur des titres courts. Le sentiment agrégé pondère chaque article par sa "
                "fraîcheur (1 / (1 + jours)).\n\n"
                "**Impact potentiel (matérialité estimée).** Dimension **distincte** du sentiment : "
                "un article peut être très négatif sans conséquence financière, ou neutre en ton tout "
                "en annonçant un événement majeur (augmentation de capital, taux directeur…). Le niveau "
                "(Faible/Moyen/Élevé) et sa **raison** (mots-clés déclencheurs) sont affichés pour être "
                "vérifiables.\n\n"
                "Les deux mesures sont **indicatives et heuristiques** (mots-clés) : elles ne remplacent "
                "pas une lecture humaine et ne constituent ni une prévision ni un conseil."
            )


# ═══════════════════════════ Filtres ═══════════════════════════


def _filters(df: pd.DataFrame) -> pd.DataFrame:
    sources = sorted([str(s) for s in df["source"].dropna().unique()])
    c1, c2, c3, c4 = st.columns([2, 1.3, 1.3, 1])
    with c1:
        search = st.text_input("Rechercher", placeholder="Mot-clé, société, secteur…")
    with c2:
        chosen_sources = st.multiselect("Sources", sources, default=[], placeholder="Toutes")
    with c3:
        tones = st.multiselect(
            "Tonalité", ["Très positif", "Positif", "Neutre", "Négatif", "Très négatif"],
            default=[], placeholder="Toutes",
        )
    with c4:
        days = st.slider("Fenêtre (jours)", 1, 14, 7)

    d1, d2 = st.columns([2, 3])
    cats = sorted([str(c) for c in df["category"].dropna().unique()]) if "category" in df.columns else []
    with d1:
        chosen_cats = st.multiselect("Catégorie", cats, default=[], placeholder="Toutes",
                                     key="news_cats")
    with d2:
        chosen_levels = st.multiselect(
            "Impact potentiel", ["Élevé", "Moyen", "Faible"], default=[], placeholder="Tous",
            key="news_levels",
        )

    out = df.copy()
    if "published" in out.columns and out["published"].notna().any():
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        out = out[out["published"].isna() | (out["published"] >= cutoff)]
    if chosen_sources:
        out = out[out["source"].isin(chosen_sources)]
    if tones:
        out = out[out["sentiment_label"].isin(tones)]
    if chosen_cats and "category" in out.columns:
        out = out[out["category"].isin(chosen_cats)]
    if chosen_levels and "impact_level" in out.columns:
        out = out[out["impact_level"].isin(chosen_levels)]
    if search:
        needle = search.strip().lower()
        out = out[
            out["title"].str.lower().str.contains(needle, na=False)
            | out["summary"].str.lower().str.contains(needle, na=False)
        ]
    st.caption(f"{len(out)} article(s) correspondent aux critères.")
    return out


# ═══════════════════════════ Flux ═══════════════════════════


def _feed(df: pd.DataFrame) -> None:
    ui.section("Fil d'actualités", "Cliquez sur un titre pour ouvrir l'article dans un nouvel onglet.")
    if df.empty:
        ui.empty_state("Aucun article ne correspond aux filtres.", "🔍")
        return

    for _, item in df.head(40).iterrows():
        _card(item)


def _card(item: pd.Series) -> None:
    score = item.get("sentiment") or 0.0
    tone = "up" if score > 0.12 else "down" if score < -0.12 else "flat"
    published = item.get("published")
    date = "—"
    if published is not None and not pd.isna(published):
        try:
            date = pd.Timestamp(published).strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError):
            date = str(published)

    link = str(item.get("link") or "#")
    title = html_mod.escape(str(item.get("title") or "Sans titre"))
    source = html_mod.escape(str(item.get("source") or ""))
    scope = html_mod.escape(str(item.get("scope") or ""))
    summary = html_mod.escape(str(item.get("summary") or ""))
    summary = summary[:300] + ("…" if len(summary) > 300 else "")
    category = html_mod.escape(str(item.get("category") or ""))
    impact = html_mod.escape(str(item.get("impact_level") or ""))
    reason = html_mod.escape(str(item.get("impact_reason") or ""))
    held = html_mod.escape(str(item.get("held") or ""))
    impact_tone = {"Élevé": "down", "Moyen": "warn"}.get(str(item.get("impact_level") or ""), "flat")

    st.markdown(
        f"""
        <div class="ei-card" style="margin-bottom:.65rem">
          <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start">
            <a href="{link}" target="_blank" rel="noopener"
               style="font-weight:700;font-size:1rem;line-height:1.4;color:{COLORS['text']};text-decoration:none">
              {title}
            </a>
            <span class="ei-badge ei-{tone}">{html_mod.escape(str(item.get('sentiment_label') or 'Neutre'))}</span>
          </div>
          <div class="ei-muted" style="font-size:.75rem;margin:.3rem 0">
            {source}{(' · ' + scope) if scope else ''} · {date} · score {score:+.2f}
          </div>
          <div class="ei-muted" style="font-size:.75rem;margin:.15rem 0">
            {category}{(' · impact : ' + impact) if impact else ''}{(' — ' + reason) if reason else ''}
            <span class="ei-badge ei-{impact_tone}" style="margin-left:.4rem">impact {impact or '—'}</span>
            {(' · <strong>Portefeuille : ' + held + '</strong>') if held else ''}
          </div>
          <div class="ei-muted" style="font-size:.83rem;line-height:1.5">{summary}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
