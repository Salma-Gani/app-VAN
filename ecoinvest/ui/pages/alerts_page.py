"""Centre d'alertes locales : niveaux techniques, RSI, drawdown et VIX."""
from __future__ import annotations

import html
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from ...analytics import alerts as alerts_mod
from ...config import COLORS
from ...utils.formatting import fmt_num, fmt_pct
from .. import components as ui
from . import shared

_TONE = {"critical": "down", "warning": "warn", "info": "info"}
_ICON = {"critical": "⛔", "warning": "⚠️", "info": "ℹ️"}
_LABEL = {"critical": "Critique", "warning": "Vigilance", "info": "Information"}


def render() -> None:
    ui.hero(
        "Alertes & surveillance",
        "Un scanner explicable des niveaux techniques, du RSI, du drawdown et de la volatilité "
        "internationale. Les alertes sont des observations conditionnelles, pas des ordres.",
        badge=ui.badge("Scanner local · aucune notification push", "info"),
    )

    ui.note(
        "**Comment lire une alerte ?** Chaque règle est calculée sur des données réelles et affiche "
        "sa valeur, son seuil, sa date et sa source. Une alerte de support ou de RSI ne constitue "
        "jamais une recommandation d'achat ou de vente. Aucun e-mail ni message n'est envoyé.",
        "info", "🔔",
    )

    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles : le scanner ne peut pas fonctionner.", "📡")
        return

    watch = shared.watchlist()
    thresholds = _threshold_controls()
    scope, include_vix = _scope_controls(watch)

    c1, c2 = st.columns([1, 2])
    with c1:
        scan = st.button("🔎 Scanner les alertes", type="primary", use_container_width=True)
    with c2:
        st.caption(
            f"Périmètre : {scope.lower()} · {len(watch)} valeur(s) en liste de suivi · "
            f"source cours : BVC, clôture du {shared.last_market_date(table)}."
        )

    if scan:
        with st.spinner("Calcul des alertes sur les données en cache…"):
            st.session_state["alerts_scan"] = _run_scan(table, watch, scope, thresholds, include_vix)
            st.session_state["alerts_scan_at"] = pd.Timestamp.now().strftime("%d/%m/%Y %H:%M")

    raw = st.session_state.get("alerts_scan")
    if raw is None:
        ui.note(
            "Lancez le scanner pour évaluer les règles sur votre liste de suivi ou sur l'ensemble "
            "du marché. Les valeurs de la liste de suivi bénéficient en plus des niveaux de support "
            "et de résistance calculés sur l'historique.",
            "info", "🧭",
        )
        _watchlist_panel(watch)
        ui.disclaimer()
        return

    alerts = [_from_dict(item) for item in raw]
    counts = alerts_mod.counts(alerts)
    selected = st.multiselect(
        "Gravité affichée",
        options=["critical", "warning", "info"],
        default=["critical", "warning", "info"],
        format_func=lambda key: _LABEL.get(key, key),
        key="alerts_severity",
    )
    filtered = [a for a in alerts if a.severity in selected]

    ui.kpi_row(
        [
            {"label": "Alertes", "value": str(counts["total"]), "sub": "règles déclenchées", "tone": "blue"},
            {"label": "Critiques", "value": str(counts["critical"]), "sub": "drawdown / VIX élevé", "tone": "down"},
            {"label": "Vigilance", "value": str(counts["warning"]), "sub": "RSI, support, variation", "tone": "warn"},
            {"label": "Informations", "value": str(counts["info"]), "sub": "résistance, signaux", "tone": "info"},
        ],
        per_row=4,
    )
    st.caption(f"Dernier scan : {st.session_state.get('alerts_scan_at', '—')} · "
               f"{len(filtered)} alerte(s) affichée(s).")

    if not filtered:
        ui.empty_state("Aucune alerte ne correspond aux filtres et aux seuils actuels.", "✅")
    else:
        _render_alerts(filtered)
        frame = alerts_mod.to_frame(filtered)
        with st.expander("📋 Tableau exportable", expanded=False):
            display = frame[["symbol", "name", "severity", "kind", "title", "detail", "as_of", "source"]].copy()
            display.columns = ["Symbole", "Valeur", "Gravité", "Règle", "Alerte", "Détail", "Date", "Source"]
            display["Gravité"] = display["Gravité"].map(_LABEL).fillna(display["Gravité"])
            ui.table(display, height=min(520, 80 + 34 * len(display)), key="alerts_table")
            ui.download_row(display, "marketmind_alertes.csv", "⬇️ Exporter les alertes (CSV)",
                            key="alerts_download")

    _watchlist_panel(watch)
    st.caption(
        "Méthode : RSI(14), moyennes mobiles, support/résistance 120 jours et drawdown calculés sur "
        "l'historique BVC ; VIX issu de Yahoo Finance (volatilité implicite des options S&P 500, "
        "et non du MASI). Les seuils sont modifiables et ne sont pas des recommandations."
    )
    ui.disclaimer()


def _threshold_controls() -> Dict[str, float]:
    with st.expander("⚙️ Paramètres du scanner", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            rsi_low = st.number_input("RSI survente", min_value=5, max_value=50, value=30, step=1,
                                      key="alert_rsi_low")
            rsi_high = st.number_input("RSI surachat", min_value=50, max_value=95, value=70, step=1,
                                       key="alert_rsi_high")
        with c2:
            drawdown = st.number_input("Drawdown critique (%)", min_value=-80, max_value=-5, value=-20,
                                       step=5, key="alert_drawdown")
            proximity = st.number_input("Proximité niveau (%)", min_value=0.0, max_value=10.0, value=1.5,
                                        step=0.5, key="alert_proximity")
        with c3:
            daily_move = st.number_input("Variation journalière (%)", min_value=1.0, max_value=30.0,
                                         value=5.0, step=0.5, key="alert_move")
            vix_high = st.number_input("Seuil VIX", min_value=15.0, max_value=80.0, value=25.0,
                                       step=1.0, key="alert_vix")
        st.caption(
            "Les seuils s'appliquent au prochain scan. Un drawdown de -20 % signifie une baisse "
            "d'au moins 20 % depuis le plus haut observé."
        )
    return alerts_mod.thresholds(
        rsi_low=rsi_low,
        rsi_high=rsi_high,
        drawdown=drawdown / 100.0,
        proximity=proximity / 100.0,
        daily_move=daily_move / 100.0,
        vix_high=vix_high,
    )


def _scope_controls(watch: List[str]) -> tuple:
    options = (["Ma liste de suivi", "Tout le marché"] if watch else ["Tout le marché"])
    c1, c2 = st.columns([1.4, 1])
    with c1:
        scope = st.radio("Périmètre du scan", options, horizontal=True, key="alerts_scope")
    with c2:
        include_vix = st.checkbox("Inclure l'alerte VIX", value=True, key="alerts_vix",
                                  help="Le VIX concerne les options sur le S&P 500, pas directement le MASI.")
    return scope, include_vix


def _run_scan(table: pd.DataFrame, watch: List[str], scope: str,
              thresholds: Dict[str, float], include_vix: bool) -> List[Dict[str, Any]]:
    if scope == "Ma liste de suivi" and watch:
        summaries = {sym: shared.technical_summary(sym) for sym in watch}
        found = alerts_mod.scan_with_histories(table, watch, summaries, thresholds)
    else:
        found = alerts_mod.scan_market(table, None, thresholds)
    if include_vix:
        vix = alerts_mod.vix_alert(shared.vix_regime(), thresholds)
        if vix is not None:
            found.append(vix)
    return [a.to_dict() for a in found[:120]]


def _from_dict(data: Dict[str, Any]) -> alerts_mod.Alert:
    return alerts_mod.Alert(
        symbol=str(data.get("symbol") or ""),
        name=str(data.get("name") or ""),
        kind=str(data.get("kind") or ""),
        severity=str(data.get("severity") or "info"),
        title=str(data.get("title") or ""),
        detail=str(data.get("detail") or ""),
        value=data.get("value"),
        threshold=data.get("threshold"),
        as_of=str(data.get("as_of") or ""),
        source=str(data.get("source") or ""),
    )


def _render_alerts(alerts: List[alerts_mod.Alert]) -> None:
    for alert in alerts:
        tone = _TONE.get(alert.severity, "info")
        color = COLORS["danger"] if alert.severity == "critical" else (
            COLORS["warning"] if alert.severity == "warning" else COLORS["accent"]
        )
        details = html.escape(alert.detail)
        source = html.escape(" · ".join(p for p in (alert.source, alert.as_of) if p))
        st.markdown(
            f"""
            <div class="ei-card" style="border-left:4px solid {color};margin-bottom:.55rem">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:baseline">
                <div><b>{html.escape(alert.symbol)}</b>
                  <span class="ei-muted" style="font-size:.8rem">— {html.escape(alert.name)}</span></div>
                {ui.badge(_LABEL.get(alert.severity, alert.severity), tone)}
              </div>
              <div style="font-weight:700;margin:.2rem 0">{html.escape(alert.title)}</div>
              <div class="ei-muted" style="font-size:.84rem;line-height:1.45">{details}</div>
              <div class="ei-muted" style="font-size:.72rem;margin-top:.3rem">{source}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _watchlist_panel(watch: List[str]) -> None:
    st.divider()
    ui.section("Ma liste de suivi", "Ajoutez ou retirez des valeurs depuis la fiche société.")
    if not watch:
        ui.note(
            "Votre liste de suivi est vide. Ouvrez **Analyse société**, puis cliquez sur "
            "« Suivre cette valeur » pour bénéficier des alertes de support et de résistance.",
            "info", "⭐",
        )
        return
    cols = st.columns(min(8, len(watch)))
    for i, symbol in enumerate(watch[:16]):
        with cols[i % len(cols)]:
            st.markdown(ui.badge(symbol, "info"), unsafe_allow_html=True)
    if len(watch) > 16:
        st.caption(f"… et {len(watch) - 16} autres valeurs.")
