"""Parcours d'analyse guidé : de l'information à la surveillance d'une thèse.

Cette page relie explicitement les cinq étapes du produit autour d'une même
valeur :

1. **Comprendre** — que dit le marché et l'actualité ?
2. **Analyser** — que disent les états financiers et les ratios ?
3. **Valoriser** — quel prix théorique selon vos hypothèses ?
4. **Surveiller** — les conditions de la thèse sont-elles réunies (prix, métrique) ?
5. **Portefeuille** — quelle exposition éventuelle dans votre patrimoine ?

Chaque étape affiche ce qui est disponible, ce qui manque et où le compléter.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from ...analytics import alerts as alerts_mod
from ...analytics import thesis as thesis_mod
from ...config import COLORS
from ...data import fundamentals, statements as stmt
from ...utils.formatting import as_float, fmt_money, fmt_num, fmt_pct
from .. import components as ui
from . import shared

_STEPS = [
    ("comprendre", "1", "Comprendre", "🌍", "Marché, actualité et contexte"),
    ("analyser", "2", "Analyser", "🧾", "États financiers et ratios"),
    ("valoriser", "3", "Valoriser", "🧮", "Prix théorique et hypothèses"),
    ("surveiller", "4", "Surveiller", "🔔", "Conditions de la thèse"),
    ("portefeuille", "5", "Relier au portefeuille", "💼", "Exposition et risque"),
]


def _goto(page_key: str, symbol: Optional[str] = None) -> None:
    if symbol:
        st.session_state["selected_symbol"] = symbol
    pages = st.session_state.get("_nav_pages") or {}
    target = pages.get(page_key)
    if target is not None:
        st.switch_page(target)
    else:
        st.info("Navigation indisponible dans ce contexte de test.")


def _selector(table: pd.DataFrame) -> str:
    symbols = table["symbol"].astype(str).tolist()
    names = dict(zip(table["symbol"].astype(str), table["name"]))
    requested = str(st.session_state.get("selected_symbol") or "").upper()
    if requested not in symbols:
        requested = st.session_state.get("_last_symbol") or ("ATW" if "ATW" in symbols else symbols[0])
    index = symbols.index(requested) if requested in symbols else 0
    symbol = st.selectbox(
        "Valeur du parcours",
        symbols,
        index=index,
        format_func=lambda s: f"{s} — {names.get(s, s)}",
        key="parcours_symbol",
    )
    st.session_state["selected_symbol"] = symbol
    st.session_state["_last_symbol"] = symbol
    return symbol


def _ribbon(active: str) -> None:
    parts = []
    for key, num, title, icon, _ in _STEPS:
        cls = "mm-step mm-step-active" if key == active else "mm-step"
        parts.append(
            f'<div class="{cls}"><span class="mm-step-num">{num}</span>'
            f'<span class="mm-step-ico">{icon}</span><span>{title}</span></div>'
        )
    st.markdown(f'<div class="mm-steps">{"".join(parts)}</div>', unsafe_allow_html=True)


def render() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles.", "📡")
        return

    symbol = _selector(table)
    row = table[table["symbol"] == symbol].iloc[0]
    f = fundamentals.get_fundamentals(symbol, row)
    price = as_float(row.get("close")) or as_float(f.get("price"))
    cap = as_float(row.get("cap")) or as_float(f.get("market_cap"))

    ui.hero(
        "Parcours d'analyse",
        "Un même fil conducteur, de la compréhension d'une société à la surveillance de vos "
        "hypothèses de valorisation. Rien n'est un conseil : chaque étape expose ses données, "
        "ses sources et ses manques.",
        badge=ui.badge(symbol, "accent"),
    )
    _ribbon("comprendre")

    context = _context(symbol, row, f, table)

    st.divider()
    ui.section(
        "Les cinq étapes",
        "Suivez la colonne de gauche à droite : chaque étape exploite le résultat de la précédente.",
    )
    left, right = st.columns(2, gap="medium")
    with left:
        _step(
            "comprendre", "Comprendre", "🌍",
            status=context["market_status"], tone=context["market_tone"],
            lines=context["market_lines"],
            actions=[("Analyse société", "company"), ("Actualités", "news_page")],
            symbol=symbol,
        )
        _step(
            "valoriser", "Valoriser", "🧮",
            status=context["valuation_status"], tone=context["valuation_tone"],
            lines=context["valuation_lines"],
            actions=[("Valuation Lab", "valuation"), ("Analyse IA", "ai_page")],
            symbol=symbol,
        )
        _step(
            "portefeuille", "Relier au portefeuille", "💼",
            status=context["portfolio_status"], tone=context["portfolio_tone"],
            lines=context["portfolio_lines"],
            actions=[("Mon patrimoine", "profile_page"), ("Portefeuille", "portfolio_builder")],
            symbol=symbol,
        )
    with right:
        _step(
            "analyser", "Analyser", "🧾",
            status=context["analysis_status"], tone=context["analysis_tone"],
            lines=context["analysis_lines"],
            actions=[("États financiers", "statements_page"), ("Données fondamentales", "fundamentals_page")],
            symbol=symbol,
        )
        _step(
            "surveiller", "Surveiller", "🔔",
            status=context["watch_status"], tone=context["watch_tone"],
            lines=context["watch_lines"],
            actions=[("Alertes & thèses", "alerts_page")],
            symbol=symbol,
        )

    st.divider()
    _evidence(context)

    st.divider()
    ui.note(
        "**Ce que le parcours ne fait pas** : il ne recommande pas d'acheter ou de vendre, ne prédit "
        "pas le cours et ne garantit aucun prix cible. Il relie des données sourcées, des calculs "
        "reproductibles et des conditions de surveillance que vous définissez.",
        "warn", "⚠️",
    )


# ═══════════════════════════ Contexte par étape ═══════════════════════════

def _context(symbol: str, row: pd.Series, f: Dict[str, Any],
             table: pd.DataFrame) -> Dict[str, Any]:
    price = as_float(row.get("close")) or as_float(f.get("price"))
    change = as_float(row.get("change_pct"))
    summary = shared.technical_summary(symbol)
    trend = (summary.get("trend") or {}).get("state") if summary else None

    # Actualités liées (recherche simple par symbole / nom)
    news_count = 0
    try:
        news_df = shared.market_news()
        if news_df is not None and not news_df.empty:
            name = str(row.get("name") or "")
            blob = news_df.astype(str).agg(" ".join, axis=1)
            mask = blob.str.contains(symbol, case=False, na=False)
            if name:
                mask = mask | blob.str.contains(name.split()[0], case=False, na=False)
            news_count = int(mask.sum())
    except Exception:
        news_count = 0

    # Ratios
    ratios = fundamentals.ratio_table(f, price=price, cap=as_float(row.get("cap")))
    computed = int(ratios["Valeur"].notna().sum()) if not ratios.empty else 0
    records = stmt.get_statements(symbol)
    latest = records[0] if records else None

    # Thèses
    theses = thesis_mod.list_for(symbol)
    evaluated = thesis_mod.evaluate(theses[0], price, f) if theses else None

    # Alertes
    try:
        alerts = alerts_mod.evaluate_row(row.to_dict(), summary)
    except Exception:
        alerts = []

    # Portefeuille
    holdings = shared.enriched_holdings()
    weight = None
    if holdings is not None and not holdings.empty and "symbol" in holdings.columns:
        line = holdings[holdings["symbol"].astype(str) == symbol]
        if not line.empty:
            weight = as_float(line.iloc[0].get("weight"))

    market_status = "Disponible"
    market_tone = "up"
    market_lines = [
        ("Cours", f"{fmt_num(price, 2)} MAD"),
        ("Variation", fmt_pct(change, 2, signed=True) if change is not None else "—"),
        ("Tendance 120 j", trend or "indisponible"),
        ("Actualités liées", str(news_count)),
    ]

    if records:
        analysis_status = f"{len(records)} exercice(s)"
        analysis_tone = "up"
        analysis_lines = [
            ("Chiffre d'affaires", fmt_money((latest.get('income') or {}).get('revenue'), 'MAD', compact=True)),
            ("Résultat net", fmt_money((latest.get('income') or {}).get('net_income'), 'MAD', compact=True)),
            ("Ratios calculés", str(computed)),
            ("Source", str(latest.get("source") or "—")[:48]),
        ]
    else:
        analysis_status = "États manquants"
        analysis_tone = "warn"
        analysis_lines = [
            ("États financiers", "aucun"),
            ("Ratios calculés", str(computed)),
            ("À faire", "importer bilan, CPC, trésorerie"),
            ("Source", f.get("_source") or "—"),
        ]

    if evaluated:
        valuation_status = evaluated.get("status_label") or "Thèse active"
        valuation_tone = {"entry_reached": "up", "near": "accent", "stale": "warn",
                          "invalid": "warn"}.get(evaluated.get("status"), "info")
        valuation_lines = [
            ("Méthode", str(evaluated.get("method_label") or "—")),
            ("Prix théorique", f"{fmt_num(evaluated.get('target_price'), 2)} MAD"),
            ("Prix d'entrée", f"{fmt_num(evaluated.get('entry_price'), 2)} MAD"),
            ("Marge exigée", fmt_pct(evaluated.get("required_margin"), 0)),
        ]
    else:
        valuation_status = "Aucune thèse enregistrée"
        valuation_tone = "info"
        valuation_lines = [
            ("Méthode", "à choisir"),
            ("Prix théorique", "—"),
            ("Prix d'entrée", "—"),
            ("À faire", "ouvrir le Valuation Lab"),
        ]

    if alert_count := len(alerts):
        watch_status = f"{alert_count} alerte(s)"
        watch_tone = "warn" if any(a.severity == "critical" for a in alerts) else "info"
    elif evaluated:
        watch_status = evaluated.get("status_label") or "Sous surveillance"
        watch_tone = "up" if evaluated.get("status") == "entry_reached" else "info"
    else:
        watch_status = "Rien à surveiller"
        watch_tone = "info"
    watch_lines = [
        ("Thèses actives", str(len(theses))),
        ("Alertes techniques", str(len(alerts))),
        ("Variation métrique",
         fmt_pct(evaluated.get("metric_change"), 2, signed=True)
         if evaluated and evaluated.get("metric_change") is not None else "—"),
        ("Recalcul requis",
         "oui" if evaluated and evaluated.get("needs_recalc") else "non"),
    ]

    if weight is not None:
        portfolio_status = f"Poids {fmt_pct(weight, 1)}"
        portfolio_tone = "info"
    else:
        portfolio_status = "Hors portefeuille"
        portfolio_tone = "flat"
    portfolio_lines = [
        ("Détention", "oui" if weight is not None else "non"),
        ("Poids simulé", fmt_pct(weight, 1) if weight is not None else "—"),
        ("Concentration", "à surveiller" if (weight or 0) > 0.15 else "—"),
        ("Simulation", "ouvrir le portefeuille"),
    ]

    return {
        "symbol": symbol, "row": row, "f": f, "price": price,
        "market_status": market_status, "market_tone": market_tone, "market_lines": market_lines,
        "analysis_status": analysis_status, "analysis_tone": analysis_tone, "analysis_lines": analysis_lines,
        "valuation_status": valuation_status, "valuation_tone": valuation_tone, "valuation_lines": valuation_lines,
        "watch_status": watch_status, "watch_tone": watch_tone, "watch_lines": watch_lines,
        "portfolio_status": portfolio_status, "portfolio_tone": portfolio_tone, "portfolio_lines": portfolio_lines,
        "latest": latest, "evaluated": evaluated, "theses": theses, "news_count": news_count,
        "computed": computed, "records": records,
    }


# ═══════════════════════════ Rendu des étapes ═══════════════════════════

def _step(key: str, title: str, icon: str, status: str, tone: str,
          lines: List[Any], actions: List[Any], symbol: str) -> None:
    with st.container(border=True):
        header, badge = st.columns([3, 1])
        with header:
            st.markdown(f"### {icon} {title}")
        with badge:
            st.markdown(ui.badge(status, tone), unsafe_allow_html=True)
        for label, value in lines:
            c1, c2 = st.columns([1.4, 1.6])
            with c1:
                st.caption(str(label))
            with c2:
                st.markdown(f"**{value}**")
        st.write("")
        cols = st.columns(len(actions))
        for col, (label, page) in zip(cols, actions):
            with col:
                if st.button(label, key=f"parcours_{key}_{page}_{symbol}", use_container_width=True):
                    _goto(page, symbol)


def _evidence(context: Dict[str, Any]) -> None:
    f = context["f"]
    latest = context["latest"]
    ui.section("Dossier de preuve", "Sources, dates et statuts de la valeur active.")
    rows = [
        {"Élément": "Cours", "Source": "Bourse de Casablanca (API publique)",
         "Date / exercice": shared.last_market_date(), "Statut": "différé"},
        {"Élément": "États financiers",
         "Source": (latest.get("source") if latest else "aucun") or "—",
         "Date / exercice": (f"exercice {latest.get('fiscal_year')}" if latest else "—"),
         "Statut": (latest.get("status") if latest else "non couvert") or "—"},
        {"Élément": "Nombre de titres / dividende", "Source": "Bourse de Casablanca (référentiel)",
         "Date / exercice": f"DPA {f.get('dps_year') or '—'}", "Statut": "quotidien / annuel"},
        {"Élément": "Indicateurs techniques", "Source": "Calcul sur l'historique BVC",
         "Date / exercice": shared.last_market_date(), "Statut": "calculé"},
        {"Élément": "Actualités", "Source": "Flux RSS publics",
         "Date / exercice": "date de publication", "Statut": "cache 15 min"},
    ]
    ui.table(pd.DataFrame(rows), height=240, key="parcours_evidence")
