"""Simulateur de patrimoine : projections, Monte-Carlo et comparaison des classes d'actifs."""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...analytics import forecast
from ...config import BROKERAGE_FEE, COLORS, INFLATION_RATE
from ...portfolio import optimize, simulate
from ...utils.formatting import fmt_money, fmt_num, fmt_pct
from .. import charts, components as ui
from . import shared


@st.cache_data(show_spinner=False, ttl=3600, max_entries=2)
def _frontier(n: int = 10000) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any], List[str]]:
    classes = optimize.asset_classes()
    codes = [c.code for c in classes]
    df = optimize.random_portfolios(classes, n=n)
    front = optimize.efficient_frontier(df)
    idx = df["sharpe"].idxmax()
    row = df.loc[idx]
    best = {
        "weights": {code: float(row[code]) for code in codes},
        "expected_return": float(row["return"]),
        "volatility": float(row["vol"]),
        "sharpe": float(row["sharpe"]),
    }
    return df, front, best, codes


def render() -> None:
    profile = shared.get_profile()
    ui.hero(
        "Simulateur d'investissement",
        "Projetez votre patrimoine, mesurez l'incertitude et comparez objectivement les classes "
        "d'actifs disponibles au Maroc et à l'international.",
        badge=ui.badge(profile.investor_type()["label"], "accent"),
    )

    ui.source_note(
        ["Hypothèses du moteur", "Statistiques BVC / Yahoo Finance"],
        detail="Rendements attendus, volatilité, inflation, fiscalité et frais sont des hypothèses "
               "explicites, pas des prévisions. Les rendements passés ne préjugent pas des rendements futurs.",
    )

    params = _inputs(profile)
    _headline(params)
    st.divider()
    _monte_carlo(params)
    st.divider()
    _comparison(params, profile)
    st.divider()
    _objective(params, profile)
    ui.disclaimer()


# ═══════════════════════════ Paramètres ═══════════════════════════


def _inputs(profile: Any) -> Dict[str, Any]:
    ui.section("Paramètres de simulation")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        initial = st.number_input("Capital initial (MAD)", min_value=0.0,
                                  value=float(max(profile.savings + profile.equities_value, 10_000.0)),
                                  step=5_000.0, format="%.0f")
    with c2:
        monthly = st.number_input("Versement mensuel (MAD)", min_value=0.0,
                                  value=float(profile.monthly_investment), step=250.0, format="%.0f")
    with c3:
        years = st.slider("Horizon (années)", 1, 30, int(min(max(profile.horizon_years, 1), 30)))
    with c4:
        target = st.number_input("Objectif de capital (MAD)", min_value=0.0,
                                 value=float(max(profile.target_capital, 100_000.0)),
                                 step=50_000.0, format="%.0f")

    c5, c6, c7 = st.columns(3)
    with c5:
        expected = st.slider("Rendement annuel attendu (%)", 0.0, 20.0,
                             float(round(profile.recommended_equity_share() * 0.09 * 100, 1)), 0.25) / 100.0
    with c6:
        volatility = st.slider("Volatilité annuelle (%)", 1.0, 45.0, 15.0, 0.5) / 100.0
    with c7:
        st.metric("Rendement réel attendu", fmt_pct((1 + expected) / (1 + INFLATION_RATE) - 1, 1))
        st.caption(f"Inflation retenue : {INFLATION_RATE:.1%} · fiscalité TPCVM 15 %")

    c8, c9 = st.columns(2)
    with c8:
        contribution_fee = st.slider(
            "Frais par versement (%)", 0.0, 3.0, float(round(BROKERAGE_FEE * 100, 2)), 0.05
        ) / 100.0
    with c9:
        annual_fee = st.slider("Frais annuels de gestion (%)", 0.0, 3.0, 0.0, 0.05) / 100.0

    return {
        "initial": initial, "monthly": monthly, "years": years,
        "target": target, "expected": expected, "volatility": volatility,
        "contribution_fee": contribution_fee, "annual_fee": annual_fee,
    }


# ═══════════════════════════ Projection déterministe ═══════════════════════════


def _headline(params: Dict[str, Any]) -> None:
    projection = forecast.projection_table(
        params["initial"], params["monthly"], params["expected"], params["years"],
        annual_fee=params["annual_fee"], contribution_fee=params["contribution_fee"],
    )
    final = projection.iloc[-1]
    invested = float(final["Versements cumulés"])
    value = float(final["Capital projeté"])
    gain = value - invested
    real = float(final["Valeur en dirhams constants"])

    ui.kpi_row(
        [
            {"label": "Capital projeté", "value": fmt_money(value, "MAD", compact=True),
             "sub": f"dans {params['years']} ans", "tone": "accent"},
            {"label": "Total versé", "value": fmt_money(invested, "MAD", compact=True),
             "sub": f"{fmt_money(params['monthly'], 'MAD', decimals=0)} / mois", "tone": "blue"},
            {"label": "Plus-value latente", "value": fmt_money(gain, "MAD", compact=True),
             "sub": fmt_pct((gain / invested) if invested else None, 1, signed=True),
             "tone": "up" if gain >= 0 else "down"},
            {"label": "Pouvoir d'achat constant", "value": fmt_money(real, "MAD", compact=True),
             "sub": f"après inflation ({INFLATION_RATE:.1%})", "tone": "warn"},
            {"label": "Écart à l'objectif", "value": fmt_money(value - params["target"], "MAD", compact=True),
             "sub": f"objectif {fmt_money(params['target'], 'MAD', compact=True)}",
             "tone": "up" if value >= params["target"] else "down"},
        ],
        per_row=5,
    )

    left, right = st.columns([1.5, 1], gap="medium")
    with left:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=projection["Année"], y=projection["Capital projeté"], name="Capital projeté",
                       mode="lines+markers", line=dict(color=COLORS["primary"], width=2.6),
                       fill="tozeroy", fillcolor="rgba(34,211,166,.08)")
        )
        fig.add_trace(
            go.Scatter(x=projection["Année"], y=projection["Versements cumulés"], name="Versements cumulés",
                       mode="lines", line=dict(color=COLORS["warning"], width=2, dash="dash"))
        )
        fig.add_trace(
            go.Scatter(x=projection["Année"], y=projection["Valeur en dirhams constants"],
                       name="Pouvoir d'achat", mode="lines",
                       line=dict(color=COLORS["accent"], width=1.8, dash="dot"))
        )
        fig.add_hline(y=params["target"], line_dash="dot", line_color=COLORS["accent2"],
                      annotation_text="Objectif", annotation_font_color=COLORS["accent2"])
        fig.update_layout(height=400, xaxis_title="Année", yaxis_title="Valeur (MAD)",
                          hovermode="x unified", margin=dict(l=10, r=10, t=20, b=10))
        ui.plot(fig, key="sim_projection")
    with right:
        ui.section("Détail annuel")
        display = projection.copy()
        display["Capital projeté"] = display["Capital projeté"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        display["Versements cumulés"] = display["Versements cumulés"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        display["Plus-value latente"] = display["Plus-value latente"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        display["Valeur en dirhams constants"] = display["Valeur en dirhams constants"].apply(
            lambda v: fmt_money(v, "MAD", compact=True)
        )
        display["Rendement cumulé"] = display["Rendement cumulé"].apply(lambda v: fmt_pct(v, 1, signed=True))
        ui.table(display, height=400, key="sim_projection_table")


# ═══════════════════════════ Monte-Carlo ═══════════════════════════


def _monte_carlo(params: Dict[str, Any]) -> None:
    ui.section(
        "Distribution des résultats",
        "2 000 trajectoires simulées : la médiane, la fourchette 10–90 % et le risque de perte. "
        "Frais par versement et frais annuels déduits.",
    )
    result = forecast.portfolio_fan_chart(
        params["initial"], params["monthly"], params["expected"], params["volatility"],
        years=params["years"], n_sims=2000,
        annual_fee=params["annual_fee"], contribution_fee=params["contribution_fee"],
    )
    ui.kpi_row(
        [
            {"label": "Médiane", "value": fmt_money(result["final_median"], "MAD", compact=True),
             "sub": f"sur {params['years']} ans", "tone": "accent"},
            {"label": "Scénario défavorable (10 %)", "value": fmt_money(result["final_p10"], "MAD", compact=True),
             "sub": "1 chance sur 10 de faire moins", "tone": "down"},
            {"label": "Scénario favorable (90 %)", "value": fmt_money(result["final_p90"], "MAD", compact=True),
             "sub": "1 chance sur 10 de faire mieux", "tone": "up"},
            {"label": "Total versé", "value": fmt_money(result["total_invested"], "MAD", compact=True),
             "sub": "capital + versements bruts", "tone": "blue"},
            {"label": "Probabilité de perte", "value": fmt_pct(result["prob_loss"], 1),
             "sub": "valeur finale < versements", "tone": "warn" if result["prob_loss"] < 0.3 else "down"},
        ],
        per_row=5,
    )
    prob_target = float((result["final"] >= params["target"]).mean()) if params["target"] else None
    benchmark_stats, benchmark_path = _benchmark_reference(params, result["months"])
    benchmark_label = (
        f"MASI historique ({benchmark_stats['cagr']:.1%}/an)"
        if benchmark_stats else "Référence"
    )
    fig = charts.fan_chart(result["months"], result["percentiles"], invested=result["invested"],
                           target=params["target"] if params["target"] else None, height=460,
                           benchmark=benchmark_path, benchmark_label=benchmark_label)
    ui.plot(fig, key="sim_fan")
    if benchmark_stats:
        ui.note(
            f"Référence MASI : **{benchmark_stats['cagr']:.2%} annualisé** sur "
            f"{benchmark_stats['years']:.1f} ans ({benchmark_stats['start']} → {benchmark_stats['end']}), "
            f"volatilité observée {benchmark_stats['volatility']:.1%}. La ligne pointillée applique ce rythme "
            "historique aux mêmes versements. Un historique n'est pas une prévision.",
            "info", "📈",
        )
    else:
        ui.note(
            "Historique MASI indisponible : aucune référence de marché n'est affichée "
            "(aucune performance n'est inventée).",
            "warn", "⚠️",
        )
    if prob_target is not None:
        ui.note(
            f"Probabilité d'atteindre l'objectif de {fmt_money(params['target'], 'MAD', compact=True)} : "
            f"**{prob_target:.0%}** sur {params['years']} ans, dans les hypothèses retenues.",
            "up" if prob_target >= 0.6 else "warn" if prob_target >= 0.3 else "down",
            "🎯",
        )


def _benchmark_reference(params: Dict[str, Any], months) -> tuple:
    """Trajectoire de référence fondée sur l'historique réel du MASI."""
    try:
        history = shared.index_history("MASI", period="5Y")
    except Exception as exc:
        st.caption(f"Historique MASI indisponible : {exc.__class__.__name__}.")
        return {}, None
    stats = forecast.annualized_stats(history)
    if not stats:
        return {}, None
    net_annual = (1 + stats["cagr"]) * (1 - params["annual_fee"]) - 1
    monthly_rate = (1 + net_annual) ** (1 / 12) - 1
    net_monthly = params["monthly"] * (1 - params["contribution_fee"])
    path = []
    for month in months:
        growth = (1 + monthly_rate) ** int(month)
        if abs(monthly_rate) > 1e-12:
            annuity = (growth - 1) / monthly_rate
        else:
            annuity = int(month)
        path.append(params["initial"] * growth + net_monthly * annuity)
    return stats, path


# ═══════════════════════════ Comparaison ═══════════════════════════


def _comparison(params: Dict[str, Any], profile: Any) -> None:
    ui.section(
        "Comparer les placements",
        f"Un montant de {fmt_money(params['initial'], 'MAD', compact=True)} placé sur "
        f"{params['years']} ans, classé selon votre profil.",
    )
    options = simulate.compare_investments(params["initial"], params["years"])
    if options.empty:
        ui.empty_state("Classes d'actifs indisponibles.", "📊")
        return
    ranked = simulate.rank_options(options, profile)

    display = ranked[[
        "Option", "Score profil", "Verdict", "Rendement brut", "Rendement net", "Rendement réel net",
        "Valeur nette finale", "Volatilité", "Ratio de Sharpe", "Liquidité", "Statistiques réelles",
    ]].copy()
    for col in ("Rendement brut", "Rendement net", "Rendement réel net", "Volatilité"):
        display[col] = display[col].apply(lambda v: fmt_pct(v, 2))
    display["Valeur nette finale"] = display["Valeur nette finale"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    display["Ratio de Sharpe"] = display["Ratio de Sharpe"].apply(lambda v: fmt_num(v, 2))
    display["Score profil"] = display["Score profil"].apply(lambda v: fmt_num(v, 0))
    display["Statistiques réelles"] = display["Statistiques réelles"].apply(lambda v: "✅" if v else "hypothèse")
    ui.table(display, height=min(480, 60 + 36 * len(display)), key="sim_options")

    best = ranked.iloc[0]
    second = ranked.iloc[1] if len(ranked) > 1 else None
    gap = (best["Valeur nette finale"] - second["Valeur nette finale"]) if second is not None else None
    ui.verdict(
        f"Meilleure option pour votre profil : {best['Option']}",
        f"Score d'adéquation **{best['Score profil']:.0f}/100** · rendement net estimé "
        f"**{fmt_pct(best['Rendement net'], 2)}** par an · valeur nette finale "
        f"**{fmt_money(best['Valeur nette finale'], 'MAD', compact=True)}**"
        + (f" · soit **{fmt_money(gap, 'MAD', compact=True)}** de plus que la deuxième option "
           f"({second['Option']})." if gap is not None else "."),
        best.get("_color") or COLORS["primary"],
    )

    left, right = st.columns([1, 1], gap="medium")
    with left:
        ui.plot(
            go.Figure(
                go.Bar(
                    x=ranked["Option"][::-1], y=ranked["Valeur nette finale"][::-1],
                    orientation="h", marker_color=COLORS["primary"], opacity=0.85,
                    text=[fmt_money(v, "MAD", compact=True) for v in ranked["Valeur nette finale"][::-1]],
                    textposition="outside",
                )
            ).update_layout(height=380, xaxis_title="Valeur nette finale (MAD)", showlegend=False,
                            margin=dict(l=10, r=60, t=10, b=10)),
            key="sim_options_bar",
        )
    with right:
        df, front, best_port, codes = _frontier()
        classes = optimize.asset_classes()
        current_weights = optimize.target_allocation(profile, classes)
        p_ret, p_vol, _ = optimize.portfolio_risk(current_weights, classes)
        ui.plot(
            charts.efficient_frontier_chart(
                df, front, best=best_port,
                current={"volatility": p_vol, "expected_return": p_ret}, height=380,
            ),
            key="sim_frontier",
        )

    ui.note(
        "Les statistiques « réelles » proviennent des séries historiques (MASI 5 ans, S&P 500 et or "
        "10 ans). Les autres classes reposent sur des hypothèses explicites. Aucun rendement futur "
        "n'est garanti.",
        "info", "📐",
    )


# ═══════════════════════════ Objectif ═══════════════════════════


def _objective(params: Dict[str, Any], profile: Any) -> None:
    ui.section("Atteindre mon objectif", "Effort d'épargne nécessaire selon le rendement retenu.")
    plan = simulate.objective_plan(profile, monthly=params["monthly"], years=params["years"])
    table = plan["table"]

    display = table.copy()
    display["Rendement annuel"] = display["Rendement annuel"].apply(lambda v: fmt_pct(v, 1))
    display["Capital projeté"] = display["Capital projeté"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    display["Objectif"] = display["Objectif"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    display["Écart"] = display["Écart"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    display["Atteint"] = display["Atteint"].apply(lambda v: "✅ Oui" if v else "❌ Non")
    display["Versement nécessaire"] = display["Versement nécessaire"].apply(
        lambda v: fmt_money(v, "MAD", decimals=0) if v is not None else "—"
    )
    ui.table(display, height=220, key="sim_objective")

    gap = forecast.goal_gap(
        params["target"], params["initial"] + profile.equities_value, params["monthly"],
        params["expected"], params["years"],
    )
    tone = "up" if gap["atteint"] else "down"
    ui.note(
        f"Avec **{fmt_money(params['monthly'], 'MAD', decimals=0)}/mois** et un rendement de "
        f"**{fmt_pct(params['expected'], 1)}**, le capital projeté atteint "
        f"**{fmt_money(gap['capital_projete'], 'MAD', compact=True)}** pour un objectif de "
        f"**{fmt_money(gap['objectif'], 'MAD', compact=True)}** "
        f"({'objectif atteint' if gap['atteint'] else 'objectif non atteint'})."
        + (
            f" Il faudrait verser **{fmt_money(gap['versement_necessaire'], 'MAD', decimals=0)}/mois** "
            f"(soit {fmt_money(gap['effort_supplementaire'], 'MAD', decimals=0)} de plus) pour l'atteindre."
            if gap.get("versement_necessaire") is not None and not gap["atteint"] else ""
        ),
        tone, "🎯" if gap["atteint"] else "⚠️",
    )

    income = forecast.income_projection(
        params["initial"], params["monthly"], params["expected"], params["years"],
        target_income=profile.target_monthly_income,
    )
    ui.kpi_row(
        [
            {"label": "Capital à l'horizon", "value": fmt_money(income["capital_final"], "MAD", compact=True),
             "sub": "projection déterministe", "tone": "accent"},
            {"label": "Rente mensuelle (4 %)", "value": fmt_money(income["revenu_mensuel"], "MAD", decimals=0),
             "sub": f"soit {fmt_money(income['revenu_annuel'], 'MAD', compact=True)} / an", "tone": "blue"},
            {"label": "Revenu visé", "value": fmt_money(profile.target_monthly_income, "MAD", decimals=0),
             "sub": "objectif déclaré", "tone": "warn"},
            {"label": "Capital nécessaire", "value": fmt_money(income["capital_necessaire"], "MAD", compact=True),
             "sub": "pour générer ce revenu à 4 %", "tone": "accent"},
        ],
        per_row=4,
    )
