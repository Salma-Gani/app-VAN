"""Comparateur de projets d'investissement : VAN, TRI, payback et sensibilité.

Reprend l'outil historique de l'application (comparaison Projet A / Projet B) dans le
thème Market Mind.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...config import COLORS
from ...utils import finance
from ...utils.formatting import fmt_money, fmt_num, fmt_pct
from .. import components as ui

_DEFAULT_A = [30_000, 35_000, 40_000, 40_000, 35_000]
_DEFAULT_B = [20_000, 25_000, 35_000, 50_000, 60_000]


def render() -> None:
    ui.hero(
        "Projets d'investissement",
        "Comparez deux projets sur les critères de la finance d'entreprise : Valeur Actuelle "
        "Nette, Taux de Rentabilité Interne, délai de récupération et conformité budgétaire.",
        badge=ui.badge("Outil historique · VAN / TRI / Payback", "info"),
    )

    params = _parameters()
    inv_a, cfs_a, inv_b, cfs_b = _projects(params["horizon"])
    results = _compute(params, inv_a, cfs_a, inv_b, cfs_b)

    _budget_check(params, inv_a, inv_b)
    st.divider()
    _kpis(results)
    st.divider()
    _charts(params, results)
    st.divider()
    _recommendation(params, results)
    st.divider()
    _recap(params, results)
    ui.disclaimer()


# ═══════════════════════════ Paramètres ═══════════════════════════


def _parameters() -> Dict[str, Any]:
    ui.section("Paramètres globaux", "Ajustez les hypothèses : tous les calculs se mettent à jour.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        rate = st.slider("Taux d'actualisation / coût du capital (%)", 0.0, 20.0, 8.0, 0.1) / 100.0
    with c2:
        horizon = st.slider("Horizon d'investissement (années)", 1, 15, 5, 1)
    with c3:
        budget = st.number_input("Budget global alloué (MAD)", min_value=0.0,
                                 value=100_000.0, step=10_000.0, format="%.0f")
    with c4:
        volatility = st.slider("Incertitude sur les cash-flows (%)", 0, 50, 20, 1) / 100.0

    ui.note(
        f"Scénarios de sensibilité : pessimiste (cash-flows × {1 - volatility:.0%}), "
        f"base (× 100 %) et optimiste (× {1 + volatility:.0%}).",
        "info", "🎲",
    )
    return {"rate": rate, "horizon": horizon, "budget": budget, "volatility": volatility}


def _projects(horizon: int) -> Tuple[float, List[float], float, List[float]]:
    col_a, col_b = st.columns(2, gap="medium")
    with col_a:
        inv_a, cfs_a = _project_block("🅰️ Projet A", 100_000.0, _DEFAULT_A, horizon)
    with col_b:
        inv_b, cfs_b = _project_block("🅱️ Projet B", 120_000.0, _DEFAULT_B, horizon)
    return inv_a, cfs_a, inv_b, cfs_b


def _project_block(name: str, default_invest: float, default_cfs: List[float],
                   horizon: int) -> Tuple[float, List[float]]:
    st.markdown(f"### {name}")
    invest = st.number_input(
        f"Investissement initial — {name} (MAD)", min_value=0.0, value=default_invest,
        step=10_000.0, format="%.0f", key=f"inv_{name}",
    )
    cfs: List[float] = []
    cols = st.columns(min(horizon, 5))
    for i in range(horizon):
        default = default_cfs[i] if i < len(default_cfs) else default_cfs[-1]
        with cols[i % len(cols)]:
            cfs.append(
                st.number_input(
                    f"Année {i + 1}", min_value=0.0, value=float(default), step=5_000.0,
                    format="%.0f", key=f"cf_{name}_{i}",
                )
            )
    return invest, cfs


# ═══════════════════════════ Calculs ═══════════════════════════


def _compute(params: Dict[str, Any], inv_a: float, cfs_a: List[float],
             inv_b: float, cfs_b: List[float]) -> Dict[str, Any]:
    rate, volatility = params["rate"], params["volatility"]

    van_a = finance.van(inv_a, cfs_a, rate)
    van_b = finance.van(inv_b, cfs_b, rate)
    tri_a = finance.tri(inv_a, cfs_a)
    tri_b = finance.tri(inv_b, cfs_b)
    pb_simple_a, _ = finance.payback(inv_a, cfs_a)
    pb_simple_b, _ = finance.payback(inv_b, cfs_b)
    pb_actual_a, _ = finance.payback(inv_a, cfs_a, rate)
    pb_actual_b, _ = finance.payback(inv_b, cfs_b, rate)

    return {
        "inv_a": inv_a, "inv_b": inv_b, "cfs_a": cfs_a, "cfs_b": cfs_b,
        "van_a": van_a, "van_b": van_b, "tri_a": tri_a, "tri_b": tri_b,
        "pb_simple_a": pb_simple_a, "pb_simple_b": pb_simple_b,
        "pb_actual_a": pb_actual_a, "pb_actual_b": pb_actual_b,
        "van_a_pess": finance.van(inv_a, [c * (1 - volatility) for c in cfs_a], rate),
        "van_a_opt": finance.van(inv_a, [c * (1 + volatility) for c in cfs_a], rate),
        "van_b_pess": finance.van(inv_b, [c * (1 - volatility) for c in cfs_b], rate),
        "van_b_opt": finance.van(inv_b, [c * (1 + volatility) for c in cfs_b], rate),
        "rate": rate,
    }


def _budget_check(params: Dict[str, Any], inv_a: float, inv_b: float) -> None:
    c1, c2 = st.columns(2)
    for col, label, invest in ((c1, "Projet A", inv_a), (c2, "Projet B", inv_b)):
        with col:
            if invest <= params["budget"]:
                ui.note(f"**{label} conforme** — {fmt_money(invest, 'MAD', compact=True)} ≤ "
                        f"budget {fmt_money(params['budget'], 'MAD', compact=True)}.", "up", "✅")
            else:
                ui.note(f"**{label} dépasse le budget** de "
                        f"{fmt_money(invest - params['budget'], 'MAD', compact=True)} — "
                        f"{fmt_money(invest, 'MAD', compact=True)} > "
                        f"{fmt_money(params['budget'], 'MAD', compact=True)}.", "down", "⚠️")


def _kpis(results: Dict[str, Any]) -> None:
    ui.section("Indicateurs clés")
    ui.kpi_row(
        [
            {"label": "VAN — Projet A", "value": fmt_money(results["van_a"], "MAD", compact=True),
             "sub": f"taux {fmt_pct(results['rate'], 1)}",
             "tone": "up" if results["van_a"] > 0 else "down"},
            {"label": "VAN — Projet B", "value": fmt_money(results["van_b"], "MAD", compact=True),
             "sub": f"taux {fmt_pct(results['rate'], 1)}",
             "tone": "up" if results["van_b"] > 0 else "down"},
            {"label": "TRI — Projet A", "value": fmt_pct(results["tri_a"], 2) if results["tri_a"] is not None else "—",
             "sub": "vs coût du capital",
             "tone": "up" if (results["tri_a"] or 0) > results["rate"] else "warn"},
            {"label": "TRI — Projet B", "value": fmt_pct(results["tri_b"], 2) if results["tri_b"] is not None else "—",
             "sub": "vs coût du capital",
             "tone": "up" if (results["tri_b"] or 0) > results["rate"] else "warn"},
        ],
        per_row=4,
    )
    ui.kpi_row(
        [
            {"label": "Payback actualisé A", "value": _fmt_payback(results["pb_actual_a"]),
             "sub": f"simple : {_fmt_payback(results['pb_simple_a'])}", "tone": "accent"},
            {"label": "Payback actualisé B", "value": _fmt_payback(results["pb_actual_b"]),
             "sub": f"simple : {_fmt_payback(results['pb_simple_b'])}", "tone": "accent"},
            {"label": "Cash-flows cumulés A",
             "value": fmt_money(sum(results["cfs_a"]), "MAD", compact=True),
             "sub": "non actualisés", "tone": "blue"},
            {"label": "Cash-flows cumulés B",
             "value": fmt_money(sum(results["cfs_b"]), "MAD", compact=True),
             "sub": "non actualisés", "tone": "blue"},
        ],
        per_row=4,
    )


# ═══════════════════════════ Graphiques ═══════════════════════════


def _charts(params: Dict[str, Any], results: Dict[str, Any]) -> None:
    years = list(range(0, params["horizon"] + 1))
    cum_a = _cumulative(results["inv_a"], results["cfs_a"], params["rate"])
    cum_b = _cumulative(results["inv_b"], results["cfs_b"], params["rate"])

    ui.section("Récupération du capital", "Flux cumulés actualisés — le seuil zéro marque la rentabilité.")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=cum_a, mode="lines+markers", name="Projet A",
                             line=dict(color=COLORS["primary"], width=3),
                             fill="tozeroy", fillcolor="rgba(34,211,166,.08)"))
    fig.add_trace(go.Scatter(x=years, y=cum_b, mode="lines+markers", name="Projet B",
                             line=dict(color=COLORS["accent"], width=3, dash="dash"),
                             fill="tozeroy", fillcolor="rgba(91,141,239,.08)"))
    fig.add_hline(y=0, line_dash="dot", line_color=COLORS["muted"],
                  annotation_text="Seuil de rentabilité", annotation_font_color=COLORS["muted"])
    fig.update_layout(height=400, xaxis_title="Année", yaxis_title="Flux cumulé actualisé (MAD)",
                      hovermode="x unified", margin=dict(l=10, r=10, t=20, b=10))
    ui.plot(fig, key="proj_cumulative")

    left, right = st.columns(2, gap="medium")
    with left:
        ui.section("Scénarios", f"VAN selon une variation de ±{params['volatility']:.0%} des cash-flows.")
        fig = go.Figure()
        scen = ["Pessimiste", "Base", "Optimiste"]
        fig.add_trace(go.Bar(x=scen, y=[results["van_a_pess"], results["van_a"], results["van_a_opt"]],
                             name="Projet A", marker_color=COLORS["primary"], opacity=0.9))
        fig.add_trace(go.Bar(x=scen, y=[results["van_b_pess"], results["van_b"], results["van_b_opt"]],
                             name="Projet B", marker_color=COLORS["accent"], opacity=0.9))
        fig.add_hline(y=0, line_dash="dot", line_color=COLORS["muted"])
        fig.update_layout(height=330, barmode="group", yaxis_title="VAN (MAD)",
                          margin=dict(l=10, r=10, t=10, b=10))
        ui.plot(fig, key="proj_scenarios")
    with right:
        ui.section("Sensibilité au taux", "VAN en fonction du taux d'actualisation.")
        rates = np.linspace(max(0.001, params["rate"] - 0.08), params["rate"] + 0.12, 60)
        sens_a = [finance.van(results["inv_a"], results["cfs_a"], r) for r in rates]
        sens_b = [finance.van(results["inv_b"], results["cfs_b"], r) for r in rates]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=rates * 100, y=sens_a, name="Projet A",
                                 line=dict(color=COLORS["primary"], width=2.6)))
        fig.add_trace(go.Scatter(x=rates * 100, y=sens_b, name="Projet B",
                                 line=dict(color=COLORS["accent"], width=2.6, dash="dash")))
        fig.add_hline(y=0, line_dash="dot", line_color=COLORS["muted"])
        fig.add_vline(x=params["rate"] * 100, line_dash="dot", line_color=COLORS["warning"],
                      annotation_text="Taux actuel", annotation_font_color=COLORS["warning"])
        fig.update_layout(height=330, xaxis_title="Taux d'actualisation (%)", yaxis_title="VAN (MAD)",
                          hovermode="x unified", margin=dict(l=10, r=10, t=10, b=10))
        ui.plot(fig, key="proj_sensitivity")


# ═══════════════════════════ Recommandation ═══════════════════════════


def _recommendation(params: Dict[str, Any], results: Dict[str, Any]) -> None:
    ui.section("Recommandation")
    score_a = _score(results, "a", params)
    score_b = _score(results, "b", params)

    if score_a == score_b and results["van_a"] == results["van_b"]:
        ui.verdict("Égalité", "Les deux projets sont équivalents sur les critères mesurés.", COLORS["muted"])
        return

    winner = "a" if score_a > score_b else "b"
    reasons = _reasons(results, winner, params)
    tone = COLORS["primary"] if score_a > score_b else COLORS["accent"]
    body = " · ".join(reasons) + "." if reasons else "Meilleur score global sur les critères retenus."

    warnings = []
    if results["van_a"] < 0 and results["van_b"] < 0:
        warnings.append("⚠️ Les deux VAN sont négatives : aucun projet n'est rentable au taux retenu.")
    if results["inv_a"] > params["budget"] and results["inv_b"] > params["budget"]:
        warnings.append("⛔ Les deux projets dépassent le budget global.")
    if warnings:
        body += "\n\n" + "\n\n".join(warnings)

    ui.verdict(f"Projet {winner.upper()} recommandé", body, tone)


def _score(results: Dict[str, Any], suffix: str, params: Dict[str, Any]) -> float:
    van = results[f"van_{suffix}"]
    tri = results[f"tri_{suffix}"]
    payback = results[f"pb_actual_{suffix}"]
    invest = results[f"inv_{suffix}"]
    score = 3 if van > 0 else -3
    score += van / 100_000.0
    if tri is not None and tri > params["rate"]:
        score += 2
    if tri is None:
        score -= 2
    if invest > params["budget"]:
        score -= 5
    if payback is None:
        score -= 1
    return float(score)


def _reasons(results: Dict[str, Any], winner: str, params: Dict[str, Any]) -> List[str]:
    other = "b" if winner == "a" else "a"
    reasons: List[str] = []
    if results[f"van_{winner}"] > results[f"van_{other}"]:
        reasons.append(
            f"VAN supérieure ({fmt_money(results[f'van_{winner}'], 'MAD', compact=True)} vs "
            f"{fmt_money(results[f'van_{other}'], 'MAD', compact=True)})"
        )
    tri_w, tri_o = results[f"tri_{winner}"], results[f"tri_{other}"]
    if tri_w is not None and (tri_o is None or tri_w > tri_o):
        reasons.append(f"TRI supérieur ({fmt_pct(tri_w, 1)} vs {fmt_pct(tri_o, 1)})")
    if results[f"inv_{winner}"] <= params["budget"] < results[f"inv_{other}"]:
        reasons.append("seul projet conforme au budget")
    pb_w, pb_o = results[f"pb_actual_{winner}"], results[f"pb_actual_{other}"]
    if pb_w is not None and (pb_o is None or pb_w < pb_o):
        reasons.append("récupération du capital plus rapide")
    if (results[f"van_{winner}_opt"] > results[f"van_{other}_opt"]
            and results[f"van_{winner}_pess"] > results[f"van_{other}_pess"]):
        reasons.append("plus résilient dans tous les scénarios de risque")
    return reasons


# ═══════════════════════════ Récapitulatif ═══════════════════════════


def _recap(params: Dict[str, Any], results: Dict[str, Any]) -> None:
    ui.section("Tableau récapitulatif")
    recap = pd.DataFrame(
        {
            "Indicateur": [
                "Investissement initial", "Conforme au budget",
                "VAN — scénario base", "VAN — pessimiste", "VAN — optimiste",
                "TRI", "TRI > coût du capital",
                "Payback simple", "Payback actualisé",
                "Cash-flows cumulés (non actualisés)",
            ],
            "Projet A": [
                fmt_money(results["inv_a"], "MAD", compact=True),
                "✅ Oui" if results["inv_a"] <= params["budget"] else "❌ Non",
                fmt_money(results["van_a"], "MAD", compact=True),
                fmt_money(results["van_a_pess"], "MAD", compact=True),
                fmt_money(results["van_a_opt"], "MAD", compact=True),
                fmt_pct(results["tri_a"], 2) if results["tri_a"] is not None else "—",
                "—" if results["tri_a"] is None else ("✅ Oui" if results["tri_a"] > params["rate"] else "❌ Non"),
                _fmt_payback(results["pb_simple_a"]),
                _fmt_payback(results["pb_actual_a"]),
                fmt_money(sum(results["cfs_a"]), "MAD", compact=True),
            ],
            "Projet B": [
                fmt_money(results["inv_b"], "MAD", compact=True),
                "✅ Oui" if results["inv_b"] <= params["budget"] else "❌ Non",
                fmt_money(results["van_b"], "MAD", compact=True),
                fmt_money(results["van_b_pess"], "MAD", compact=True),
                fmt_money(results["van_b_opt"], "MAD", compact=True),
                fmt_pct(results["tri_b"], 2) if results["tri_b"] is not None else "—",
                "—" if results["tri_b"] is None else ("✅ Oui" if results["tri_b"] > params["rate"] else "❌ Non"),
                _fmt_payback(results["pb_simple_b"]),
                _fmt_payback(results["pb_actual_b"]),
                fmt_money(sum(results["cfs_b"]), "MAD", compact=True),
            ],
        }
    )
    ui.table(recap, height=440, key="proj_recap")
    ui.download_row(recap, "comparaison_projets.csv", "⬇️ Exporter le rapport", key="proj_export")

    st.caption(
        "Formules : VAN = −I₀ + Σ CFₜ/(1+r)ᵗ · TRI = taux annulant la VAN · "
        "Payback = première année où le cumul des flux (actualisés) devient positif."
    )


# ═══════════════════════════ Utilitaires ═══════════════════════════


def _cumulative(invest: float, cashflows: List[float], rate: float) -> List[float]:
    out = [-float(invest)]
    total = -float(invest)
    for i, cf in enumerate(cashflows, start=1):
        total += cf / (1 + rate) ** i
        out.append(total)
    return out


def _fmt_payback(value: Optional[float]) -> str:
    if value is None:
        return "Jamais"
    years = int(value)
    months = int(round((value - years) * 12))
    if years == 0:
        return f"{months} mois"
    return f"{years} ans {months} mois"
