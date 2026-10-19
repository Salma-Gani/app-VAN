"""Profil de l'investisseur : revenus, patrimoine, tolérance au risque et portefeuille détenu."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...config import COLORS
from ...portfolio import profile as profile_mod
from ...portfolio import simulate
from ...utils.formatting import fmt_money, fmt_num, fmt_pct
from .. import charts, components as ui
from . import shared

_LEVEL_TONE = {"good": "up", "warn": "warn", "danger": "down", "info": "info"}
_LEVEL_ICON = {"good": "✅", "warn": "⚠️", "danger": "⛔", "info": "💡"}


def render() -> None:
    profile = shared.get_profile()

    ui.hero(
        "Mon patrimoine",
        "Revenus, charges, patrimoine et tolérance au risque : ces informations pilotent "
        "l'allocation cible, les recommandations et les simulations.",
        badge=ui.badge(profile.investor_type()["label"], _type_tone(profile)),
    )

    ui.note(
        "**Confidentialité** : vos revenus, actifs, dettes et positions restent stockés localement "
        "dans `data/user/`. Ils ne sont jamais envoyés à un modèle de langage sans votre accord explicite "
        "(onglet Configuration de Market Mind AI).",
        "info", "🔒",
    )

    _kpis(profile)
    st.divider()
    _diagnostics(profile)
    st.divider()
    _form(profile)
    st.divider()
    _holdings(profile)
    ui.disclaimer()


# ═══════════════════════════ Indicateurs ═══════════════════════════


def _kpis(profile: profile_mod.InvestorProfile) -> None:
    items = [
        {"label": "Revenu mensuel net", "value": fmt_money(profile.monthly_income, "MAD", decimals=0),
         "sub": f"salaire {fmt_money(profile.salary_monthly, 'MAD', decimals=0)} + autres",
         "tone": "accent"},
        {"label": "Capacité d'épargne", "value": fmt_money(profile.savings_capacity, "MAD", decimals=0),
         "sub": f"taux d'épargne {fmt_pct(profile.savings_rate, 0)}",
         "tone": "up" if (profile.savings_capacity or 0) > 0 else "down"},
        {"label": "Patrimoine net", "value": fmt_money(profile.net_worth, "MAD", compact=True),
         "sub": f"actifs {fmt_money(profile.gross_assets, 'MAD', compact=True)} − dettes "
                f"{fmt_money(profile.total_debt, 'MAD', compact=True)}",
         "tone": "blue"},
        {"label": "Épargne de précaution", "value": f"{fmt_num(profile.emergency_months, 1)} mois",
         "sub": "objectif : 6 mois de charges",
         "tone": "up" if (profile.emergency_months or 0) >= 6 else "warn"},
        {"label": "Part actions recommandée", "value": fmt_pct(profile.recommended_equity_share(), 0),
         "sub": f"actuelle {fmt_pct(profile.equity_share, 0)}", "tone": "accent"},
    ]
    ui.kpi_row(items, per_row=5)

    st.write("")
    left, right = st.columns([1, 1], gap="medium")
    with left:
        st.markdown("**Capacité vs tolérance au risque**")
        ui.plot(
            charts.radar(
                {
                    "Capacité objective": profile.risk_capacity_score() * 100,
                    "Tolérance déclarée": profile.risk_tolerance_score() * 100,
                    "Score global": profile.overall_risk_score() * 100,
                    "Horizon": min(profile.horizon_years / 20 * 100, 100),
                    "Épargne de précaution": min((profile.emergency_months or 0) / 9 * 100, 100),
                },
                title="Profil de risque (0–100)",
                height=340,
            ),
            key="profile_radar",
        )
    with right:
        itype = profile.investor_type()
        ui.verdict(
            f"Profil : {itype['label']}",
            f"{itype['desc']}\n\n"
            f"**Score de risque global : {profile.overall_risk_score():.0%}** "
            "(la contrainte la plus stricte entre capacité et tolérance).\n\n"
            f"Horizon : **{profile.horizon_years} ans** · drawdown maximal accepté : "
            f"**{profile.max_acceptable_drawdown:.0%}** · expérience : {profile.experience}/5.",
            itype.get("color"),
        )
        plan = simulate.objective_plan(profile)
        table = plan["table"]
        best = table.iloc[-1]
        ui.note(
            f"À **{fmt_money(plan['monthly'], 'MAD', decimals=0)}/mois** pendant "
            f"**{plan['years']} ans**, le capital projeté va de "
            f"**{fmt_money(table.iloc[0]['Capital projeté'], 'MAD', compact=True)}** (prudent) à "
            f"**{fmt_money(best['Capital projeté'], 'MAD', compact=True)}** (offensif) pour un "
            f"objectif de {fmt_money(profile.target_capital, 'MAD', compact=True)}.",
            "info", "🎯",
        )


def _diagnostics(profile: profile_mod.InvestorProfile) -> None:
    ui.section("Diagnostic patrimonial", "Alertes calculées à partir de votre situation déclarée.")
    diags = profile.diagnostics()
    if not diags:
        ui.note("Aucune alerte : votre situation ne présente pas de déséquilibre manifeste.", "up", "✅")
        return
    for diag in diags:
        level = str(diag.get("level") or "info")
        ui.note(f"**{diag.get('title')}** — {diag.get('text')}", _LEVEL_TONE.get(level, "info"),
                _LEVEL_ICON.get(level, "ℹ️"))


# ═══════════════════════════ Formulaire ═══════════════════════════


def _form(profile: profile_mod.InvestorProfile) -> None:
    ui.section("Mettre à jour ma situation", "Les modifications sont enregistrées localement sur votre machine.")

    with st.form("profile_form", clear_on_submit=False):
        st.markdown("#### 💰 Revenus et charges (mensuel)")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            salary = st.number_input("Salaire net mensuel (MAD)", min_value=0.0,
                                     value=float(profile.salary_monthly), step=500.0, format="%.0f")
        with c2:
            other = st.number_input("Autres revenus mensuels (MAD)", min_value=0.0,
                                    value=float(profile.other_income_monthly), step=500.0, format="%.0f")
        with c3:
            bonus = st.number_input("Prime annuelle (MAD)", min_value=0.0,
                                    value=float(profile.bonus_annual), step=1_000.0, format="%.0f")
        with c4:
            expenses = st.number_input("Dépenses courantes mensuelles (MAD)", min_value=0.0,
                                       value=float(profile.monthly_expenses), step=500.0, format="%.0f")
        c5, c6, c7, c8 = st.columns(4)
        with c5:
            rent = st.number_input("Loyer mensuel (MAD)", min_value=0.0,
                                   value=float(profile.rent_monthly), step=500.0, format="%.0f")
        with c6:
            loan = st.number_input("Mensualités de crédit (MAD)", min_value=0.0,
                                   value=float(profile.loan_monthly), step=500.0, format="%.0f")
        with c7:
            monthly_invest = st.number_input("Investissement mensuel prévu (MAD)", min_value=0.0,
                                             value=float(profile.monthly_investment), step=250.0, format="%.0f")
        with c8:
            horizon = st.number_input("Horizon d'investissement (années)", min_value=1, max_value=40,
                                      value=int(profile.horizon_years), step=1)

        st.markdown("#### 🏦 Patrimoine")
        c9, c10, c11, c12 = st.columns(4)
        with c9:
            cash = st.number_input("Liquidités (MAD)", min_value=0.0,
                                   value=float(profile.cash), step=5_000.0, format="%.0f")
        with c10:
            savings = st.number_input("Épargne / dépôts (MAD)", min_value=0.0,
                                      value=float(profile.savings), step=5_000.0, format="%.0f")
        with c11:
            equities = st.number_input("Portefeuille actions (MAD)", min_value=0.0,
                                       value=float(profile.equities_value), step=5_000.0, format="%.0f")
        with c12:
            other_assets = st.number_input("Autres actifs (MAD)", min_value=0.0,
                                           value=float(profile.other_assets), step=5_000.0, format="%.0f")
        c13, c14, c15, c16 = st.columns(4)
        with c13:
            real_estate = st.number_input("Immobilier (valeur, MAD)", min_value=0.0,
                                          value=float(profile.real_estate_value), step=10_000.0, format="%.0f")
        with c14:
            real_estate_debt = st.number_input("Crédit immobilier restant (MAD)", min_value=0.0,
                                               value=float(profile.real_estate_debt), step=10_000.0, format="%.0f")
        with c15:
            consumer_debt = st.number_input("Autres dettes (MAD)", min_value=0.0,
                                            value=float(profile.consumer_debt), step=5_000.0, format="%.0f")
        with c16:
            target_capital = st.number_input("Objectif patrimonial (MAD)", min_value=0.0,
                                             value=float(profile.target_capital), step=50_000.0, format="%.0f")

        st.markdown("#### 🧠 Objectifs et comportement")
        c17, c18, c19, c20 = st.columns(4)
        with c17:
            target_income = st.number_input("Revenu mensuel visé (MAD)", min_value=0.0,
                                            value=float(profile.target_monthly_income), step=500.0, format="%.0f")
        with c18:
            age = st.number_input("Âge", min_value=18, max_value=90, value=int(profile.age), step=1)
        with c19:
            dependents = st.number_input("Personnes à charge", min_value=0, max_value=15,
                                         value=int(profile.dependents), step=1)
        with c20:
            max_dd = st.slider("Drawdown maximal accepté (%)", 2, 60,
                               int(round(profile.max_acceptable_drawdown * 100)), 1) / 100.0

        c21, c22 = st.columns(2)
        with c21:
            risk_tolerance = st.select_slider(
                "Tolérance au risque",
                options=[1, 2, 3, 4, 5],
                value=int(profile.risk_tolerance),
                format_func=lambda v: {1: "1 — Très prudent", 2: "2 — Prudent", 3: "3 — Équilibré",
                                       4: "4 — Dynamique", 5: "5 — Très offensif"}[v],
            )
        with c22:
            experience = st.select_slider(
                "Expérience des marchés",
                options=[1, 2, 3, 4, 5],
                value=int(profile.experience),
                format_func=lambda v: {1: "1 — Débutant", 2: "2 — Initié", 3: "3 — Confirmé",
                                       4: "4 — Avancé", 5: "5 — Expert"}[v],
            )

        submitted = st.form_submit_button("💾 Enregistrer mon profil", use_container_width=True)

    if submitted:
        updated = profile_mod.InvestorProfile(
            salary_monthly=salary, other_income_monthly=other, bonus_annual=bonus,
            monthly_expenses=expenses, rent_monthly=rent, loan_monthly=loan,
            age=int(age), dependents=int(dependents), horizon_years=int(horizon),
            cash=cash, savings=savings, equities_value=equities, real_estate_value=real_estate,
            real_estate_debt=real_estate_debt, other_assets=other_assets, consumer_debt=consumer_debt,
            target_capital=target_capital, target_monthly_income=target_income,
            risk_tolerance=int(risk_tolerance), experience=int(experience),
            max_acceptable_drawdown=max_dd, monthly_investment=monthly_invest,
            holdings=profile.holdings,
        )
        shared.set_profile(updated)
        shared.recommendation.clear()
        st.success("Profil enregistré. Les recommandations et simulations sont recalculées.")
        st.rerun()


# ═══════════════════════════ Portefeuille détenu ═══════════════════════════


def _holdings(profile: profile_mod.InvestorProfile) -> None:
    ui.section(
        "Mon portefeuille détenu",
        "Déclarez vos lignes : elles seront valorisées aux cours réels et comparées aux meilleures opportunités.",
    )
    table = shared.market_table()
    symbols = sorted(table["symbol"].tolist()) if not table.empty else []

    current = profile_mod.holdings_frame(profile)
    if not current.empty:
        current = current.copy()
        current["quantity"] = pd.to_numeric(current.get("quantity"), errors="coerce").fillna(0.0)
        current["purchase_price"] = pd.to_numeric(current.get("purchase_price"), errors="coerce").fillna(0.0)
        if "purchase_date" not in current.columns:
            current["purchase_date"] = None
        current["purchase_date"] = pd.to_datetime(current["purchase_date"], errors="coerce")
    else:
        current = pd.DataFrame(
            [{"symbol": symbols[0] if symbols else "", "quantity": 0.0,
              "purchase_price": 0.0, "purchase_date": None}]
        )
    editor = current[["symbol", "quantity", "purchase_price", "purchase_date"]].copy()

    config: Dict[str, Any] = {}
    try:
        config = {
            "symbol": st.column_config.SelectboxColumn("Symbole", options=symbols, required=True),
            "quantity": st.column_config.NumberColumn("Quantité", min_value=0.0, step=1.0, format="%.0f"),
            "purchase_price": st.column_config.NumberColumn("Prix d'achat (MAD)", min_value=0.0, step=0.01,
                                                            format="%.2f"),
            "purchase_date": st.column_config.DateColumn("Date d'achat", format="DD/MM/YYYY"),
        }
    except Exception:
        config = {}

    edited = ui.data_editor(
        editor, num_rows="dynamic", hide_index=True,
        column_config=config, key="holdings_editor",
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("💾 Enregistrer le portefeuille", key="save_holdings", use_container_width=True):
            records: List[Dict[str, Any]] = []
            for _, r in edited.iterrows():
                symbol = str(r.get("symbol") or "").strip().upper()
                quantity = float(r.get("quantity") or 0.0)
                if not symbol or quantity <= 0:
                    continue
                purchase_date = r.get("purchase_date")
                if purchase_date is None or pd.isna(purchase_date):
                    iso_date = None
                elif hasattr(purchase_date, "isoformat"):
                    iso_date = purchase_date.strftime("%Y-%m-%d")
                else:
                    iso_date = str(purchase_date)
                records.append(
                    {
                        "symbol": symbol,
                        "name": str(table.loc[table["symbol"] == symbol, "name"].iloc[0])
                        if (not table.empty and (table["symbol"] == symbol).any()) else symbol,
                        "quantity": quantity,
                        "purchase_price": float(r.get("purchase_price") or 0.0),
                        "purchase_date": iso_date,
                    }
                )
            updated = profile_mod.InvestorProfile(**{**profile.to_dict(), "holdings": records})
            shared.set_profile(updated)
            shared.recommendation.clear()
            st.success(f"{len(records)} ligne(s) enregistrée(s).")
            st.rerun()
    with c2:
        if st.button("🗑️ Vider le portefeuille", key="clear_holdings", use_container_width=True):
            updated = profile_mod.InvestorProfile(**{**profile.to_dict(), "holdings": []})
            shared.set_profile(updated)
            shared.recommendation.clear()
            st.success("Portefeuille vidé.")
            st.rerun()

    enriched = shared.enriched_holdings(profile)
    if enriched.empty:
        ui.empty_state(
            "Aucune ligne enregistrée. Ajoutez vos positions ci-dessus pour activer la comparaison "
            "avec les meilleures opportunités du marché.",
            "💼",
        )
        return

    summary = profile_mod.portfolio_summary(enriched, profile)
    ui.kpi_row(
        [
            {"label": "Valeur de marché", "value": fmt_money(summary["value"], "MAD", compact=True),
             "sub": f"coût {fmt_money(summary['cost'], 'MAD', compact=True)}", "tone": "accent"},
            {"label": "Plus ou moins-value", "value": fmt_money(summary["pnl"], "MAD", compact=True),
             "sub": fmt_pct(summary["pnl_pct"], 1, signed=True),
             "tone": "up" if (summary["pnl"] or 0) >= 0 else "down"},
            {"label": "Positions", "value": str(summary["positions"]),
             "sub": f"{summary['sectors']} secteurs", "tone": "blue"},
            {"label": "Concentration", "value": fmt_pct(summary["concentration"], 0),
             "sub": "poids de la première ligne", "tone": "warn"},
            {"label": "Impôt latent (TPCVM)", "value": fmt_money(summary["taxes_latentes"], "MAD", compact=True),
             "sub": "si tout était vendu", "tone": "warn"},
        ],
        per_row=5,
    )

    left, right = st.columns([1.4, 1], gap="medium")
    with left:
        display = enriched[["symbol", "name", "sector", "quantity", "purchase_price", "price",
                            "value", "weight", "pnl", "pnl_pct"]].copy()
        display = display.rename(columns={
            "symbol": "Symbole", "name": "Société", "sector": "Secteur", "quantity": "Quantité",
            "purchase_price": "Prix d'achat", "price": "Cours", "value": "Valeur",
            "weight": "Poids", "pnl": "P/L (MAD)", "pnl_pct": "P/L (%)",
        })
        display["Prix d'achat"] = display["Prix d'achat"].apply(lambda v: fmt_num(v, 2))
        display["Cours"] = display["Cours"].apply(lambda v: fmt_num(v, 2))
        display["Valeur"] = display["Valeur"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        display["Poids"] = display["Poids"].apply(lambda v: fmt_pct(v, 1))
        display["P/L (MAD)"] = display["P/L (MAD)"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        display["P/L (%)"] = display["P/L (%)"].apply(lambda v: fmt_pct(v, 1, signed=True))
        ui.table(display, height=min(380, 60 + 34 * len(display)), key="profile_holdings")
    with right:
        by_sector = enriched.groupby("sector")["value"].sum().sort_values(ascending=False)
        weights = (by_sector / by_sector.sum()).to_dict()
        ui.plot(charts.donut(weights, title="Répartition par secteur", height=340), key="profile_donut")

    ui.note(
        "Ouvrez la page « Portefeuille & arbitrage » pour comparer cette allocation à la cible "
        "recommandée et obtenir le plan de rééquilibrage chiffré.",
        "info", "🧭",
    )
    _sector_vs_market(enriched)


def _sector_vs_market(enriched: pd.DataFrame) -> None:
    """Compare le poids des secteurs détenus à leur poids dans la capitalisation de la Bourse."""
    table = shared.market_table()
    if table.empty or enriched.empty or not {"sector", "cap"}.issubset(table.columns):
        return
    ui.section(
        "Allocation sectorielle : portefeuille vs marché",
        "Poids de chaque secteur dans le portefeuille, face à son poids dans la capitalisation BVC.",
    )
    pf = enriched.groupby("sector")["value"].sum()
    pf_w = pf / pf.sum() if pf.sum() else pf
    mkt = table.groupby("sector")["cap"].sum()
    mkt_w = mkt / mkt.sum() if mkt.sum() else mkt

    sectors = sorted(set(pf_w.index) | set(mkt_w.index))
    frame = pd.DataFrame(
        [
            {
                "Secteur": s,
                "Portefeuille %": float(pf_w.get(s, 0.0)) * 100,
                "Marché %": float(mkt_w.get(s, 0.0)) * 100,
                "Écart (pts)": (float(pf_w.get(s, 0.0)) - float(mkt_w.get(s, 0.0))) * 100,
            }
            for s in sectors
        ]
    ).sort_values("Portefeuille %", ascending=False)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=frame["Secteur"], y=frame["Portefeuille %"], name="Portefeuille",
                         marker_color=COLORS["primary"]))
    fig.add_trace(go.Bar(x=frame["Secteur"], y=frame["Marché %"], name="Marché (cap. BVC)",
                         marker_color=COLORS["muted"]))
    fig.update_layout(barmode="group", height=380, yaxis_title="Poids (%)", showlegend=True,
                      margin=dict(l=10, r=10, t=10, b=10))
    ui.plot(fig, key="profile_sector_vs_market")

    display = frame.copy()
    for col in ("Portefeuille %", "Marché %", "Écart (pts)"):
        display[col] = display[col].round(1)
    ui.table(display, height=min(360, 42 * (len(display) + 1)), key="profile_sector_table")
    ui.note(
        "Le poids « marché » reflète la part du secteur dans la capitalisation boursière totale — "
        "ce n'est **pas** une performance. Une surpondération signifie une exposition plus forte que "
        "le marché, pas un rendement supérieur attendu.",
        "info", "⚖️",
    )


# ═══════════════════════════ Utilitaires ═══════════════════════════


def _type_tone(profile: profile_mod.InvestorProfile) -> str:
    score = profile.overall_risk_score()
    if score >= 0.68:
        return "warn"
    if score < 0.45:
        return "info"
    return "up"
