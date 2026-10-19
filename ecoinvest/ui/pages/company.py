"""Analyse détaillée d'une valeur cotée à la Bourse de Casablanca."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from ...analytics import backtest, technical
from ...config import COLORS
from ...data import fundamentals, news
from ...utils.formatting import fmt_money, fmt_multiple, fmt_num, fmt_pct
from .. import charts, components as ui
from ..reporting import download_analysis
from . import shared

_TONE_BY_COLOR = {
    COLORS["primary"]: "up",
    COLORS["up"]: "up",
    COLORS["down"]: "down",
    COLORS["danger"]: "down",
    COLORS["warning"]: "warn",
    COLORS["muted"]: "flat",
    COLORS["accent"]: "info",
}


def render() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles. Vérifiez votre connexion.", "📡")
        return

    symbol = _selector(table)
    row = table[table["symbol"] == symbol].iloc[0]
    hist = shared.stock_history(symbol)
    enriched = technical.add_indicators(hist) if not hist.empty else hist
    summary = technical.technical_summary(enriched) if not enriched.empty else {}

    _header(row, symbol)
    _kpis(row)
    ui.source_note(
        ["Bourse de Casablanca (cours, volumes)", "Référentiel BVC (titres, dividende)", "RSS publics"],
        as_of=f"clôture du {_date(row.get('last_date'))}",
        detail="Les ratios fondamentaux ne sont calculés que si les états financiers correspondants sont saisis.",
    )

    tabs = st.tabs(
        ["🧭 Synthèse", "📈 Technique", "📊 Fondamentaux & ratios", "📰 Actualités",
         "🔬 Backtest", "🤖 Agent IA"]
    )
    with tabs[0]:
        _overview(row, enriched, summary)
    with tabs[1]:
        _technical(enriched, summary)
    with tabs[2]:
        _fundamentals(row, symbol)
    with tabs[3]:
        _news(row, symbol)
    with tabs[4]:
        _backtest(hist, symbol)
    with tabs[5]:
        _agent(symbol)

    ui.disclaimer()


# ═══════════════════════════ En-tête ═══════════════════════════


def _selector(table: pd.DataFrame) -> str:
    symbols = table["symbol"].tolist()
    names = dict(zip(table["symbol"], table["name"]))
    requested = str(st.session_state.get("selected_symbol") or "").upper()
    if requested not in symbols:
        requested = st.session_state.get("_last_symbol") or ("ATW" if "ATW" in symbols else symbols[0])
    index = symbols.index(requested) if requested in symbols else 0

    col, col_watch, col_refresh = st.columns([3, 1, 1])
    with col:
        symbol = st.selectbox(
            "Valeur analysée",
            symbols,
            index=index,
            format_func=lambda s: f"{s} — {names.get(s, s)}",
            key="company_symbol",
        )
    st.session_state["_last_symbol"] = symbol
    st.session_state["selected_symbol"] = symbol

    in_watch = symbol in shared.watchlist()
    with col_watch:
        st.write("")
        label = "⭐ Retirer du suivi" if in_watch else "☆ Suivre cette valeur"
        if st.button(label, key="company_watch", use_container_width=True):
            shared.toggle_watchlist(symbol)
            st.rerun()
    with col_refresh:
        st.write("")
        if st.button("🔄 Rafraîchir", key="company_refresh", use_container_width=True):
            shared.clear_caches()
            st.rerun()
    return symbol


def _header(row: pd.Series, symbol: str) -> None:
    change = row.get("change_pct")
    tone = "up" if (change or 0) > 0 else "down" if (change or 0) < 0 else "flat"
    price = fmt_num(row.get("close"), 2)
    badges = " ".join(
        b
        for b in (
            ui.badge(str(row.get("sector") or "—"), "info"),
            ui.badge(str(row.get("trend_state") or "—"), _state_tone(row.get("trend_state"))),
            ui.badge(str(row.get("momentum_state") or "—"), _state_tone(row.get("momentum_state"))),
            ui.badge(str(row.get("signal") or "—"), _signal_tone(row.get("signal"))),
            f'<span class="ei-badge ei-{tone}">{fmt_pct(change, 2, signed=True)}</span>',
        )
        if b
    )
    ui.hero(
        f"{row.get('name') or symbol} · {symbol}",
        f"Dernier cours **{price} MAD** · clôture du {_date(row.get('last_date'))} · "
        f"capitalisation {fmt_money(row.get('cap'), 'MAD', compact=True)}",
        badge=badges,
    )


def _kpis(row: pd.Series) -> None:
    items = [
        {"label": "Cours", "value": fmt_num(row.get("close"), 2) + " MAD",
         "sub": f"Veille {fmt_num(row.get('prev_close'), 2)}", "tone": "accent"},
        {"label": "Performance séance", "value": fmt_pct(row.get("change_pct"), 2, signed=True),
         "sub": "variation du jour", "tone": "up" if (row.get("change_pct") or 0) >= 0 else "down"},
        {"label": "Performance 1 an", "value": fmt_pct(row.get("return_12m"), 1, signed=True),
         "sub": f"YTD {fmt_pct(row.get('ytd_pct'), 1, signed=True)}",
         "tone": "up" if (row.get("return_12m") or 0) >= 0 else "down"},
        {"label": "Score composite", "value": fmt_num(row.get("composite_score"), 0) + " / 100",
         "sub": "marché + technique + fondamentaux", "tone": "blue"},
        {"label": "Volatilité annualisée", "value": fmt_pct(row.get("volatility"), 1),
         "sub": f"bêta {fmt_num(row.get('beta'), 2)}", "tone": "warn"},
        {"label": "Volume du jour", "value": fmt_money(row.get("volume"), "MAD", compact=True),
         "sub": f"{fmt_num(row.get('transactions'), 0)} transactions", "tone": "blue"},
    ]
    ui.kpi_row(items, per_row=6)


# ═══════════════════════════ Onglet Synthèse ═══════════════════════════


def _overview(row: pd.Series, enriched: pd.DataFrame, summary: Dict[str, Any]) -> None:
    left, right = st.columns([1.7, 1], gap="medium")
    with left:
        ui.section("Cours et tendance", "Chandeliers, moyennes mobiles 20/50/200 et bandes de Bollinger.")
        if enriched.empty:
            ui.empty_state("Historique de cours indisponible pour cette valeur.", "📉")
        else:
            ui.plot(charts.candlestick(enriched.tail(180), symbol=str(row.get("symbol"))),
                    key="company_candle", height=560)

        ui.section("Performance comparée", "Base 100 sur douze mois, face au MASI.")
        comp = _comparison(row)
        if comp is None:
            ui.empty_state("Comparaison indisponible.", "📊")
        else:
            ui.plot(comp, key="company_compare", height=380)

    with right:
        score = row.get("composite_score")
        st.markdown(ui.score_ring(score), unsafe_allow_html=True)
        st.write("")
        explain = _explain(row)
        if explain:
            ui.plot(charts.radar(explain, title="Profil multifactoriel", height=330),
                    key="company_radar")

        plan = row.get("entry_plan")
        if isinstance(plan, dict):
            ui.section("Plan d'entrée suggéré")
            ui.stat_line(
                [
                    ("Zone d'entrée", f"{fmt_num(plan.get('entree_zone_basse'), 2)} – "
                                      f"{fmt_num(plan.get('entree_zone_haute'), 2)}"),
                    ("Stop de protection", fmt_num(plan.get("stop"), 2) + " MAD"),
                    ("Objectif", fmt_num(plan.get("objectif"), 2) + " MAD"),
                    ("Ratio risque / rendement", fmt_num(plan.get("ratio_rr"), 2)),
                ],
                per_row=2,
            )
            ui.note(
                "Le plan d'entrée est calculé à partir de la volatilité observée et des plus hauts "
                "52 semaines. Il ne constitue pas un conseil personnalisé.",
                "info", "🎯",
            )

        st.write("")
        verdict = _verdict(row)
        ui.verdict(verdict["title"], verdict["body"], verdict["color"])


def _comparison(row: pd.Series) -> Optional[Any]:
    import plotly.graph_objects as go

    hist = shared.stock_history(str(row.get("symbol")), days=400)
    index = shared.index_history("MASI", "1Y")
    if hist.empty or index.empty:
        return None
    start = pd.Timestamp.today() - pd.Timedelta(days=365)
    stock = hist[hist["date"] >= start].set_index("date")["close"].astype(float)
    masi = index[index["date"] >= start].set_index("date")["value"].astype(float)
    if len(stock) < 2 or len(masi) < 2:
        return None

    fig = go.Figure()
    for label, series, color in (
        (str(row.get("symbol")), stock, COLORS["primary"]),
        ("MASI", masi, COLORS["accent"]),
    ):
        base = series.dropna()
        if base.empty or base.iloc[0] == 0:
            continue
        norm = base / base.iloc[0] * 100
        fig.add_trace(
            go.Scatter(x=norm.index, y=norm.values, name=label, mode="lines",
                       line=dict(color=color, width=2.3))
        )
    fig.update_layout(
        title="", height=380, yaxis_title="Base 100", hovermode="x unified",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


def _explain(row: pd.Series) -> Dict[str, Optional[float]]:
    from ...analytics.scoring import DIMENSION_LABELS, explain_score

    detail = explain_score(row)["dimensions"]
    out: Dict[str, Optional[float]] = {}
    for key, info in detail.items():
        points = info.get("points")
        if points is not None:
            out[DIMENSION_LABELS[key]] = float(points)
    return out


def _verdict(row: pd.Series) -> Dict[str, str]:
    signal = str(row.get("signal") or "")
    color = str(row.get("signal_color") or COLORS["muted"])
    trend = str(row.get("trend_state") or "—")
    momentum = str(row.get("momentum_state") or "—")
    score = row.get("composite_score")
    completeness = row.get("data_completeness") or 0.0

    body = (
        f"Tendance **{trend.lower()}**, momentum **{momentum.lower()}**, "
        f"score composite **{fmt_num(score, 0)}/100**."
    )
    if completeness < 0.34:
        body += (
            "\n\n⚠️ **Analyse technique seule** : aucune donnée comptable n'est renseignée pour "
            "cette valeur. Le score ne reflète ni la valorisation, ni la qualité des bénéfices. "
            "Complétez la page « Données fondamentales » pour un diagnostic complet."
        )
    else:
        body += (
            f"\n\nValorisation et qualité sont intégrées (complétion des données : "
            f"{completeness:.0%})."
        )
    return {"title": signal.replace(" (technique seul)", "") or "Analyse", "body": body, "color": color}


# ═══════════════════════════ Onglet Technique ═══════════════════════════


def _technical(enriched: pd.DataFrame, summary: Dict[str, Any]) -> None:
    if enriched.empty:
        ui.empty_state("Historique indisponible : impossible de calculer les indicateurs.", "📉")
        return

    trend = summary.get("trend") or {}
    momentum = summary.get("momentum") or {}
    volume = summary.get("volume") or {}
    levels = summary.get("levels") or {}

    ui.kpi_row(
        [
            {"label": "Tendance", "value": str(trend.get("state") or "—"),
             "sub": "moyennes mobiles", "tone": _state_tone(trend.get("state"))},
            {"label": "Momentum", "value": str(momentum.get("state") or "—"),
             "sub": f"RSI {fmt_num(momentum.get('rsi'), 0)}", "tone": _state_tone(momentum.get("state"))},
            {"label": "Volume", "value": str(volume.get("state") or "—"),
             "sub": str(volume.get("note") or "—"), "tone": "blue"},
            {"label": "Support 120 j", "value": fmt_num(levels.get("support"), 2),
             "sub": f"résistance {fmt_num(levels.get('resistance'), 2)}", "tone": "warn"},
            {"label": "Score technique", "value": fmt_num(summary.get("score"), 2),
             "sub": "échelle −1 à +1", "tone": "accent"},
        ],
        per_row=5,
    )

    ui.section("Oscillateurs", "RSI, MACD et histogramme de momentum.")
    ui.plot(charts.indicator_panel(enriched.tail(180)), key="company_indicators", height=520)

    ui.section("Volatilité et drawdown", "Volatilité glissante 20 jours et correction depuis le plus haut.")
    ui.plot(charts.volatility_cone(enriched.tail(250)), key="company_vol", height=380)

    left, right = st.columns(2, gap="medium")
    with left:
        ui.section("Lecture de la tendance")
        for line_msg in trend.get("notes") or []:
            st.markdown(f"- {line_msg}")
        st.markdown("**Momentum**")
        for line_msg in momentum.get("notes") or []:
            st.markdown(f"- {line_msg}")
    with right:
        ui.section("Signaux techniques actifs")
        signals = summary.get("signals") or []
        if not signals:
            ui.note("Aucun signal de croisement actif sur la dernière séance.", "info", "ℹ️")
        for sig in signals:
            tone = "up" if sig.get("type") == "achat" else "down"
            ui.note(f"**{sig.get('signal')}** — {sig.get('detail')}", tone,
                    "🟢" if tone == "up" else "🔴")

        ui.section("Niveaux clés")
        ui.stat_line(
            [
                ("Support", fmt_num(levels.get("support"), 2)),
                ("Pivot", fmt_num(levels.get("pivot"), 2)),
                ("Résistance", fmt_num(levels.get("resistance"), 2)),
                ("Distance support", fmt_pct(levels.get("distance_support"), 2, signed=True)),
                ("Distance résistance", fmt_pct(levels.get("distance_resistance"), 2, signed=True)),
                ("MM 20 / 50 / 200",
                 f"{fmt_num(enriched['sma20'].iloc[-1], 1)} / {fmt_num(enriched['sma50'].iloc[-1], 1)} / "
                 f"{fmt_num(enriched['sma200'].iloc[-1], 1)}"),
            ],
            per_row=3,
        )


# ═══════════════════════════ Onglet Fondamentaux ═══════════════════════════


def _fundamentals(row: pd.Series, symbol: str) -> None:
    f = fundamentals.get_fundamentals(symbol, row)
    ratios = fundamentals.compute_ratios(f, price=row.get("close"), cap=row.get("cap"))
    table = fundamentals.ratio_table(f, price=row.get("close"), cap=row.get("cap"))

    computed = int(table["Valeur"].notna().sum())
    statement_status = f.get("statement_status")
    ui.note(
        f"**{computed} ratios calculés** sur {len(table)}. Les ratios proviennent des états "
        "financiers (AMMC, API configurée ou import vérifié) et du cours de bourse réel. "
        "Aucune donnée n'est inventée : les champs non renseignés restent vides."
        + (
            f" Exercice suivi : **{f.get('statement_fiscal_year')}** "
            f"({statement_status or 'source à vérifier'})."
            if f.get("statement_source") else ""
        ),
        "info", "📚",
    )
    pages = st.session_state.get("_nav_pages") or {}
    if "statements_page" in pages:
        st.page_link(
            pages["statements_page"],
            label="🧾 Ouvrir les états financiers (bilan, compte de résultat, trésorerie)",
            icon="🧾",
        )

    key_ratios = ["per", "pb", "dividend_yield", "roe", "net_margin", "debt_to_equity",
                  "fcf_yield", "revenue_growth"]
    _ratio_cards(table, key_ratios)

    st.write("")
    ui.section("Tableau complet des ratios", "Valeur, appréciation et interprétation.")
    display = table.copy()
    display["Valeur"] = [
        _fmt_ratio_value(r.get("Valeur"), r.get("Unit")) for _, r in display.iterrows()
    ]
    display = display[["Ratio", "Valeur", "Appréciation", "Interprétation"]]
    display.columns = ["Ratio", "Valeur", "Appréciation", "Interprétation"]
    ui.table(display, height=min(620, 60 + 32 * len(display)), key="company_ratios")

    with st.expander("📖 Comprendre chaque ratio", expanded=False):
        for _, r in table.iterrows():
            if pd.isna(r.get("Valeur")):
                continue
            info = fundamentals.interpret_ratio(str(r["key"]), r.get("Valeur"))
            st.markdown(
                f"**{info['label']}** — *{info['grade']}*  \n"
                f"{info.get('meaning', '')}  \n"
                f"> {info.get('text', '')}"
            )

    if computed == 0:
        ui.note(
            "Aucun état financier n'est encore disponible pour cette société. Ouvrez la page "
            "« États financiers » pour importer le bilan, le CPC et la trésorerie (API, CSV "
            "vérifié ou documents AMMC) : les ratios, la valorisation et les signaux "
            "fondamentaux seront alors calculés automatiquement.",
            "warn", "⚙️",
        )


def _ratio_cards(table: pd.DataFrame, keys: List[str]) -> None:
    subset = table[table["key"].isin(keys)]
    if subset.empty:
        return
    cols = st.columns(4)
    for i, (_, r) in enumerate(subset.iterrows()):
        info = fundamentals.interpret_ratio(str(r["key"]), r.get("Valeur"))
        color = info.get("color") or COLORS["muted"]
        tone = _TONE_BY_COLOR.get(color, "info")
        value = _fmt_ratio_value(r.get("Valeur"), r.get("Unit"))
        with cols[i % 4]:
            st.markdown(
                f'<div class="ei-card" style="border-left:4px solid {color};min-height:132px">'
                f'<div class="ei-kpi-label">{info["label"]}</div>'
                f'<div class="ei-kpi-value" style="font-size:1.35rem">{value}</div>'
                f'<div style="margin:.25rem 0">{ui.badge(str(info["grade"]), tone)}</div>'
                f'<div class="ei-kpi-sub" style="font-size:.74rem;line-height:1.35">'
                f'{info.get("text", "")[:150]}</div></div>',
                unsafe_allow_html=True,
            )


def _fmt_ratio_value(value: Any, unit: Optional[str]) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if unit == "%":
        return fmt_pct(v, 2)
    if unit == "x":
        return fmt_multiple(v, 2)
    return fmt_num(v, 2)


# ═══════════════════════════ Onglet Actualités ═══════════════════════════


def _news(row: pd.Series, symbol: str) -> None:
    ui.section("Actualités de la société", "Flux RSS publics, dédupliqués et analysés en sentiment.")
    try:
        with st.spinner("Recherche des actualités…"):
            df = news.company_news(str(row.get("name") or symbol), symbol, limit=20)
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        ui.empty_state("Aucune actualité récente trouvée pour cette valeur.", "📰")
        return
    for _, item in df.head(15).iterrows():
        _news_card(item)


def _news_card(item: pd.Series) -> None:
    import html as html_mod

    score = item.get("sentiment") or 0.0
    tone = "up" if score > 0.12 else "down" if score < -0.12 else "flat"
    date = _date(item.get("published"))
    link = str(item.get("link") or "#")
    title = html_mod.escape(str(item.get("title") or "Sans titre"))
    source = html_mod.escape(str(item.get("source") or ""))
    summary = html_mod.escape(str(item.get("summary") or ""))[:240]
    st.markdown(
        f"""
        <div class="ei-card" style="margin-bottom:.6rem">
          <div style="display:flex;justify-content:space-between;gap:1rem;align-items:baseline">
            <a href="{link}" target="_blank" style="font-weight:700;font-size:.98rem;color:{COLORS['text']};text-decoration:none">{title}</a>
            <span class="ei-badge ei-{tone}">{html_mod.escape(str(item.get('sentiment_label') or 'Neutre'))}</span>
          </div>
          <div class="ei-muted" style="font-size:.76rem;margin:.25rem 0">{source} · {date}</div>
          <div class="ei-muted" style="font-size:.82rem;line-height:1.45">{summary}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ═══════════════════════════ Onglet Agent IA ═══════════════════════════


def _backtest(hist: pd.DataFrame, symbol: str) -> None:
    ui.section(
        "Backtest d'une règle simple",
        "Une stratégie mécanique appliquée à l'historique réel des cours, frais de transaction inclus.",
    )
    if hist is None or hist.empty or "close" not in hist.columns:
        ui.note("Historique de prix indisponible pour cette valeur.", "warn", "📉")
        return

    frame = hist.dropna(subset=["close"]).copy()
    prices = pd.Series(frame["close"].to_numpy(dtype=float),
                       index=pd.to_datetime(frame["date"])).sort_index()
    prices = prices[prices > 0]

    ui.note(
        "**Méthode honnête.** Un signal calculé en clôture n'agit que le lendemain (aucune "
        "anticipation). Chaque aller-retour paie des frais. Les paramètres sont choisis sur une "
        "première période puis testés **hors échantillon**, une seule fois. Un backtest ne prédit "
        "rien : il montre seulement ce qu'une règle aurait donné sur le passé.",
        "info", "🔬",
    )

    strategy_keys = list(backtest.STRATEGIES)
    columns = st.columns(len(backtest.STRATEGIES["ma_cross"]["params"]) + 3)
    with columns[0]:
        strategy = st.selectbox(
            "Stratégie", strategy_keys,
            format_func=lambda key: backtest.STRATEGIES[key]["label"], key="bt_strategy",
        )
    meta = backtest.STRATEGIES[strategy]
    params: Dict[str, Any] = {}
    for i, (name, label, default) in enumerate(meta["params"]):
        with columns[i + 1]:
            params[name] = st.number_input(
                label, value=float(default), min_value=1.0, step=1.0, key=f"bt_{strategy}_{name}"
            )
    with columns[-2]:
        cost_bps = st.number_input("Frais A/R (pb)", value=20.0, min_value=0.0, step=5.0,
                                   key="bt_cost", help="Courtage et taxes, en points de base, facturés à l'aller et au retour.")
    with columns[-1]:
        slippage_bps = st.number_input("Slippage (pb)", value=0.0, min_value=0.0, step=5.0,
                                       key="bt_slip")

    signals = backtest._strategy_signals(strategy, prices, params)
    result = backtest.run(prices, signals, cost_bps=cost_bps, slippage_bps=slippage_bps)
    if not result["available"]:
        ui.note(result["reason"], "warn", "📉")
        return

    metrics, market = result["metrics"], result["buy_hold"]
    tone = "up" if (metrics["total_return"] or 0) >= 0 else "down"
    ui.kpi_row(
        [
            {"label": "Stratégie", "value": fmt_pct(metrics["total_return"], 1),
             "sub": f"{metrics['entries']} entrée(s)", "tone": tone},
            {"label": "Achat-conservation", "value": fmt_pct(market["total_return"], 1),
             "sub": "même période", "tone": "blue"},
            {"label": "Sharpe", "value": fmt_num(metrics["sharpe"], 2),
             "sub": "annualisé, hors taux sans risque", "tone": "info"},
            {"label": "Drawdown max", "value": fmt_pct(metrics["max_drawdown"], 1),
             "sub": "pire baisse", "tone": "warn"},
            {"label": "Exposition", "value": fmt_pct(metrics["exposure"], 0),
             "sub": "du temps investi", "tone": "info"},
        ],
        per_row=5,
    )

    curve = pd.DataFrame({
        "Stratégie": result["equity"],
        "Achat-conservation": result["buy_hold_equity"],
    })
    ui.plot(
        charts.normalized_comparison(
            {"Stratégie": result["equity"], "Achat-conservation": result["buy_hold_equity"]},
            title=f"{symbol} — capital simulé (base 100), frais inclus", height=360,
        ),
        key=f"bt_curve_{symbol}",
    )
    ui.download_row(curve.reset_index().rename(columns={"index": "date"}),
                    f"backtest_{symbol}.csv", "⬇️ Exporter la courbe (CSV)")

    st.divider()
    _walk_forward(symbol, prices, strategy, cost_bps, slippage_bps)


def _walk_forward(symbol: str, prices: pd.Series, strategy: str,
                  cost_bps: float, slippage_bps: float) -> None:
    ui.section(
        "Validation hors échantillon",
        "Les paramètres sont choisis sur la première période et vérifiés une seule fois sur la seconde.",
    )
    train_frac = st.slider("Part d'apprentissage", 0.4, 0.8, 0.6, 0.05, key="bt_train")
    wf = backtest.walk_forward(
        prices, strategy, train_frac=train_frac, cost_bps=cost_bps, slippage_bps=slippage_bps
    )
    if not wf["available"]:
        ui.note(wf["reason"], "warn", "📉")
        return

    params = wf["best_params"]
    pretty = " · ".join(f"{key} = {value:.0f}" for key, value in params.items())
    st.caption(f"Paramètres retenus sur l'apprentissage : **{pretty}** "
               f"({wf['strategy_label']}).")
    oos, ins = wf["out_of_sample"], wf["in_sample"]
    cols = st.columns(2)
    for col, label, block in ((cols[0], "Apprentissage", ins), (cols[1], "Hors échantillon", oos)):
        with col:
            st.markdown(f"**{label}**")
            ui.kpi_row(
                [
                    {"label": "Rendement", "value": fmt_pct(block["total_return"], 1),
                     "sub": f"{block['sessions']} séances",
                     "tone": "up" if (block["total_return"] or 0) >= 0 else "down"},
                    {"label": "Sharpe", "value": fmt_num(block["sharpe"], 2), "sub": "", "tone": "info"},
                    {"label": "Drawdown", "value": fmt_pct(block["max_drawdown"], 1), "sub": "", "tone": "warn"},
                ],
                per_row=3,
            )
    drop = (ins["total_return"] is not None and oos["total_return"] is not None
            and oos["total_return"] < ins["total_return"])
    ui.note(
        "**Lecture.** Un écart entre apprentissage et hors échantillon signale une règle fragile "
        "(sur-ajustée). Les frais, le slippage et l'absence d'anticipation sont inclus ; la "
        "fiscalité, les frais de conservation et la liquidité réelle ne le sont pas. "
        + ("Ici la performance hors échantillon est **inférieure** : prudence." if drop
           else "Ici la performance hors échantillon ne se dégrade pas franchement — cela ne garantit rien."),
        "warn", "⚠️",
    )


def _agent(symbol: str) -> None:
    ui.section(
        "Analyse de l'agent IA",
        "Synthèse fondamentale, technique et risque, adaptée à votre profil. Le rapport PDF reprend "
        "les données, les sources, les limites et l'avertissement.",
    )
    key = f"company_analysis_{symbol}"
    direct_key = f"company_direct_{symbol}"
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🤖 Générer l'analyse complète", key=f"agent_btn_{symbol}", use_container_width=True):
            with st.spinner("Analyse en cours…"):
                agent = shared.build_agent()
                st.session_state[key] = agent.analyse_company(symbol)
    with c2:
        if st.button("⚡ Analyse directe : tendance & scénarios", key=f"agent_direct_btn_{symbol}",
                     use_container_width=True):
            with st.spinner("Analyse en cours…"):
                agent = shared.build_agent()
                st.session_state[direct_key] = agent.analyse_titre(symbol)

    for label, state_key in (("Analyse complète", key), ("Analyse directe", direct_key)):
        result = st.session_state.get(state_key)
        if not result:
            continue
        st.markdown(f"#### {label}")
        st.caption(
            f"Moteur : {result.get('provider') or '—'} · généré le "
            f"{result.get('generated_at') or '—'} · valeur : {result.get('symbol') or symbol}"
        )
        st.markdown(result.get("text") or "")
        download_analysis(result, symbol, key=f"company_{state_key}")
        st.divider()

    if not st.session_state.get(key) and not st.session_state.get(direct_key):
        ui.note(
            "L'agent combine les données de marché réelles, les indicateurs techniques, les ratios "
            "disponibles et votre profil d'investisseur. Sans clé d'API, il fonctionne en mode "
            "analyste local hors-ligne. L'analyse directe ajoute les scénarios haussier/baissier "
            "et les niveaux d'invalidation observables.",
            "info", "🤖",
        )
    pages = st.session_state.get("_nav_pages") or {}
    if "alerts_page" in pages:
        st.page_link(pages["alerts_page"], label="🔔 Ouvrir le centre d'alertes", icon="🔔")


# ═══════════════════════════ Utilitaires ═══════════════════════════


def _state_tone(state: Any) -> str:
    text = str(state or "").lower()
    if "hausse" in text or "fort" in text or "positif" in text:
        return "up"
    if "baisse" in text or "négatif" in text or "faible" in text:
        return "down"
    if "neutre" in text or "indécise" in text:
        return "warn"
    return "info"


def _signal_tone(signal: Any) -> str:
    text = str(signal or "")
    if "Achat" in text:
        return "up"
    if "Éviter" in text or "vendre" in text:
        return "down"
    if "Attendre" in text or "Alléger" in text:
        return "warn"
    return "info"


def _date(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    try:
        return pd.Timestamp(value).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)
