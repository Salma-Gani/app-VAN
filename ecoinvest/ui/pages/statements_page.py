"""États financiers d'une société : bilan, compte de résultat et trésorerie.

La page affiche uniquement des chiffres sourcés (AMMC, API configurée ou import
vérifié). Les postes absents ressortent « — ». Aucune valeur n'est extrapolée.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...config import COLORS
from ...data import statements as stmt
from ...utils.formatting import as_float, fmt_money, fmt_pct
from .. import components as ui
from . import shared

_STATUS_TONE = {
    "official": "up",
    "api": "info",
    "manual": "accent",
    "preview": "warn",
}


def _goto(page_key: str, symbol: Optional[str] = None) -> None:
    if symbol:
        st.session_state["selected_symbol"] = symbol
    pages = st.session_state.get("_nav_pages") or {}
    target = pages.get(page_key)
    if target is not None:
        st.switch_page(target)
    else:
        st.info("Navigation indisponible dans ce contexte de test.")


def _selector(table: pd.DataFrame) -> str:
    symbols = table["symbol"].astype(str).tolist()
    names = dict(zip(table["symbol"].astype(str), table["name"]))
    requested = str(st.session_state.get("selected_symbol") or "").upper()
    if requested not in symbols:
        requested = st.session_state.get("_last_symbol") or symbols[0]
    index = symbols.index(requested) if requested in symbols else 0
    symbol = st.selectbox(
        "Société",
        symbols,
        index=index,
        format_func=lambda s: f"{s} — {names.get(s, s)}",
        key="statements_symbol",
    )
    st.session_state["selected_symbol"] = symbol
    st.session_state["_last_symbol"] = symbol
    return symbol


def _fmt_block(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for column in ("Exercice", "Exercice précédent"):
        if column in out.columns:
            out[column] = out[column].apply(
                lambda value: fmt_money(value, "MAD", compact=True)
                if value is not None and pd.notna(value) else "—"
            )
    return out


def render() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles.", "📡")
        return

    symbol = _selector(table)
    row = table[table["symbol"] == symbol].iloc[0]
    records = stmt.get_statements(symbol)
    covered = len([r for r in records]) if records else 0

    ui.hero(
        "États financiers",
        "Compte de résultat, bilan et tableau de trésorerie des sociétés cotées. Chaque poste "
        "porte sa source, son exercice et son statut. Les cases vides ne sont jamais comblées.",
        badge=ui.badge(f"{covered} exercice(s) disponible(s)", "accent" if covered else "warn"),
    )

    if not records:
        ui.note(
            "**Aucun état financier n'est encore disponible pour cette société.** Importez les "
            "comptes depuis un CSV vérifié, une API configurée (EODHD, FMP, Yahoo Finance) ou les "
            "documents officiels AMMC ci-dessous. Aucun chiffre n'est inventé pour combler le vide.",
            "warn", "🧾",
        )
        _import_tabs(symbol, row, table)
        return

    record = records[0]
    _source_note(record)
    _kpis(record)

    st.divider()
    tabs = st.tabs([
        "📄 Compte de résultat", "🏦 Bilan", "💧 Trésorerie",
        "🕰️ Historique", "📥 Importer / API", "📚 Couverture",
    ])
    with tabs[0]:
        _block(record, "income", "Compte de produits et charges", "Modèle normal marocain.")
    with tabs[1]:
        _balance(record)
    with tabs[2]:
        _block(record, "cashflow", "Trésorerie & autofinancement",
               "Capacité d'autofinancement, investissements et distributions.")
    with tabs[3]:
        _history(symbol, records)
    with tabs[4]:
        _import_tabs(symbol, row, table)
    with tabs[5]:
        _coverage(table)

    st.divider()
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("🧮 Valoriser cette société", use_container_width=True):
            _goto("valuation", symbol)
    with c2:
        if st.button("🏢 Analyse complète", use_container_width=True):
            _goto("company", symbol)
    with c3:
        st.caption(
            "Les ratios (PER, P/B, ROE, EV/EBITDA…) et le Valuation Lab utilisent automatiquement "
            "ces états financiers. Une saisie manuelle dans « Données fondamentales » reste prioritaire."
        )


# ═══════════════════════════ Bandeaux et KPI ═══════════════════════════

def _source_note(record: Dict[str, Any]) -> None:
    status = str(record.get("status") or "")
    tone = _STATUS_TONE.get(status, "info")
    parts = [record.get("source") or "source non renseignée"]
    if record.get("source_url"):
        parts.append(str(record["source_url"]))
    st.markdown(
        ui.badge(f"Statut : {status or '—'}", tone) + " " +
        ui.badge(f"{record.get('currency', 'MAD')} · {record.get('unit', 'MAD')}", "info"),
        unsafe_allow_html=True,
    )
    ui.source_note(
        parts,
        as_of=f"exercice {record.get('fiscal_year')} · document du {record.get('as_of') or '—'}",
        detail="Comptes sociaux, non consolidés, sauf mention contraire. Les montants sont en unités "
               "de la devise indiquée.",
    )


def _kpis(record: Dict[str, Any]) -> None:
    income = record.get("income") or {}
    balance = record.get("balance") or {}
    cashflow = record.get("cashflow") or {}
    ui.kpi_row(
        [
            {"label": "Chiffre d'affaires", "value": fmt_money(income.get("revenue"), "MAD", compact=True),
             "sub": f"exercice {record.get('fiscal_year')}", "tone": "blue"},
            {"label": "Résultat d'exploitation", "value": fmt_money(income.get("operating_income"), "MAD", compact=True),
             "sub": "EBIT", "tone": "accent"},
            {"label": "Résultat net", "value": fmt_money(income.get("net_income"), "MAD", compact=True),
             "sub": "part du groupe", "tone": "up"},
            {"label": "Capitaux propres", "value": fmt_money(balance.get("equity"), "MAD", compact=True),
             "sub": "actif net comptable", "tone": "info"},
            {"label": "Free Cash-Flow", "value": fmt_money(cashflow.get("free_cash_flow"), "MAD", compact=True),
             "sub": "CAF − investissements", "tone": "accent"},
        ],
        per_row=5,
    )


def _block(record: Dict[str, Any], block: str, title: str, subtitle: str) -> None:
    ui.section(title, subtitle)
    table = stmt.block_table(record, block)
    if table.empty:
        ui.note("Aucun poste renseigné pour ce bloc.", "warn", "—")
        return
    ui.table(_fmt_block(table), height=420, key=f"stmt_{record.get('symbol')}_{block}")


def _balance(record: Dict[str, Any]) -> None:
    ui.section("Bilan", "Actif et passif, exercice courant et précédent.")
    assets = stmt.block_table(record, "balance_assets")
    liabilities = stmt.block_table(record, "balance_liabilities")
    if assets.empty and liabilities.empty:
        ui.note("Aucun poste de bilan renseigné.", "warn", "—")
        return
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.markdown("**Actif**")
        ui.table(_fmt_block(assets), height=380, key=f"stmt_assets_{record.get('symbol')}")
    with c2:
        st.markdown("**Passif**")
        ui.table(_fmt_block(liabilities), height=380, key=f"stmt_liab_{record.get('symbol')}")


def _history(symbol: str, records: List[Dict[str, Any]]) -> None:
    ui.section("Historique", "Évolution des principaux agrégats sur les exercices disponibles.")
    rows = []
    for record in records:
        income = record.get("income") or {}
        balance = record.get("balance") or {}
        cashflow = record.get("cashflow") or {}
        rows.append({
            "Exercice": record.get("fiscal_year"),
            "Chiffre d'affaires": income.get("revenue"),
            "EBITDA": income.get("ebitda"),
            "Résultat net": income.get("net_income"),
            "Capitaux propres": balance.get("equity"),
            "Free Cash-Flow": cashflow.get("free_cash_flow"),
        })
    frame = pd.DataFrame(rows).sort_values("Exercice")
    if frame.empty or frame.drop(columns=["Exercice"]).dropna(how="all").empty:
        ui.note("Aucun agrégat disponible pour tracer un historique.", "warn", "—")
        return
    display = frame.copy()
    for column in display.columns[1:]:
        display[column] = display[column].apply(
            lambda value: fmt_money(value, "MAD", compact=True) if pd.notna(value) else "—"
        )
    ui.table(display, height=260, key=f"stmt_history_{symbol}")

    fig = go.Figure()
    for column, color in (("Chiffre d'affaires", COLORS["primary"]),
                          ("Résultat net", COLORS["accent"]),
                          ("Free Cash-Flow", COLORS["navy"])):
        if frame[column].notna().any():
            fig.add_trace(go.Bar(x=frame["Exercice"], y=frame[column], name=column, marker_color=color))
    fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=20, b=30),
                      legend=dict(orientation="h", y=-0.2))
    ui.plot(fig, key=f"stmt_history_chart_{symbol}")


# ═══════════════════════════ Import / API ═══════════════════════════

def _import_tabs(symbol: str, row: pd.Series, table: pd.DataFrame) -> None:
    tabs = st.tabs(["🔌 API externe", "📄 CSV vérifié", "🏛️ Documents AMMC", "✍️ Saisie manuelle"])

    with tabs[0]:
        _api_import(symbol)
    with tabs[1]:
        _csv_import()
    with tabs[2]:
        _ammc_import(symbol, row)
    with tabs[3]:
        st.caption(
            "La saisie manuelle détaillée se fait dans « Données fondamentales ». Elle reste "
            "prioritaire sur les états importés et convient aux retraitements ou aux données "
            "consolidées."
        )
        if st.button("🧾 Ouvrir la saisie fondamentale", key="stmt_manual_link"):
            _goto("fundamentals_page", symbol)


def _api_import(symbol: str) -> None:
    ui.section("Importer depuis une API", "Les clés restent dans l'environnement (.env), jamais dans le code.")
    status = pd.DataFrame([
        {"Fournisseur": item["label"], "Clé requise": item["env"] or "—",
         "État": "configuré" if item["configured"] else "non configuré",
         "Note": item["note"]}
        for item in stmt.provider_status()
    ])
    ui.table(status, height=230, key="stmt_providers")

    usable = [item for item in stmt.provider_status() if item["configured"] and item["key"] != "manual"]
    if not usable:
        ui.note(
            "Aucune API externe n'est configurée. Ajoutez `EODHD_API_KEY` ou `FMP_API_KEY` dans "
            "`.env`, ou utilisez Yahoo Finance (sans clé) pour les valeurs internationales.",
            "warn", "🔑",
        )
        return

    options = {item["key"]: item["label"] for item in usable}
    c1, c2 = st.columns([1.4, 1])
    with c1:
        provider = st.selectbox("Fournisseur", list(options),
                                format_func=lambda key: options[key], key="stmt_provider")
    with c2:
        target = st.text_input("Code / ticker (ex. ATW, ATW.MA, AAPL)", value=symbol,
                               key="stmt_api_symbol")
    if st.button("⬇️ Récupérer les états financiers", key="stmt_api_fetch"):
        try:
            with st.spinner("Interrogation du fournisseur…"):
                records = stmt.fetch_provider(provider, target.strip().upper())
            st.session_state["_stmt_preview"] = records
        except stmt.StatementError as exc:
            st.error(str(exc))
        except Exception as exc:  # réseau, format inattendu
            st.error(f"Erreur inattendue : {exc}")

    preview = st.session_state.get("_stmt_preview")
    if preview:
        st.success(f"{len(preview)} exercice(s) récupéré(s). Vérifiez avant d'enregistrer.")
        summary = pd.DataFrame([
            {"Exercice": r.get("fiscal_year"), "CA": r.get("income", {}).get("revenue"),
             "Résultat net": r.get("income", {}).get("net_income"),
             "Total bilan": r.get("balance", {}).get("total_assets"),
             "Source": r.get("source")}
            for r in preview
        ])
        ui.table(summary, height=220, key="stmt_preview")
        if st.button("💾 Enregistrer ces états", key="stmt_api_save"):
            result = stmt.save_many([dict(r, symbol=symbol) for r in preview])
            st.session_state.pop("_stmt_preview", None)
            st.success(f"{result['saved']} état(s) enregistré(s) pour {symbol}.")
            if result["errors"]:
                st.warning(" · ".join(result["errors"]))


def _csv_import() -> None:
    ui.section("Importer un CSV vérifié", "Une ligne par société et par exercice.")
    st.download_button(
        "⬇️ Modèle CSV",
        data=stmt.template_csv().encode("utf-8"),
        file_name="modele_etats_financiers.csv",
        mime="text/csv",
        key="stmt_csv_template",
    )
    uploaded = st.file_uploader("Fichier CSV", type=["csv"], key="stmt_csv_upload")
    if uploaded is not None and st.button("💾 Importer le CSV", key="stmt_csv_import"):
        try:
            result = stmt.import_csv(uploaded.getvalue())
        except Exception as exc:
            st.error(f"Import impossible : {exc}")
            return
        st.success(f"{result['imported']} état(s) importé(s).")
        if result["errors"]:
            st.warning(" · ".join(result["errors"]))
        st.caption("Rechargez la page ou changez de société pour visualiser les états importés.")


def _ammc_import(symbol: str, row: pd.Series) -> None:
    ui.section(
        "Documents officiels AMMC",
        "Recherche dans la liste publique des états financiers des émetteurs. Les PDF sont des "
        "documents officiels : leur lecture est fournie à titre d'évidence, la saisie reste manuelle.",
    )
    issuer = str(row.get("name") or symbol)
    if st.button("🔎 Chercher les documents AMMC", key=f"stmt_ammc_{symbol}"):
        try:
            with st.spinner("Lecture de la liste AMMC…"):
                docs = stmt.ammc_documents(issuer)
        except stmt.StatementError as exc:
            st.error(str(exc))
            docs = []
        st.session_state["_stmt_ammc"] = docs

    docs = st.session_state.get("_stmt_ammc") or []
    if not docs:
        st.caption("Aucun document mis en cache pour cette recherche.")
        return
    for doc in docs[:8]:
        pdf = doc.get("pdf_url")
        label = doc.get("title") or "Document"
        if pdf:
            st.markdown(f"- [{label}]({pdf})")
        else:
            st.markdown(f"- [{label}]({doc.get('url')})")
    if st.button("📄 Lire le premier PDF et extraire les postes clés", key=f"stmt_ammc_read_{symbol}"):
        docs_with_pdf = [d for d in docs if d.get("pdf_url")]
        if not docs_with_pdf:
            st.warning("Aucun PDF direct n'a été trouvé pour ces documents.")
            return
        try:
            with st.spinner("Téléchargement et extraction du texte…"):
                content = stmt.fetch_bytes(docs_with_pdf[0]["pdf_url"])
                text = stmt.extract_pdf_text(content)
        except stmt.StatementError as exc:
            st.error(str(exc))
            return
        lines = stmt.key_lines(text)
        if not lines:
            st.warning("Aucune ligne comptable reconnue automatiquement. Saisissez les postes "
                       "manuellement depuis le PDF.")
            return
        st.warning(
            "**Extraction automatique indicative.** La mise en page des rapports est hétérogène : "
            "vérifiez chaque ligne dans le PDF d'origine avant de saisir le chiffre. Rien n'est "
            "enregistré automatiquement."
        )
        ui.table(pd.DataFrame(lines)[["block", "field", "line"]], height=360, key="stmt_ammc_lines")


def _coverage(table: pd.DataFrame) -> None:
    ui.section("Couverture comptable", "Exercices disponibles par société et statut de la source.")
    coverage = stmt.coverage(table)
    if coverage.empty:
        ui.note("Aucune société couverte pour le moment.", "warn", "—")
        return
    displayed = coverage.copy()
    displayed["Statut"] = displayed["Statut"].replace({
        "official": "Officiel (AMMC)", "api": "API", "manual": "Saisie/import",
    })
    displayed["Exercices"] = displayed["Exercices"].apply(
        lambda value: value.replace("**", "") if isinstance(value, str) else value
    )
    ui.table(displayed, height=460, key="stmt_coverage")
    ui.download_row(coverage, "couverture_etats_financiers.csv", "⬇️ Exporter en CSV")
