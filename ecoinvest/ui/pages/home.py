"""Accueil Market Mind : centre de pilotage et vue synthétique du marché."""
from __future__ import annotations

import html
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from ...config import APP_TAGLINE, COLORS
from .. import charts, components as ui
from . import shared

_NNBSP = "\u202f"


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _num(value: Any, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value):,.{decimals}f}".replace(",", _NNBSP).replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value) * 100:+.{decimals}f}".replace(".", ",") + f"{_NNBSP}%"
    except (TypeError, ValueError):
        return "—"


def _tone(value: Optional[float]) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "flat"
    return "up" if value > 0 else "down" if value < 0 else "flat"


def _goto(page_key: str, symbol: Optional[str] = None) -> None:
    if symbol:
        st.session_state["selected_symbol"] = symbol
    pages = st.session_state.get("_nav_pages") or {}
    target = pages.get(page_key)
    if target is not None:
        st.switch_page(target)
    else:
        st.info("Navigation indisponible dans ce contexte de test.")


def _resolve_symbol(query: str, universe: pd.DataFrame) -> Optional[str]:
    q = (query or "").strip().lower()
    if not q or universe is None or universe.empty:
        return None
    symbols = universe["symbol"].astype(str)
    exact = universe[symbols.str.lower() == q]
    if not exact.empty:
        return str(exact.iloc[0]["symbol"])
    names = universe["name"].astype(str).str.lower()
    for mask in (names.str.startswith(q), names.str.contains(q, regex=False)):
        hit = universe[mask]
        if not hit.empty:
            return str(hit.iloc[0]["symbol"])
    # Dernier recours : code boursier partiel.
    hit = universe[symbols.str.lower().str.startswith(q)]
    return str(hit.iloc[0]["symbol"]) if not hit.empty else None


def render() -> None:
    regime = shared.market_regime()
    indices = shared.indices()
    snapshot = shared.snapshot()
    news_df = shared.market_news()
    universe = shared.universe()

    _brandbar(snapshot)
    _hero(regime, indices, universe)
    _categories()
    _market_pulse(snapshot, indices, regime)
    _news_and_ai(regime, snapshot, news_df)
    ui.source_note(
        ["Bourse de Casablanca (API publique)", "Yahoo Finance", "Flux RSS publics"],
        as_of=f"clôture du {_last_date(snapshot)}",
        detail="Cours différés, non temps réel. Les fondamentaux hors nombre de titres et dividende "
               "sont saisis par l'utilisateur.",
    )


# ═══════════════════════════ En-tête et héros ═══════════════════════════


def _brandbar(snapshot: pd.DataFrame) -> None:
    st.markdown(
        f"""
        <div class="mm-brandbar">
          <div class="mm-wordmark">MARKET <span>MIND</span></div>
          <div class="mm-brandsub">{_esc(APP_TAGLINE)}</div>
          <div class="mm-brandsub" style="margin-left:auto">
            Bourse de Casablanca · {_esc(_last_date(snapshot))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _hero(regime: Dict[str, Any], indices: pd.DataFrame, universe: pd.DataFrame) -> None:
    left, right = st.columns([1.5, 0.95], gap="large")
    with left:
        st.markdown(
            f"""
            <div class="mm-eyebrow">Investment intelligence platform</div>
            <h1 class="mm-title">Votre capital. Votre stratégie.<br>
              <em>Une vision plus claire.</em></h1>
            <p class="mm-lede">
              Analysez les marchés, comprenez les risques et explorez les opportunités
              d'investissement. Données de marché réelles, hypothèses explicites,
              aucune donnée fondamentale inventée.
            </p>
            """,
            unsafe_allow_html=True,
        )
        with st.form("home_search", clear_on_submit=False):
            c1, c2 = st.columns([5, 1.2])
            with c1:
                query = st.text_input(
                    "Rechercher une valeur",
                    placeholder="Symbole ou société — ex. ATW, IAM, Cosumar…",
                    label_visibility="collapsed",
                )
            with c2:
                submitted = st.form_submit_button("Ouvrir", use_container_width=True)
        if submitted:
            symbol = _resolve_symbol(query, universe)
            if symbol:
                _goto("company", symbol)
            else:
                st.warning("Aucune valeur trouvée. Essayez un symbole BVC (ATW, IAM, MNG…).")

        chips = st.columns(5)
        quick = (("MASI", "dashboard"), ("ATW", "company"), ("IAM", "company"),
                 ("MNG", "company"), ("BCP", "company"))
        for col, (label, page) in zip(chips, quick):
            with col:
                if st.button(label, key=f"home_chip_{label}", use_container_width=True):
                    _goto(page, None if page == "dashboard" else label)

    with right:
        st.markdown(_pulse_html(indices, regime), unsafe_allow_html=True)


def _pulse_html(indices: pd.DataFrame, regime: Dict[str, Any]) -> str:
    vix = regime.get("vix") or {}
    rows = []
    for code, label in (("MASI", "MASI"), ("MSI20", "MASI 20"), ("MASIMS", "MASI MS"),
                        ("ESGI", "ESGI")):
        if indices is None or indices.empty:
            continue
        sub = indices[indices["code"] == code]
        if sub.empty:
            continue
        row = sub.iloc[0]
        change = row.get("change_pct")
        rows.append(
            f'<div class="mm-index-row"><span class="mm-index-name">{_esc(label)}</span>'
            f'<span><span class="mm-index-val">{_num(row.get("value"))}</span> '
            f'<span class="mm-delta {_tone(change)}">{_pct(change)}</span></span></div>'
        )
    vix_level = vix.get("level")
    vix_change = vix.get("change")
    rows.append(
        f'<div class="mm-index-row"><span class="mm-index-name">VIX</span>'
        f'<span><span class="mm-index-val">{_num(vix_level)}</span> '
        f'<span class="mm-delta {_tone(vix_change)}">{_pct(vix_change)}</span></span></div>'
    )
    gate = regime.get("entry_gate")
    gate_tone = "up" if (gate or 0) >= 0.1 else "down" if (gate or 0) <= -0.1 else "flat"
    return f"""
    <div class="mm-pulse">
      <div class="mm-pulse-head"><span>Market Pulse</span><span>Données différées</span></div>
      {''.join(rows)}
      <div style="margin-top:12px">
        {ui.badge(regime.get("label", "Régime indisponible"), gate_tone)}
      </div>
      <div class="ei-kpi-sub" style="margin-top:8px">{_esc(regime.get("advice", ""))}</div>
    </div>
    """


# ═══════════════════════════ Catégories ═══════════════════════════


def _categories() -> None:
    st.markdown('<div class="mm-section-label">Explorer la plateforme</div>', unsafe_allow_html=True)
    cards = [
        ("dashboard", "🌍", "Vue globale du marché",
         "Indices, cotations, tendances et actualités en un coup d'œil."),
        ("screener", "📈", "Analyse technique",
         "Prix, momentum, volatilité et signaux sur les 81 valeurs BVC."),
        ("fundamentals_page", "🧾", "Analyse fondamentale",
         "Ratios, valorisation, cash-flows et couverture des données."),
        ("profile_page", "👤", "Mon patrimoine",
         "Revenus, actifs, dettes, profil de risque et portefeuille."),
        ("ai_page", "🧠", "Market Mind AI",
         "Analyse directe, scénarios, sources, rapport PDF et alertes explicables."),
        ("portfolio_builder", "⚖️", "Comparateur d'investissements",
         "Comparez votre portefeuille à des alternatives, coûts inclus."),
    ]
    for start in range(0, len(cards), 3):
        cols = st.columns(3, gap="medium")
        for col, (key, icon, title, desc) in zip(cols, cards[start:start + 3]):
            with col:
                with st.container(border=True):
                    st.markdown(
                        f'<div class="mm-cat-icon">{icon}</div>'
                        f'<div class="mm-cat-title">{_esc(title)}</div>'
                        f'<div class="mm-cat-desc">{_esc(desc)}</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("Explorer →", key=f"home_card_{key}", use_container_width=True):
                        _goto(key)
    st.write("")


# ═══════════════════════════ Market pulse détaillé ═══════════════════════════


def _market_pulse(snapshot: pd.DataFrame, indices: pd.DataFrame, regime: Dict[str, Any]) -> None:
    st.markdown('<div class="mm-section-label">Marché — synthèse de la séance</div>',
                unsafe_allow_html=True)
    left, right = st.columns([1.7, 1], gap="large")
    with left:
        hist = shared.index_history("MASI", "6M")
        if hist is not None and not hist.empty:
            fig = charts.line_series(
                hist["date"], hist["value"], name="MASI", color=COLORS["primary"],
                fill=False, height=310, y_title="Points",
            )
            values = pd.to_numeric(hist["value"], errors="coerce").dropna()
            if not values.empty:
                pad = max((values.max() - values.min()) * 0.14, 1.0)
                fig.update_yaxes(range=[values.min() - pad, values.max() + pad])
                fig.update_layout(margin=dict(l=48, r=24, t=16, b=38))
            ui.plot(fig, key="home_masi")
        else:
            ui.empty_state("Série MASI indisponible pour le moment.", "📉")

    with right:
        _regime_card(regime)
        st.write("")
        _movers(snapshot)


def _regime_card(regime: Dict[str, Any]) -> None:
    vix = regime.get("vix") or {}
    breadth = regime.get("breadth") or {}
    gate = regime.get("entry_gate")
    tone = "up" if (gate or 0) >= 0.1 else "down" if (gate or 0) <= -0.1 else "flat"
    st.markdown(
        f"""
        <div class="mm-card">
          <div class="ei-kpi-label">Lecture du marché</div>
          <div style="margin:.5rem 0">{ui.badge(regime.get("label", "Indisponible"), tone)}</div>
          <div style="display:flex;gap:18px;margin-top:10px">
            <div><div class="ei-kpi-label">VIX</div>
                 <div class="ei-kpi-value" style="font-size:1.3rem">{_num(vix.get("level"))}</div></div>
            <div><div class="ei-kpi-label">Hausses</div>
                 <div class="ei-kpi-value" style="font-size:1.3rem">{int(breadth.get("advancers") or 0)}</div></div>
            <div><div class="ei-kpi-label">Baisses</div>
                 <div class="ei-kpi-value" style="font-size:1.3rem">{int(breadth.get("decliners") or 0)}</div></div>
          </div>
          <div class="ei-kpi-sub" style="margin-top:10px;line-height:1.5">
            {_esc(regime.get("advice", ""))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _movers(snapshot: pd.DataFrame) -> None:
    if snapshot is None or snapshot.empty or "change_pct" not in snapshot.columns:
        return
    frame = snapshot.dropna(subset=["change_pct"])
    if frame.empty:
        return
    up = frame.nlargest(3, "change_pct")
    down = frame.nsmallest(3, "change_pct")
    rows = []
    for _, r in pd.concat([up, down]).iterrows():
        rows.append(
            f'<div class="mm-index-row" style="padding:6px 0">'
            f'<span class="mm-index-name">{_esc(r.get("symbol"))} '
            f'<span class="ei-muted" style="font-weight:400">· {_esc(str(r.get("name"))[:18])}</span></span>'
            f'<span><span class="mm-index-val">{_num(r.get("close"))}</span> '
            f'<span class="mm-delta {_tone(r.get("change_pct"))}">{_pct(r.get("change_pct"))}</span></span>'
            f'</div>'
        )
    st.markdown(
        f'<div class="mm-card"><div class="ei-kpi-label">Mouvements de la séance</div>'
        f'{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════ Actualités et lecture IA ═══════════════════════════


def _news_and_ai(regime: Dict[str, Any], snapshot: pd.DataFrame, news_df: pd.DataFrame) -> None:
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        st.markdown('<div class="mm-section-label">À la une</div>', unsafe_allow_html=True)
        with st.container(border=True):
            if news_df is None or news_df.empty:
                ui.empty_state("Aucune actualité chargée pour le moment.", "📰")
            else:
                for _, row in news_df.head(5).iterrows():
                    tone = {"Positif": "up", "Négatif": "down"}.get(row.get("sentiment_label"), "flat")
                    link = str(row.get("link") or "")
                    safe_link = link if link.startswith(("http://", "https://")) else "#"
                    st.markdown(
                        f'<div class="mm-news-item">'
                        f'<div class="mm-news-title"><a href="{_esc(safe_link)}" target="_blank" '
                        f'rel="noopener noreferrer">{_esc(row.get("title"))}</a></div>'
                        f'<div class="mm-news-meta">{_esc(row.get("source"))} · '
                        f'{_esc(_when(row.get("published")))} · '
                        f'{ui.badge(str(row.get("sentiment_label") or "Neutre"), tone)}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

    with right:
        st.markdown('<div class="mm-section-label">Lecture Market Mind</div>', unsafe_allow_html=True)
        top = None
        if snapshot is not None and not snapshot.empty and "return_12m" in snapshot.columns:
            up = snapshot.dropna(subset=["return_12m", "change_pct"])
            if not up.empty:
                top = up[(up["sma20"] > up["sma50"])].nlargest(1, "composite_score") \
                    if "composite_score" in up.columns else up.nlargest(1, "return_12m")
        lines = [
            f"Régime : <b>{_esc(regime.get('label', 'indisponible'))}</b>.",
            f"Largeur : {(regime.get('breadth') or {}).get('advancers', 0)} hausses / "
            f"{(regime.get('breadth') or {}).get('decliners', 0)} baisses.",
        ]
        if top is not None and not top.empty:
            r = top.iloc[0]
            lines.append(
                f"À surveiller : <b>{_esc(r.get('symbol'))}</b> ({_esc(r.get('sector'))}), "
                f"momentum 12 mois {_pct(r.get('return_12m'))}."
            )
        if (regime.get("news") or {}).get("label"):
            lines.append(f"Sentiment presse : <b>{_esc((regime.get('news') or {}).get('label'))}</b>.")
        st.markdown(
            f'<div class="mm-ai-card"><div class="ei-kpi-label">Synthèse explicable</div>'
            f'<div style="font-size:.9rem;line-height:1.65;margin-top:8px">'
            f'{"<br>".join(lines)}</div>'
            f'<div class="ei-kpi-sub" style="margin-top:10px">'
            f'Chaque conclusion est reliée à un facteur observable. Les données manquantes sont signalées.'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        st.write("")
        if st.button("Ouvrir Market Mind AI →", key="home_ai", use_container_width=True):
            _goto("ai_page")


# ═══════════════════════════ Utilitaires ═══════════════════════════


def _last_date(snapshot: pd.DataFrame) -> str:
    if snapshot is None or snapshot.empty or "last_date" not in snapshot.columns:
        return "date indisponible"
    dates = pd.to_datetime(snapshot["last_date"], errors="coerce").dropna()
    if dates.empty:
        return "date indisponible"
    return dates.max().strftime("%d/%m/%Y")


def _when(value: Any) -> str:
    if value is None:
        return ""
    try:
        stamp = pd.to_datetime(value, errors="coerce")
        if pd.isna(stamp):
            return ""
        return stamp.strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return ""
