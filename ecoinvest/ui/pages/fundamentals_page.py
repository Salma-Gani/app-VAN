"""Saisie et import des données fondamentales (états financiers) par société."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...config import COLORS
from ...data import fundamentals
from ...utils.formatting import as_float, fmt_money, fmt_num, fmt_pct
from .. import components as ui
from . import shared

_PERCENT_FIELDS = {"payout", "revenue_growth", "net_income_growth", "fcf_growth"}
_TEXT_FIELDS = {"fiscal_year", "source", "as_of"}


def render() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles.", "📡")
        return

    coverage = shared.coverage()
    filled = int((coverage["% complétion"] > 0).sum()) if not coverage.empty else 0
    average = float(coverage["% complétion"].mean()) if not coverage.empty else 0.0

    ui.hero(
        "Données fondamentales",
        "Renseignez les états financiers des sociétés cotées : les ratios, la valorisation DCF et "
        "les signaux fondamentaux sont calculés automatiquement.",
        badge=ui.badge(f"{filled} / {len(coverage)} sociétés renseignées", "info"),
    )

    ui.kpi_row(
        [
            {"label": "Sociétés couvertes", "value": f"{filled}", "sub": f"sur {len(coverage)}",
             "tone": "accent"},
            {"label": "Complétion moyenne", "value": fmt_pct(average, 1),
             "sub": "des champs numériques", "tone": "blue"},
            {"label": "Champs par société", "value": str(len(fundamentals.NUMERIC_FIELDS)),
             "sub": "compte de résultat, bilan, trésorerie", "tone": "info"},
            {"label": "Source des données", "value": "Vous", "sub": "aucune donnée inventée",
             "tone": "warn"},
        ],
        per_row=4,
    )

    tabs = st.tabs(["✍️ Saisie", "📥 Import CSV", "📊 Couverture", "📖 Mode d'emploi"])
    with tabs[0]:
        _editor(table)
    with tabs[1]:
        _import()
    with tabs[2]:
        _coverage(coverage)
    with tabs[3]:
        _help()
    ui.disclaimer()


# ═══════════════════════════ Saisie ═══════════════════════════


def _editor(table: pd.DataFrame) -> None:
    symbols = table["symbol"].tolist()
    names = dict(zip(table["symbol"], table["name"]))
    requested = str(st.session_state.get("selected_symbol") or "").upper()
    index = symbols.index(requested) if requested in symbols else 0
    symbol = st.selectbox(
        "Société", symbols, index=index,
        format_func=lambda s: f"{s} — {names.get(s, s)}", key="funda_symbol",
    )
    record = fundamentals.get_record(symbol)
    row = table[table["symbol"] == symbol].iloc[0]

    ui.note(
        f"Exercice de référence : **{record.get('fiscal_year') or 'non renseigné'}** · "
        f"source : **{record.get('source') or '—'}** · dernière mise à jour : "
        f"**{record.get('as_of') or '—'}**.",
        "info", "🗂️",
    )

    ref = fundamentals.market_reference().get(symbol, {}) or {}
    if ref.get("shares") or ref.get("dps"):
        bits = []
        if ref.get("isin"):
            bits.append(f"ISIN {ref['isin']}")
        if ref.get("shares"):
            bits.append(f"{fmt_num(ref['shares'], 0)} titres")
        if ref.get("dps"):
            bits.append(
                f"dernier dividende {fmt_num(ref['dps'], 2)} MAD"
                + (f" ({ref.get('dps_year')})" if ref.get("dps_year") else "")
            )
        ui.note(
            "Référentiel officiel BVC chargé automatiquement : " + " · ".join(bits) + ".",
            "up", "🏛️",
        )

    ratios = fundamentals.compute_ratios(
        fundamentals.get_fundamentals(symbol, row), price=row.get("close"), cap=row.get("cap")
    )
    computed = sum(1 for v in ratios.values() if v is not None)
    st.caption(f"{computed} ratios calculables avec les données actuellement enregistrées.")

    with st.form(f"funda_form_{symbol}"):
        values: Dict[str, Any] = {}
        groups: List[str] = []
        for field in fundamentals.FIELD_SCHEMA:
            if field["group"] not in groups:
                groups.append(field["group"])

        for group in groups:
            fields = [f for f in fundamentals.FIELD_SCHEMA if f["group"] == group]
            st.markdown(f"#### {group}")
            cols = st.columns(4)
            for i, field in enumerate(fields):
                key = field["key"]
                with cols[i % 4]:
                    values[key] = _field_input(field, record.get(key), symbol)

        submitted = st.form_submit_button("💾 Enregistrer les données", use_container_width=True)

    if submitted:
        cleaned: Dict[str, Any] = {}
        for key, raw in values.items():
            if raw in (None, ""):
                continue
            if key in _TEXT_FIELDS:
                cleaned[key] = str(raw).strip()
            else:
                value = as_float(str(raw).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                if value is None:
                    continue
                cleaned[key] = value / 100.0 if key in _PERCENT_FIELDS else value
        fundamentals.save_override(symbol, cleaned)
        _invalidate()
        st.success(f"Données enregistrées pour {symbol}. Les scores et ratios sont recalculés.")
        st.rerun()

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("🗑️ Effacer les données de cette société", key="funda_delete"):
            fundamentals.delete_override(symbol)
            _invalidate()
            st.success(f"Données supprimées pour {symbol}.")
            st.rerun()
    with c2:
        if st.button("🔄 Recalculer les scores", key="funda_refresh"):
            _invalidate()
            st.rerun()
    with c3:
        ui.download_row(
            fundamentals.ratio_table(
                fundamentals.get_fundamentals(symbol, row), price=row.get("close"), cap=row.get("cap")
            ),
            f"ratios_{symbol}.csv", "⬇️ Exporter les ratios", key="funda_export",
        )

    if computed:
        _preview(symbol, row)


def _field_input(field: Dict[str, Any], current: Any, symbol: str) -> str:
    key = field["key"]
    label = f"{field['label']} ({field['unit']})" if field["unit"] else field["label"]
    value = "" if current is None else str(current)
    if key in _PERCENT_FIELDS and current is not None:
        try:
            value = f"{float(current) * 100:.2f}"
        except (TypeError, ValueError):
            value = ""
    return st.text_input(label, value=value, key=f"f_{symbol}_{key}", help=field.get("hint") or None)


def _preview(symbol: str, row: pd.Series) -> None:
    st.divider()
    ui.section("Ratios calculés", "Aperçu immédiat des ratios disponibles avec les données enregistrées.")
    f = fundamentals.get_fundamentals(symbol, row)
    table = fundamentals.ratio_table(f, price=row.get("close"), cap=row.get("cap"))
    table = table[table["Valeur"].notna()].copy()
    if table.empty:
        ui.empty_state("Aucun ratio calculable pour l'instant.", "🧮")
        return
    display = table[["Ratio", "Valeur", "Unit", "Appréciation", "Interprétation"]].copy()
    display["Valeur"] = [
        fmt_pct(v, 2) if u == "%" else fmt_num(v, 2) for v, u in zip(display["Valeur"], display["Unit"])
    ]
    display = display.drop(columns=["Unit"])
    ui.table(display, height=min(420, 60 + 34 * len(display)), key="funda_preview")


# ═══════════════════════════ Import CSV ═══════════════════════════


def _import() -> None:
    ui.section(
        "Import en masse",
        "Un fichier CSV avec une ligne par société. La première colonne doit être le symbole BVC.",
    )
    st.download_button(
        "⬇️ Télécharger le modèle CSV",
        fundamentals.template_csv().encode("utf-8-sig"),
        "modele_fondamentaux.csv",
        "text/csv",
        key="funda_template",
    )
    st.caption("Le modèle contient une ligne d'exemple : remplacez-la par vos données.")

    uploaded = st.file_uploader("Fichier CSV", type=["csv"], key="funda_upload")
    if uploaded is None:
        return
    try:
        preview = pd.read_csv(uploaded, sep=None, engine="python", nrows=8)
        st.markdown("**Aperçu**")
        ui.table(preview, height=240, key="funda_upload_preview")
    except Exception as exc:
        st.error(f"Lecture impossible : {exc}")
        return

    if st.button("📥 Importer les données", key="funda_import_btn"):
        uploaded.seek(0)
        result = fundamentals.import_csv(uploaded.read())
        _invalidate()
        if result["errors"]:
            st.warning(f"{result['imported']} société(s) importée(s), {len(result['errors'])} erreur(s).")
            for err in result["errors"][:10]:
                st.caption(f"• {err}")
        else:
            st.success(f"{result['imported']} société(s) importée(s) avec succès.")
        st.rerun()


# ═══════════════════════════ Couverture ═══════════════════════════


def _coverage(coverage: pd.DataFrame) -> None:
    if coverage.empty:
        ui.empty_state("Rapport de couverture indisponible.", "📊")
        return
    ui.section(
        "Taux de complétion",
        "Champs numériques renseignés par société. Objectif : couvrir au moins les 8 sociétés "
        "les plus capitalisées pour des signaux représentatifs.",
    )
    display = coverage.copy()
    display["% complétion"] = display["% complétion"].apply(lambda v: fmt_pct(v, 0))
    ui.table(display.head(40), height=460, key="funda_coverage")

    fig = go.Figure(
        go.Histogram(
            x=coverage["% complétion"], nbinsx=20, marker_color=COLORS["accent"], opacity=0.8,
        )
    )
    fig.update_layout(height=280, xaxis_title="Complétion des données", yaxis_title="Nombre de sociétés",
                      xaxis_tickformat=".0%", showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
    ui.plot(fig, key="funda_coverage_hist")

    missing = coverage[coverage["% complétion"] == 0]
    if not missing.empty:
        ui.note(
            f"**{len(missing)} sociétés** n'ont aucune donnée fondamentale. Leurs signaux reposent "
            "uniquement sur le marché et la technique — ils sont marqués « technique seul ».",
            "warn", "⚠️",
        )


# ═══════════════════════════ Aide ═══════════════════════════


def _help() -> None:
    ui.section("D'où viennent les données ?", "Transparence totale sur la provenance de chaque chiffre.")
    st.markdown(
        """
**1. Données de marché — réelles et automatiques**

Cours, volumes, capitalisation, plus hauts/bas 52 semaines et historiques proviennent de
l'API publique de la Bourse de Casablanca (`casablanca-bourse.com/api/boursenova`). Le VIX,
les indices internationaux, l'or, le pétrole et les devises proviennent de Yahoo Finance.
Les actualités proviennent de flux RSS publics.

**2. Données fondamentales — BVC + saisie**

Deux champs sont récupérés **automatiquement et réellement** depuis les pages publiques de la
Bourse de Casablanca : le **nombre de titres** (page « actions ») et le **dividende par action**
(calendrier financier). Ils alimentent le rendement du dividende et la capitalisation.

En revanche, la BVC ne publie pas de P/E, de résultat net, de chiffre d'affaires ni de fonds
propres via son API. Ces informations doivent être extraites des **rapports annuels** ou des
**états financiers AMMC**, puis saisies ici. L'application ne les invente jamais.

**3. Ce qui est calculé automatiquement**

Dès que vous renseignez le résultat net, les capitaux propres, le chiffre d'affaires, le FCF
ou le dividende par action, l'application calcule : P/E, P/B, P/S, EV/EBITDA, rendement du
dividende, ROE, ROA, marges, levier, ratio de liquidité, rendement du FCF, croissance — puis
les confronte aux médianes sectorielles et les intègre au score composite.

**4. Conseil de saisie**

| Champ | Où le trouver |
|---|---|
| Chiffre d'affaires, résultat net, EBITDA | Compte de résultat consolidé |
| Capitaux propres, dette, trésorerie | Bilan |
| FCF, cash-flow d'exploitation, capex | Tableau des flux de trésorerie |
| Dividende par action | Rapport annuel / avis de l'AG |
| Nombre de titres | Déduit automatiquement de la capitalisation |

**5. Format des pourcentages**

Saisissez `8` pour 8 %. L'application convertit en fraction (0,08) pour les calculs.

Les champs laissés vides restent `None` : aucun ratio n'est extrapolé.
        """
    )
    ui.note(
        "Les données sont stockées uniquement sur votre machine, dans "
        "`data/user/fundamentals_overrides.json`. Aucune donnée n'est envoyée à un serveur.",
        "info", "🔒",
    )


# ═══════════════════════════ Utilitaires ═══════════════════════════


def _invalidate() -> None:
    """Purge les caches qui dépendent des fondamentaux (sans toucher aux historiques de cours)."""
    from ...utils import cache as disk_cache

    try:
        shared.market_table.clear()
    except Exception:
        pass
    try:
        shared.coverage.clear()
    except Exception:
        pass
    disk_cache.clear("screener")
    disk_cache.clear("fundamentals")
