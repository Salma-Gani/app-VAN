"""Valorisation DCF, scénarios et simulation Monte-Carlo d'une valeur."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...analytics import forecast
from ...analytics import valuation_lab as lab
from ...config import COLORS, RISK_FREE_RATE
from ...data import fundamentals
from ...utils.formatting import as_float, fmt_money, fmt_num, fmt_pct
from .. import charts, components as ui
from ..reporting import download_analysis
from . import shared


def render() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles.", "📡")
        return

    symbol = _selector(table)
    row = table[table["symbol"] == symbol].iloc[0]
    f = fundamentals.get_fundamentals(symbol, row)

    ui.hero(
        "Valorisation & prévisions",
        "Discounted Cash-Flow, scénarios, sensibilité et distribution Monte-Carlo — "
        "à partir des états financiers saisis et du cours réel.",
        badge=ui.badge(symbol, "accent"),
    )

    ui.source_note(
        ["BVC (cours, nombre de titres, dividende)", "États financiers saisis/importés"],
        as_of=f"clôture du {shared.last_market_date(table)}",
        detail="Le DCF repose sur des hypothèses explicites : croissance, marge, taux d'actualisation et valeur terminale.",
    )

    _valuation_lab(row, f)
    st.divider()

    fcf_start = forecast.base_fcf(f)
    if fcf_start is None or fcf_start <= 0:
        ui.note(
            "Le **Free Cash-Flow** de cette société n'est pas renseigné : le DCF ne peut pas être "
            "calculé sur des données réelles. Saisissez-le dans « Données fondamentales », ou "
            "utilisez le mode simulation ci-dessous (hypothèse explicite, non issue des comptes).",
            "warn", "⚠️",
        )
        with st.expander("🧪 Mode simulation — saisir un FCF de départ", expanded=True):
            fcf_start = st.number_input(
                "FCF de départ (MAD)",
                min_value=0.0,
                value=float(max((f.get("net_income") or 0) * 1.1, 50_000_000.0)),
                step=10_000_000.0,
                format="%.0f",
                help="Montant libre utilisé uniquement pour la simulation. Il n'est pas enregistré.",
            )
            st.caption(
                "Astuce : renseignez le FCF réel dans « Données fondamentales » pour un DCF "
                "directement exploitable."
            )

    assumptions = _assumptions(row, f, fcf_start)
    # Le FCF saisi en mode simulation est injecté explicitement (aucune donnée inventée :
    # il s'agit d'une hypothèse affichée à l'utilisateur).
    f_dcf = dict(f)
    if fcf_start:
        f_dcf["fcf"] = float(fcf_start)
    result = forecast.valuation(
        f_dcf, price=row.get("close"), assumptions=assumptions, years=assumptions["years"]
    )

    if not result.get("available"):
        ui.empty_state(result.get("reason") or "Valorisation impossible.", "🧮")
        return

    _verdict(result, row)
    st.divider()
    _projection(result)
    st.divider()
    col_a, col_b = st.columns([1, 1], gap="medium")
    with col_a:
        _sensitivity(result, assumptions)
    with col_b:
        _scenarios(result, assumptions)
    st.divider()
    _monte_carlo(result, assumptions, row)
    st.divider()
    _relative(row, symbol)
    ui.disclaimer()


# ═══════════════════════════ Valuation Lab ═══════════════════════════


def _valuation_lab(row: pd.Series, f: Dict[str, Any]) -> None:
    """Prix théorique d'entrée par multiples, comparé au cours observable."""
    price = as_float(row.get("close")) or as_float(f.get("price"))
    cap = as_float(row.get("cap")) or as_float(f.get("market_cap"))
    catalog = lab.method_catalog(f, price=price, cap=cap)
    specs = {m["key"]: m for m in catalog}

    ui.section(
        "Valuation Lab — prix théorique d'entrée",
        "Choisissez une méthode, un multiple cible et une marge de sécurité. Le résultat est une "
        "valeur conditionnelle à vos hypothèses, jamais un objectif de cours ni une recommandation.",
    )

    if price is None:
        ui.note("Le cours actuel n'est pas disponible : impossible de comparer le prix théorique au marché.",
                "warn", "⚠️")
        return

    available = [m for m in catalog if m["available"]]
    if not available:
        ui.note(
            "**Aucun multiple calculable pour cette société.** Les états financiers (BPA, EBITDA, "
            "capitaux propres, chiffre d'affaires) ne sont pas renseignés. Le dividende BVC permet "
            "parfois une valorisation par rendement ; sinon, complétez les données fondamentales. "
            "Aucune valeur n'est inventée.",
            "warn", "🧾",
        )
    keys = [m["key"] for m in catalog]
    labels = {
        m["key"]: f"{m['label']} — {'disponible' if m['available'] else 'donnée manquante'}"
        for m in catalog
    }
    default_index = next((i for i, m in enumerate(catalog) if m["available"]), 0)
    method = st.selectbox(
        "Méthode de valorisation",
        keys,
        index=default_index,
        format_func=lambda k: labels.get(k, k),
        key="lab_method",
    )
    spec = specs[method]
    if method == "per":
        st.caption("Formule : prix théorique = PER cible × BPA. Exemple pédagogique : 20 × 12 = 240 MAD "
                   "(illustration mathématique, pas une valorisation réelle).")

    metric_override = None
    net_debt = float(as_float(f.get("total_debt")) or 0.0) - float(as_float(f.get("cash")) or 0.0)
    shares = as_float(f.get("shares"))

    if method in ("ev_ebitda", "ev_ebit"):
        with st.expander("⚙️ Ajustements EV → capitaux propres", expanded=not spec["available"]):
            c1, c2 = st.columns(2)
            with c1:
                net_debt = st.number_input(
                    "Dette nette (MAD)", value=float(net_debt), step=10_000_000.0, format="%.0f",
                    key=f"lab_net_debt_{method}",
                    help="Dette financière brute moins trésorerie. Déduite de la valeur d'entreprise.",
                )
            with c2:
                shares = st.number_input(
                    "Nombre d'actions", min_value=0.0,
                    value=float(shares or 0.0), step=1_000_000.0, format="%.0f",
                    key=f"lab_shares_{method}",
                    help="Nombre de titres utilisé pour passer de la valeur des capitaux propres au prix par action.",
                )

    if not spec["available"]:
        with st.expander("✍️ Saisir une donnée de référence vérifiée", expanded=True):
            st.caption(
                "Cette valeur doit provenir d'un rapport annuel, d'un communiqué de résultats ou d'une "
                "source documentaire identifiée. Elle est utilisée pour le calcul mais **n'est pas enregistrée** "
                "dans la fiche fondamentale."
            )
            if method == "per":
                metric_override = st.number_input(
                    "BPA de référence (MAD/action)", min_value=0.0, value=0.0, step=0.1,
                    key="lab_override_per",
                ) or None
            elif method == "ev_ebitda":
                metric_override = st.number_input(
                    "EBITDA de référence (MAD)", min_value=0.0, value=0.0, step=10_000_000.0,
                    format="%.0f", key="lab_override_ebitda",
                ) or None
            elif method == "ev_ebit":
                metric_override = st.number_input(
                    "EBIT de référence (MAD)", min_value=0.0, value=0.0, step=10_000_000.0,
                    format="%.0f", key="lab_override_ebit",
                ) or None
            elif method == "pb":
                metric_override = st.number_input(
                    "Valeur comptable par action (MAD/action)", min_value=0.0, value=0.0, step=0.1,
                    key="lab_override_bvps",
                ) or None
            elif method == "ps":
                metric_override = st.number_input(
                    "Ventes par action (MAD/action)", min_value=0.0, value=0.0, step=0.1,
                    key="lab_override_sales_ps",
                ) or None
            else:
                metric_override = st.number_input(
                    "Dividende par action (MAD/action)", min_value=0.0, value=0.0, step=0.1,
                    key="lab_override_dps",
                ) or None

    current_target = spec.get("default_target") or 1.0
    if spec.get("target_kind") == "yield":
        input_target = st.number_input(
            "Rendement exigé (%)", min_value=0.1, max_value=30.0,
            value=float(round(current_target * 100, 2)), step=0.1,
            key="lab_target_yield",
            help="Plus le rendement exigé est élevé, plus le prix théorique d'entrée est bas.",
        )
        target = input_target / 100.0
    else:
        target = st.number_input(
            spec["target_label"], min_value=0.1, max_value=100.0,
            value=float(round(current_target, 2)), step=0.5,
            key="lab_target_multiple",
            help="Multiple appliqué à la métrique de référence. Il doit être justifié par l'historique, "
                 "le secteur ou votre scénario.",
        )
    required_margin = st.slider(
        "Marge de sécurité exigée (%)", min_value=0, max_value=50, value=20, step=5,
        key="lab_margin",
        help="Prix d'entrée = valeur théorique × (1 − marge). Une marge élevée réduit le prix payé.",
    ) / 100.0

    result = lab.target_entry(
        method, target, f, price=price, net_debt=net_debt, shares=shares,
        required_margin=required_margin, metric_override=metric_override,
    )
    if not result.get("available"):
        ui.note(result.get("reason") or "Calcul impossible avec ces données.", "warn", "⚠️")
        return

    fair = result.get("fair_value")
    entry = result.get("entry_price")
    current = result.get("current_ratio")
    zone = result.get("zone") or {}
    ratio_is_yield = spec.get("target_kind") == "yield"

    def ratio_text(value: Optional[float]) -> str:
        if value is None:
            return "—"
        return fmt_pct(value, 2) if ratio_is_yield else f"{fmt_num(value, 2)}x"

    ui.kpi_row(
        [
            {"label": "Cours actuel", "value": fmt_num(price, 2) + " MAD",
             "sub": "BVC, dernier cours", "tone": "blue"},
            {"label": "Ratio actuel", "value": ratio_text(current),
             "sub": spec["metric"], "tone": "accent"},
            {"label": "Hypothèse cible", "value": ratio_text(target),
             "sub": spec["target_label"], "tone": "info"},
            {"label": "Prix théorique", "value": fmt_num(fair, 2) + " MAD",
             "sub": "selon vos hypothèses", "tone": "up"},
            {"label": "Prix d'entrée", "value": fmt_num(entry, 2) + " MAD",
             "sub": f"marge {fmt_pct(required_margin, 0)}", "tone": "accent"},
        ],
        per_row=5,
    )

    body = (
        f"Valeur théorique : **{fmt_num(fair, 2)} MAD** par action. "
        f"Écart avec le cours : **{fmt_pct(result.get('upside'), 1, signed=True)}**. "
        f"Prix d'entrée avec une marge de sécurité de {fmt_pct(required_margin, 0)} : "
        f"**{fmt_num(entry, 2)} MAD**. "
        f"Marge de sécurité observée au cours actuel : **{fmt_pct(result.get('margin_of_safety'), 1, signed=True)}**."
    )
    tone = {"up": "up", "down": "down", "info": "info"}.get(zone.get("tone"), "info")
    ui.verdict(zone.get("label", "Prix théorique calculé"), body, COLORS["primary"] if tone == "up"
               else COLORS["danger"] if tone == "down" else COLORS["accent"])
    ui.note(zone.get("text") or "", tone, "🎯")

    assumptions = pd.DataFrame(
        [
            {"Paramètre": "Méthode", "Valeur": spec["label"]},
            {"Paramètre": "Métrique de référence", "Valeur": spec["metric"]},
            {"Paramètre": "Valeur de la métrique",
             "Valeur": f"{fmt_num(result.get('metric_value'), 2)} {spec['metric_unit']}"},
            {"Paramètre": "Ratio cible", "Valeur": ratio_text(target)},
            {"Paramètre": "Marge de sécurité exigée", "Valeur": fmt_pct(required_margin, 1)},
            {"Paramètre": "Nombre d'actions", "Valeur": fmt_num(shares, 0) if shares else "—"},
            {"Paramètre": "Dette nette", "Valeur": fmt_money(net_debt, "MAD", compact=True)},
            {"Paramètre": "Exercice comptable", "Valeur": str(f.get("fiscal_year") or "non renseigné")},
            {"Paramètre": "Source documentaire", "Valeur": str(f.get("source") or "non renseignée")},
            {"Paramètre": "Mise à jour de la fiche", "Valeur": str(f.get("as_of") or "non renseignée")},
        ]
    )
    with st.expander("📋 Hypothèses et traçabilité", expanded=False):
        ui.table(assumptions, height=360, key="lab_assumptions")

    table = lab.sensitivity(
        method, target, f, price=price, net_debt=net_debt, shares=shares,
        required_margin=required_margin, metric_override=metric_override, steps=9,
    )
    if not table.empty and table["Prix théorique"].notna().any():
        display = table.copy()
        display["Hypothèse cible"] = display["Hypothèse cible"].apply(
            lambda v: fmt_pct(v, 2) if ratio_is_yield else f"{v:.2f}x"
        )
        display["Prix théorique"] = display["Prix théorique"].apply(lambda v: fmt_num(v, 2))
        display["Prix d'entrée"] = display["Prix d'entrée"].apply(lambda v: fmt_num(v, 2))
        display["Écart vs cours"] = display["Écart vs cours"].apply(lambda v: fmt_pct(v, 1, signed=True))
        display = display.drop(columns=["Disponible"])
        with st.expander("📈 Sensibilité au multiple cible", expanded=True):
            c1, c2 = st.columns([1.1, 1])
            with c1:
                ui.table(display, height=340, key="lab_sensitivity_table")
            with c2:
                fig = go.Figure()
                x = table["Hypothèse cible"]
                fig.add_trace(go.Scatter(
                    x=x, y=table["Prix théorique"], mode="lines+markers",
                    name="Prix théorique", line=dict(color=COLORS["primary"], width=2.4),
                ))
                fig.add_trace(go.Scatter(
                    x=x, y=table["Prix d'entrée"], mode="lines",
                    name="Prix d'entrée", line=dict(color=COLORS["accent"], width=1.8, dash="dash"),
                ))
                fig.add_hline(y=price, line_dash="dot", line_color=COLORS["warning"],
                              annotation_text="Cours actuel", annotation_position="bottom right")
                fig.add_vline(x=target, line_dash="dot", line_color=COLORS["muted"])
                fig.update_layout(height=340, margin=dict(l=10, r=10, t=20, b=30))
                ui.plot(fig, key="lab_sensitivity_chart")

    ui.note(
        "**Limites** : le prix théorique dépend entièrement de la métrique, de l'exercice comptable, "
        "du nombre d'actions et du multiple retenu. Il ne s'agit ni d'un objectif de cours, ni d'une "
        "prévision, ni d'une recommandation d'achat. Vérifiez la source et la date des états financiers.",
        "warn", "⚠️",
    )

    _valuation_report(
        symbol=str(row.get("symbol") or ""),
        name=str(row.get("name") or ""),
        spec=spec,
        f=f,
        row=row,
        price=price,
        target=target,
        ratio_text=ratio_text,
        fair=fair,
        entry=entry,
        required_margin=required_margin,
        result=result,
        zone=zone,
        display=display if "display" in locals() else pd.DataFrame(),
        shares=shares,
        net_debt=net_debt,
        as_of=shared.last_market_date(table),
    )


def _valuation_report(symbol: str, name: str, spec: Dict[str, Any], f: Dict[str, Any],
                      row: pd.Series, price: Optional[float], target: float,
                      ratio_text: Any, fair: Optional[float], entry: Optional[float],
                      required_margin: float, result: Dict[str, Any], zone: Dict[str, str],
                      display: pd.DataFrame, shares: Optional[float], net_debt: float,
                      as_of: str) -> None:
    """Construit un rapport PDF traçable du calcul de prix d'entrée."""
    lines = [
        f"## Valorisation — {spec.get('label')}",
        "",
        "### Hypothèses",
        f"- Cours actuel : **{fmt_num(price, 2)} MAD** (clôture du {as_of}).",
        f"- Métrique de référence : **{spec.get('metric')} = {fmt_num(result.get('metric_value'), 2)} "
        f"{spec.get('metric_unit', '')}**.",
        f"- Ratio cible : **{ratio_text(target)}** ({spec.get('target_label')}).",
        f"- Marge de sécurité exigée : **{fmt_pct(required_margin, 1)}**.",
        f"- Nombre d'actions : **{fmt_num(shares, 0) if shares else 'non renseigné'}**.",
        f"- Dette nette : **{fmt_money(net_debt, 'MAD', compact=True)}**.",
        f"- Exercice comptable : **{f.get('fiscal_year') or 'non renseigné'}** · "
        f"source : **{f.get('source') or 'non renseignée'}** · mise à jour : **{f.get('as_of') or 'non renseignée'}**.",
        "",
        "### Résultat",
        f"- Prix théorique : **{fmt_num(fair, 2)} MAD**.",
        f"- Prix d'entrée avec marge : **{fmt_num(entry, 2)} MAD**.",
        f"- Écart avec le cours : **{fmt_pct(result.get('upside'), 1, signed=True)}**.",
        f"- Marge de sécurité observée au cours actuel : "
        f"**{fmt_pct(result.get('margin_of_safety'), 1, signed=True)}**.",
        f"- Position : **{zone.get('label', '—')}** — {zone.get('text', '')}",
    ]
    if not display.empty:
        lines += [
            "",
            "### Sensibilité au multiple cible",
            "",
            "| Hypothèse cible | Prix théorique | Prix d'entrée | Écart vs cours |",
            "|---|---|---|---|",
        ]
        for _, item in display.iterrows():
            lines.append("| {} | {} | {} | {} |".format(
                item.get("Hypothèse cible"),
                item.get("Prix théorique"),
                item.get("Prix d'entrée"),
                item.get("Écart vs cours"),
            ))
    lines += [
        "",
        "### Limites",
        "Le prix théorique dépend de la métrique, de l'exercice comptable, du nombre d'actions, "
        "du multiple cible et de la marge de sécurité. Il ne s'agit ni d'un objectif de cours, ni "
        "d'une prévision, ni d'une recommandation d'achat. Vérifiez la source et la date des états "
        "financiers avant toute décision.",
    ]
    ratios_raw = fundamentals.compute_ratios(f, price=price, cap=row.get("cap"))
    ratios = {k: fundamentals.interpret_ratio(k, v) for k, v in ratios_raw.items()}
    result_payload = {
        "symbol": symbol,
        "row": row.to_dict(),
        "ratios": ratios,
        "sources": [
            "Bourse de Casablanca (cours, nombre de titres, dividende)",
            "États financiers saisis/importés par l'utilisateur",
            "Valuation Lab — calcul déterministe, hypothèses explicites",
        ],
        "as_of": as_of,
        "fundamentals_source": str(f.get("source") or ""),
    }
    report_result = {
        "symbol": symbol,
        "provider": "Valuation Lab",
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "text": "\n".join(lines),
        "payload": result_payload,
    }
    st.caption(
        "Le rapport PDF reprend le cours, la métrique, le multiple cible, la marge, le prix "
        "théorique, le prix d'entrée, la sensibilité, les sources et les limites."
    )
    download_analysis(report_result, symbol, key="valuation_lab_report")


# ═══════════════════════════ Sélection et hypothèses ═══════════════════════════


def _selector(table: pd.DataFrame) -> str:
    symbols = table["symbol"].tolist()
    names = dict(zip(table["symbol"], table["name"]))
    requested = str(st.session_state.get("selected_symbol") or "").upper()
    if requested not in symbols:
        requested = symbols[0]
    return st.selectbox(
        "Valeur à valoriser",
        symbols,
        index=symbols.index(requested),
        format_func=lambda s: f"{s} — {names.get(s, s)}",
        key="valuation_symbol",
    )


def _assumptions(row: pd.Series, f: Dict[str, Any], fcf_start: Optional[float]) -> Dict[str, Any]:
    defaults = forecast.default_assumptions(f, beta=row.get("beta"))
    ui.section("Hypothèses de valorisation", "Ajustez les paramètres : le DCF se recalcule instantanément.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        growth = st.number_input(
            "Croissance des FCF (%)", min_value=-20.0, max_value=50.0,
            value=float(round((defaults.get("growth") or 0.05) * 100, 1)), step=0.5,
            help="Taux de croissance annuel des cash-flows sur l'horizon explicite.",
        ) / 100.0
    with c2:
        discount = st.number_input(
            "Taux d'actualisation (%)", min_value=4.0, max_value=30.0,
            value=float(round((defaults.get("discount_rate") or 0.10) * 100, 1)), step=0.25,
            help=f"Coût des fonds propres estimé par le CAPM (taux sans risque {RISK_FREE_RATE:.1%} "
                 "+ bêta × prime de risque).",
        ) / 100.0
    with c3:
        terminal = st.number_input(
            "Croissance terminale (%)", min_value=0.0, max_value=4.0,
            value=float(round((defaults.get("growth_terminal") or 0.02) * 100, 1)), step=0.25,
            help="Croissance perpétuelle après l'horizon explicite. Doit rester sous l'inflation "
                 "de long terme et sous le taux d'actualisation.",
        ) / 100.0
    with c4:
        years = st.slider("Horizon explicite (ans)", 3, 10, 5, 1)

    c5, c6, c7 = st.columns(3)
    with c5:
        net_debt = st.number_input(
            "Dette nette (MAD)", value=float(defaults.get("net_debt") or 0.0),
            step=10_000_000.0, format="%.0f",
            help="Dette financière moins trésorerie. Déduite de la valeur d'entreprise.",
        )
    with c6:
        shares = st.number_input(
            "Nombre de titres", min_value=0.0, value=float(defaults.get("shares") or 0.0),
            step=1_000_000.0, format="%.0f",
            help="Déduit automatiquement de la capitalisation boursière si non renseigné.",
        )
    with c7:
        st.metric("FCF de départ", fmt_money(fcf_start, "MAD", compact=True))
        st.caption(f"Bêta retenu : {fmt_num(defaults.get('beta'), 2)}")

    return {
        "growth": growth,
        "discount_rate": discount,
        "growth_terminal": terminal,
        "years": years,
        "net_debt": net_debt,
        "shares": shares if shares > 0 else None,
    }


# ═══════════════════════════ Verdict ═══════════════════════════


def _verdict(result: Dict[str, Any], row: pd.Series) -> None:
    price = result.get("price")
    fair = result.get("fair_value")
    mos = result.get("margin_of_safety")
    upside = result.get("upside")
    if fair is None:
        ui.note("Nombre de titres inconnu : impossible de calculer une valeur par action.", "warn", "⚠️")
        return

    if mos is None:
        tone, title = "info", "Valorisation calculée"
    elif mos >= 0.30:
        tone, title = "up", "Forte décote — potentiel significatif"
    elif mos >= 0.10:
        tone, title = "up", "Décote modérée"
    elif mos >= -0.10:
        tone, title = "info", "Cours proche de la valeur intrinsèque"
    elif mos >= -0.30:
        tone, title = "warn", "Prime de valorisation"
    else:
        tone, title = "down", "Cours très supérieur à la valeur intrinsèque"

    color = {"up": COLORS["primary"], "down": COLORS["danger"],
             "warn": COLORS["warning"], "info": COLORS["accent"]}[tone]
    body = (
        f"Valeur intrinsèque estimée : **{fmt_num(fair, 2)} MAD** par action, "
        f"contre un cours de **{fmt_num(price, 2)} MAD** "
        f"({'potentiel de hausse' if (upside or 0) >= 0 else 'potentiel de baisse'} de "
        f"**{fmt_pct(upside, 1, signed=True)}**). "
        f"Marge de sécurité : **{fmt_pct(mos, 1, signed=True)}**. "
        f"Valeur des fonds propres : {fmt_money(result.get('equity_value'), 'MAD', compact=True)} · "
        f"part de la valeur terminale : {fmt_pct(result.get('terminal_share'), 0)}."
    )
    if (result.get("terminal_share") or 0) > 0.75:
        body += (
            "\n\n⚠️ Plus des trois quarts de la valeur provient de la valeur terminale : le "
            "résultat est très sensible aux hypothèses de long terme."
        )
    ui.verdict(title, body, color)

    ui.kpi_row(
        [
            {"label": "Valeur intrinsèque", "value": fmt_num(fair, 2) + " MAD",
             "sub": "par action", "tone": tone if tone != "down" else "down"},
            {"label": "Cours actuel", "value": fmt_num(price, 2) + " MAD",
             "sub": "BVC, dernier cours", "tone": "blue"},
            {"label": "Potentiel", "value": fmt_pct(upside, 1, signed=True),
             "sub": "vs valeur intrinsèque", "tone": "up" if (upside or 0) >= 0 else "down"},
            {"label": "Marge de sécurité", "value": fmt_pct(mos, 1, signed=True),
             "sub": "30 % recommandé", "tone": "accent"},
            {"label": "Valeur terminale", "value": fmt_pct(result.get("terminal_share"), 0),
             "sub": "part de l'EV", "tone": "warn"},
        ],
        per_row=5,
    )


# ═══════════════════════════ Projection ═══════════════════════════


def _projection(result: Dict[str, Any]) -> None:
    ui.section("Projection des cash-flows", "FCF projetés avec atténuation progressive de la croissance.")
    projection = result.get("projection") or []
    if not projection:
        return
    labels = [f"Année {i}" for i in range(1, len(projection) + 1)]
    values = [float(v) for v in projection]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=labels, y=values, name="FCF projeté", marker_color=COLORS["primary"], opacity=0.85,
               text=[fmt_money(v, "MAD", compact=True) for v in values], textposition="outside")
    )
    fig.add_hline(
        y=float(result.get("fcf_start") or 0), line_dash="dot", line_color=COLORS["warning"],
        annotation_text="FCF de départ", annotation_font_color=COLORS["warning"],
    )
    fig.update_layout(title="", height=380, yaxis_title="FCF (MAD)", showlegend=False,
                      margin=dict(l=10, r=10, t=20, b=10))
    ui.plot(fig, key="val_projection")

    table = pd.DataFrame(
        {
            "Année": labels,
            "FCF projeté": values,
            "Croissance appliquée": [
                (values[0] / float(result.get("fcf_start") or 1) - 1)
            ] + [values[i] / values[i - 1] - 1 for i in range(1, len(values))],
            "Facteur d'actualisation": [
                (1 + float(result["assumptions"]["discount_rate"])) ** -(i + 0.5)
                for i in range(len(values))
            ],
        }
    )
    table["FCF projeté"] = table["FCF projeté"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    table["Croissance appliquée"] = table["Croissance appliquée"].apply(lambda v: fmt_pct(v, 1))
    table["Facteur d'actualisation"] = table["Facteur d'actualisation"].apply(lambda v: fmt_num(v, 3))
    ui.table(table, height=280, key="val_proj_table")


# ═══════════════════════════ Sensibilité ═══════════════════════════


def _sensitivity(result: Dict[str, Any], assumptions: Dict[str, Any]) -> None:
    ui.section("Sensibilité", "Prix par action selon le taux d'actualisation et la croissance terminale.")
    base_rate = float(assumptions["discount_rate"])
    base_terminal = float(assumptions["growth_terminal"])
    rates = [round(base_rate + d, 3) for d in (-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03)]
    terminals = [round(max(base_terminal + d, 0.0), 3) for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]

    df = forecast.sensitivity_table(
        float(result["fcf_start"]),
        float(assumptions["growth"]),
        rates,
        terminals,
        years=int(assumptions["years"]),
        net_debt=float(assumptions["net_debt"]),
        shares=assumptions.get("shares"),
    )
    if df.empty:
        ui.empty_state("Sensibilité non calculable.", "🧮")
        return

    fig = go.Figure(
        go.Heatmap(
            z=df.values.astype(float),
            x=list(df.columns),
            y=list(df.index),
            colorscale=[[0, COLORS["danger"]], [0.5, "#EDE8DD"], [1, COLORS["primary"]]],
            colorbar=dict(title="MAD", tickfont=dict(color=COLORS["muted"])),
            hovertemplate="Taux %{x}<br>g terminal %{y}<br>Valeur : %{z:,.2f} MAD<extra></extra>",
        )
    )
    fig.update_layout(
        title="", height=390, xaxis_title="Taux d'actualisation",
        yaxis_title="Croissance terminale", margin=dict(l=10, r=10, t=10, b=10),
    )
    ui.plot(fig, key="val_sensitivity")
    price = result.get("price")
    if price:
        st.caption(
            f"Cellule centrale = scénario retenu. Cours actuel : **{fmt_num(price, 2)} MAD**. "
            "Les cellules au-dessus du cours traduisent une sous-évaluation."
        )


# ═══════════════════════════ Scénarios ═══════════════════════════


def _scenarios(result: Dict[str, Any], assumptions: Dict[str, Any]) -> None:
    ui.section("Scénarios", "Pessimiste, base et optimiste — croissance et taux ajustés.")
    df = forecast.scenario_analysis(
        float(result["fcf_start"]),
        float(assumptions["growth"]),
        float(assumptions["discount_rate"]),
        float(assumptions["net_debt"]),
        shares=assumptions.get("shares"),
        years=int(assumptions["years"]),
        terminal_growth=float(assumptions["growth_terminal"]),
    )
    if df.empty:
        ui.empty_state("Scénarios non calculables.", "🧮")
        return

    display = df.copy()
    display["Croissance FCF"] = display["Croissance FCF"].apply(lambda v: fmt_pct(v, 1))
    display["Taux d'actualisation"] = display["Taux d'actualisation"].apply(lambda v: fmt_pct(v, 1))
    display["Croissance terminale"] = display["Croissance terminale"].apply(lambda v: fmt_pct(v, 1))
    display["Valeur des fonds propres"] = display["Valeur des fonds propres"].apply(
        lambda v: fmt_money(v, "MAD", compact=True)
    )
    display["Valeur par action"] = display["Valeur par action"].apply(lambda v: fmt_num(v, 2))
    display["FCF année 1"] = display["FCF année 1"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    display["FCF année finale"] = display["FCF année finale"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    ui.table(display, height=200, key="val_scenarios")

    fig = go.Figure()
    colors = [COLORS["danger"], COLORS["accent"], COLORS["primary"]]
    fig.add_trace(
        go.Bar(x=df["Scénario"], y=df["Valeur par action"], marker_color=colors,
               text=[fmt_num(v, 2) for v in df["Valeur par action"]], textposition="outside")
    )
    if result.get("price"):
        fig.add_hline(y=float(result["price"]), line_dash="dot", line_color=COLORS["warning"],
                      annotation_text="Cours actuel", annotation_font_color=COLORS["warning"])
    fig.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="Valeur par action (MAD)", showlegend=False)
    ui.plot(fig, key="val_scenario_bars")


# ═══════════════════════════ Monte-Carlo ═══════════════════════════


def _monte_carlo(result: Dict[str, Any], assumptions: Dict[str, Any], row: pd.Series) -> None:
    ui.section("Simulation Monte-Carlo", "Distribution de la valeur intrinsèque sous incertitude.")
    mc = forecast.monte_carlo_valuation(
        float(result["fcf_start"]),
        float(assumptions["growth"]),
        float(assumptions["discount_rate"]),
        float(assumptions["net_debt"]),
        shares=assumptions.get("shares"),
        years=int(assumptions["years"]),
        terminal_growth=float(assumptions["growth_terminal"]),
        n_sims=4000,
        price=result.get("price"),
    )
    ui.kpi_row(
        [
            {"label": "Médiane", "value": fmt_num(mc.get("median"), 2) + " MAD",
             "sub": "valeur centrale", "tone": "accent"},
            {"label": "Intervalle 10–90 %", "value": f"{fmt_num(mc.get('p10'), 1)} – {fmt_num(mc.get('p90'), 1)}",
             "sub": "fourchette de confiance", "tone": "blue"},
            {"label": "Probabilité de sous-évaluation",
             "value": fmt_pct(mc.get("prob_undervalued"), 0),
             "sub": "valeur > cours", "tone": "up" if (mc.get("prob_undervalued") or 0) > 0.5 else "warn"},
        ],
        per_row=3,
    )

    raw_values = mc.get("values")
    values = np.asarray(raw_values if raw_values is not None else [], dtype=float)
    if values.size == 0:
        return
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(x=values, nbinsx=60, marker_color=COLORS["accent"], opacity=0.75, name="Simulations")
    )
    price = result.get("price")
    if price:
        fig.add_vline(x=float(price), line_color=COLORS["warning"], line_width=2,
                      annotation_text="Cours actuel", annotation_font_color=COLORS["warning"])
    fig.add_vline(x=float(mc["median"]), line_color=COLORS["primary"], line_width=2, line_dash="dot",
                  annotation_text="Médiane", annotation_font_color=COLORS["primary"])
    fig.update_layout(height=360, xaxis_title="Valeur par action (MAD)", yaxis_title="Fréquence",
                      showlegend=False, margin=dict(l=10, r=10, t=20, b=10))
    ui.plot(fig, key="val_montecarlo")


# ═══════════════════════════ Valorisation relative ═══════════════════════════


def _relative(row: pd.Series, symbol: str) -> None:
    ui.section("Valorisation relative", "Ratios de la société comparés à la médiane de son secteur.")
    f = fundamentals.get_fundamentals(symbol, row)
    ratios = fundamentals.compute_ratios(f, price=row.get("close"), cap=row.get("cap"))
    sector = str(row.get("sector") or "")
    keys = [
        ("per", "P/E", "x"),
        ("pb", "P/B", "x"),
        ("roe", "ROE", "%"),
        ("net_margin", "Marge nette", "%"),
        ("dividend_yield", "Rendement du dividende", "%"),
    ]
    rows = []
    for key, label, unit in keys:
        value = ratios.get(key)
        median = fundamentals.sector_median_ratios(sector, shared.market_table(), key)
        rows.append(
            {
                "Ratio": label,
                "Société": _fmt_value(value, unit),
                "Médiane du secteur": _fmt_value(median, unit),
                "Écart": _fmt_value((value - median) if (value is not None and median not in (None, 0)) else None, unit),
            }
        )
    ui.table(pd.DataFrame(rows), height=240, key="val_relative")
    st.caption(
        "La médiane sectorielle est calculée uniquement sur les sociétés dont le ratio est "
        "calculable — donc sur les données réellement renseignées."
    )


def _fmt_value(value: Optional[float], unit: str) -> str:
    if value is None:
        return "—"
    return fmt_pct(value, 2) if unit == "%" else fmt_num(value, 2)
