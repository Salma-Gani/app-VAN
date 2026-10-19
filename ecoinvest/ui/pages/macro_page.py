"""Analyse macroéconomique : Maroc, contexte de marché et limites explicites.

Les séries sont **annuelles et différées** (World Bank Open Data). Elles ne
remplacent ni les publications trimestrielles du HCP ni les décisions de Bank
Al-Maghrib, qui ne sont pas connectées. Aucune valeur n'est inventée : une
donnée absente est affichée comme telle.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...config import COLORS
from ...data import macro
from ...utils.formatting import fmt_num, fmt_pct
from .. import components as ui
from . import shared


def render() -> None:
    data = macro.morocco_indicators()
    indicators = data.get("indicators") or {}
    years = sorted({str(v.get("year")) for v in indicators.values() if v.get("year")})

    ui.hero(
        "Analyse macroéconomique",
        "Croissance, inflation et chômage au Maroc, avec leur année de référence. "
        "Ces séries annuelles servent de contexte : elles ne datent pas la séance boursière.",
        badge=ui.badge(
            f"World Bank · {', '.join(years)}" if years else "World Bank · donnée indisponible",
            "info",
        ),
    )

    ui.source_note(
        ["World Bank Open Data (séries annuelles)"],
        as_of=f"dernière observation publiée : {', '.join(years)}" if years else "aucune observation disponible",
        detail=(
            "Données publiques différées, mises à jour par la Banque mondiale. "
            "Bank Al-Maghrib (taux directeur) et le HCP (trimestriel) ne sont pas connectés : "
            "leur absence est signalée, jamais comblée par une estimation."
        ),
    )

    _kpis(indicators)
    st.divider()
    _reading(indicators)
    st.divider()
    _sector_market()
    st.divider()
    _limits(data)
    ui.disclaimer()


def _kpis(indicators: Dict[str, Any]) -> None:
    items: List[Dict[str, Any]] = []
    for key, label in (
        ("gdp_growth", "Croissance du PIB"),
        ("inflation", "Inflation (IPC)"),
        ("unemployment", "Taux de chômage"),
    ):
        item = indicators.get(key) or {}
        value = item.get("value")
        year = item.get("year") or "—"
        available = value is not None
        items.append({
            "label": label,
            "value": f"{value:.2f} %" if available else "Non disponible",
            "sub": f"Année {year} · World Bank" if available else (item.get("error") or "série non publiée"),
            "tone": "info" if available else "warn",
        })
    items.append({
        "label": "Statut de la donnée",
        "value": "Annuelle",
        "sub": "différée, non temps réel",
        "tone": "blue",
    })
    ui.kpi_row(items, per_row=4)


def _reading(indicators: Dict[str, Any]) -> None:
    """Lecture factuelle, déterministe, sans prévision ni recommandation."""
    ui.section(
        "Lecture factuelle",
        "Chaque phrase ne reprend que les valeurs publiées ci-dessus ; aucune extrapolation.",
    )
    lines: List[str] = []
    gdp = indicators.get("gdp_growth") or {}
    if gdp.get("value") is not None:
        lines.append(
            f"La croissance du PIB ressort à **{gdp['value']:.2f} %** pour l'année "
            f"**{gdp.get('year')}** (World Bank)."
        )
    inflation = indicators.get("inflation") or {}
    if inflation.get("value") is not None:
        lines.append(
            f"L'inflation mesurée par l'IPC atteint **{inflation['value']:.2f} %** "
            f"pour **{inflation.get('year')}**."
        )
    unemployment = indicators.get("unemployment") or {}
    if unemployment.get("value") is not None:
        lines.append(
            f"Le taux de chômage publié est de **{unemployment['value']:.2f} %** "
            f"pour **{unemployment.get('year')}**."
        )
    if not lines:
        ui.empty_state(
            "Aucune série macro n'a pu être chargée. Vérifiez la connexion à l'API "
            "World Bank ; aucune valeur de remplacement n'est affichée.",
            "🌍",
        )
        return

    st.markdown("\n\n".join(f"- {line}" for line in lines))
    st.caption(
        "Ces constats décrivent des observations passées. Ils ne constituent ni une prévision "
        "de croissance, ni une recommandation d'investissement. La date de séance du marché "
        "est indiquée séparément sur la vue globale."
    )


def _sector_market() -> None:
    """Contexte de marché : performance YTD des indices sectoriels BVC (passé, pas prévision)."""
    ui.section(
        "Contexte de marché — indices sectoriels BVC",
        "Performance depuis le 1er janvier, calculée par la Bourse de Casablanca. "
        "Une performance passée n'implique pas une surperformance future.",
    )
    try:
        indices = shared.sector_indices()
    except Exception:
        indices = pd.DataFrame()
    if indices is None or indices.empty or "ytd_pct" not in indices.columns:
        ui.empty_state("Indices sectoriels indisponibles pour le moment.", "📊")
        return

    frame = indices.copy()
    frame["ytd_pct"] = pd.to_numeric(frame["ytd_pct"], errors="coerce")
    frame = frame.dropna(subset=["ytd_pct"]).sort_values("ytd_pct")
    if frame.empty:
        ui.empty_state("Aucune variation sectorielle publiée.", "📊")
        return

    fig = go.Figure(
        go.Bar(
            x=frame["ytd_pct"] * 100,
            y=frame["name"],
            orientation="h",
            marker_color=[COLORS["up"] if v >= 0 else COLORS["down"] for v in frame["ytd_pct"]],
            hovertemplate="<b>%{y}</b><br>YTD %{x:+.2f} %<extra></extra>",
        )
    )
    fig.update_layout(
        height=max(360, 26 * len(frame)),
        xaxis_title="Variation YTD (%)",
        margin=dict(l=10, r=20, t=10, b=30),
        showlegend=False,
    )
    ui.plot(fig, key="macro_sectors")

    table = frame[["name", "value", "change_pct", "ytd_pct"]].copy()
    table.columns = ["Indice", "Niveau", "Séance", "YTD"]
    table["Séance"] = table["Séance"].map(lambda v: fmt_pct(v, 2, signed=True))
    table["YTD"] = table["YTD"].map(lambda v: fmt_pct(v, 2, signed=True))
    table["Niveau"] = table["Niveau"].map(lambda v: fmt_num(v, 2))
    ui.table(table, height=320, key="macro_sector_table")


def _limits(data: Dict[str, Any]) -> None:
    ui.section("Ce que cette page ne dit pas", "Limites explicites de couverture.")
    st.markdown(
        "- **Pas de taux directeur Bank Al-Maghrib** : le connecteur BAM n'est pas configuré.\n"
        "- **Pas de séries trimestrielles HCP** : seules les séries annuelles World Bank sont chargées.\n"
        "- **Pas de prévision macro** : aucune projection n'est produite ni présentée comme certaine.\n"
        "- **Pas de données Bloomberg / LSEG-Reuters / Investing.com** : ces sources nécessitent une "
        "licence ou ne proposent pas d'API publique ; aucun scraping n'est effectué.\n"
        "- **Décalage temporel** : une observation annuelle peut précéder de plusieurs mois la séance "
        "boursière affichée sur la vue globale."
    )
    errors = data.get("errors") or []
    if errors:
        st.warning("Certaines séries n'ont pas pu être chargées :\n\n" + "\n".join(f"- {e}" for e in errors))
