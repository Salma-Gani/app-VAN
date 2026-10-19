"""Tableau de bord : vue d'ensemble du marché marocain et international."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pandas as pd
import streamlit as st

from ...ai import llm as llm_mod
from ...analytics import technical
from ...config import COLORS
from ...data import bvc, market
from ...utils.formatting import fmt_money, fmt_num, fmt_pct
from .. import charts, components as ui
from . import shared


def render() -> None:
    regime = shared.market_regime()
    indices = shared.indices()
    table = shared.market_table()

    ui.hero(
        "Vue globale du marché",
        "Synthèse du marché : Bourse de Casablanca, régime de volatilité, secteurs et opportunités.",
        badge=ui.badge(f"Régime : {regime.get('label', '—')}", _tone(regime.get("entry_gate"))),
    )

    ui.source_note(
        ["Bourse de Casablanca (API publique)", "Yahoo Finance", "Flux RSS publics"],
        as_of=f"séance de clôture du {shared.last_market_date(table)} (dernière séance disponible)",
        detail=(
            f"Données récupérées le {datetime.now().strftime('%d/%m/%Y à %H:%M')} · "
            "cours différés BVC (cache 15 min), indicateurs internationaux selon Yahoo Finance · "
            "la période comptable des fondamentaux est indiquée sur chaque fiche, elle ne correspond "
            "pas à la date de séance."
        ),
    )

    _kpi_strip(regime, indices, table)
    st.write("")

    col_left, col_right = st.columns([1.65, 1], gap="medium")
    with col_left:
        _masi_chart()
    with col_right:
        _vix_block(regime)

    st.divider()
    _market_map(table)

    st.divider()
    col_a, col_b = st.columns(2, gap="medium")
    with col_a:
        _movers(table)
    with col_b:
        ui.section("Risque / rendement", "Chaque bulle est une valeur cotée.")
        ui.plot(charts.risk_return_scatter(table), key="dash_rr", height=430)

    st.divider()
    _briefing()
    st.divider()
    _global_block()
    ui.disclaimer()


# ═══════════════════════════ Sections ═══════════════════════════


def _tone(gate: Any) -> str:
    try:
        g = float(gate)
    except (TypeError, ValueError):
        return "flat"
    if g >= 0.1:
        return "up"
    if g <= -0.1:
        return "down"
    return "info"


def _kpi_strip(regime: Dict[str, Any], indices: pd.DataFrame, table: pd.DataFrame) -> None:
    masi = indices[indices["code"] == "MASI"]
    masi_row = masi.iloc[0] if not masi.empty else None
    breadth = regime.get("breadth") or {}
    vix = regime.get("vix") or {}
    news_sum = regime.get("news") or {}

    items = []
    if masi_row is not None:
        items.append({
            "label": "MASI",
            "value": fmt_num(masi_row["value"], 2),
            "sub": f"{fmt_pct(masi_row['change_pct'], 2, signed=True)} · YTD "
                   f"{fmt_pct(masi_row['ytd_pct'], 2, signed=True)}",
            "tone": "accent" if (masi_row["change_pct"] or 0) >= 0 else "danger",
            "color": COLORS["up"] if (masi_row["change_pct"] or 0) >= 0 else COLORS["down"],
        })
    items.append({
        "label": "Largeur de marché",
        "value": f"{breadth.get('advancers', 0)} / {breadth.get('decliners', 0)}",
        "sub": f"{breadth.get('total', 0)} valeurs · "
               f"{'majorité haussière' if (breadth.get('breadth') or 0) > 0 else 'majorité baissière'}",
        "tone": "accent" if (breadth.get("breadth") or 0) > 0 else "danger",
    })
    items.append({
        "label": "VIX (S&P 500)",
        "value": fmt_num(vix.get("level"), 2),
        "sub": str(vix.get("label") or "—"),
        "tone": "warn",
        "color": vix.get("color"),
    })
    items.append({
        "label": "Sentiment des news",
        "value": str(news_sum.get("label") or "Neutre"),
        "sub": f"score {fmt_num(news_sum.get('score'), 2)} · {news_sum.get('count', 0)} articles",
        "tone": "accent" if (news_sum.get("score") or 0) >= 0 else "danger",
    })
    items.append({
        "label": "Capitalisation totale",
        "value": fmt_money(table["cap"].sum(), "MAD", compact=True) if not table.empty else "—",
        "sub": f"{len(table)} valeurs cotées",
        "tone": "blue",
    })
    ui.kpi_row(items, per_row=5)


def _masi_chart() -> None:
    ui.section("Indice MASI", "Six derniers mois, avec moyennes mobiles 20 et 50 séances.")
    hist = shared.index_history("MASI", "6M")
    if hist.empty:
        ui.empty_state("Historique MASI indisponible.", "📉")
        return
    frame = hist.rename(columns={"value": "close"})
    enriched = technical.add_indicators(frame)
    import plotly.graph_objects as go

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=enriched["date"], y=enriched["close"], name="MASI", mode="lines",
        line=dict(color=COLORS["primary"], width=2.6),
    ))
    for col, color, label in (("sma20", COLORS["accent"], "MM 20"), ("sma50", COLORS["warning"], "MM 50")):
        if col in enriched.columns:
            fig.add_trace(go.Scatter(x=enriched["date"], y=enriched[col], name=label,
                                     line=dict(color=color, width=1.7)))
    lo = enriched["low"].min() if "low" in enriched else None
    hi = enriched["high"].max() if "high" in enriched else None
    if lo and hi:
        fig.add_hrect(y0=lo, y1=hi, fillcolor="rgba(91,141,239,.04)", line_width=0)
    vals = enriched["close"].dropna()
    if not vals.empty:
        pad = max((vals.max() - vals.min()) * 0.12, 1.0)
        fig.update_yaxes(range=[vals.min() - pad, vals.max() + pad])
    fig.update_layout(title="", height=430, hovermode="x unified",
                      margin=dict(l=48, r=24, t=10, b=38))
    ui.plot(fig, key="dash_masi")


def _market_map(table: pd.DataFrame) -> None:
    """Carte thermique filtrable + largeur de marché calculée sur les mêmes données."""
    ui.section(
        "Carte du marché",
        "Taille = capitalisation boursière · couleur = performance sur la période choisie. "
        "Une valeur sans donnée reste grise : aucune variation n'est inventée.",
    )
    if table is None or table.empty:
        ui.empty_state(
            "Carte indisponible : aucune capitalisation n'a pu être chargée depuis la BVC. "
            "Réessayez l'actualisation ; les autres modules restent utilisables.",
            "🗺️",
        )
        return

    sectors = sorted(str(s) for s in table["sector"].dropna().unique()) if "sector" in table.columns else []
    c1, c2, c3 = st.columns([1.6, 1, 1])
    with c1:
        chosen_sectors = st.multiselect(
            "Secteurs", sectors, default=[], placeholder="Tous les secteurs",
            key="dash_map_sectors",
        )
    with c2:
        metric_label = st.selectbox(
            "Couleur", ["Séance", "YTD", "1 an", "3 mois"], index=0, key="dash_map_metric",
        )
    with c3:
        index_code = st.selectbox("Indice", ["Tous", "MASI", "MSI20"], index=0, key="dash_map_index")

    metric_col = {
        "Séance": "change_pct", "YTD": "ytd_pct", "1 an": "return_12m", "3 mois": "return_3m",
    }[metric_label]

    sub = table.copy()
    if chosen_sectors and "sector" in sub.columns:
        sub = sub[sub["sector"].isin(chosen_sectors)]
    if index_code != "Tous" and "symbol" in sub.columns:
        members = shared.index_members(index_code)
        if members:
            sub = sub[sub["symbol"].astype(str).isin(members)]
        else:
            st.caption(
                f"Composition officielle de {index_code} indisponible : le filtre d'indice est "
                "ignoré, la carte affiche toutes les valeurs."
            )

    if sub.empty:
        ui.empty_state("Aucune valeur ne correspond aux filtres sélectionnés.", "🔍")
    else:
        ui.plot(
            charts.sector_treemap(
                sub, color_col=metric_col, color_label=metric_label, height=560,
            ),
            key="dash_treemap", height=560,
        )

    _breadth_bar(table, sub)
    st.caption(
        "Vert = hausse, rouge = baisse, gris = donnée indisponible ou inchangée. "
        "La capitalisation provient de la BVC ; elle n'est pas estimée à partir d'un cours théorique."
    )


def _breadth_bar(table: pd.DataFrame, selected: pd.DataFrame) -> None:
    """Largeur de marché : hausses / baisses / inchangés, en nombre et en proportion."""
    change = pd.to_numeric(table.get("change_pct"), errors="coerce") if "change_pct" in table.columns else pd.Series(dtype=float)
    up = int((change > 0).sum())
    down = int((change < 0).sum())
    flat = int((change == 0).sum())
    missing = int(change.isna().sum())
    total = up + down + flat + missing
    if total == 0:
        st.caption("Largeur de marché indisponible : aucune variation publiée.")
        return
    pct = lambda n: 100.0 * n / total
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:.8rem;margin:.4rem 0 .2rem">
          <span class="ei-badge ei-up">▲ {up} hausses · {pct(up):.0f} %</span>
          <span class="ei-badge ei-down">▼ {down} baisses · {pct(down):.0f} %</span>
          <span class="ei-badge ei-flat">= {flat} inchangés · {pct(flat):.0f} %</span>
          <span class="ei-muted" style="font-size:.78rem">{missing} sans variation publiée · {len(selected)} affichées après filtres</span>
        </div>
        <div style="display:flex;height:10px;border-radius:6px;overflow:hidden;border:1px solid {COLORS['border']}">
          <div style="width:{pct(up):.2f}%;background:{COLORS['up']}"></div>
          <div style="width:{pct(flat):.2f}%;background:{COLORS['flat']}"></div>
          <div style="width:{pct(missing):.2f}%;background:{COLORS['muted']}"></div>
          <div style="width:{pct(down):.2f}%;background:{COLORS['down']}"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _masi_volatility() -> None:
    """Volatilité réalisée du MASI, calculée sur l'historique réel (pas le VIX)."""
    hist = shared.index_history("MASI", "6M")
    if hist is None or hist.empty or "value" not in hist.columns:
        st.caption("Volatilité réalisée du MASI indisponible : historique d'indice non chargé.")
        return
    frame = hist.copy()
    if "date" in frame.columns:
        frame = frame.sort_values("date")
    series = pd.to_numeric(frame["value"], errors="coerce").dropna()
    if len(series) < 20:
        st.caption("Volatilité réalisée du MASI : historique insuffisant (moins de 20 séances).")
        return
    returns = series.pct_change().dropna().tail(60)
    vol = float(returns.std(ddof=1) * (252 ** 0.5) * 100.0)
    st.metric("Volatilité réalisée du MASI (annualisée)", f"{vol:.1f} %")
    st.caption(
        f"Calcul : écart-type des rendements quotidiens du MASI sur {len(returns)} séances × √252. "
        "Mesure **réalisée** (passée) propre à Casablanca, distincte de la volatilité implicite du VIX."
    )


def _vix_block(regime: Dict[str, Any]) -> None:
    vix = regime.get("vix") or {}
    ui.section(
        "Volatilité — VIX (S&P 500)",
        "Référence internationale : le VIX mesure la volatilité implicite des options sur le S&P 500, "
        "**pas** celle du MASI.",
    )
    ui.plot(charts.gauge(vix.get("level"), title="VIX", max_value=45,
                         steps=[(0, 12, COLORS["accent"]), (12, 16, COLORS["primary"]),
                                (16, 22, COLORS["accent"]), (22, 30, COLORS["warning"]),
                                (30, 45, COLORS["danger"])]),
            key="dash_vix", height=250)
    pct = vix.get("percentile")
    ui.note(
        f"**{vix.get('label') or '—'}** — {vix.get('advice') or ''}",
        "good" if (vix.get("score") or 0) > 0.2 else "warn" if (vix.get("score") or 0) < -0.2 else "info",
        "📊",
    )
    if pct is not None:
        st.caption(f"Niveau actuel supérieur à {pct:.0%} des observations des trois dernières années.")
    _masi_volatility()
    comps = regime.get("components") or {}
    if comps:
        st.markdown("**Décomposition du régime de marché**")
        for label, value in comps.items():
            v = float(value or 0)
            color = COLORS["up"] if v > 0 else COLORS["down"] if v < 0 else COLORS["muted"]
            width = min(abs(v), 1.0) * 100
            direction = "left" if v < 0 else "left"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:.6rem;margin:.15rem 0">'
                f'<div style="flex:0 0 40%;font-size:.8rem" class="ei-muted">{label}</div>'
                f'<div style="flex:1;background:rgba(141,162,192,.14);border-radius:6px;height:8px">'
                f'<div style="width:{width:.0f}%;height:8px;border-radius:6px;background:{color}"></div></div>'
                f'<div style="flex:0 0 46px;text-align:right;font-size:.78rem;font-weight:700;color:{color}">'
                f'{v:+.2f}</div></div>',
                unsafe_allow_html=True,
            )


def _movers(table: pd.DataFrame) -> None:
    ui.section("Mouvements de la séance", "Cinq plus fortes hausses et baisses, et volumes les plus élevés.")
    if table.empty:
        ui.empty_state("Données indisponibles.", "📉")
        return
    movers = table.dropna(subset=["change_pct"])
    if movers.empty:
        ui.empty_state("Aucun mouvement enregistré.", "📉")
        return
    top = pd.concat([
        movers.nlargest(5, "change_pct")[["symbol", "name", "close", "change_pct"]],
        movers.nsmallest(5, "change_pct")[["symbol", "name", "close", "change_pct"]],
    ])
    ui.plot(charts.movers_bar(top), key="dash_movers", height=430)

    vols = movers.dropna(subset=["volume"]).nlargest(6, "volume")[
        ["symbol", "name", "close", "change_pct", "volume"]
    ].copy()
    if not vols.empty:
        st.markdown("**Volumes les plus élevés**")
        display = vols.rename(columns={
            "symbol": "Symbole", "name": "Société", "close": "Cours (MAD)",
            "change_pct": "Séance", "volume": "Volume (MAD)",
        })
        display["Séance"] = display["Séance"].apply(lambda v: fmt_pct(v, 2, signed=True))
        display["Cours (MAD)"] = display["Cours (MAD)"].apply(lambda v: fmt_num(v, 2))
        display["Volume (MAD)"] = display["Volume (MAD)"].apply(lambda v: fmt_money(v, "MAD", compact=True))
        ui.table(display, height=250, key="dash_vols")


def _briefing() -> None:
    ui.section("Briefing de l'agent IA", "Synthèse générée à partir des données réelles du marché.")
    status = llm_mod.provider_status()
    ui.note(
        f"Moteur : **{status['active']}** — "
        + ("analyse rédigée par un modèle de langage." if status["mode"] == "llm"
           else "mode analyste local (aucune clé d'API requise, 100 % hors-ligne)."),
        "info", "🤖",
    )
    if st.button("📰 Générer le briefing", key="dash_briefing_btn"):
        with st.spinner("Rédaction du briefing…"):
            agent = shared.build_agent()
            st.session_state["dash_briefing"] = agent.briefing()

    result = st.session_state.get("dash_briefing")
    if result:
        st.caption(f"Moteur : {result.get('provider') or '—'}")
        st.markdown(result.get("text") or "")
    else:
        ui.note(
            "Le briefing est régénéré à la demande à partir du régime de marché, de la largeur, "
            "des secteurs et des meilleures opportunités.",
            "info", "📰",
        )


def _global_block() -> None:
    ui.section("Marchés internationaux", "Contexte macro : indices, taux, matières premières et devises.")
    quotes = shared.global_quotes()
    if quotes.empty:
        ui.empty_state("Données internationales indisponibles (Yahoo Finance injoignable).", "🌍")
        return
    display = quotes[["name", "price", "change_pct", "return_1y"]].copy()
    display = display.rename(columns={
        "name": "Instrument", "price": "Niveau",
        "change_pct": "Séance", "return_1y": "1 an",
    })
    display["Niveau"] = display["Niveau"].apply(lambda v: fmt_num(v, 2))
    display["Séance"] = display["Séance"].apply(lambda v: fmt_pct(v, 2, signed=True))
    display["1 an"] = display["1 an"].apply(lambda v: fmt_pct(v, 1, signed=True))
    ui.table(display, height=430, key="dash_global")

    macro = shared.macro()
    if macro:
        items = [
            {"label": "US 10 ans", "value": fmt_num(macro.get("us10y"), 2) + " %",
             "sub": macro.get("rates_regime", ""), "tone": "blue"},
            {"label": "Or (once)", "value": fmt_num(macro.get("gold"), 0) + " $",
             "sub": fmt_pct(macro.get("gold_change"), 2, signed=True), "tone": "warn"},
            {"label": "Pétrole WTI", "value": fmt_num(macro.get("oil"), 2) + " $",
             "sub": fmt_pct(macro.get("oil_change"), 2, signed=True), "tone": "blue"},
        ]
        rates = shared.fx_rates()
        items.append({
            "label": "EUR / MAD", "value": fmt_num(rates.get("EUR"), 3),
            "sub": "Taux de conversion appliqué", "tone": "accent",
        })
        items.append({
            "label": "USD / MAD", "value": fmt_num(rates.get("USD"), 3),
            "sub": "Taux de conversion appliqué", "tone": "accent",
        })
        ui.kpi_row(items, per_row=5)
