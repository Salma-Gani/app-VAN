"""Portefeuille : allocation actuelle vs cible, arbitrages et recommandations comparées."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from ...config import BROKERAGE_FEE, COLORS
from ...portfolio import ledger, optimize, profile as profile_mod, simulate
from ...utils.formatting import fmt_money, fmt_num, fmt_pct
from .. import charts, components as ui
from . import shared


def render() -> None:
    profile = shared.get_profile()
    enriched = shared.enriched_holdings(profile)
    table = shared.market_table()
    classes = optimize.asset_classes()

    ui.hero(
        "Portefeuille & alternatives",
        "Comparez votre allocation actuelle à la cible recommandée, chiffrez les arbitrages et "
        "identifiez les meilleures opportunités du marché.",
        badge=ui.badge(profile.investor_type()["label"], "accent"),
    )

    ui.source_note(
        ["Vos positions (cours BVC)", "Hypothèses de coûts et de fiscalité"],
        detail="Frais de rééquilibrage estimés à 0,60 % des montants arbitrés ; fiscalité et rendements "
               "attendus affichés dans les tableaux. Aucune option n'est déclarée « meilleure » sur le seul rendement.",
    )

    current, current_value = _current_allocation(profile, enriched)
    target = optimize.target_allocation(profile, classes)
    if not current:
        ui.empty_state(
            "Renseignez votre patrimoine financier dans « Mon profil » pour activer l'analyse.",
            "💼",
        )
        return

    _kpis(profile, current, target, classes, current_value)
    st.divider()
    _allocation(current, target, classes)
    st.divider()
    _rebalancing(current_value, current, target)
    st.divider()
    _recommendation(profile, table)
    st.divider()
    _holdings_comparison(profile, enriched, table)
    st.divider()
    _ledger_section(table)
    ui.disclaimer()


# ═══════════════════════════ Journal d'opérations ═══════════════════════════


def _prices_from_table(table: pd.DataFrame) -> Dict[str, float]:
    """Cours de clôture réels par symbole (aucun cours inventé)."""
    prices: Dict[str, float] = {}
    if table is None or table.empty or "symbol" not in table.columns:
        return prices
    for _, row in table.iterrows():
        symbol = str(row.get("symbol") or "").upper()
        try:
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if symbol and pd.notna(close):
            prices[symbol] = close
    return prices


def _ledger_section(table: pd.DataFrame) -> None:
    ui.section(
        "Journal d'opérations",
        "Achats, ventes, dividendes, frais et mouvements de trésorerie : le coût de revient, "
        "les plus-values réalisées et latentes et le solde de trésorerie sont recalculés "
        "à partir des opérations saisies.",
    )
    ui.source_note(
        ["Opérations saisies par vous", "Cours BVC pour la valorisation"],
        detail="Méthode du coût moyen pondéré. Les frais d'achat sont inclus dans le coût de "
               "revient. Un cours manquant rend la plus-value latente indisponible : aucun "
               "cours n'est extrapolé.",
    )

    transactions = ledger.load_transactions()
    prices = _prices_from_table(table)

    with st.expander("➕ Ajouter une opération", expanded=not transactions):
        with st.form("ledger_form", clear_on_submit=True):
            row1 = st.columns(3)
            kind = row1[0].selectbox(
                "Type d'opération",
                options=list(ledger.KINDS),
                format_func=lambda key: ledger.KIND_LABELS[key],
            )
            tx_date = row1[1].date_input("Date", value=date.today())
            currency = row1[2].text_input("Devise", value="MAD")
            row2 = st.columns(3)
            symbol = row2[0].text_input("Symbole (achat / vente / dividende)", value="")
            quantity = row2[1].number_input("Quantité", min_value=0.0, step=1.0, value=0.0)
            price = row2[2].number_input("Prix unitaire", min_value=0.0, step=0.01, value=0.0)
            row3 = st.columns(2)
            amount = row3[0].number_input(
                "Montant (frais, apport, retrait, dividende)", min_value=0.0, step=1.0, value=0.0
            )
            fees = row3[1].number_input("Frais de l'opération", min_value=0.0, step=0.01, value=0.0)
            note = st.text_input("Note (facultatif)")
            submitted = st.form_submit_button("Enregistrer l'opération", type="primary")
        if submitted:
            payload = {
                "kind": kind,
                "date": tx_date.isoformat(),
                "symbol": symbol.strip().upper(),
                "quantity": quantity or None,
                "price": price or None,
                "amount": amount or None,
                "fees": fees or 0.0,
                "currency": currency.strip().upper() or "MAD",
                "note": note,
            }
            try:
                ledger.add_transaction(payload)
            except ledger.LedgerError as exc:
                st.error(f"Opération refusée : {exc}")
            else:
                st.success("Opération enregistrée.")
                st.rerun()

    if not transactions:
        ui.note(
            "Aucune opération enregistrée. Ajoutez un apport, puis vos achats et ventes : "
            "les positions et la performance seront calculées à partir du journal.",
            "warn", "📒",
        )
        return

    report = ledger.summary(transactions, prices)
    ui.kpi_row(
        [
            {"label": "Valeur des positions", "value": fmt_money(report["market_value"], "MAD"),
             "sub": f"{report['positions']} ligne(s)", "tone": "blue"},
            {"label": "Capital investi", "value": fmt_money(report["invested"], "MAD"),
             "sub": "coût de revient", "tone": "flat"},
            {"label": "Plus-value latente", "value": fmt_money(report["unrealized_pnl"], "MAD"),
             "sub": "cours disponibles", "tone": "up" if report["unrealized_pnl"] >= 0 else "down"},
            {"label": "Plus-value réalisée", "value": fmt_money(report["realized_pnl"], "MAD"),
             "sub": "ventes", "tone": "up" if report["realized_pnl"] >= 0 else "down"},
            {"label": "Trésorerie", "value": fmt_money(report["cash"], "MAD"),
             "sub": "flux enregistrés", "tone": "accent"},
        ],
        per_row=5,
    )

    if report["missing_prices"]:
        ui.note(
            "Cours indisponible pour : " + ", ".join(report["missing_prices"]) +
            ". La plus-value latente de ces lignes n'est pas calculée (aucun cours inventé) "
            "et le total de valeur les exclut.",
            "warn", "⚠️",
        )

    positions = ledger.compute_positions(transactions)
    oversold = [issue for position in positions.values() for issue in position["issues"]]
    for issue in oversold:
        st.warning(issue)

    frame = ledger.positions_frame(positions, prices)
    if not frame.empty:
        display = frame.copy()
        for column in ("Coût de revient moyen", "Investi", "Cours", "Valeur",
                       "Plus-value latente", "Dividendes", "Frais", "Plus-value réalisée"):
            display[column] = display[column].apply(
                lambda value: fmt_money(value, "MAD") if pd.notna(value) else "—"
            )
        display["Quantité"] = display["Quantité"].apply(
            lambda value: fmt_num(value, 0) if pd.notna(value) else "—"
        )
        ui.table(display, height=320, key="ledger_positions")

    with st.expander("Historique des opérations", expanded=False):
        history = ledger.transactions_frame(transactions)
        ui.table(history, height=340, key="ledger_history")
        labels = {
            tx["id"]: f"{tx['date']} · {ledger.KIND_LABELS[tx['kind']]} · {tx.get('symbol') or '—'}"
            for tx in transactions
        }
        to_delete = st.selectbox(
            "Supprimer une opération", options=[""] + list(labels), format_func=lambda key: labels.get(key, "—"),
            key="ledger_delete_select",
        )
        if to_delete and st.button("Supprimer définitivement", key="ledger_delete_button"):
            if ledger.delete_transaction(to_delete):
                st.success("Opération supprimée.")
                st.rerun()
            else:
                st.error("Opération introuvable : le journal n'a pas été modifié.")


# ═══════════════════════════ Allocation actuelle ═══════════════════════════


def _current_allocation(profile: Any, enriched: pd.DataFrame) -> tuple:
    if enriched is not None and not enriched.empty:
        equity_value = float(enriched["value"].sum())
        equity_weights = optimize.allocation_from_holdings(enriched)
    else:
        equity_value = float(profile.equities_value)
        equity_weights = {"BVC_SELECT": 1.0} if equity_value > 0 else {}

    total = float(profile.cash + profile.savings + equity_value + profile.other_assets)
    if total <= 0:
        return {}, 0.0

    current: Dict[str, float] = {}
    for code, weight in equity_weights.items():
        current[code] = current.get(code, 0.0) + weight * equity_value / total
    if profile.cash:
        current["CASH"] = current.get("CASH", 0.0) + profile.cash / total
    if profile.savings:
        current["DEPOSIT"] = current.get("DEPOSIT", 0.0) + profile.savings / total
    if profile.other_assets:
        current["GLOBAL_EQ"] = current.get("GLOBAL_EQ", 0.0) + profile.other_assets / total
    return current, total


def _kpis(profile: Any, current: Dict[str, float], target: Dict[str, float],
          classes: List[Any], value: float) -> None:
    c_ret, c_vol, c_sharpe = optimize.portfolio_risk(current, classes)
    t_ret, t_vol, t_sharpe = optimize.portfolio_risk(target, classes)
    equity_codes = {"BVC_MASI", "BVC_BLUECHIP", "BVC_SELECT", "GLOBAL_EQ"}
    c_equity = sum(v for k, v in current.items() if k in equity_codes)
    t_equity = sum(v for k, v in target.items() if k in equity_codes)

    ui.kpi_row(
        [
            {"label": "Patrimoine financier", "value": fmt_money(value, "MAD", compact=True),
             "sub": "hors immobilier", "tone": "accent"},
            {"label": "Exposition actions actuelle", "value": fmt_pct(c_equity, 0),
             "sub": f"cible {fmt_pct(t_equity, 0)}",
             "tone": "warn" if abs(c_equity - t_equity) > 0.15 else "up"},
            {"label": "Rendement attendu (actuel)", "value": fmt_pct(c_ret, 2),
             "sub": f"cible {fmt_pct(t_ret, 2)}", "tone": "blue"},
            {"label": "Volatilité (actuelle)", "value": fmt_pct(c_vol, 2),
             "sub": f"cible {fmt_pct(t_vol, 2)}",
             "tone": "down" if c_vol > t_vol * 1.15 else "up"},
            {"label": "Sharpe (actuel)", "value": fmt_num(c_sharpe, 2),
             "sub": f"cible {fmt_num(t_sharpe, 2)}", "tone": "accent"},
        ],
        per_row=5,
    )

    hhi_current = sum(v * v for v in current.values())
    hhi_target = sum(v * v for v in target.values())
    effective_current = 1 / hhi_current if hhi_current else 0.0
    effective_target = 1 / hhi_target if hhi_target else 0.0
    hist = shared.index_history("MASI", "5Y")
    drawdown = _max_drawdown(hist["value"]) if hist is not None and not hist.empty else None
    detail = (
        f"**Concentration** : {effective_current:.1f} classes d'actifs équivalentes aujourd'hui, "
        f"{effective_target:.1f} en cible (indice de Herfindahl)."
    )
    if drawdown is not None:
        detail += (f" **Drawdown maximal du MASI sur 5 ans** : {fmt_pct(drawdown, 1)} — "
                   "repère historique, pas une prévision.")
    ui.note(detail, "info", "📐")


def _max_drawdown(values: Any) -> Optional[float]:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if series.empty:
        return None
    peak = series.cummax()
    return float((series / peak - 1.0).min())


# ═══════════════════════════ Graphiques d'allocation ═══════════════════════════


def _allocation(current: Dict[str, float], target: Dict[str, float], classes: List[Any]) -> None:
    labels = {c.code: c.label for c in classes}
    current_labels = {labels.get(k, k): v for k, v in current.items() if v > 0.001}
    target_labels = {labels.get(k, k): v for k, v in target.items() if v > 0.001}

    ui.section("Allocation actuelle vs cible", "Chaque poche est exprimée en pourcentage du patrimoine financier.")
    left, right = st.columns(2, gap="medium")
    with left:
        ui.plot(charts.donut(current_labels, title="Allocation actuelle", height=380), key="pb_donut_current")
    with right:
        ui.plot(charts.donut(target_labels, title="Allocation cible recommandée", height=380),
                key="pb_donut_target")

    diff = optimize.compare_allocations(current, target, classes)
    fig = charts.stacked_allocation(current, target, height=320)
    ui.plot(fig, key="pb_stacked")

    display = diff.copy()
    display["Actuel"] = display["Actuel"].apply(lambda v: fmt_pct(v, 1))
    display["Recommandé"] = display["Recommandé"].apply(lambda v: fmt_pct(v, 1))
    display["Écart"] = display["Écart"].apply(lambda v: fmt_pct(v, 1, signed=True))
    display = display[["Classe d'actifs", "Actuel", "Recommandé", "Écart", "Action"]]
    ui.table(display, height=min(400, 60 + 34 * len(display)), key="pb_compare")


# ═══════════════════════════ Rééquilibrage ═══════════════════════════


def _rebalancing(value: float, current: Dict[str, float], target: Dict[str, float]) -> None:
    ui.section(
        "Plan de rééquilibrage",
        "Montants à arbitrer pour rejoindre l'allocation cible, et frais de courtage estimés.",
    )
    plan = optimize.rebalancing_plan(value, current, target)
    if plan.empty:
        ui.empty_state("Aucun arbitrage nécessaire.", "✅")
        return

    display = plan.copy()
    display["Actuel"] = display["Actuel"].apply(lambda v: fmt_pct(v, 1))
    display["Recommandé"] = display["Recommandé"].apply(lambda v: fmt_pct(v, 1))
    display["Écart"] = display["Écart"].apply(lambda v: fmt_pct(v, 1, signed=True))
    for col in ("Actuel (MAD)", "Recommandé (MAD)", "À arbitrer (MAD)", "Frais estimés (MAD)"):
        if col in display.columns:
            display[col] = display[col].apply(lambda v: fmt_money(v, "MAD", compact=True))
    ui.table(display, height=min(440, 60 + 34 * len(display)), key="pb_rebalancing")

    actions = plan[plan["Action"] != "Statu quo"]
    if actions.empty:
        ui.note("Votre allocation est déjà alignée sur la cible : aucun arbitrage n'est requis.", "up", "✅")
        return
    st.markdown("**Actions prioritaires**")
    for _, row in actions.head(6).iterrows():
        amount = abs(float(row.get("À arbitrer (MAD)") or 0.0))
        label = str(row["Classe d'actifs"])
        if row["Action"] == "Renforcer":
            ui.note(
                f"Renforcer **{label}** de {fmt_money(amount, 'MAD', compact=True)} "
                f"({fmt_pct(row['Écart'], 1, signed=True)} de l'allocation).",
                "up", "➕",
            )
        else:
            ui.note(
                f"Alléger **{label}** de {fmt_money(amount, 'MAD', compact=True)} "
                f"({fmt_pct(row['Écart'], 1, signed=True)} de l'allocation).",
                "warn", "➖",
            )
    total_fees = float(plan.get("Frais estimés (MAD)", pd.Series(dtype=float)).abs().sum())
    ui.note(
        f"Frais de courtage estimés pour l'ensemble des arbitrages : **{fmt_money(total_fees, 'MAD', compact=True)}** "
        f"({BROKERAGE_FEE:.2%} par aller-retour). Fractionnez les ordres pour limiter l'impact de marché.",
        "info", "🧾",
    )


# ═══════════════════════════ Recommandation ═══════════════════════════


def _recommendation(profile: Any, table: pd.DataFrame) -> None:
    ui.section(
        "Recommandation comparée",
        "Votre placement actuel est confronté à la meilleure alternative disponible pour votre profil.",
    )
    amount = max(float(profile.monthly_investment) * 12, 10_000.0)
    years = int(profile.horizon_years)
    rec = simulate.recommend(profile, table, amount=amount, years=years)
    narrative = simulate.narrative_recommendation(rec, profile)
    ui.verdict(narrative["title"], narrative["body"], narrative.get("color"))

    left, right = st.columns([1.2, 1], gap="medium")
    with left:
        target_table = rec["target_table"].copy()
        display = target_table[["Classe d'actifs", "Poids", "Rendement attendu", "Contribution rendement",
                                "Liquidité", "Source"]].copy()
        display["Poids"] = display["Poids"].apply(lambda v: fmt_pct(v, 1))
        display["Rendement attendu"] = display["Rendement attendu"].apply(lambda v: fmt_pct(v, 2))
        display["Contribution rendement"] = display["Contribution rendement"].apply(lambda v: fmt_pct(v, 2))
        ui.table(display, height=min(360, 60 + 34 * len(display)), key="pb_target_table")
    with right:
        ui.note(
            f"Portefeuille diversifié cible : **{fmt_pct(rec['portfolio_return'], 2)}** de rendement "
            f"attendu pour **{fmt_pct(rec['portfolio_volatility'], 2)}** de volatilité "
            f"(Sharpe {fmt_num(rec['portfolio_sharpe'], 2)}).",
            "info", "📐",
        )
        options = rec["options"].head(7)
        cols = ["Option", "Score profil", "Rendement net", "Volatilité", "Frais estimés",
                "Valeur nette finale", "Verdict"]
        display = options[[c for c in cols if c in options.columns]].copy()
        for col in ("Rendement net", "Volatilité"):
            if col in display.columns:
                display[col] = display[col].apply(lambda v: fmt_pct(v, 2))
        if "Frais estimés" in display.columns:
            display["Frais estimés"] = display["Frais estimés"].apply(
                lambda v: fmt_money(v, "MAD", compact=True)
            )
        if "Valeur nette finale" in display.columns:
            display["Valeur nette finale"] = display["Valeur nette finale"].apply(
                lambda v: fmt_money(v, "MAD", compact=True)
            )
        if "Score profil" in display.columns:
            display["Score profil"] = display["Score profil"].apply(lambda v: fmt_num(v, 0))
        ui.table(display, height=min(360, 60 + 34 * len(display)), key="pb_options")

    best = rec.get("best") or {}
    by_return = rec["options"].sort_values("Rendement net", ascending=False).iloc[0]
    if best and str(by_return.get("Option")) != str(best.get("Option")):
        ui.note(
            f"L'option au **rendement net le plus élevé** est « {by_return.get('Option')} » "
            f"({fmt_pct(by_return.get('Rendement net'), 2)}), mais elle n'est pas la mieux classée : "
            f"« {best.get('Option')} » obtient un meilleur score d'adéquation une fois la volatilité, "
            "l'horizon et votre tolérance au risque pris en compte. Le rendement seul ne suffit pas.",
            "warn", "⚖️",
        )

    st.write("")
    ui.section(
        "Opportunités du marché",
        "Meilleures valeurs du screener — à intégrer dans la poche actions, en respectant la taille de position.",
    )
    picks = rec.get("stock_picks") or []
    if not picks:
        ui.empty_state("Aucune opportunité identifiée pour le moment.", "🔍")
        return
    rows = []
    for p in picks:
        plan = p.get("entry_plan") or {}
        rows.append(
            {
                "Symbole": p.get("symbol"),
                "Société": p.get("name"),
                "Secteur": p.get("sector"),
                "Cours": fmt_num(p.get("close"), 2),
                "Score": fmt_num(p.get("score"), 0),
                "Signal": p.get("signal"),
                "P/E": fmt_num(p.get("per"), 1),
                "Rdt dividende": fmt_pct(p.get("dividend_yield"), 2),
                "Stop": fmt_num(plan.get("stop"), 2),
                "Objectif": fmt_num(plan.get("objectif"), 2),
            }
        )
    ui.table(pd.DataFrame(rows), height=min(440, 60 + 34 * len(rows)), key="pb_picks")
    ui.note(
        "Le plan d'entrée (stop, objectif) est calculé à partir de la volatilité observée. "
        "Dimensionnez chaque ligne selon votre tolérance au risque, sans dépasser 10–15 % du "
        "portefeuille par valeur.",
        "info", "🎯",
    )


# ═══════════════════════════ Portefeuille détenu ═══════════════════════════


def _holdings_comparison(profile: Any, enriched: pd.DataFrame, table: pd.DataFrame) -> None:
    ui.section(
        "Vos lignes face au marché",
        "Chaque position est comparée à la meilleure opportunité actuelle du screener.",
    )
    if enriched is None or enriched.empty:
        ui.empty_state("Déclarez vos lignes dans « Mon profil » pour activer cette comparaison.", "💼")
        return
    comparison = simulate.holding_comparison(profile, enriched, table)
    if comparison.empty:
        ui.empty_state("Comparaison indisponible.", "📊")
        return
    display = comparison.copy()
    display["Valeur (MAD)"] = display["Valeur (MAD)"].apply(lambda v: fmt_money(v, "MAD", compact=True))
    display["Poids"] = display["Poids"].apply(lambda v: fmt_pct(v, 1))
    display["Plus-value"] = display["Plus-value"].apply(lambda v: fmt_pct(v, 1, signed=True))
    display["Score composite"] = display["Score composite"].apply(lambda v: fmt_num(v, 0))
    display["Score meilleure"] = display["Score meilleure"].apply(lambda v: fmt_num(v, 0))
    display["Écart de score"] = display["Écart de score"].apply(lambda v: fmt_num(v, 1, ))
    ui.table(display, height=min(420, 60 + 34 * len(display)), key="pb_holdings")

    best = comparison.iloc[0]
    if float(best.get("Écart de score") or 0) > 10:
        ui.note(
            f"**{best['Symbole']}** affiche le plus grand écart de score face à **{best['Meilleure opportunité']}** "
            f"({fmt_num(best['Écart de score'], 1)} points). Étudiez un arbitrage partiel si votre "
            "thèse d'investissement n'est plus valide.",
            "warn", "🔁",
        )
    else:
        ui.note("Vos lignes restent compétitives face aux meilleures opportunités du marché.", "up", "✅")
