"""Analyse guidée : marché, fondamentaux, valorisation et risques.

Le parcours ne remplace pas les pages spécialisées : il les relie autour d'une
même valeur et rend explicite ce qui est calculable, ce qui manque et pourquoi.

Principes :

- une donnée absente n'est jamais remplacée par zéro ;
- chaque ratio affiche sa formule et, lorsque c'est possible, la médiane de son
  secteur et le nombre de sociétés réellement utilisées ;
- une société sans états financiers conserve une page utile (cours, performance,
  volatilité, dividende, actualités) au lieu d'une série de cartes vides ;
- aucun prix cible n'est fabriqué : une valorisation n'apparaît que si
  l'utilisateur a enregistré une thèse dans le Valuation Lab.
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from ...analytics import alerts as alerts_mod
from ...analytics import sector_compare
from ...analytics import thesis as thesis_mod
from ...config import COLORS
from ...data import fundamentals, statements as stmt
from ...utils.formatting import as_float, fmt_money, fmt_multiple, fmt_num, fmt_pct
from .. import components as ui
from . import shared

STEP_LABELS = [
    "1 · Synthèse",
    "2 · Fondamentaux",
    "3 · Valorisation",
    "4 · Risques & actualités",
]

# Ratios affichés dans le parcours : libellé, unité, formule, sens.
RATIO_META: Tuple[Dict[str, Any], ...] = (
    {"key": "per", "label": "P/E", "unit": "x", "better": "lower",
     "formula": "Capitalisation / résultat net (ou cours / BPA)."},
    {"key": "pb", "label": "P/B", "unit": "x", "better": "lower",
     "formula": "Capitalisation / fonds propres (ou cours / actif net par action)."},
    {"key": "roe", "label": "ROE", "unit": "%", "better": "higher",
     "formula": "Résultat net / fonds propres."},
    {"key": "net_margin", "label": "Marge nette", "unit": "%", "better": "higher",
     "formula": "Résultat net / chiffre d'affaires."},
    {"key": "debt_to_equity", "label": "Dette / fonds propres", "unit": "x", "better": "lower",
     "formula": "Dette financière / fonds propres."},
    {"key": "current_ratio", "label": "Liquidité courante", "unit": "x", "better": "higher",
     "formula": "Actif circulant / passif circulant."},
    {"key": "interest_coverage", "label": "Couverture des intérêts", "unit": "x", "better": "higher",
     "formula": "Résultat d'exploitation / charges d'intérêts."},
    {"key": "dividend_yield", "label": "Rendement du dividende", "unit": "%", "better": "higher",
     "formula": "Dividende par action / cours."},
    {"key": "payout", "label": "Taux de distribution", "unit": "%", "better": None,
     "formula": "Dividende par action / bénéfice par action."},
    {"key": "fcf_yield", "label": "Rendement du FCF", "unit": "%", "better": "higher",
     "formula": "Free cash-flow / capitalisation."},
    {"key": "revenue_growth", "label": "Croissance du CA", "unit": "%", "better": "higher",
     "formula": "(CA exercice N − CA exercice N−1) / CA exercice N−1."},
    {"key": "ev_ebitda", "label": "EV/EBITDA", "unit": "x", "better": "lower",
     "formula": "(Capitalisation + dette nette) / EBITDA."},
)

VALUATION_KEYS = ("per", "pb", "dividend_yield", "ev_ebitda")


# ═══════════════════════════ Navigation et sélection ═══════════════════════════

def _goto(page_key: str, symbol: Optional[str] = None) -> None:
    if symbol:
        st.session_state["selected_symbol"] = symbol
    pages = st.session_state.get("_nav_pages") or {}
    target = pages.get(page_key)
    if target is not None:
        st.switch_page(target)
    else:
        st.info("Navigation indisponible dans ce contexte de test.")


def _set_step(label: str) -> None:
    st.session_state["parcours_step"] = label
    st.rerun()


def _selector(table: pd.DataFrame) -> str:
    symbols = table["symbol"].astype(str).tolist()
    names = dict(zip(table["symbol"].astype(str), table["name"]))
    sectors = dict(zip(table["symbol"].astype(str), table["sector"]))
    covered = set(stmt.covered_symbols())

    requested = str(st.session_state.get("selected_symbol") or "").upper()
    if requested not in symbols:
        requested = str(st.session_state.get("_last_symbol") or "").upper()

    if requested not in symbols:
        # Valeur par défaut : celle qui offre le plus de ratios fondamentaux,
        # puis la capitalisation. On ne s'ouvre plus sur une coquille vide.
        fund_cols = [
            column for column in ("r_per", "r_pb", "r_roe", "r_net_margin",
                                  "r_dividend_yield")
            if column in table.columns
        ]
        work = table.copy()
        for column in fund_cols:
            work[column] = pd.to_numeric(work[column], errors="coerce")
        work["_ratio_count"] = work[fund_cols].notna().sum(axis=1) if fund_cols else 0
        work["_has_statement"] = work["symbol"].astype(str).map(lambda s: s in covered)
        work = work.sort_values(
            ["_has_statement", "_ratio_count", "cap"],
            ascending=[False, False, False],
            na_position="last",
        )
        requested = str(work.iloc[0]["symbol"])

    # Les sociétés couvertes restent en tête de liste, sans masquer les autres.
    ordered = [s for s in symbols if s in covered] + [s for s in symbols if s not in covered]
    index = ordered.index(requested) if requested in ordered else 0

    def label(symbol: str) -> str:
        suffix = " · états vérifiés" if symbol in covered else " · marché seul"
        return f"{symbol} — {names.get(symbol, symbol)} ({sectors.get(symbol, '—')}){suffix}"

    widget_key = "parcours_symbol"
    previous = st.session_state.get("_parcours_requested_symbol")
    current = st.session_state.get(widget_key)
    if current not in ordered:
        st.session_state[widget_key] = ordered[index]
    elif requested in ordered and requested != previous:
        st.session_state[widget_key] = requested
    st.session_state["_parcours_requested_symbol"] = requested

    symbol = st.selectbox(
        "Valeur analysée", ordered, index=index, format_func=label, key=widget_key,
    )
    st.session_state["selected_symbol"] = symbol
    st.session_state["_last_symbol"] = symbol
    st.caption(
        f"{len(covered)} société(s) avec états vérifiés : "
        + (", ".join(sorted(covered)) if covered else "aucune")
        + f" · {len(symbols)} valeurs dans l'univers."
    )
    return symbol


# ═══════════════════════════ Utilitaires ═══════════════════════════

def _perimeter(record: Optional[Dict[str, Any]]) -> str:
    if not record:
        return "non couvert"
    if record.get("consolidated") is True:
        return "comptes consolidés"
    if record.get("consolidated") is False:
        return "comptes sociaux"
    return "périmètre non renseigné"


def _ratio_value(key: str, value: Any) -> str:
    numeric = as_float(value)
    if numeric is None:
        return "—"
    meta = next((item for item in RATIO_META if item["key"] == key), {})
    if meta.get("unit") == "%":
        return fmt_pct(numeric, 1)
    if meta.get("unit") == "x":
        return fmt_multiple(numeric, 2)
    return fmt_num(numeric, 2)


def _sector_median(table: pd.DataFrame, sector: str, key: str) -> Tuple[Optional[float], int]:
    column = f"r_{key}"
    if table is None or table.empty or column not in table.columns:
        return None, 0
    sub = table[table["sector"].astype(str) == str(sector)]
    values = pd.to_numeric(sub[column], errors="coerce").dropna()
    if values.empty:
        return None, 0
    return float(values.median()), int(len(values))


def _gap(value: Optional[float], median: Optional[float]) -> Optional[float]:
    if value is None or median in (None, 0):
        return None
    return value / median - 1.0


def _num(row: pd.Series, key: str) -> Optional[float]:
    return as_float(row.get(key))


def _range_52w(row: pd.Series) -> str:
    low, high = _num(row, "low_52w"), _num(row, "high_52w")
    if low is None or high is None:
        return "—"
    return f"{fmt_num(low, 2)} – {fmt_num(high, 2)} MAD"


# ═══════════════════════════ Page ═══════════════════════════

def render() -> None:
    table = shared.market_table()
    if table is None or table.empty:
        ui.empty_state(
            "Données de marché indisponibles : l'analyse guidée ne peut pas être calculée. "
            "Vérifiez la connexion à la Bourse de Casablanca puis rechargez la page.",
            "📡",
        )
        return

    symbol = _selector(table)
    row = table[table["symbol"].astype(str) == symbol].iloc[0]
    records = stmt.get_statements(symbol)
    latest = records[0] if records else None
    f = fundamentals.get_fundamentals(symbol, row)
    price = _num(row, "close") or as_float(f.get("price"))
    cap = _num(row, "cap") or as_float(f.get("market_cap"))
    sector = str(row.get("sector") or "—")
    ratios = fundamentals.compute_ratios(
        f, price=price, cap=cap, sector=sector,
    )

    coverage = "états vérifiés" if records else "marché seul"
    ui.hero(
        "Analyse guidée",
        "Un fil conducteur en quatre étapes : comprendre le marché, lire les comptes, "
        "situer la valorisation, puis identifier les risques. Chaque étape dit ce qu'elle "
        "peut calculer et ce qui manque. Aucun conseil d'achat ou de vente.",
        badge=ui.badge(f"{symbol} · {sector} · {coverage}", "accent" if records else "warn"),
    )

    _coverage_strip(symbol, row, records, latest, f, ratios, sector, table)

    if st.session_state.get("parcours_step") not in STEP_LABELS:
        st.session_state["parcours_step"] = STEP_LABELS[0]
    step = st.radio(
        "Étape du parcours", STEP_LABELS, horizontal=True,
        label_visibility="collapsed", key="parcours_step",
    )

    if step == STEP_LABELS[0]:
        _step_synthesis(symbol, row, records, latest, f, ratios, sector, table)
    elif step == STEP_LABELS[1]:
        _step_fundamentals(symbol, row, records, latest, f, ratios, sector, table)
    elif step == STEP_LABELS[2]:
        _step_valuation(symbol, row, records, latest, f, ratios, sector, table)
    else:
        _step_risk(symbol, row, records, latest, f, ratios, sector, table)

    st.divider()
    ui.note(
        "**Ce que cette analyse ne fait pas** : elle ne recommande pas d'acheter ou de vendre, "
        "ne prédit pas le cours et ne fabrique pas de prix cible. Elle relie des données "
        "sourcées, des calculs reproductibles et les manques à combler.",
        "warn", "⚠️",
    )
    ui.disclaimer()


def _coverage_strip(symbol: str, row: pd.Series, records: List[Dict[str, Any]],
                    latest: Optional[Dict[str, Any]], f: Dict[str, Any],
                    ratios: Dict[str, Optional[float]], sector: str,
                    table: pd.DataFrame) -> None:
    if records:
        ui.note(
            f"**États financiers disponibles pour {symbol}** — exercice "
            f"{latest.get('fiscal_year')} · {_perimeter(latest)} · source : "
            f"{str(latest.get('source') or 'non renseignée')[:90]}. "
            f"{len(records)} exercice(s) couvert(s).",
            "info", "🧾",
        )
    else:
        ui.note(
            f"**Aucun état financier vérifié pour {symbol}.** Les métriques de marché et "
            "le dividende restent disponibles, mais P/E, P/B, ROE, marge nette et FCF ne "
            "peuvent pas être calculés. Importez le rapport annuel AMMC pour les activer.",
            "warn", "📄",
        )


# ═══════════════════════════ Étape 1 — Synthèse ═══════════════════════════

def _step_synthesis(symbol: str, row: pd.Series, records: List[Dict[str, Any]],
                    latest: Optional[Dict[str, Any]], f: Dict[str, Any],
                    ratios: Dict[str, Optional[float]], sector: str,
                    table: pd.DataFrame) -> None:
    price = _num(row, "close") or as_float(f.get("price"))
    cap = _num(row, "cap") or as_float(f.get("market_cap"))
    change = _num(row, "change_pct")
    dy = ratios.get("dividend_yield")
    per = ratios.get("per")

    ui.kpi_grid(
        [
            {"label": "Cours", "value": f"{fmt_num(price, 2)} MAD",
             "sub": f"variation {fmt_pct(change, 2, signed=True)}" if change is not None else "—",
             "tone": "blue"},
            {"label": "Capitalisation", "value": fmt_money(cap, "MAD", compact=True),
             "sub": "cours × nombre de titres", "tone": "accent"},
            {"label": "Performance 12 mois", "value": fmt_pct(_num(row, "return_12m"), 1, signed=True),
             "sub": "historique BVC", "tone": "up" if (_num(row, "return_12m") or 0) >= 0 else "warn"},
            {"label": "Volatilité annualisée", "value": fmt_pct(_num(row, "volatility"), 1),
             "sub": "écart-type des rendements", "tone": "info"},
            {"label": "Rendement du dividende", "value": fmt_pct(dy, 1),
             "sub": f"DPA {fmt_num(f.get('dps'), 2)} MAD" if f.get("dps") is not None else "DPA non renseigné",
             "tone": "warn"},
            {"label": "P/E", "value": _ratio_value("per", per),
             "sub": "résultat net de l'exercice" if per is not None else "états financiers requis",
             "tone": "flat"},
        ],
        min_width=160,
    )

    st.divider()
    left, right = st.columns(2, gap="medium")
    with left:
        ui.section("Ce que l'on sait", "Données disponibles et leur date.")
        known = [
            f"Cours de clôture : **{fmt_num(price, 2)} MAD**.",
            f"Capitalisation : **{fmt_money(cap, 'MAD', compact=True)}**.",
            f"Performance 12 mois : **{fmt_pct(_num(row, 'return_12m'), 1, signed=True)}**.",
            f"Volatilité annualisée : **{fmt_pct(_num(row, 'volatility'), 1)}**.",
            f"Rendement du dividende : **{fmt_pct(dy, 1)}**."
            + (f" (DPA {fmt_num(f.get('dps'), 2)} MAD, {f.get('dps_year') or 'année non renseignée'})."
               if f.get("dps") is not None else "."),
        ]
        if records:
            known.append(
                f"États financiers : **exercice {latest.get('fiscal_year')}**, "
                f"{_perimeter(latest)}, source AMMC."
            )
        st.markdown("\n".join(f"- {line}" for line in known))

    with right:
        ui.section("Ce qui manque", "Les limites à connaître avant d'aller plus loin.")
        missing = []
        if not records:
            missing.append("Aucun bilan, CPC ou trésorerie vérifié : les ratios fondamentaux sont indisponibles.")
        if not records:
            missing.append("Pas de P/E, P/B, ROE ni marge nette calculables.")
        if f.get("dps") is None:
            missing.append("Dividende par action non renseigné : le rendement est indisponible.")
        if not thesis_mod.list_for(symbol):
            missing.append("Aucune thèse de valorisation enregistrée : aucun prix cible n'est affiché.")
        if not missing:
            missing.append("Les données disponibles couvrent le dernier exercice ; les suivants restent à importer.")
        st.markdown("\n".join(f"- {line}" for line in missing))

    st.divider()
    _price_chart(symbol, row)

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("🧾 Voir les comptes", use_container_width=True,
                     key=f"parcours_stmt_{symbol}"):
            _goto("statements_page", symbol)
    with c2:
        if st.button("🧮 Valorisation", use_container_width=True,
                     key=f"parcours_val_{symbol}"):
            _set_step(STEP_LABELS[2])
    with c3:
        if st.button("📰 Actualités", use_container_width=True,
                     key=f"parcours_news_{symbol}"):
            _goto("news_page", symbol)
    with c4:
        if st.button("🏢 Fiche société", use_container_width=True,
                     key=f"parcours_company_{symbol}"):
            _goto("company", symbol)


def _price_chart(symbol: str, row: pd.Series) -> None:
    ui.section("Cours sur 12 mois", "Historique réel de la Bourse de Casablanca ; aucune projection.")
    hist = shared.stock_history(symbol, days=400)
    if hist is None or hist.empty or "close" not in hist.columns:
        ui.note(
            "Historique de cours indisponible pour cette valeur : le graphique ne peut pas "
            "être tracé. Le cours et la variation restent affichés dans la synthèse.",
            "warn", "📉",
        )
        return
    dates = pd.to_datetime(hist["date"], errors="coerce") if "date" in hist.columns else hist.index
    close = pd.to_numeric(hist["close"], errors="coerce")
    frame = pd.DataFrame({"date": dates, "close": close}).dropna()
    if frame.empty:
        ui.note("Historique vide après nettoyage : aucun graphique n'est inventé.", "warn", "📉")
        return
    fig = go.Figure(
        go.Scatter(
            x=frame["date"], y=frame["close"], mode="lines",
            line=dict(color=COLORS["accent"], width=2),
            fill="tozeroy", fillcolor="rgba(28,169,159,.08)",
            name="Cours",
        )
    )
    for key, label in (("high_52w", "Plus haut 52 semaines"), ("low_52w", "Plus bas 52 semaines")):
        value = _num(row, key)
        if value is not None:
            fig.add_hline(
                y=value, line_dash="dot", line_color=COLORS["muted"],
                annotation_text=label, annotation_font_color=COLORS["muted"],
            )
    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=20, b=10),
        yaxis_title="MAD", xaxis_title="", showlegend=False,
    )
    ui.plot(fig, key=f"parcours_price_{symbol}")
    st.caption(
        f"Dernière clôture : {shared.last_market_date()}. La volatilité et la performance "
        "passées ne préjugent pas des résultats futurs."
    )


# ═══════════════════════════ Étape 2 — Fondamentaux ═══════════════════════════

def _step_fundamentals(symbol: str, row: pd.Series, records: List[Dict[str, Any]],
                       latest: Optional[Dict[str, Any]], f: Dict[str, Any],
                       ratios: Dict[str, Optional[float]], sector: str,
                       table: pd.DataFrame) -> None:
    if not records:
        _no_statements_panel(symbol, row, f, ratios, sector, table)
        return

    income = latest.get("income") or {}
    balance = latest.get("balance") or {}
    cashflow = latest.get("cashflow") or {}
    financial = fundamentals.is_financial_sector(sector)
    revenue_label = "Produit net bancaire" if financial else "Chiffre d'affaires"
    ui.section(
        "Comptes de l'exercice",
        f"Exercice {latest.get('fiscal_year')} · {_perimeter(latest)} · "
        "montants en MAD, sans retraitement.",
    )
    ui.kpi_grid(
        [
            {"label": revenue_label, "value": fmt_money(income.get("revenue"), "MAD", compact=True),
             "sub": f"exercice {latest.get('fiscal_year')}", "tone": "blue"},
            {"label": "Résultat net", "value": fmt_money(income.get("net_income"), "MAD", compact=True),
             "sub": "part du groupe" if latest.get("consolidated") else "comptes sociaux",
             "tone": "up"},
            {"label": "Capitaux propres", "value": fmt_money(balance.get("equity"), "MAD", compact=True),
             "sub": "actif net comptable", "tone": "accent"},
            {"label": "Free cash-flow", "value": fmt_money(cashflow.get("free_cash_flow"), "MAD", compact=True),
             "sub": "flux opérationnel − capex", "tone": "info"},
            {"label": "ROE", "value": _ratio_value("roe", ratios.get("roe")),
             "sub": "résultat net / fonds propres", "tone": "flat"},
            {"label": "P/E", "value": _ratio_value("per", ratios.get("per")),
             "sub": "capitalisation / résultat net", "tone": "flat"},
        ],
        min_width=160,
    )

    st.divider()
    _trend_chart(symbol, records, sector)

    st.divider()
    _ratio_table(ratios, sector, table, keys=[m["key"] for m in RATIO_META])

    st.divider()
    _statement_evidence(latest)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("📊 Ouvrir le bilan, le CPC et la trésorerie",
                     use_container_width=True, key=f"parcours_detail_{symbol}"):
            _goto("statements_page", symbol)
    with c2:
        if st.button("🏢 Voir la fiche société", use_container_width=True,
                     key=f"parcours_company_fund_{symbol}"):
            _goto("company", symbol)


def _no_statements_panel(symbol: str, row: pd.Series, f: Dict[str, Any],
                         ratios: Dict[str, Optional[float]], sector: str,
                         table: pd.DataFrame) -> None:
    ui.section(
        "Couverture financière absente",
        "La page reste utile : voici ce qui est réellement disponible, et ce qui ne l'est pas.",
    )
    ui.note(
        f"**Aucun bilan, CPC ou tableau de trésorerie vérifié pour {symbol}.** "
        "Les ratios fondamentaux ne sont pas calculés de force : ils restent indisponibles "
        "tant que les états AMMC ne sont pas importés et validés.",
        "warn", "📄",
    )
    price = _num(row, "close") or as_float(f.get("price"))
    cap = _num(row, "cap") or as_float(f.get("market_cap"))
    dy = ratios.get("dividend_yield")
    sparkline = _num(row, "return_12m")
    ui.kpi_grid(
        [
            {"label": "Cours", "value": f"{fmt_num(price, 2)} MAD", "sub": "dernière clôture", "tone": "blue"},
            {"label": "Capitalisation", "value": fmt_money(cap, "MAD", compact=True),
             "sub": "cours × titres", "tone": "accent"},
            {"label": "Rendement du dividende", "value": fmt_pct(dy, 1),
             "sub": "DPA BVC / cours" if dy is not None else "DPA non renseigné", "tone": "warn"},
            {"label": "Performance 12 mois", "value": fmt_pct(sparkline, 1, signed=True),
             "sub": "historique BVC", "tone": "up" if (sparkline or 0) >= 0 else "warn"},
            {"label": "Volatilité annualisée", "value": fmt_pct(_num(row, "volatility"), 1),
             "sub": "rendements quotidiens", "tone": "info"},
            {"label": "Plus haut / plus bas 52 s.", "value": _range_52w(row),
             "sub": "fourchette observée", "tone": "flat"},
        ],
        min_width=160,
    )

    st.divider()
    left, right = st.columns(2, gap="medium")
    with left:
        ui.section("Calculable dès maintenant", "Métriques de marché et dividende.")
        st.markdown(
            "\n".join([
                f"- Cours, capitalisation et volume : sources BVC.",
                f"- Performance et volatilité sur l'historique réel.",
                f"- Rendement du dividende : {fmt_pct(dy, 1)}"
                + (f" (DPA {fmt_num(f.get('dps'), 2)} MAD)." if f.get("dps") is not None else "."),
                f"- Comparaison de ces métriques avec le secteur « {sector} ».",
            ])
        )
    with right:
        ui.section("Non calculable sans états", "Aucune estimation n'est substituée aux comptes.")
        st.markdown(
            "\n".join([
                "- P/E : nécessite le résultat net.",
                "- P/B et ROE : nécessitent les fonds propres.",
                "- Marge nette : nécessite le chiffre d'affaires et le résultat net.",
                "- FCF et rendement du FCF : nécessitent la trésorerie et les capex.",
                "- EV/EBITDA : nécessite l'EBITDA et la dette nette.",
            ])
        )

    dy_median, dy_count = _sector_median(table, sector, "dividend_yield")
    if dy is not None and dy_median is not None and dy_count > 1:
        gap = _gap(dy, dy_median)
        ui.note(
            f"**Contexte sectoriel** : rendement du dividende de {fmt_pct(dy, 1)} pour "
            f"{symbol}, contre une médiane de {fmt_pct(dy_median, 1)} sur {dy_count} "
            f"société(s) du secteur « {sector} » ({fmt_pct(gap, 1, signed=True)} d'écart). "
            "Cette comparaison ne remplace pas une analyse des comptes.",
            "info", "🏭",
        )
    elif dy is not None:
        ui.note(
            f"**Rendement du dividende : {fmt_pct(dy, 1)}.** Aucune médiane sectorielle "
            "comparable n'est disponible (moins de deux sociétés avec dividende et cours "
            "dans ce secteur) : aucune comparaison n'est inventée.",
            "info", "🏭",
        )
    else:
        ui.note(
            "Le rendement du dividende et sa médiane sectorielle ne sont pas disponibles : "
            "aucune comparaison n'est inventée.",
            "info", "🏭",
        )

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🏛️ Importer les états AMMC", use_container_width=True,
                     key=f"parcours_import_{symbol}"):
            _goto("statements_page", symbol)
    with c2:
        if st.button("🏭 Comparer le secteur", use_container_width=True,
                     key=f"parcours_sector_{symbol}"):
            _goto("sector_page", symbol)
    with c3:
        if st.button("🏢 Fiche société", use_container_width=True,
                     key=f"parcours_company_nostmt_{symbol}"):
            _goto("company", symbol)


def _trend_chart(symbol: str, records: List[Dict[str, Any]], sector: str) -> None:
    rows = []
    for record in sorted(records, key=lambda r: int(r.get("fiscal_year") or 0)):
        income = record.get("income") or {}
        balance = record.get("balance") or {}
        rows.append({
            "Exercice": record.get("fiscal_year"),
            "Chiffre d'affaires": as_float(income.get("revenue")),
            "Résultat net": as_float(income.get("net_income")),
            "Fonds propres": as_float(balance.get("equity")),
        })
    frame = pd.DataFrame(rows).dropna(subset=["Exercice"])
    if frame.empty or frame[["Chiffre d'affaires", "Résultat net"]].notna().sum().sum() == 0:
        ui.note(
            "Aucun historique chiffré exploitable : le graphique de tendance ne peut pas "
            "être tracé. Les agrégats de l'exercice restent affichés ci-dessus.",
            "warn", "📈",
        )
        return
    financial = fundamentals.is_financial_sector(sector)
    revenue_label = "Produit net bancaire" if financial else "Chiffre d'affaires"
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=frame["Exercice"], y=frame["Chiffre d'affaires"],
            name=revenue_label, marker_color=COLORS["primary"],
            text=[fmt_money(v, "MAD", compact=True) for v in frame["Chiffre d'affaires"]],
            textposition="outside",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["Exercice"], y=frame["Résultat net"],
            name="Résultat net", mode="lines+markers",
            line=dict(color=COLORS["accent"], width=3),
            marker=dict(size=8),
        ),
        secondary_y=True,
    )
    fig.update_yaxes(title_text="MAD (histogramme)", secondary_y=False)
    fig.update_yaxes(title_text="Résultat net (MAD)", secondary_y=True)
    fig.update_layout(
        height=380, margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(dtick=1),
    )
    ui.plot(fig, key=f"parcours_trend_{symbol}")
    st.caption(
        "Montants issus des états vérifiés, sans lissage ni estimation. "
        "Les exercices affichés sont ceux réellement importés."
    )


def _ratio_table(ratios: Dict[str, Optional[float]], sector: str,
                 table: pd.DataFrame, keys: List[str]) -> None:
    ui.section(
        "Ratios et comparaison sectorielle",
        "Chaque ratio est calculé à partir des comptes de l'exercice ; la médiane "
        "sectorielle n'utilise que les sociétés où le ratio est disponible.",
    )
    financial = fundamentals.is_financial_sector(sector)
    main_rows: List[Dict[str, Any]] = []
    detail_rows: List[Dict[str, Any]] = []
    for key in keys:
        meta = next((item for item in RATIO_META if item["key"] == key), None)
        if not meta:
            continue
        if financial and key in {"ev_ebitda", "debt_to_equity", "current_ratio", "interest_coverage"}:
            status = "non applicable (banque / assurance)"
            main_rows.append({
                "Ratio": meta["label"], "Valeur": "—", "Médiane": "non applicable",
                "N": "—", "Écart": "—",
            })
            detail_rows.append({"Ratio": meta["label"], "Formule": meta["formula"], "Statut": status})
            continue
        value = as_float(ratios.get(key))
        median, count = _sector_median(table, sector, key)
        comparable = median is not None and count > 1
        gap = _gap(value, median) if comparable else None
        if value is None:
            status = "non disponible"
        elif comparable:
            status = "disponible"
        else:
            status = "disponible · référence unique"
        main_rows.append({
            "Ratio": meta["label"],
            "Valeur": _ratio_value(key, value),
            "Médiane": _ratio_value(key, median) if comparable else "—",
            "N": str(count) if count else "0",
            "Écart": fmt_pct(gap, 1, signed=True) if gap is not None else "—",
        })
        detail_rows.append({"Ratio": meta["label"], "Formule": meta["formula"], "Statut": status})
    columns = {
        "Ratio": st.column_config.TextColumn("Ratio", width="medium"),
        "Valeur": st.column_config.TextColumn("Valeur", width="small"),
        "Médiane": st.column_config.TextColumn("Médiane", width="medium"),
        "N": st.column_config.TextColumn("N", width="small"),
        "Écart": st.column_config.TextColumn("Écart", width="small"),
    }
    ui.table(
        pd.DataFrame(main_rows), columns=columns,
        height=min(520, 36 * len(main_rows) + 42),
        key=f"parcours_ratios_{sector}",
    )
    with st.expander("Formules et statut de chaque ratio", expanded=False):
        for item in detail_rows:
            st.markdown(
                f"- **{item['Ratio']}** — {item['Formule']}  \n"
                f"  *{item['Statut']}*"
            )
    st.caption(
        "L'écart est relatif à la médiane du secteur : positif = au-dessus, négatif = en dessous. "
        "Il ne constitue ni une recommandation ni un jugement de valeur. Une médiane n'est "
        "affichée que si au moins deux sociétés du secteur disposent du ratio ; sinon la "
        "référence est dite unique. Le rendement du dividende et le taux de distribution "
        "utilisent le dernier DPA connu du référentiel BVC, dont l'exercice peut être "
        "postérieur à l'exercice comptable. "
        "« non applicable » signale un ratio non pertinent pour le modèle bancaire."
    )


def _statement_evidence(record: Dict[str, Any]) -> None:
    ui.section("Source et périmètre", "Ce que l'on peut vérifier dans le document d'origine.")
    rows = [
        {"Élément": "Source", "Valeur": record.get("source") or "—"},
        {"Élément": "Exercice", "Valeur": record.get("fiscal_year") or "—"},
        {"Élément": "Périmètre", "Valeur": _perimeter(record)},
        {"Élément": "Devise / unité", "Valeur": f"{record.get('currency') or 'MAD'} · {record.get('unit') or 'MAD'}"},
        {"Élément": "Statut", "Valeur": record.get("status") or "—"},
        {"Élément": "Document", "Valeur": record.get("source_url") or "—"},
    ]
    ui.table(pd.DataFrame(rows), height=260, key="parcours_statement_evidence")


# ═══════════════════════════ Étape 3 — Valorisation ═══════════════════════════

def _step_valuation(symbol: str, row: pd.Series, records: List[Dict[str, Any]],
                    latest: Optional[Dict[str, Any]], f: Dict[str, Any],
                    ratios: Dict[str, Optional[float]], sector: str,
                    table: pd.DataFrame) -> None:
    available = [key for key in VALUATION_KEYS if as_float(ratios.get(key)) is not None]
    if not available:
        ui.section(
            "Valorisation relative",
            "Aucun multiple de valorisation n'est calculable pour cette valeur.",
        )
        if not records:
            ui.note(
                f"**P/E, P/B et EV/EBITDA sont indisponibles pour {symbol}.** Le rendement du "
                "dividende peut rester calculable, mais il ne suffit pas à valoriser une société. "
                "Aucun prix cible n'est fabriqué.",
                "warn", "🧮",
            )
            _no_statements_panel(symbol, row, f, ratios, sector, table)
        else:
            ui.note(
                f"**Les comptes de {symbol} sont présents, mais aucun multiple n'est "
                "calculable.** Causes possibles : résultat net négatif ou nul, fonds propres "
                "négatifs, capitalisation ou nombre de titres indisponible, ou données "
                "incompatibles. Les montants restent consultables dans l'étape "
                "« Fondamentaux » ; aucun ratio n'est forcé.",
                "warn", "🧮",
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🧾 Vérifier les comptes", use_container_width=True,
                             key=f"parcours_val_stmt_{symbol}"):
                    _goto("statements_page", symbol)
            with c2:
                if st.button("🏢 Voir la fiche société", use_container_width=True,
                             key=f"parcours_val_company_{symbol}"):
                    _goto("company", symbol)
        return

    ui.section(
        "Multiples de valorisation",
        "Comparaison avec la médiane du secteur, à périmètre et exercice identifiés.",
    )
    _ratio_table(ratios, sector, table, keys=list(VALUATION_KEYS) + ["payout", "fcf_yield"])

    st.divider()
    _multiples_chart(symbol, ratios, sector, table)

    st.divider()
    ui.section("Ce que ces multiples ne disent pas", "Les limites à garder en tête.")
    limitations = [
        "Le cours est une donnée de marché datée ; les comptes sont ceux du dernier exercice publié.",
        f"Périmètre : {_perimeter(latest)}. Un multiple calculé sur des comptes sociaux n'est pas comparable à un multiple consolidé.",
        "Capitaux propres et résultat net retenus : part du groupe lorsqu'il existe des intérêts minoritaires. Les totaux incluant les minoritaires ne servent pas au ROE ni au P/B.",
        "Un résultat net exceptionnellement faible ou négatif gonfle le P/E ou le rend ininterprétable.",
        "Le P/B dépend du modèle comptable et de la qualité des actifs ; il est peu comparable entre banques et industrielles.",
        "La médiane sectorielle ne compte que les sociétés où le ratio est disponible : le nombre est indiqué.",
    ]
    payout = as_float(ratios.get("payout"))
    if payout is not None and payout > 1:
        limitations.append(
            "Le taux de distribution dépasse 100 % : le dividende versé n'est pas couvert par "
            "le résultat net de l'exercice. Vérifiez s'il provient de réserves ou d'un élément non récurrent."
        )
    st.markdown("\n".join(f"- {line}" for line in limitations))

    st.divider()
    theses = thesis_mod.list_for(symbol)
    if theses:
        evaluated = thesis_mod.evaluate(theses[0], _num(row, "close"), f)
        ui.section("Thèse enregistrée", "Hypothèses saisies par l'utilisateur, jamais par l'application.")
        ui.kpi_grid(
            [
                {"label": "Méthode", "value": str(evaluated.get("method_label") or "—"),
                 "sub": "thèse utilisateur", "tone": "info"},
                {"label": "Prix théorique", "value": f"{fmt_num(evaluated.get('target_price'), 2)} MAD",
                 "sub": "selon vos hypothèses", "tone": "accent"},
                {"label": "Prix d'entrée", "value": f"{fmt_num(evaluated.get('entry_price'), 2)} MAD",
                 "sub": "seuil que vous avez fixé", "tone": "flat"},
                {"label": "Statut", "value": str(evaluated.get("status_label") or "—"),
                 "sub": "recalculé au cours actuel", "tone": "up"},
            ],
            min_width=160,
        )
        if st.button("🔔 Ouvrir les alertes et la thèse", use_container_width=True,
                     key=f"parcours_thesis_{symbol}"):
            _goto("alerts_page", symbol)
    else:
        ui.note(
            "**Aucune thèse de valorisation enregistrée.** L'application ne fournit pas de "
            "prix cible par défaut : ouvrez le Valuation Lab pour saisir vos hypothèses "
            "(méthode, taux, croissance) et obtenir un prix théorique traçable.",
            "info", "🧮",
        )
        if st.button("🧮 Ouvrir le Valuation Lab", use_container_width=True,
                     key=f"parcours_valuation_lab_{symbol}"):
            _goto("valuation", symbol)


def _multiples_chart(symbol: str, ratios: Dict[str, Optional[float]],
                     sector: str, table: pd.DataFrame) -> None:
    keys = [key for key in ("per", "pb", "dividend_yield") if as_float(ratios.get(key)) is not None]
    if not keys:
        return
    labels, gaps = [], []
    for key in keys:
        meta = next(item for item in RATIO_META if item["key"] == key)
        median, count = _sector_median(table, sector, key)
        if median is None or count <= 1:
            continue
        gap = _gap(as_float(ratios.get(key)), median)
        if gap is None:
            continue
        labels.append(meta["label"])
        gaps.append(gap * 100.0)
    if not labels:
        ui.note(
            "Aucune médiane sectorielle comparable n'est disponible (moins de deux sociétés "
            "du secteur avec le ratio) : le graphique de comparaison n'est pas affiché. "
            "Le tableau ci-dessus reste la référence, avec la mention « référence unique ».",
            "info", "🏭",
        )
        return
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=gaps, y=labels, orientation="h",
        marker_color=COLORS["accent"],
        text=[fmt_pct(value / 100.0, 1, signed=True) for value in gaps],
        textposition="outside",
        hovertemplate="%{y} : %{x:+.1f} %<extra></extra>",
    ))
    fig.update_layout(
        height=300, margin=dict(l=10, r=30, t=20, b=10),
        xaxis_title="Écart à la médiane du secteur (%)",
        yaxis=dict(autorange="reversed"),
        showlegend=False,
    )
    fig.add_vline(x=0, line_width=1, line_color=COLORS["muted"])
    ui.plot(fig, key=f"parcours_multiples_{symbol}")
    st.caption(
        f"Secteur « {sector} ». Écart relatif à la médiane, en pourcentage : positif = "
        "au-dessus de la médiane, négatif = en dessous. Pour un multiple, être au-dessus "
        "ne signifie pas automatiquement « cher » : la croissance, le risque et la qualité "
        "des bénéfices doivent être lus en parallèle."
    )


# ═══════════════════════════ Étape 4 — Risques & actualités ═══════════════════════════

def _step_risk(symbol: str, row: pd.Series, records: List[Dict[str, Any]],
               latest: Optional[Dict[str, Any]], f: Dict[str, Any],
               ratios: Dict[str, Optional[float]], sector: str,
               table: pd.DataFrame) -> None:
    ui.section(
        "Risque de marché",
        "Mesures calculées sur l'historique réel de la valeur ; elles ne préjugent pas du futur.",
    )
    ui.kpi_grid(
        [
            {"label": "Volatilité annualisée", "value": fmt_pct(_num(row, "volatility"), 1),
             "sub": "écart-type × √252", "tone": "info"},
            {"label": "Drawdown maximal", "value": fmt_pct(_num(row, "max_drawdown"), 1, signed=True),
             "sub": "plus forte baisse observée", "tone": "warn"},
            {"label": "Bêta vs MASI", "value": fmt_num(_num(row, "beta"), 2),
             "sub": "sensibilité au marché", "tone": "flat"},
            {"label": "Performance 12 mois", "value": fmt_pct(_num(row, "return_12m"), 1, signed=True),
             "sub": "historique BVC", "tone": "up" if (_num(row, "return_12m") or 0) >= 0 else "warn"},
            {"label": "Plus haut / plus bas 52 s.", "value": _range_52w(row),
             "sub": "fourchette observée", "tone": "blue"},
            {"label": "Volume", "value": fmt_num(_num(row, "volume"), 0),
             "sub": "dernière séance", "tone": "accent"},
        ],
        min_width=160,
    )

    st.divider()
    _performance_chart(symbol, row)

    st.divider()
    _drawdown_chart(symbol)

    st.divider()
    left, right = st.columns(2, gap="medium")
    with left:
        _news_block(symbol, row)
    with right:
        _alerts_block(symbol, row)
        st.divider()
        _portfolio_block(symbol)

    st.divider()
    _evidence_table(symbol, row, latest, f)


def _performance_chart(symbol: str, row: pd.Series) -> None:
    ui.section("Performance par période", "Variations réelles, sans extrapolation.")
    periods = [
        ("1 mois", "return_1m"),
        ("3 mois", "return_3m"),
        ("6 mois", "return_6m"),
        ("12 mois", "return_12m"),
        ("Depuis janvier", "ytd_pct"),
    ]
    labels, values = [], []
    for label, key in periods:
        value = _num(row, key)
        if value is not None:
            labels.append(label)
            values.append(value)
    if not labels:
        ui.note("Performances indisponibles pour cette valeur.", "warn", "📉")
        return
    colors = [COLORS["up"] if value >= 0 else COLORS["down"] for value in values]
    fig = go.Figure(
        go.Bar(
            x=labels, y=values, marker_color=colors,
            text=[fmt_pct(value, 1, signed=True) for value in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=20, b=10),
        yaxis_tickformat=".0%", showlegend=False,
    )
    ui.plot(fig, key=f"parcours_perf_{symbol}")


def _drawdown_chart(symbol: str) -> None:
    ui.section("Drawdown", "Baisse depuis le plus haut précédent, sur l'historique disponible.")
    hist = shared.stock_history(symbol, days=400)
    if hist is None or hist.empty or "close" not in hist.columns:
        ui.note("Historique indisponible : le drawdown ne peut pas être calculé.", "warn", "📉")
        return
    dates = pd.to_datetime(hist["date"], errors="coerce") if "date" in hist.columns else hist.index
    close = pd.to_numeric(hist["close"], errors="coerce")
    frame = pd.DataFrame({"date": dates, "close": close}).dropna()
    if frame.empty:
        ui.note("Historique vide après nettoyage : aucun drawdown n'est inventé.", "warn", "📉")
        return
    running_max = frame["close"].cummax()
    frame["drawdown"] = frame["close"] / running_max - 1.0
    fig = go.Figure(
        go.Scatter(
            x=frame["date"], y=frame["drawdown"], mode="lines",
            line=dict(color=COLORS["down"], width=1.5),
            fill="tozeroy", fillcolor="rgba(220,80,80,.12)",
            name="Drawdown",
        )
    )
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=20, b=10),
        yaxis_tickformat=".0%", showlegend=False,
    )
    ui.plot(fig, key=f"parcours_drawdown_{symbol}")


def _news_block(symbol: str, row: pd.Series) -> None:
    ui.section("Actualités liées", "Flux RSS publics ; une absence n'est pas un signal neutre.")
    try:
        news_df = shared.market_news()
    except Exception:
        news_df = pd.DataFrame()
    if news_df is None or news_df.empty:
        ui.note(
            "Aucun flux d'actualités disponible pour le moment. L'absence d'article ne signifie "
            "pas que la société n'a pas d'actualité : le flux peut être incomplet ou indisponible.",
            "warn", "📰",
        )
        return
    name = str(row.get("name") or "")
    tokens = [symbol]
    if name:
        tokens.append(name)
        first = name.split()[0]
        if len(first) >= 4:
            tokens.append(first)
    blob = news_df.astype(str).agg(" ".join, axis=1)
    mask = pd.Series(False, index=news_df.index)
    for token in tokens:
        mask = mask | blob.str.contains(token, case=False, na=False)
    sub = news_df[mask].head(6)
    if sub.empty:
        ui.note(
            f"Aucune actualité de {symbol} dans le flux courant. Le flux couvre l'actualité "
            "générale et peut ne pas indexer toutes les publications de la société.",
            "info", "📰",
        )
        return
    for _, item in sub.iterrows():
        title = str(item.get("title") or item.get("Title") or "Sans titre")
        source = str(item.get("source") or item.get("Source") or "source non renseignée")
        date = str(item.get("date") or item.get("published") or item.get("Date") or "date non renseignée")
        link = str(item.get("link") or item.get("url") or "")
        st.markdown(f"**{escape(title)}**")
        if link:
            st.caption(f"{escape(source)} · {escape(date)} · [lire l'article]({link})")
        else:
            st.caption(f"{escape(source)} · {escape(date)}")
    st.caption(
        "Les titres sont affichés en texte brut, sans HTML. Ils ne sont pas résumés par "
        "l'application et ne constituent pas une recommandation."
    )


def _alerts_block(symbol: str, row: pd.Series) -> None:
    ui.section("Alertes techniques", "Règles calculées sur le cours et les volumes.")
    try:
        summary = shared.technical_summary(symbol)
        alerts = alerts_mod.evaluate_row(row.to_dict(), summary)
    except Exception:
        alerts = []
    if not alerts:
        ui.note(
            "Aucune alerte technique déclenchée. Cela ne signifie pas que le titre est sans risque.",
            "info", "🔔",
        )
        return
    rows = [
        {"Alerte": alert.title, "Gravité": alert.severity,
         "Détail": alert.detail[:160]}
        for alert in alerts
    ]
    ui.table(pd.DataFrame(rows), height=min(360, 40 * (len(rows) + 1)),
             key=f"parcours_alerts_{symbol}")
    st.caption("Les seuils sont ceux de l'application ; ils sont modifiables dans la page Alertes.")


def _portfolio_block(symbol: str) -> None:
    ui.section("Exposition au portefeuille", "Position simulée, pas un ordre.")
    holdings = shared.enriched_holdings()
    if holdings is None or holdings.empty or "symbol" not in holdings.columns:
        ui.note("Aucune position enregistrée dans le portefeuille simulé.", "info", "💼")
        return
    line = holdings[holdings["symbol"].astype(str) == symbol]
    if line.empty:
        ui.note(f"{symbol} n'est pas détenu dans le portefeuille simulé.", "info", "💼")
        return
    weight = as_float(line.iloc[0].get("weight"))
    value = as_float(line.iloc[0].get("value"))
    if value is None:
        value = as_float(line.iloc[0].get("market_value"))
    ui.kpi_grid(
        [
            {"label": "Poids", "value": fmt_pct(weight, 1), "sub": "part du portefeuille", "tone": "info"},
            {"label": "Valeur", "value": fmt_money(value, "MAD", compact=True),
             "sub": "au cours actuel", "tone": "accent"},
        ],
        min_width=160,
    )


def _evidence_table(symbol: str, row: pd.Series,
                    latest: Optional[Dict[str, Any]], f: Dict[str, Any]) -> None:
    ui.section("Dossier de preuve", "Sources, dates et statuts de la valeur active.")
    rows = [
        {"Élément": "Cours et capitalisation", "Source": "Bourse de Casablanca (API publique)",
         "Date / exercice": shared.last_market_date(), "Statut": "différé"},
        {"Élément": "États financiers",
         "Source": (latest.get("source") if latest else "aucun") or "—",
         "Date / exercice": (f"exercice {latest.get('fiscal_year')}" if latest else "non couvert"),
         "Statut": (latest.get("status") if latest else "non couvert") or "—"},
        {"Élément": "Source fondamentale", "Source": str(f.get("_source") or "non renseignée"),
         "Date / exercice": (f"exercice {latest.get('fiscal_year')}" if latest else "—"),
         "Statut": "mixte" if f.get("manual_fields") else "documentée"},
        {"Élément": "Champs saisis par l'utilisateur",
         "Source": ", ".join(f.get("manual_fields") or []) or "aucun",
         "Date / exercice": "hors document vérifié" if f.get("manual_fields") else "—",
         "Statut": "à vérifier" if f.get("manual_fields") else "—"},
        {"Élément": "Dividende par action", "Source": "Bourse de Casablanca (référentiel)",
         "Date / exercice": f"DPA {f.get('dps_year') or '—'}", "Statut": "annuel"},
        {"Élément": "Indicateurs techniques", "Source": "Calcul sur l'historique BVC",
         "Date / exercice": shared.last_market_date(), "Statut": "calculé"},
        {"Élément": "Actualités", "Source": "Flux RSS publics",
         "Date / exercice": "date de publication", "Statut": "cache 15 min"},
    ]
    ui.table(pd.DataFrame(rows), height=260, key=f"parcours_evidence_{symbol}")
