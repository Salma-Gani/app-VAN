"""Screener sectoriel de toutes les valeurs cotées à la Bourse de Casablanca."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd
import streamlit as st

from ...analytics import scoring
from ...config import COLORS, SECTOR_RISK
from ...data import bvc
from ...utils.formatting import fmt_money, fmt_num, fmt_pct
from .. import charts, components as ui
from . import shared


def render() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Impossible de charger les données de marché. Vérifiez la connexion.", "📡")
        return

    ui.hero(
        "Screener BVC",
        f"{len(table)} valeurs cotées à la Bourse de Casablanca · filtrage par secteur, "
        "score, valorisation, risque et liquidité.",
        badge=ui.badge(f"{table['sector'].nunique()} secteurs", "info"),
    )

    filtered, params = _filters(table)
    _summary(filtered, table)
    st.divider()
    _results(filtered, params)


# ═══════════════════════════ Filtres ═══════════════════════════


def _filters(table: pd.DataFrame) -> tuple:
    sectors = sorted([s for s in table["sector"].dropna().unique() if s != "Autres"])
    if "Autres" in set(table["sector"]):
        sectors.append("Autres")

    with st.expander("🎛️ Filtres de sélection", expanded=True):
        row1 = st.columns([2, 1.4, 1.4, 1.6])
        with row1[0]:
            chosen_sectors = st.multiselect(
                "Secteurs", sectors, default=[],
                placeholder="Tous les secteurs",
                help="Filtre les valeurs par secteur officiel de la Bourse de Casablanca.",
            )
        with row1[1]:
            signals = st.multiselect(
                "Signaux", ["🟢 Achat fort", "🟢 Achat", "🔵 Consolider", "🟡 Attendre",
                            "🟠 Alléger", "🔴 Éviter"],
                default=[], placeholder="Tous les signaux",
            )
        with row1[2]:
            sort_by = st.selectbox(
                "Trier par",
                ["Score composite", "Performance séance", "Performance 1 an", "Capitalisation",
                 "Volume", "Rendement du dividende", "P/E croissant", "Volatilité croissante",
                 "Ratio de Sharpe"],
            )
        with row1[3]:
            search = st.text_input("Recherche", placeholder="Symbole ou nom de société…")

        row2 = st.columns([2, 1.2, 1.2, 1.2])
        with row2[0]:
            cap_range = st.slider(
                "Capitalisation (MAD)",
                min_value=0.0,
                max_value=float(max(table["cap"].max() or 1e9, 1e9)),
                value=(0.0, float(max(table["cap"].max() or 1e9, 1e9))),
                step=1e9,
                format="%.0f",
            )
        with row2[1]:
            score_range = st.slider("Score composite", 0, 100, (0, 100), step=5)
        with row2[2]:
            max_per = st.number_input("P/E maximum", min_value=0.0, value=0.0, step=1.0,
                                      help="0 = pas de filtre. Ne retient que les valeurs dont le P/E est renseigné.")
        with row2[3]:
            min_div = st.number_input("Rendement minimum (%)", min_value=0.0, value=0.0, step=0.5,
                                      help="0 = pas de filtre.")

        row3 = st.columns([1.2, 1.2, 1.2, 1.6])
        with row3[0]:
            min_vol = st.number_input("Volume minimum (MAD)", min_value=0.0, value=0.0, step=100000.0,
                                      format="%.0f")
        with row3[1]:
            min_sharpe = st.number_input("Sharpe minimum", value=0.0, step=0.1)
        with row3[2]:
            max_volat = st.number_input("Volatilité maximum (%)", min_value=0.0, value=0.0, step=5.0,
                                        help="0 = pas de filtre. Ex. 30 pour ne garder que les valeurs dont la volatilité annualisée est sous 30 %.")
        with row3[3]:
            only_funda = st.checkbox(
                "Uniquement les valeurs avec fondamentaux renseignés",
                value=False,
                help="Masque les sociétés dont aucun ratio comptable n'a encore été saisi.",
            )

    filtered = scoring.filter_market(
        table,
        sectors=chosen_sectors or None,
        signal_filter=signals or None,
        min_cap=cap_range[0] or None,
        max_cap=cap_range[1] if cap_range[1] < float(max(table["cap"].max() or 1e9, 1e9)) else None,
        min_score=score_range[0] or None,
        max_score=score_range[1] if score_range[1] < 100 else None,
        min_volume=min_vol or None,
        max_per=max_per or None,
        min_dividend=(min_div / 100.0) if min_div else None,
        min_sharpe=min_sharpe if min_sharpe != 0 else None,
        max_volatility=(max_volat / 100.0) if max_volat else None,
        only_with_fundamentals=only_funda,
        search=search,
    )
    filtered = _sort(filtered, sort_by)
    params: Dict[str, Any] = {
        "sort_by": sort_by, "sectors": chosen_sectors, "signals": signals,
        "only_fundamentals": only_funda,
    }
    return filtered, params


def _sort(df: pd.DataFrame, how: str) -> pd.DataFrame:
    mapping = {
        "Score composite": ("composite_score", False),
        "Performance séance": ("change_pct", False),
        "Performance 1 an": ("return_12m", False),
        "Capitalisation": ("cap", False),
        "Volume": ("volume", False),
        "Rendement du dividende": ("r_dividend_yield", False),
        "P/E croissant": ("r_per", True),
        "Volatilité croissante": ("volatility", True),
        "Ratio de Sharpe": ("sharpe", False),
    }
    col, asc = mapping.get(how, ("composite_score", False))
    if col not in df.columns:
        return df
    return df.sort_values(col, ascending=asc, na_position="last").reset_index(drop=True)


# ═══════════════════════════ Synthèse ═══════════════════════════


def _summary(filtered: pd.DataFrame, full: pd.DataFrame) -> None:
    items = [
        {"label": "Valeurs retenues", "value": f"{len(filtered)}",
         "sub": f"sur {len(full)} cotées", "tone": "accent"},
        {"label": "Score composite moyen", "value": fmt_num(filtered["composite_score"].mean(), 0),
         "sub": "sur 100", "tone": "blue"},
        {"label": "Performance 1 an médiane",
         "value": fmt_pct(filtered["return_12m"].median(), 1, signed=True),
         "sub": "des valeurs filtrées", "tone": "accent" if (filtered["return_12m"].median() or 0) >= 0 else "danger"},
        {"label": "Capitalisation retenue",
         "value": fmt_money(filtered["cap"].sum(), "MAD", compact=True),
         "sub": "cumulée", "tone": "blue"},
        {"label": "Volume cumulé séance",
         "value": fmt_money(filtered["volume"].sum(), "MAD", compact=True),
         "sub": "liquidité du jour", "tone": "warn"},
    ]
    ui.kpi_row(items, per_row=5)

    with st.expander("📊 Synthèse par secteur", expanded=False):
        sec = scoring.sector_summary(filtered)
        if sec.empty:
            ui.empty_state("Aucun secteur dans la sélection.", "🗂️")
            return
        display = sec.rename(columns={
            "sector": "Secteur", "Valeurs": "Valeurs", "Perf. jour": "Perf. jour",
            "Perf. 1 an": "Perf. 1 an", "Perf. YTD": "Perf. YTD",
            "Score moyen": "Score moyen", "Volatilité moy.": "Volatilité",
            "Capitalisation": "Capitalisation", "Volume": "Volume",
        })
        for col in ("Perf. jour", "Perf. 1 an", "Perf. YTD", "Volatilité"):
            display[col] = display[col].apply(lambda v: fmt_pct(v, 1, signed=True))
        display["Score moyen"] = display["Score moyen"].apply(lambda v: fmt_num(v, 1))
        display["Capitalisation"] = display["Capitalisation"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        display["Volume"] = display["Volume"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        ui.table(display, height=min(460, 60 + 36 * len(display)), key="scr_sectors")
        ui.plot(charts.sector_bars(sec), key="scr_sector_bars", height=440)


# ═══════════════════════════ Résultats ═══════════════════════════


def _results(filtered: pd.DataFrame, params: Dict[str, Any]) -> None:
    ui.section("Résultats", "Cliquez sur une ligne pour ouvrir l'analyse détaillée de la valeur.")

    if filtered.empty:
        ui.empty_state("Aucune valeur ne correspond aux critères sélectionnés.", "🔍")
        return

    frame = filtered.copy()
    numeric = (
        "close", "change_pct", "return_12m", "ytd_pct", "cap", "volume", "composite_score",
        "rsi14", "volatility", "beta", "sharpe", "r_per", "r_dividend_yield",
    )
    for col in numeric:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    view = pd.DataFrame({
        "Symbole": frame["symbol"],
        "Société": frame["name"],
        "Secteur": frame["sector"],
        "Cours": frame["close"].round(2),
        "Séance %": (frame["change_pct"] * 100).round(2),
        "1 an %": (frame["return_12m"] * 100).round(1),
        "YTD %": (frame["ytd_pct"] * 100).round(1),
        "Capitalisation": frame["cap"],
        "Volume": frame["volume"],
        "Score": frame["composite_score"].round(0),
        "Tendance": frame["trend_state"],
        "Momentum": frame["momentum_state"],
        "RSI": frame["rsi14"].round(0),
        "Volatilité %": (frame["volatility"] * 100).round(1),
        "Bêta": frame["beta"].round(2),
        "Sharpe": frame["sharpe"].round(2),
        "P/E": frame["r_per"].round(1),
        "Rdt dividende %": (frame["r_dividend_yield"] * 100).round(2),
        "Signal": frame["signal"],
    })

    config = _column_config()
    try:
        event = st.dataframe(
            view, width="stretch", height=min(760, 60 + 35 * len(view)),
            column_config=config, hide_index=True, key="screener_table",
            on_select="rerun", selection_mode="single-row",
        )
        rows = event.selection.rows if hasattr(event, "selection") else []
    except TypeError:
        st.dataframe(view, use_container_width=True, hide_index=True)
        rows = []

    if rows:
        symbol = str(filtered.iloc[rows[0]]["symbol"])
        _goto_company(symbol)

    st.write("")
    col_a, col_b, col_c = st.columns([1.2, 1.2, 2])
    with col_a:
        if st.button("🔎 Analyser la meilleure opportunité", key="scr_best"):
            best = scoring.top_opportunities(filtered, n=1)
            if not best.empty:
                _goto_company(str(best.iloc[0]["symbol"]))
            else:
                st.warning("Aucune valeur avec un momentum positif dans la sélection.")
    with col_b:
        ui.download_row(view, "screener_bvc.csv", "⬇️ Exporter la sélection", key="scr_export")

    with st.expander("📈 Top opportunités du moteur", expanded=False):
        best = scoring.top_opportunities(filtered, n=12)
        if best.empty:
            ui.empty_state("Aucune valeur ne combine score élevé et momentum positif.", "🎯")
        else:
            disp = best.rename(columns={
                "symbol": "Symbole", "name": "Société", "sector": "Secteur", "close": "Cours",
                "change_pct": "Séance", "composite_score": "Score", "signal": "Signal",
                "momentum_score": "Momentum", "valuation_score": "Valorisation",
                "quality_score": "Qualité", "sharpe": "Sharpe",
            })
            for col in ("Séance",):
                disp[col] = disp[col].apply(lambda v: fmt_pct(v, 2, signed=True))
            for col in ("Momentum", "Valorisation", "Qualité"):
                disp[col] = disp[col].apply(lambda v: fmt_num(v, 2))
            disp["Score"] = disp["Score"].apply(lambda v: fmt_num(v, 0))
            disp["Sharpe"] = disp["Sharpe"].apply(lambda v: fmt_num(v, 2))
            ui.table(disp, height=min(480, 60 + 34 * len(disp)), key="scr_top")

        if not params["only_fundamentals"]:
            miss = int((filtered["data_completeness"].fillna(0) < 0.34).sum())
            if miss:
                ui.note(
                    f"{miss} valeur(s) de la sélection n'ont **aucune donnée fondamentale** renseignée : "
                    "leur score repose uniquement sur le marché et la technique. Complétez l'onglet "
                    "« Données fondamentales » pour affiner les signaux.",
                    "warn", "⚙️",
                )


def _column_config() -> Dict[str, Any]:
    try:
        return {
            "Cours": st.column_config.NumberColumn("Cours", format="%.2f MAD"),
            "Séance %": st.column_config.NumberColumn("Séance %", format="%+.2f %%"),
            "1 an %": st.column_config.NumberColumn("1 an %", format="%+.1f %%"),
            "YTD %": st.column_config.NumberColumn("YTD %", format="%+.1f %%"),
            "Capitalisation": st.column_config.NumberColumn("Capitalisation", format="%.0f"),
            "Volume": st.column_config.NumberColumn("Volume", format="%.0f"),
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            "RSI": st.column_config.NumberColumn("RSI", format="%.0f"),
            "Volatilité %": st.column_config.NumberColumn("Volatilité %", format="%.1f %%"),
            "Bêta": st.column_config.NumberColumn("Bêta", format="%.2f"),
            "Sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "P/E": st.column_config.NumberColumn("P/E", format="%.1f"),
            "Rdt dividende %": st.column_config.NumberColumn("Rdt dividende %", format="%.2f %%"),
        }
    except Exception:
        return {}


def _goto_company(symbol: str) -> None:
    st.session_state["selected_symbol"] = symbol
    st.session_state["_focus_company"] = True
    pages = st.session_state.get("_nav_pages") or {}
    target = pages.get("company")
    if target is not None:
        st.switch_page(target)
    else:
        st.success(f"Valeur sélectionnée : **{symbol}**. Ouvrez la page « Analyse société ».")
