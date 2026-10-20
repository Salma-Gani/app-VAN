"""Comparaison sectorielle : entreprises d'un même secteur, métriques vérifiables.

La page distingue systématiquement :

- les **métriques de marché** (disponibles pour toutes les valeurs) ;
- les **ratios fondamentaux** (uniquement si les états financiers sont renseignés) ;
- les **métriques non applicables** aux banques et assurances (EV/EBITDA, levier).

Aucune valeur absente n'est remplacée par zéro. Chaque médiane indique le nombre
de sociétés réellement utilisées.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...analytics import sector_compare
from ...config import COLORS
from ...utils.formatting import fmt_money, fmt_multiple, fmt_num, fmt_pct
from .. import components as ui
from . import shared

MARKET_KEYS = ("cap", "close", "return_12m", "volatility", "max_drawdown", "r_dividend_yield")
FUNDAMENTAL_KEYS = ("r_per", "r_pb", "r_ev_ebitda", "r_roe", "r_net_margin",
                    "r_debt_to_equity", "r_revenue_growth")

# Libellé affiché → (colonne de la synthèse, clé de métrique pour le formatage).
OVERVIEW_METRICS = {
    "Performance 12 mois médiane": ("Perf. 12 mois médiane", "return_12m"),
    "P/E médian": ("P/E médian", "r_per"),
    "ROE médian": ("ROE médian", "r_roe"),
    "Volatilité médiane": ("Volatilité médiane", "volatility"),
}


def _fmt_value(key: str, value: Any) -> str:
    metric = sector_compare.METRIC_BY_KEY.get(key, {})
    unit = metric.get("unit")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "—"
    if numeric != numeric:
        return "—"
    if unit == "MAD":
        return fmt_money(numeric, "MAD", compact=True)
    if unit == "%":
        return fmt_pct(numeric, 1)
    if unit == "x":
        return fmt_multiple(numeric, 1)
    return fmt_num(numeric, 2)


def _median_sub(medians: Dict[str, Dict[str, Any]], key: str) -> str:
    info = medians.get(key, {})
    if not info.get("applicable", True):
        return "non applicable"
    if info.get("value") is None:
        return "non disponible"
    return f"{info.get('count', 0)} valeur(s)"


def render() -> None:
    table = shared.market_table()
    if table is None or table.empty:
        ui.empty_state(
            "Aucune donnée de marché disponible : la comparaison sectorielle ne peut pas être "
            "calculée. Vérifiez la connexion à la Bourse de Casablanca puis rechargez la page.",
            "🏭",
        )
        return

    sectors = sorted(str(s) for s in table["sector"].dropna().unique() if str(s).strip())
    ui.hero(
        "Comparaison sectorielle",
        "Comparez les sociétés d'un même secteur sur des métriques de marché et des ratios "
        "fondamentaux tracés. Les banques et assurances ne sont pas mélangées aux industrielles.",
        badge=ui.badge(f"{len(sectors)} secteurs · {len(table)} valeurs", "info"),
    )
    ui.source_note(
        ["Bourse de Casablanca (cours, capitalisation, volumes)",
         "États financiers vérifiés (AMMC / import validé) et référentiel BVC"],
        detail="Les métriques de marché sont calculées pour toutes les valeurs. Les ratios "
               "fondamentaux proviennent des états vérifiés lorsqu'ils existent, sinon du "
               "référentiel BVC ou d'une saisie utilisateur. Chaque fiche indique l'exercice "
               "et la source lorsqu'ils sont connus. Une donnée absente reste « — », jamais zéro.",
    )

    default_index = _default_sector_index(table, sectors)
    overview = sector_compare.sector_overview(table)
    counts_by_sector = dict(zip(overview["Secteur"], overview["Valeurs"])) if not overview.empty else {}
    ratios_by_sector = (
        dict(zip(overview["Secteur"], overview["Valeurs avec ratios"])) if not overview.empty else {}
    )

    def _sector_label(sector: str) -> str:
        count = int(counts_by_sector.get(sector, 0))
        ratios = int(ratios_by_sector.get(sector, 0))
        return f"{sector} — {count} valeur(s) · {ratios} avec ratios"

    chosen = st.selectbox(
        "Secteur à comparer", sectors, index=default_index, format_func=_sector_label,
        key="sector_compare_choice",
    )
    frame, metadata = sector_compare.comparison_frame(table, chosen)
    if frame.empty:
        ui.empty_state(
            f"Le secteur « {chosen} » ne contient aucune valeur exploitable dans le snapshot "
            "de marché. Choisissez un autre secteur ou actualisez les données.",
            "🏭",
        )
        return

    medians = sector_compare.sector_medians(frame, chosen)
    coverage = sector_compare.coverage_summary(frame)
    _kpis(chosen, frame, medians, coverage)

    for note in sector_compare.comparability_notes(metadata, chosen):
        ui.note(note, "warn", "⚠️")

    tabs = st.tabs([
        "📊 Tableau comparatif", "🎯 Risque / rendement",
        "🗂️ Tous les secteurs", "🧮 Méthode & sources",
    ])
    with tabs[0]:
        _comparison_tab(frame, medians, metadata, chosen)
    with tabs[1]:
        _risk_return_tab(frame, chosen)
    with tabs[2]:
        _overview_tab(table, chosen, overview)
    with tabs[3]:
        _method_tab(chosen)

    ui.disclaimer()


def _default_sector_index(table: pd.DataFrame, sectors: List[str]) -> int:
    counts = table["sector"].astype(str).value_counts()
    if counts.empty:
        return 0
    leader = str(counts.index[0])
    return sectors.index(leader) if leader in sectors else 0


def _kpis(chosen: str, frame: pd.DataFrame, medians: Dict[str, Dict[str, Any]],
          coverage: Dict[str, int]) -> None:
    ui.kpi_grid(
        [
            {"label": "Sociétés", "value": fmt_num(len(frame), 0),
             "sub": f"{coverage['with_statement']} états vérifiés · "
                    f"{coverage['with_ratios']} avec ratios", "tone": "blue"},
            {"label": "Cap. médiane",
             "value": _fmt_value("cap", medians["cap"]["value"]),
             "sub": _median_sub(medians, "cap"), "tone": "accent"},
            {"label": "P/E médian", "value": _fmt_value("r_per", medians["r_per"]["value"]),
             "sub": _median_sub(medians, "r_per"), "tone": "flat"},
            {"label": "ROE médian", "value": _fmt_value("r_roe", medians["r_roe"]["value"]),
             "sub": _median_sub(medians, "r_roe"), "tone": "up"},
            {"label": "Rendement médian",
             "value": _fmt_value("r_dividend_yield", medians["r_dividend_yield"]["value"]),
             "sub": _median_sub(medians, "r_dividend_yield"), "tone": "warn"},
        ],
        min_width=170,
    )


# ═══════════════════════════ Tableau comparatif ═══════════════════════════


def _comparison_tab(frame: pd.DataFrame, medians: Dict[str, Dict[str, Any]],
                    metadata: Dict[str, Dict[str, Any]], sector: str) -> None:
    ui.section(
        "Marché", "Cours, taille, performance et risque — disponibles pour toutes les valeurs.",
    )
    market_keys = [k for k in MARKET_KEYS if medians.get(k, {}).get("applicable", True)]
    ui.table(_display_frame(frame, medians, market_keys), height=min(420, 44 * (len(frame) + 2)),
             key=f"sector_market_{sector}")
    _coverage_caption(medians, market_keys)

    ui.section(
        "Fondamentaux",
        "Ratios calculés uniquement à partir d'états financiers renseignés et compatibles.",
    )
    fundamental_keys = [k for k in FUNDAMENTAL_KEYS if medians.get(k, {}).get("applicable", True)]
    available = sum(1 for key in fundamental_keys if medians[key]["count"] > 0)
    if fundamental_keys and available:
        ui.table(
            _display_frame(frame, medians, fundamental_keys),
            height=min(420, 44 * (len(frame) + 2)),
            key=f"sector_fundamentals_{sector}",
        )
        _coverage_caption(medians, fundamental_keys)
    elif fundamental_keys:
        ui.empty_state(
            "Aucun ratio fondamental calculable pour ce secteur : aucun état financier vérifié "
            "n'est enregistré pour ses sociétés. Sélectionnez un secteur dont le libellé indique "
            "des ratios disponibles, ou importez les états dans « États financiers ».",
            "📄",
        )
    else:
        ui.note(
            "Aucun ratio fondamental applicable : les multiples d'entreprise sont exclus pour "
            "les banques et assurances.",
            "warn", "ℹ️",
        )

    st.divider()
    _company_detail(frame, medians, metadata, sector)


def _display_frame(frame: pd.DataFrame, medians: Dict[str, Dict[str, Any]],
                   keys: List[str]) -> pd.DataFrame:
    applicable = [k for k in keys if medians.get(k, {}).get("applicable", True)]
    labels = [sector_compare.METRIC_BY_KEY[k]["label"] for k in applicable]
    rows: List[Dict[str, Any]] = []
    for _, row in frame.iterrows():
        item: Dict[str, Any] = {"Symbole": row["symbol"], "Société": row["name"]}
        for key in applicable:
            item[sector_compare.METRIC_BY_KEY[key]["label"]] = _fmt_value(key, row.get(key))
        rows.append(item)
    median_row: Dict[str, Any] = {"Symbole": "—", "Société": "Médiane du secteur"}
    for key in applicable:
        median_row[sector_compare.METRIC_BY_KEY[key]["label"]] = _fmt_value(
            key, medians[key]["value"]
        )
    rows.append(median_row)
    return pd.DataFrame(rows, columns=["Symbole", "Société"] + labels)


def _coverage_caption(medians: Dict[str, Dict[str, Any]], keys: List[str]) -> None:
    parts = []
    for key in keys:
        info = medians.get(key, {})
        if info.get("applicable", True):
            parts.append(f"{sector_compare.METRIC_BY_KEY[key]['label']} : "
                         f"{info.get('count', 0)}/{info.get('total', 0)}")
    if parts:
        st.caption("Valeurs réellement utilisées pour la médiane — " + " · ".join(parts) + ".")


def _company_detail(frame: pd.DataFrame, medians: Dict[str, Dict[str, Any]],
                    metadata: Dict[str, Dict[str, Any]], sector: str) -> None:
    ui.section(
        "Détail d'une société",
        "Valeur, rang dans le secteur et formule de chaque indicateur.",
    )
    names = dict(zip(frame["symbol"], frame["name"]))
    symbols = frame["symbol"].tolist()
    choice = st.selectbox(
        "Société", symbols,
        format_func=lambda symbol: f"{symbol} — {names.get(symbol, symbol)}",
        key=f"sector_company_{sector}",
    )
    row = frame[frame["symbol"] == choice].iloc[0]
    meta = metadata.get(choice, {})
    financial = sector_compare.is_financial_sector(sector)

    detail_rows: List[Dict[str, Any]] = []
    for metric in sector_compare.SECTOR_METRICS:
        key = metric["key"]
        value = row.get(key)
        available = pd.notna(value)
        excluded = financial and metric["financial_excluded"]
        rank = None
        if available and metric["better"] and not excluded:
            rank = sector_compare.rank_position(value, frame[key], metric["better"])
        status = "non applicable" if excluded else ("disponible" if available else "non disponible")
        detail_rows.append({
            "Indicateur": metric["label"],
            "Valeur": _fmt_value(key, value) if not excluded else "—",
            "Rang /100": f"{rank:.0f}" if rank is not None else "—",
            "Type": metric["kind"],
            "Formule": metric["formula"],
            "Statut": status,
        })
    ui.table(pd.DataFrame(detail_rows), height=min(520, 40 * (len(detail_rows) + 1)),
             key=f"sector_detail_{sector}")

    if meta.get("has_statement"):
        consolidated = meta.get("consolidated")
        if consolidated is True:
            perimeter = "comptes consolidés"
        elif consolidated is False:
            perimeter = "comptes sociaux"
        else:
            perimeter = "périmètre non renseigné"
        st.caption(
            f"Exercice **{meta.get('fiscal_year')}** · {perimeter} · "
            f"source : {meta.get('source') or 'non renseignée'}."
        )
    elif bool(row.get("has_fundamentals", False)):
        ui.note(
            "Des données fondamentales sont disponibles pour cette société, mais aucun état "
            "financier vérifié n'est enregistré : elles proviennent du référentiel BVC ou d'une "
            "saisie utilisateur, et ne sont pas rattachées à un document source. Importez ses "
            "états dans « États financiers » pour les consolider.",
            "warn", "📄",
        )
    else:
        ui.note(
            "Aucun état financier vérifié pour cette société : seules les métriques de marché "
            "sont disponibles. Importez ses états dans « États financiers » pour activer les ratios.",
            "warn", "📄",
        )


# ═══════════════════════════ Risque / rendement ═══════════════════════════


def _risk_return_tab(frame: pd.DataFrame, sector: str) -> None:
    ui.section(
        "Risque et performance",
        "Volatilité annualisée et performance sur 12 mois. La taille reflète la capitalisation ; "
        "la couleur distingue les sociétés avec états financiers.",
    )
    sub = frame.dropna(subset=["volatility", "return_12m"]).copy()
    if len(sub) < 2:
        ui.note(
            "Historique insuffisant pour au moins deux valeurs du secteur : le nuage risque/rendement "
            "ne peut pas être tracé. Aucune valeur n'est simulée.",
            "warn", "📉",
        )
        return

    caps = pd.to_numeric(sub["cap"], errors="coerce")
    base = caps.median()
    sizes = np.sqrt(caps.fillna(base if base == base and base > 0 else 1e9) /
                    max((caps.max() if caps.max() == caps.max() and caps.max() > 0 else 1e9), 1)) * 42 + 8
    colors = [
        COLORS["primary"] if (bool(has_statement) or bool(has_fundamentals)) else COLORS["muted"]
        for has_statement, has_fundamentals in zip(
            sub.get("has_statement", pd.Series([False] * len(sub))),
            sub.get("has_fundamentals", pd.Series([False] * len(sub))),
        )
    ]
    fig = go.Figure(
        go.Scatter(
            x=sub["volatility"], y=sub["return_12m"], mode="markers+text",
            text=sub["symbol"], textposition="top center",
            textfont=dict(size=9, color=COLORS["muted"]),
            marker=dict(size=sizes, color=colors, line=dict(color="rgba(11,37,69,.18)", width=1),
                        opacity=0.9),
            customdata=np.stack([sub["name"], sub["cap"]], axis=-1),
            hovertemplate=(
                "<b>%{text}</b> — %{customdata[0]}<br>"
                "Volatilité : %{x:.1%}<br>Performance 12 mois : %{y:.1%}<br>"
                "Capitalisation : %{customdata[1]:,.0f} MAD<extra></extra>"
            ),
        )
    )
    median_vol = float(sub["volatility"].median())
    fig.add_vline(x=median_vol, line_dash="dot", line_color=COLORS["muted"],
                  annotation_text="Volatilité médiane", annotation_font_color=COLORS["muted"])
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(141,162,192,.5)")
    fig.update_layout(
        height=480, xaxis_title="Volatilité annualisée", yaxis_title="Performance 12 mois",
        xaxis_tickformat=".0%", yaxis_tickformat=".0%", showlegend=False,
        margin=dict(l=10, r=10, t=20, b=10),
    )
    ui.plot(fig, key=f"sector_risk_return_{sector}")
    st.caption(
        "Bleu : société disposant de données fondamentales (états vérifiés ou référentiel BVC). "
        "Gris : métriques de marché uniquement. La volatilité et la performance passées ne "
        "préjugent pas des résultats futurs."
    )


# ═══════════════════════════ Tous les secteurs ═══════════════════════════


def _overview_tab(table: pd.DataFrame, chosen: str, overview: pd.DataFrame) -> None:
    ui.section(
        "Vue d'ensemble des secteurs",
        "Médianes par secteur, calculées uniquement sur les valeurs disponibles.",
    )
    if overview is None or overview.empty:
        ui.note("Aucun secteur exploitable dans le snapshot de marché.", "warn", "🏭")
        return

    display = overview.copy()
    display["Capitalisation médiane"] = display["Capitalisation médiane"].apply(
        lambda value: fmt_money(value, "MAD", compact=True) if pd.notna(value) else "—"
    )
    for column in ("Perf. 12 mois médiane", "Volatilité médiane", "Rendement du dividende médian",
                   "ROE médian"):
        display[column] = display[column].apply(
            lambda value: fmt_pct(value, 1) if pd.notna(value) else "—"
        )
    display["P/E médian"] = display["P/E médian"].apply(
        lambda value: fmt_multiple(value, 1) if pd.notna(value) else "—"
    )
    st.caption(f"Secteur sélectionné ci-dessus : **{chosen}**.")
    ui.table(display, height=min(560, 40 * (len(display) + 1)), key="sector_overview")

    choices = OVERVIEW_METRICS
    label = st.selectbox("Indicateur à comparer entre secteurs", list(choices), key="sector_bar_metric")
    column, metric_key = choices[label]
    data = overview.dropna(subset=[column]).sort_values(column, ascending=True)
    if data.empty:
        ui.note(
            "Aucune donnée disponible pour cet indicateur : les secteurs concernés n'ont pas "
            "d'états financiers renseignés. Choisissez un indicateur de marché ou importez des états.",
            "warn", "📊",
        )
        return
    colors = [COLORS["accent"] if sector == chosen else COLORS["primary"] for sector in data["Secteur"]]
    fig = go.Figure(
        go.Bar(
            x=data[column], y=data["Secteur"], orientation="h", marker_color=colors,
            text=[_fmt_value(metric_key, value) for value in data[column]],
            textposition="outside",
        )
    )
    fig.update_layout(
        height=min(900, max(420, 90 + 30 * len(data))),
        xaxis_title=label,
        yaxis=dict(tickfont=dict(size=10)),
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_tickformat=".0%" if metric_key != "r_per" else None,
    )
    ui.plot(fig, key="sector_overview_bars")
    st.caption(
        "Le secteur sélectionné est mis en évidence. Une médiane n'est calculée que si au moins "
        "une valeur est disponible ; les secteurs sans donnée sont absents du graphique."
    )


# ═══════════════════════════ Méthode ═══════════════════════════


def _method_tab(sector: str) -> None:
    ui.section("Formules et conventions", "Chaque indicateur est reproductible à partir des données affichées.")
    rows = [
        {
            "Indicateur": metric["label"],
            "Type": metric["kind"],
            "Unité": metric["unit"],
            "Formule": metric["formula"],
            "Banques / assurances": "non applicable" if metric["financial_excluded"] else "applicable",
        }
        for metric in sector_compare.SECTOR_METRICS
    ]
    ui.table(pd.DataFrame(rows), height=560, key="sector_methods")

    ui.note(
        "**Médianes** : moyenne des deux valeurs centrales lorsque l'effectif est pair, calculée "
        "uniquement sur les valeurs non nulles et non manquantes. Le nombre de valeurs utilisées "
        "est affiché sous chaque tableau.\n\n"
        "**Aucun zéro de remplissage** : une donnée absente reste « — ». Un PER ou un EV/EBITDA "
        "négatif n'est pas affiché (il n'a pas de sens économique).\n\n"
        "**Comparabilité** : les exercices et les périmètres (social / consolidé) peuvent différer "
        "d'une société à l'autre ; un avertissement le signale. Les banques et assurances sont "
        "comparées entre elles, sans EV/EBITDA ni levier dette/fonds propres.\n\n"
        "**Performance et volatilité** sont calculées sur l'historique réel du titre ; elles ne "
        "constituent pas une prévision.",
        "info", "🧮",
    )

    financial = sector_compare.is_financial_sector(sector)
    if financial:
        ui.note(
            f"Le secteur « {sector} » est un secteur financier : les multiples d'entreprise et le "
            "levier ne sont pas affichés. Le P/E, le P/B, le ROE, la marge nette et le rendement "
            "restent comparables.",
            "warn", "🏦",
        )
