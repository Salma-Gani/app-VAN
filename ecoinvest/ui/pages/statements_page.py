"""États financiers d'une société : bilan, CPC, trésorerie et ratios.

La page affiche uniquement des chiffres sourcés (AMMC, API configurée ou import
vérifié). Les postes absents ressortent « — » et les ratios impossibles sont
expliqués. Aucune valeur n'est extrapolée.

Trois causes de tableau vide ont été corrigées :

1. la société sélectionnée par défaut n'avait aucun état (les sociétés
   couvertes sont désormais proposées en premier) ;
2. le bilan importé (CSV/Excel/API) n'avait pas de lignes détaillées et le
   repli ne connaissait pas les blocs ``balance_assets`` / ``balance_liabilities`` ;
3. la recherche AMMC parcourait des pages sans utiliser le filtre émetteur
   officiel, ce qui ne trouvait presque jamais la société ;
4. l'extraction PDF renvoyait du texte brut : le module
   ``ecoinvest.data.statements_extract`` normalise désormais les libellés et les
   montants en un tableau rubriques × exercices, éditable puis enregistré
   uniquement après validation humaine.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ...config import COLORS
from ...data import statements as stmt
from ...data import statements_extract as ext
from ...data.fundamentals import is_financial_sector
from ...utils.formatting import fmt_money, fmt_pct
from .. import components as ui
from . import shared

_STATUS_TONE = {
    "official": "up",
    "api": "info",
    "manual": "accent",
    "preview": "warn",
}

_PERIOD_LABELS = {"FY": "Annuel", "S1": "1er semestre", "S2": "2e semestre",
                  "T1": "T1", "T2": "T2", "T3": "T3", "T4": "T4"}


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
    covered = set(stmt.covered_symbols())

    requested = str(st.session_state.get("selected_symbol") or "").upper()
    if requested not in symbols:
        requested = str(st.session_state.get("_last_symbol") or "")
    if requested not in symbols:
        requested = next((s for s in symbols if s in covered), symbols[0])

    # Les sociétés couvertes sont proposées en premier : la page ne s'ouvre plus
    # sur une société vide par défaut.
    ordered = [s for s in symbols if s in covered] + [s for s in symbols if s not in covered]
    index = ordered.index(requested) if requested in ordered else 0

    def label(symbol: str) -> str:
        suffix = " · états disponibles" if symbol in covered else ""
        return f"{symbol} — {names.get(symbol, symbol)}{suffix}"

    # Navigation externe : si une autre page a fixé `selected_symbol`, on aligne
    # le widget avant sa création. Ensuite, le choix de l'utilisateur prime.
    widget_key = "statements_symbol"
    previous_request = st.session_state.get("_stmt_requested_symbol")
    if requested in ordered and requested != previous_request:
        st.session_state[widget_key] = requested
    st.session_state["_stmt_requested_symbol"] = requested

    symbol = st.selectbox("Société", ordered, index=index, format_func=label,
                          key=widget_key)
    st.caption(
        f"{len(covered)} société(s) avec états financiers : "
        + (", ".join(sorted(covered)) if covered else "aucune")
        + f" · {len(symbols)} valeurs cotées dans l'univers."
    )
    st.session_state["selected_symbol"] = symbol
    st.session_state["_last_symbol"] = symbol
    return symbol


def _variant(records: List[Dict[str, Any]], symbol: str) -> Dict[str, Any]:
    """Choisit l'exercice, la période et le type de comptes (social/consolidé)."""
    variants: List[Tuple[int, str, bool]] = []
    for record in records:
        try:
            year = int(record.get("fiscal_year") or 0)
        except (TypeError, ValueError):
            year = 0
        key = (year, str(record.get("period") or "FY").upper(), bool(record.get("consolidated")))
        if key not in variants:
            variants.append(key)
    variants.sort(reverse=True)
    if len(variants) <= 1:
        return records[0]

    def label(key: Tuple[int, str, bool]) -> str:
        year, period, consolidated = key
        kind = "Consolidé" if consolidated else "Social"
        return f"Exercice {year} · {_PERIOD_LABELS.get(period, period)} · {kind}"

    choice = st.selectbox(
        "Exercice et type de comptes",
        list(range(len(variants))),
        format_func=lambda i: label(variants[i]),
        key=f"stmt_variant_{symbol}",
    )
    chosen = variants[choice]
    for record in records:
        try:
            year = int(record.get("fiscal_year") or 0)
        except (TypeError, ValueError):
            year = 0
        key = (year, str(record.get("period") or "FY").upper(), bool(record.get("consolidated")))
        if key == chosen:
            return record
    return records[0]


def _fmt_block(df: pd.DataFrame, unit: Optional[str] = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    factor = stmt.unit_multiplier(unit)
    out = df.copy()
    for column in ("Exercice", "Exercice précédent"):
        if column in out.columns:
            out[column] = out[column].apply(
                lambda value: fmt_money(float(value) * factor, "MAD", compact=True)
                if value is not None and pd.notna(value) else "—"
            )
    return out


def _fmt_ratio_value(value: Any, unit: str) -> str:
    if value is None or pd.isna(value):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if unit == "%":
        return f"{number:.2f} %"
    if unit == "x":
        return f"{number:.2f} x"
    return fmt_money(number, "MAD", compact=True)


def render() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles.", "📡")
        return

    symbol = _selector(table)
    row = table[table["symbol"] == symbol].iloc[0]
    records = stmt.get_statements(symbol)
    covered = len(records)
    total_covered = len(stmt.covered_symbols())

    ui.hero(
        "États financiers",
        "Bilan actif et passif, compte de produits et charges (CPC), trésorerie et ratios. "
        "Chaque poste porte sa source, son exercice et son statut ; une case vide n'est jamais comblée.",
        badge=ui.badge(
            f"{total_covered} société(s) couverte(s) · {covered} exercice(s) pour {symbol}",
            "accent" if covered else "warn",
        ),
    )

    _pdf_import(symbol, row)

    if not records:
        ui.note(
            f"**Aucun état financier enregistré pour {symbol}.** La page ne fabrique aucun chiffre. "
            "La voie recommandée est de rechercher le rapport annuel officiel AMMC, puis de "
            "valider les montants extraits. Vous pouvez aussi importer un CSV/Excel vérifié ou "
            "compléter la saisie manuelle. Yahoo Finance n'est pas proposé : il ne fournit pas "
            "d'états financiers marocains exploitables.",
            "warn", "🧾",
        )
        st.markdown(
            "**Sociétés déjà couvertes :** "
            + (", ".join(f"`{s}`" for s in stmt.covered_symbols()) if total_covered else "aucune")
        )
        _import_tabs(symbol, row)
        st.divider()
        _coverage(table)
        return

    record = _variant(records, symbol)
    _source_note(record)
    _kpis(record, row)

    st.divider()
    tabs = st.tabs([
        "📊 Bilan actif", "🏦 Bilan passif", "📄 CPC", "💧 Trésorerie",
        "🧮 Ratios financiers", "🕰️ Historique", "📥 Importer / API", "📚 Couverture",
    ])
    with tabs[0]:
        _block(record, "balance_assets", "Bilan — actif",
               "Immobilisations, actif circulant, trésorerie et total actif.")
    with tabs[1]:
        _block(record, "balance_liabilities", "Bilan — passif",
               "Capitaux propres, dettes de financement, passif circulant et total passif.")
    with tabs[2]:
        revenue_label = ("Produit net bancaire" if is_financial_sector(str(row.get("sector") or ""))
                         else "Chiffre d'affaires")
        _block(record, "income", "Compte de produits et charges (CPC)",
               f"{revenue_label}, résultat d'exploitation, résultat financier, impôt et résultat net.")
    with tabs[3]:
        _block(record, "cashflow", "Trésorerie & autofinancement",
               "Flux opérationnels, investissements, financement et distributions.")
    with tabs[4]:
        _ratios(record, row)
    with tabs[5]:
        _history(symbol, records, row)
    with tabs[6]:
        _import_tabs(symbol, row)
    with tabs[7]:
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
    kind = "Comptes consolidés" if record.get("consolidated") else "Comptes sociaux"
    period = _PERIOD_LABELS.get(str(record.get("period") or "FY").upper(),
                                str(record.get("period") or "FY"))
    parts = [record.get("source") or "source non renseignée"]
    if record.get("source_url"):
        parts.append(str(record["source_url"]))
    display_unit = record.get("unit") or "MAD"
    source_unit = record.get("source_unit") or display_unit
    st.markdown(
        ui.badge(f"Statut : {status or '—'}", tone) + " " +
        ui.badge(f"{record.get('currency', 'MAD')} · {record.get('unit', 'MAD')}", "info") + " " +
        ui.badge(kind, "info"),
        unsafe_allow_html=True,
    )
    ui.source_note(
        parts,
        as_of=(
            f"exercice {record.get('fiscal_year')} · {period} · "
            f"clôture {record.get('period_end') or '—'}"
        ),
        detail=(
            f"{kind} · unité affichée {display_unit} · document source {source_unit} · "
            f"devise {record.get('currency', 'MAD')} · "
            f"émetteur {record.get('issuer') or record.get('symbol')}."
        ),
    )


def _kpis(record: Dict[str, Any], market_row: pd.Series) -> None:
    income = record.get("income") or {}
    balance = record.get("balance") or {}
    cashflow = record.get("cashflow") or {}
    currency = str(record.get("currency") or "MAD")
    factor = stmt.unit_multiplier(record.get("unit"))
    unit_label = str(record.get("unit") or "MAD")
    financial = is_financial_sector(str(market_row.get("sector") or ""))
    revenue_label = "Produit net bancaire" if financial else "Chiffre d'affaires"

    def amount(value: Any) -> str:
        try:
            return fmt_money(float(value) * factor, currency, compact=True)
        except (TypeError, ValueError):
            return "—"

    ui.kpi_row(
        [
            {"label": revenue_label, "value": amount(income.get("revenue")),
             "sub": f"exercice {record.get('fiscal_year')} · {unit_label}", "tone": "blue"},
            {"label": "Résultat d'exploitation", "value": amount(income.get("operating_income")),
             "sub": "EBIT", "tone": "accent"},
            {"label": "Résultat net", "value": amount(income.get("net_income")),
             "sub": ("consolidé · part du groupe" if financial else
                     ("consolidé" if record.get("consolidated") else "sociaux")), "tone": "up"},
            {"label": "Capitaux propres", "value": amount(balance.get("equity")),
             "sub": ("part du groupe · actif net comptable" if record.get("consolidated")
                     else "actif net comptable"), "tone": "info"},
            {"label": "Free Cash-Flow", "value": amount(cashflow.get("free_cash_flow")),
             "sub": "CAF − investissements", "tone": "accent"},
        ],
        per_row=5,
    )


def _exercise_columns(df: pd.DataFrame, record: Dict[str, Any]) -> pd.DataFrame:
    """Renomme « Exercice »/« Exercice précédent » avec l'année réellement affichée."""
    if df is None or df.empty:
        return df
    try:
        year = int(record.get("fiscal_year"))
    except (TypeError, ValueError):
        return df
    mapping = {"Exercice": f"Exercice {year}", "Exercice précédent": f"Exercice {year - 1}"}
    return df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})


def _block(record: Dict[str, Any], block: str, title: str, subtitle: str) -> None:
    ui.section(title, subtitle)
    year = record.get("fiscal_year")
    kind = "comptes consolidés" if record.get("consolidated") else "comptes sociaux"
    st.markdown(
        ui.badge(f"Exercice {year} · {kind}", "info") + " " +
        ui.badge(str(record.get("source") or "source non renseignée"), "accent"),
        unsafe_allow_html=True,
    )
    for problem in stmt.record_issues(record):
        st.warning(problem)
    table = stmt.block_table(record, block)
    if table.empty:
        ui.note(
            "Aucun poste renseigné pour ce bloc dans la source sélectionnée. "
            "Le détail peut être absent du document (comptes bancaires, présentation abrégée) "
            "ou l'import peut ne pas avoir renseigné ces champs.",
            "warn", "—",
        )
        return
    if not (record.get("lines") or {}).get(block):
        st.caption(
            f"Détail des postes non disponible pour l'exercice {year} : les agrégats "
            "vérifiés sont affichés (aucune ligne n'est inventée)."
        )
    unit = record.get("unit") or "MAD"
    source_unit = record.get("source_unit") or unit
    converted = str(source_unit).strip().lower() != str(unit).strip().lower()
    st.caption(
        f"Montants exprimés en {record.get('currency') or 'MAD'} "
        f"(document source : {source_unit})."
        + (" Valeurs converties en MAD pour l'affichage et les ratios." if converted else "")
    )
    ui.table(
        _exercise_columns(_fmt_block(table, unit), record),
        height=430,
        key=f"stmt_{record.get('symbol')}_{block}_{record.get('fiscal_year')}_{int(bool(record.get('consolidated')))}",
    )


def _ratios(record: Dict[str, Any], market_row: pd.Series) -> None:
    ui.section(
        "Ratios financiers",
        "Calculés uniquement à partir des données disponibles. La formule et la raison d'une "
        "impossibilité sont affichées pour chaque ligne.",
    )
    market = {
        "close": market_row.get("close"),
        "cap": market_row.get("cap"),
        "sector": market_row.get("sector"),
    }
    ratios = stmt.ratios_for(record, market)
    if ratios.empty:
        ui.empty_state("Aucun ratio calculable pour cet exercice.", "🧮")
        return
    display = ratios.copy()
    display["Valeur"] = [
        _fmt_ratio_value(value, unit)
        for value, unit in zip(display["Valeur"], display["Unité"])
    ]
    display = display[["Indicateur", "Valeur", "Formule", "Statut", "Note"]]
    ui.table(
        display,
        height=430,
        key=f"stmt_ratios_{record.get('symbol')}_{record.get('fiscal_year')}_{int(bool(record.get('consolidated')))}",
    )

    computed = int((ratios["Statut"] == "Calculé").sum())
    excluded = int((ratios["Statut"] == "Non pertinent").sum())
    impossible = int((ratios["Statut"] == "Impossible").sum())
    st.caption(
        f"{computed} ratio(s) calculé(s) · {impossible} impossible(s) faute de donnée · "
        f"{excluded} non pertinent(s) pour le secteur. "
        "Les ratios de marché (PER, P/B, EV/EBITDA) utilisent le cours et la capitalisation BVC."
    )
    st.caption(
        "Conventions : ROE = résultat net / capitaux propres, les deux retenus dans le même "
        "périmètre (part du groupe pour les comptes consolidés avec minoritaires) ; "
        "PER = capitalisation / résultat net (≡ cours / BPA) ; "
        "P/B = capitalisation / capitaux propres du même périmètre ; "
        "EV/EBITDA = (capitalisation + dette nette) / EBITDA ; "
        "payout = dividendes versés / résultat net. Un dénominateur négatif ou nul désactive le ratio."
    )


def _history(symbol: str, records: List[Dict[str, Any]], market_row: pd.Series) -> None:
    ui.section("Historique", "Évolution des principaux agrégats sur les exercices disponibles.")
    revenue_label = ("Produit net bancaire"
                     if is_financial_sector(str(market_row.get("sector") or ""))
                     else "Chiffre d'affaires")
    rows = []
    for record in records:
        income = record.get("income") or {}
        balance = record.get("balance") or {}
        cashflow = record.get("cashflow") or {}
        factor = stmt.unit_multiplier(record.get("unit"))

        def convert(value: Any) -> Any:
            try:
                return float(value) * factor
            except (TypeError, ValueError):
                return None

        rows.append({
            "Exercice": record.get("fiscal_year"),
            "Type": "Consolidé" if record.get("consolidated") else "Social",
            revenue_label: convert(income.get("revenue")),
            "EBITDA": convert(income.get("ebitda")),
            "Résultat net": convert(income.get("net_income")),
            "Capitaux propres": convert(balance.get("equity")),
            "Free Cash-Flow": convert(cashflow.get("free_cash_flow")),
        })
    frame = pd.DataFrame(rows).sort_values("Exercice")
    if frame.empty or frame.drop(columns=["Exercice", "Type"]).dropna(how="all").empty:
        ui.note("Aucun agrégat disponible pour tracer un historique.", "warn", "—")
        return
    display = frame.copy()
    for column in display.columns[2:]:
        display[column] = display[column].apply(
            lambda value: fmt_money(value, "MAD", compact=True) if pd.notna(value) else "—"
        )
    ui.table(display, height=280, key=f"stmt_history_{symbol}")

    fig = go.Figure()
    for column, color in ((revenue_label, COLORS["primary"]),
                          ("Résultat net", COLORS["accent"]),
                          ("Free Cash-Flow", COLORS["navy"])):
        if frame[column].notna().any():
            fig.add_trace(go.Bar(x=frame["Exercice"], y=frame[column], name=column, marker_color=color))
    fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=20, b=30),
                      legend=dict(orientation="h", y=-0.2))
    ui.plot(fig, key=f"stmt_history_chart_{symbol}")


# ═══════════════════════════ Import / API ═══════════════════════════

def _pdf_import(symbol: str, row: pd.Series) -> None:
    """Section « Récupérer un PDF » placée au-dessus des onglets.

    Elle accepte un fichier local ou l'URL d'un PDF officiel, structure les
    rubriques par exercice, laisse l'utilisateur corriger chaque montant, puis
    n'enregistre qu'après validation explicite.
    """
    key = f"_pdf_result_{symbol}"
    with st.expander(
        "📄 Récupérer / extraire des états financiers depuis un PDF",
        expanded=key in st.session_state,
    ):
        ui.section(
            "Extraire un état financier PDF",
            "Déposez un PDF officiel (AMMC) ou un fichier local. L'extraction propose un tableau "
            "rubriques × exercices ; rien n'est enregistré sans votre validation, et aucune valeur "
            "absente n'est remplacée par zéro.",
        )
        c1, c2 = st.columns(2)
        with c1:
            uploaded = st.file_uploader("Fichier PDF", type=["pdf"], key=f"stmt_pdf_up_{symbol}")
        with c2:
            url = st.text_input(
                "…ou URL d'un PDF officiel",
                value="",
                placeholder="https://www.ammc.ma/…pdf",
                key=f"stmt_pdf_url_{symbol}",
            )
        if st.button("🔎 Extraire et structurer", key=f"stmt_pdf_run_{symbol}"):
            content: Optional[bytes] = None
            source = ""
            try:
                if uploaded is not None:
                    content = uploaded.getvalue()
                    source = uploaded.name
                elif url.strip():
                    with st.spinner("Téléchargement du document…"):
                        content = stmt.fetch_bytes(url.strip())
                    source = url.strip()
                if content is None:
                    st.warning("Fournissez un fichier PDF ou une URL.")
                else:
                    with st.spinner(f"Extraction et normalisation de « {source} »…"):
                        result = ext.structure_pdf(content, source=source)
                    st.session_state[key] = {
                        "result": result, "source": source, "url": url.strip(),
                    }
            except stmt.StatementError as exc:
                st.error(str(exc))
            except Exception as exc:  # fichier illisible, format inattendu
                st.error(f"Extraction impossible : {exc}")

        payload = st.session_state.get(key)
        if payload and payload.get("result") is not None:
            _render_extraction(symbol, row, payload, key)


def _render_extraction(symbol: str, row: pd.Series, payload: Dict[str, Any], key: str) -> None:
    """Affiche un résultat d'extraction éditable et gère l'enregistrement."""
    result = payload["result"]
    value_columns = list(result.value_columns or ["Exercice", "Exercice précédent"])
    st.success(f"{len(result.rows)} ligne(s) détectée(s) sur {result.pages} page(s).")
    st.markdown(
        ui.badge(f"Unité détectée : {result.unit or 'non détectée'}", "info") + " " +
        ui.badge(f"Devise : {result.currency or 'non détectée'}", "info") + " " +
        ui.badge(f"Exercices : {', '.join(value_columns)}", "info"),
        unsafe_allow_html=True,
    )
    for issue in result.issues[:12]:
        st.warning(issue)
    if len(result.issues) > 12:
        st.caption(f"… et {len(result.issues) - 12} autre(s) anomalie(s) signalée(s).")

    frame = ext.to_editor_frame(result)
    if frame.empty:
        st.info(
            "Aucune ligne chiffrée détectée. Le PDF est peut-être une image scannée (OCR requis) "
            "ou sans colonne de montants. Utilisez l'import CSV/Excel ou la saisie manuelle."
        )
        return

    st.caption(
        "Corrigez les montants si nécessaire et assignez une **Clé** aux lignes marquées "
        "« non reconnue ». Seules les lignes portant une clé seront enregistrées."
    )
    column_config: Dict[str, Any] = {
        "Clé": st.column_config.SelectboxColumn(
            "Clé (rubrique)", options=[""] + ext.canonical_key_options(), required=False,
            help="Choisissez la rubrique canonique à enregistrer.",
        ),
        "Statut": st.column_config.TextColumn("Statut", disabled=True),
        "Bloc": st.column_config.TextColumn("Bloc", disabled=True),
        "Rubrique": st.column_config.TextColumn("Rubrique", disabled=True),
    }
    for column in value_columns:
        column_config[column] = st.column_config.NumberColumn(column, format="%.2f")
    edited = st.data_editor(
        frame, key=f"stmt_pdf_edit_{symbol}", column_config=column_config,
        num_rows="dynamic", height=420, use_container_width=True,
    )

    default_year = 0
    match = re.search(r"(19|20)\d{2}", str(value_columns[0]))
    if match:
        default_year = int(match.group(0))
    c1, c2, c3 = st.columns(3)
    with c1:
        consolidated = st.checkbox("Comptes consolidés", key=f"stmt_pdf_cons_{symbol}")
    with c2:
        fiscal_year = st.number_input(
            "Exercice", min_value=1990, max_value=2100,
            value=default_year or 2024, step=1, key=f"stmt_pdf_year_{symbol}",
        )
    with c3:
        issuer = st.text_input(
            "Émetteur", value=str(row.get("name") or symbol), key=f"stmt_pdf_issuer_{symbol}",
        )
    if st.button("💾 Enregistrer après validation", key=f"stmt_pdf_save_{symbol}"):
        try:
            record, skipped = ext.frame_to_record(
                edited, symbol, issuer=issuer.strip() or symbol,
                consolidated=consolidated,
                source=f"Extraction PDF — {payload.get('source') or 'document'}",
                source_url=payload.get("url") or "",
                fiscal_year=int(fiscal_year),
            )
            stmt.save_statement(record)
        except stmt.StatementError as exc:
            st.error(str(exc))
            return
        st.success(f"État financier {fiscal_year} enregistré pour {symbol}.")
        if skipped:
            st.warning(
                "Lignes ignorées faute de clé canonique : "
                + ", ".join(skipped[:10]) + ("…" if len(skipped) > 10 else "")
            )
        st.session_state.pop(key, None)
        st.rerun()


def _import_tabs(symbol: str, row: pd.Series) -> None:
    # L'AMMC est la source officielle marocaine : elle est proposée en premier.
    # Yahoo Finance est volontairement absent (pas d'états marocains fiables).
    tabs = st.tabs([
        "🏛️ Documents AMMC (recommandé)", "📄 CSV / Excel",
        "🔌 API externe (optionnel)", "✍️ Saisie manuelle",
    ])

    with tabs[0]:
        _ammc_import(symbol, row)
    with tabs[1]:
        _file_import()
    with tabs[2]:
        _api_import(symbol)
    with tabs[3]:
        st.caption(
            "La saisie manuelle détaillée se fait dans « Données fondamentales ». Elle reste "
            "prioritaire sur les états importés et convient aux retraitements ou aux données "
            "consolidées."
        )
        if st.button("🧾 Ouvrir la saisie fondamentale", key="stmt_manual_link"):
            _goto("fundamentals_page", symbol)


def _api_import(symbol: str) -> None:
    ui.section(
        "Importer depuis une API externe (optionnel)",
        "Les clés restent dans l'environnement (.env), jamais dans le code. "
        "Pour une valeur marocaine, la source de référence reste l'AMMC.",
    )
    api_items = [item for item in stmt.provider_status() if item["key"] in {"eodhd", "fmp"}]
    status = pd.DataFrame([
        {"Fournisseur": item["label"], "Clé requise": item["env"] or "—",
         "État": "configuré" if item["configured"] else "non configuré",
         "Note": item["note"]}
        for item in api_items
    ])
    ui.table(status, height=180, key="stmt_providers")

    usable = [item for item in api_items if item["configured"]]
    if not usable:
        ui.note(
            "**Aucune API externe n'est configurée.** Ce n'est pas bloquant : utilisez "
            "l'onglet « Documents AMMC », qui donne accès aux rapports officiels des "
            "émetteurs marocains. Yahoo Finance n'est plus proposé ici : il ne fournit "
            "pas d'états financiers marocains exploitables. Si vous disposez d'une API "
            "EODHD ou FMP, ajoutez `EODHD_API_KEY` ou `FMP_API_KEY` dans `.env`.",
            "warn", "🏛️",
        )
        st.markdown(f"[Consulter la liste officielle des états financiers AMMC]({stmt.AMMC_LIST})")
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
            {"Exercice": r.get("fiscal_year"), "CA": (r.get("income") or {}).get("revenue"),
             "Résultat net": (r.get("income") or {}).get("net_income"),
             "Total bilan": (r.get("balance") or {}).get("total_assets"),
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
            st.rerun()


def _file_import() -> None:
    ui.section(
        "Importer un CSV ou un classeur Excel vérifié",
        "Une ligne par société et par exercice. Le fichier doit reprendre les colonnes du modèle.",
    )
    st.download_button(
        "⬇️ Modèle CSV",
        data=stmt.template_csv().encode("utf-8"),
        file_name="modele_etats_financiers.csv",
        mime="text/csv",
        key="stmt_csv_template",
    )
    uploaded = st.file_uploader(
        "Fichier CSV ou Excel", type=["csv", "xlsx", "xlsm"], key="stmt_csv_upload",
        help="Excel nécessite openpyxl. En cas d'indisponibilité, exportez la feuille en CSV.",
    )
    if uploaded is not None and st.button("💾 Importer le fichier", key="stmt_csv_import"):
        try:
            result = stmt.import_table(uploaded.getvalue(), uploaded.name)
        except stmt.StatementError as exc:
            st.error(f"Import impossible : {exc}")
            return
        except Exception as exc:
            st.error(f"Import impossible : {exc}")
            return
        st.success(f"{result['imported']} état(s) importé(s).")
        if result["errors"]:
            st.warning(" · ".join(result["errors"]))
        if result["imported"]:
            st.rerun()
        else:
            st.info("Aucune ligne n'a été enregistrée. Corrigez les erreurs ci-dessus puis réessayez.")


def _ammc_import(symbol: str, row: pd.Series) -> None:
    ui.section(
        "Documents officiels AMMC",
        "Recherche par le filtre émetteur officiel de l'AMMC. Les PDF sont des documents "
        "officiels : leur extraction est une aide à la saisie, jamais un enregistrement automatique.",
    )
    issuer = str(row.get("name") or symbol)
    resolved = stmt.resolve_issuer(issuer, symbol)
    if resolved:
        st.caption(f"Émetteur AMMC identifié : {resolved[1]} (identifiant {resolved[0]}).")
    else:
        st.caption(
            "Émetteur non identifié automatiquement dans la liste AMMC : la recherche par mots-clés "
            "sera utilisée en repli."
        )

    if st.button("🔎 Chercher les documents AMMC", key=f"stmt_ammc_{symbol}"):
        try:
            with st.spinner("Lecture de la liste AMMC…"):
                docs = stmt.ammc_documents(issuer, symbol=symbol)
        except stmt.StatementError as exc:
            st.error(str(exc))
            docs = []
        st.session_state["_stmt_ammc"] = {"symbol": symbol, "docs": docs}

    cached = st.session_state.get("_stmt_ammc") or {}
    docs = cached.get("docs") or [] if cached.get("symbol") == symbol else []
    if not docs:
        st.caption("Aucun document mis en cache pour cette recherche.")
        return
    for doc in docs[:10]:
        pdf = doc.get("pdf_url")
        label = doc.get("title") or "Document"
        if pdf:
            st.markdown(f"- [{label}]({pdf})")
        else:
            st.markdown(f"- [{label}]({doc.get('url')})")

    with_pdf = [d for d in docs if d.get("pdf_url")]
    if not with_pdf:
        st.warning("Aucun PDF direct n'a été trouvé pour ces documents.")
        return

    # Priorité au rapport annuel : les rapports semestriels ne contiennent pas
    # le bilan annuel complet. On ne choisit jamais un PDF au hasard.
    annual = [
        d for d in with_pdf
        if any(token in str(d.get("title") or "").lower()
               for token in ("annuel", "rfa", "document d'enregistrement universel"))
    ]
    choices = annual or with_pdf
    labels = [
        f"{d.get('year') or '—'} — {d.get('title') or 'Document'}"
        for d in choices
    ]
    choice = st.selectbox(
        "Rapport à structurer", list(range(len(choices))),
        format_func=lambda index: labels[index],
        key=f"stmt_ammc_choice_{symbol}",
    )
    doc = choices[choice]
    st.markdown(f"[Ouvrir le PDF officiel]({doc['pdf_url']})")
    ui.note(
        "**L'extraction produit un brouillon, jamais un enregistrement automatique.** "
        "Vérifiez chaque montant, l'exercice, l'unité et la page du PDF avant de valider. "
        "Les tableaux AMMC sont hétérogènes : une ligne mal lue doit être corrigée ou ignorée.",
        "info", "🧾",
    )
    if st.button("📄 Télécharger et préparer le brouillon", key=f"stmt_ammc_read_{symbol}"):
        try:
            with st.spinner("Téléchargement et structuration du PDF…"):
                content = stmt.fetch_bytes(doc["pdf_url"])
                result = ext.structure_pdf(content, source=doc.get("title") or doc["pdf_url"])
        except stmt.StatementError as exc:
            st.error(str(exc))
            return
        st.session_state[f"_pdf_result_{symbol}"] = {
            "result": result,
            "source": doc.get("title") or doc["pdf_url"],
            "url": doc["pdf_url"],
        }

    payload = st.session_state.get(f"_pdf_result_{symbol}")
    if payload and payload.get("result") is not None:
        _render_extraction(symbol, row, payload, f"_pdf_result_{symbol}")


def _coverage(table: pd.DataFrame) -> None:
    ui.section("Couverture comptable", "Exercices disponibles par société et statut de la source.")
    coverage = stmt.coverage(table)
    covered = stmt.covered_symbols()
    if not covered:
        ui.note("Aucune société couverte pour le moment.", "warn", "—")
        return
    displayed = coverage[coverage["Symbole"].isin(covered)].copy()
    if displayed.empty:
        ui.note("Aucune société couverte pour le moment.", "warn", "—")
        return
    displayed["Statut"] = displayed["Statut"].replace({
        "official": "Officiel (AMMC)", "api": "API", "manual": "Saisie/import",
    })
    displayed["Exercices"] = displayed["Exercices"].apply(
        lambda value: value.replace("**", "") if isinstance(value, str) else value
    )
    ui.table(displayed, height=460, key="stmt_coverage")
    ui.download_row(coverage, "couverture_etats_financiers.csv", "⬇️ Exporter en CSV")
