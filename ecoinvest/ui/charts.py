"""Fabrique de graphiques Plotly pour l'ensemble de l'application."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..config import COLORS, PALETTE

C = COLORS


def _base(fig: go.Figure, title: str = "", height: int = 420) -> go.Figure:
    fig.update_layout(title=title, height=height, showlegend=True)
    return fig


# ═══════════════════════════ Cours ═══════════════════════════


def candlestick(
    df: pd.DataFrame,
    symbol: str = "",
    overlays: bool = True,
    volume: bool = True,
    height: int = 560,
    title: str = "",
) -> go.Figure:
    """Chandeliers + moyennes mobiles + bandes de Bollinger + volumes."""
    if df is None or df.empty:
        return _base(go.Figure(), "Aucune donnée", 300)

    show_bb = overlays and "bb_upper" in df.columns
    rows = 2 if volume and "volume" in df.columns else 1
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.76, 0.24] if rows == 2 else [1.0],
    )

    fig.add_trace(
        go.Candlestick(
            x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            name=symbol or "Cours",
            increasing=dict(line=dict(color=C["up"]), fillcolor=C["up"]),
            decreasing=dict(line=dict(color=C["down"]), fillcolor=C["down"]),
        ),
        row=1, col=1,
    )

    if overlays:
        if show_bb:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["bb_upper"], name="Bollinger +2σ",
                           line=dict(color="rgba(167,139,250,.65)", width=1, dash="dot")),
                row=1, col=1,
            )
            fig.add_trace(
                go.Scatter(x=df["date"], y=df["bb_lower"], name="Bollinger −2σ",
                           line=dict(color="rgba(167,139,250,.65)", width=1, dash="dot"),
                           fill="tonexty", fillcolor="rgba(167,139,250,.06)"),
                row=1, col=1,
            )
        for window, color, label in ((20, C["accent"], "MM 20"), (50, C["warning"], "MM 50"),
                                     (200, C["accent2"], "MM 200")):
            col = f"sma{window}"
            if col in df.columns and df[col].notna().any():
                fig.add_trace(
                    go.Scatter(x=df["date"], y=df[col], name=label,
                               line=dict(color=color, width=1.6)),
                    row=1, col=1,
                )

    if rows == 2:
        colors = [
            C["up"] if (c is not None and o is not None and c >= o) else C["down"]
            for c, o in zip(df["close"], df["open"])
        ]
        fig.add_trace(
            go.Bar(x=df["date"], y=df["volume"], name="Volume", marker_color=colors,
                   marker_line_width=0, opacity=0.65),
            row=2, col=1,
        )

    fig.update_layout(
        title=title or f"{symbol} — cours",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        height=height,
        bargap=0.15,
    )
    fig.update_xaxes(showgrid=False)
    return fig


def line_series(
    x: Sequence[Any],
    y: Sequence[Any],
    name: str = "",
    color: Optional[str] = None,
    fill: bool = False,
    title: str = "",
    height: int = 380,
    y_title: str = "",
    hover_suffix: str = "",
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x, y=y, name=name, mode="lines",
            line=dict(color=color or C["primary"], width=2.4),
            fill="tozeroy" if fill else None,
            fillcolor="rgba(34,211,166,.10)" if fill else None,
            hovertemplate="%{x}<br>%{y:,.2f}" + (hover_suffix or "") + "<extra></extra>",
        )
    )
    fig.update_layout(title=title, height=height, yaxis_title=y_title, showlegend=bool(name))
    return fig


def multi_line(
    df: pd.DataFrame,
    x: str,
    columns: Sequence[str],
    title: str = "",
    height: int = 420,
    y_title: str = "",
    colors: Optional[Sequence[str]] = None,
) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(columns):
        if col not in df.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=df[x], y=df[col], name=col, mode="lines",
                line=dict(color=(colors[i] if colors and i < len(colors) else PALETTE[i % len(PALETTE)]),
                          width=2.2),
            )
        )
    fig.update_layout(title=title, height=height, yaxis_title=y_title, hovermode="x unified")
    return fig


def normalized_comparison(
    series_map: Dict[str, pd.Series],
    title: str = "Performance comparée (base 100)",
    height: int = 420,
) -> go.Figure:
    """Compare plusieurs séries en base 100."""
    fig = go.Figure()
    for i, (label, s) in enumerate(series_map.items()):
        if s is None or len(s) < 2:
            continue
        base = s.dropna()
        if base.empty or base.iloc[0] == 0:
            continue
        norm = base / base.iloc[0] * 100
        fig.add_trace(
            go.Scatter(x=norm.index, y=norm.values, name=label, mode="lines",
                       line=dict(color=PALETTE[i % len(PALETTE)], width=2.1))
        )
    fig.update_layout(title=title, height=height, yaxis_title="Base 100", hovermode="x unified")
    return fig


# ═══════════════════════════ Simulation Monte-Carlo ═══════════════════════════


def monte_carlo_paths(
    mc: Dict[str, Any],
    symbol: str = "",
    height: int = 420,
    show_paths: int = 60,
) -> go.Figure:
    """Trajectoires simulées, bandes de percentiles P5–P95 et cours initial."""
    fig = go.Figure()
    if not mc or not mc.get("available"):
        return fig
    pct = mc.get("percentiles") or {}
    if "p50" not in pct:
        return fig
    x = list(range(len(pct["p50"])))

    def band(lo: str, hi: str, fill: str) -> None:
        fig.add_trace(go.Scatter(x=x, y=pct[hi], line=dict(width=0),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=pct[lo], line=dict(width=0), fill="tonexty",
                                 fillcolor=fill, name=f"{lo.upper()}–{hi.upper()}",
                                 hoverinfo="skip"))

    band("p5", "p95", "rgba(30,136,229,0.10)")
    band("p25", "p75", "rgba(30,136,229,0.18)")

    sample = mc.get("sample")
    if sample is not None:
        for i in range(min(len(sample), max(int(show_paths), 0))):
            fig.add_trace(go.Scatter(x=x, y=sample[i], mode="lines",
                                     line=dict(color="rgba(120,120,120,0.20)", width=0.7),
                                     hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=pct["p50"], name="Médiane (P50)", mode="lines",
                             line=dict(color=C["primary"], width=2.4)))
    fig.add_hline(y=mc["start"], line_color=C["warning"], line_dash="dash",
                  annotation_text="Cours initial", annotation_font_color=C["warning"])
    title = f"{symbol} — trajectoires simulées" if symbol else "Trajectoires simulées"
    fig.update_layout(title=title, height=height, xaxis_title="Séance (jours ouvrés)",
                      yaxis_title="Prix", hovermode="x unified")
    return fig


def final_distribution(
    mc: Dict[str, Any],
    price: Optional[float] = None,
    title: str = "Distribution des prix finaux",
    height: int = 320,
) -> go.Figure:
    """Histogramme des prix finaux avec médiane et cours initial."""
    fig = go.Figure()
    if not mc or not mc.get("available"):
        return fig
    final = np.asarray(mc.get("final", []), dtype=float)
    if final.size == 0:
        return fig
    fig.add_trace(go.Histogram(x=final, nbinsx=60, marker_color=C["accent"],
                               opacity=0.75, name="Prix finaux"))
    fig.add_vline(x=float(mc["start"]), line_color=C["warning"], line_width=2,
                  annotation_text="Cours initial", annotation_font_color=C["warning"])
    fig.add_vline(x=float(mc["median_final"]), line_color=C["primary"], line_width=2,
                  line_dash="dot", annotation_text="Médiane",
                  annotation_font_color=C["primary"])
    if price:
        fig.add_vline(x=float(price), line_color=C["accent2"], line_width=1, line_dash="dash",
                      annotation_text="Objectif", annotation_font_color=C["accent2"])
    fig.update_layout(title=title, height=height, xaxis_title="Prix final simulé (MAD)",
                      yaxis_title="Fréquence", showlegend=False,
                      margin=dict(l=10, r=10, t=30, b=10))
    return fig


# ═══════════════════════════ Indicateurs ═══════════════════════════


def indicator_panel(df: pd.DataFrame, height: int = 520) -> go.Figure:
    """RSI + MACD + histogramme MACD sur trois sous-graphiques."""
    if df is None or df.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05,
        row_heights=[0.34, 0.34, 0.32],
        subplot_titles=("RSI (14)", "MACD (12, 26, 9)", "Histogramme MACD"),
    )
    if "rsi14" in df.columns:
        fig.add_trace(go.Scatter(x=df["date"], y=df["rsi14"], name="RSI 14",
                                 line=dict(color=C["accent"], width=2)), row=1, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color=C["danger"], row=1, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color=C["primary"], row=1, col=1)
        fig.add_hrect(y0=70, y1=100, fillcolor=C["danger"], opacity=0.06, row=1, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor=C["primary"], opacity=0.06, row=1, col=1)
        fig.update_yaxes(range=[0, 100], row=1, col=1)
    if "macd" in df.columns:
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd"], name="MACD",
                                 line=dict(color=C["primary"], width=2)), row=2, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd_signal"], name="Signal",
                                 line=dict(color=C["warning"], width=1.6)), row=2, col=1)
    if "macd_hist" in df.columns:
        colors = [C["up"] if v is not None and v >= 0 else C["down"] for v in df["macd_hist"]]
        fig.add_trace(go.Bar(x=df["date"], y=df["macd_hist"], name="Histogramme",
                             marker_color=colors, opacity=0.7), row=3, col=1)
    fig.update_layout(height=height, hovermode="x unified", showlegend=True, bargap=0.1)
    return fig


def volatility_cone(df: pd.DataFrame, height: int = 380, title: str = "Volatilité et drawdown") -> go.Figure:
    if df is None or df.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if "volatility_20" in df.columns:
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["volatility_20"], name="Volatilité 20 j annualisée",
                       line=dict(color=C["warning"], width=2), fill="tozeroy",
                       fillcolor="rgba(245,181,71,.12)"),
            secondary_y=False,
        )
    if "drawdown" in df.columns:
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["drawdown"], name="Drawdown",
                       line=dict(color=C["danger"], width=1.8)),
            secondary_y=True,
        )
    fig.update_yaxes(title_text="Volatilité", tickformat=".0%", secondary_y=False)
    fig.update_yaxes(title_text="Drawdown", tickformat=".0%", secondary_y=True)
    fig.update_layout(title=title, height=height, hovermode="x unified")
    return fig


def gauge(value: Optional[float], title: str = "", max_value: float = 50,
          steps: Optional[Sequence[tuple]] = None, height: int = 260,
          suffix: str = "") -> go.Figure:
    """Jauge (VIX, score, etc.)."""
    v = 0 if value is None else float(value)
    if steps is None:
        steps = [(0, 12, C["accent"]), (12, 16, C["primary"]), (16, 22, C["accent"]),
                 (22, 30, C["warning"]), (30, max_value, C["danger"])]
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=v,
            number={"suffix": suffix, "font": {"size": 30, "color": C["text"]}},
            title={"text": title, "font": {"size": 13, "color": C["muted"]}},
            gauge={
                "axis": {"range": [0, max_value], "tickcolor": C["muted"], "tickfont": {"size": 10}},
                "bar": {"color": "rgba(231,238,249,.92)", "thickness": 0.22},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 0,
                "steps": [{"range": [a, b], "color": col} for a, b, col in steps],
                "threshold": {"line": {"color": C["text"], "width": 2},
                              "thickness": 0.8, "value": v},
            },
        )
    )
    fig.update_layout(height=height, margin=dict(l=18, r=18, t=42, b=8))
    return fig


def radar(dimensions: Dict[str, Optional[float]], title: str = "", height: int = 380) -> go.Figure:
    """Toile d'araignée des scores (valeurs 0–100)."""
    labels = [k for k, v in dimensions.items() if v is not None]
    values = [float(dimensions[k]) for k in labels]
    if not labels:
        return _base(go.Figure(), "Scores indisponibles", 300)
    fig = go.Figure(
        go.Scatterpolar(
            r=values + [values[0]],
            theta=labels + [labels[0]],
            fill="toself",
            fillcolor="rgba(34,211,166,.18)",
            line=dict(color=C["primary"], width=2.2),
            name="Score",
        )
    )
    fig.update_layout(
        title=title, height=height,
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 100], showline=False, gridcolor="rgba(141,162,192,.18)",
                            tickfont=dict(size=9, color=C["muted"])),
            angularaxis=dict(gridcolor="rgba(141,162,192,.18)",
                             tickfont=dict(size=11, color=C["text"])),
        ),
        showlegend=False,
    )
    return fig


# ═══════════════════════════ Marché ═══════════════════════════


def sector_treemap(df: pd.DataFrame, height: int = 520,
                   title: str = "Carte du marché — capitalisation et performance du jour") -> go.Figure:
    """Treemap secteur → valeur, taille = capitalisation, couleur = performance."""
    if df is None or df.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    sub = df.dropna(subset=["cap"]).copy()
    sub = sub[sub["cap"] > 0]
    if sub.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    sub["change_pct"] = sub["change_pct"].fillna(0.0)
    lim = float(np.nanpercentile(np.abs(sub["change_pct"]), 95)) or 0.05
    lim = max(lim, 0.01)

    fig = go.Figure(
        go.Treemap(
            labels=sub["symbol"] + " · " + sub["name"],
            parents=sub["sector"],
            values=sub["cap"],
            customdata=np.stack([sub["close"], sub["change_pct"] * 100], axis=-1),
            texttemplate="<b>%{label}</b><br>%{customdata[1]:+.2f} %",
            hovertemplate=(
                "<b>%{label}</b><br>Capitalisation : %{value:,.0f} MAD<br>"
                "Cours : %{customdata[0]:,.2f} MAD<br>Variation : %{customdata[1]:+.2f} %<extra></extra>"
            ),
            marker=dict(
                colors=sub["change_pct"],
                colorscale=[[0, C["down"]], [0.5, "#EDE8DD"], [1, C["up"]]],
                cmid=0, cmin=-lim, cmax=lim,
                line=dict(color=C["bg"], width=1.4),
            ),
            textfont=dict(size=11),
            branchvalues="total",
        )
    )
    fig.update_layout(title=title, height=height, margin=dict(l=6, r=6, t=48, b=6))
    return fig


def sector_bars(summary: pd.DataFrame, height: int = 460,
                title: str = "Performance des secteurs") -> go.Figure:
    if summary is None or summary.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    df = summary.sort_values("Perf. 1 an", ascending=True)
    colors = [C["up"] if v is not None and v >= 0 else C["down"] for v in df["Perf. 1 an"]]
    fig = go.Figure(
        go.Bar(
            x=df["Perf. 1 an"], y=df["sector"], orientation="h",
            marker_color=colors, opacity=0.85,
            customdata=np.stack([df["Valeurs"], df["Score moyen"]], axis=-1),
            hovertemplate="<b>%{y}</b><br>Perf. 1 an : %{x:.2%}<br>Valeurs : %{customdata[0]}"
                          "<br>Score moyen : %{customdata[1]:.0f}/100<extra></extra>",
        )
    )
    fig.update_layout(title=title, height=height, xaxis_title="Performance sur 1 an",
                      xaxis_tickformat=".0%", showlegend=False)
    return fig


def movers_bar(movers: pd.DataFrame, height: int = 360) -> go.Figure:
    if movers is None or movers.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    df = movers.sort_values("change_pct")
    colors = [C["up"] if v >= 0 else C["down"] for v in df["change_pct"]]
    fig = go.Figure(
        go.Bar(
            x=df["change_pct"], y=df["symbol"], orientation="h", marker_color=colors, opacity=0.9,
            customdata=df[["name", "close"]].values,
            hovertemplate="<b>%{y}</b> — %{customdata[0]}<br>%{x:.2%}<br>Cours : %{customdata[1]:,.2f} MAD<extra></extra>",
        )
    )
    fig.update_layout(title="Mouvements de la séance", height=height, xaxis_tickformat=".0%",
                      showlegend=False, margin=dict(l=10, r=20, t=48, b=30))
    return fig


def risk_return_scatter(df: pd.DataFrame, height: int = 460) -> go.Figure:
    """Nuage volatilité × performance sur 1 an, taille = capitalisation."""
    if df is None or df.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    sub = df.dropna(subset=["volatility", "return_12m"]).copy()
    if sub.empty:
        return _base(go.Figure(), "Données insuffisantes", 300)
    sizes = sub["cap"].fillna(sub["cap"].median() or 1e9)
    sizes = np.sqrt(sizes / max(sizes.max(), 1)) * 42 + 7
    fig = go.Figure(
        go.Scatter(
            x=sub["volatility"], y=sub["return_12m"], mode="markers+text",
            text=sub["symbol"], textposition="top center", textfont=dict(size=9, color=C["muted"]),
            marker=dict(size=sizes, color=sub["return_12m"],
                        colorscale=[[0, C["down"]], [0.5, "#EDE8DD"], [1, C["up"]]],
                        cmid=0, line=dict(color="rgba(11,37,69,.18)", width=1), opacity=0.9),
            customdata=np.stack([sub["name"], sub["sector"], sub["composite_score"].fillna(0)], axis=-1),
            hovertemplate=(
                "<b>%{text}</b> — %{customdata[0]}<br>Secteur : %{customdata[1]}<br>"
                "Volatilité : %{x:.1%}<br>Perf. 1 an : %{y:.1%}<br>"
                "Score : %{customdata[2]:.0f}/100<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title="Risque / rendement — toutes les valeurs de la BVC (taille = capitalisation)",
        xaxis_title="Volatilité annualisée", yaxis_title="Performance sur 1 an",
        xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=height, showlegend=False,
    )
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(141,162,192,.4)")
    return fig


def correlation_heatmap(corr: pd.DataFrame, height: int = 520,
                        title: str = "Matrice de corrélation") -> go.Figure:
    if corr is None or corr.empty:
        return _base(go.Figure(), "Aucune donnée", 300)
    fig = go.Figure(
        go.Heatmap(
            z=corr.values, x=list(corr.columns), y=list(corr.index),
            colorscale=[[0, C["down"]], [0.5, "#F3F0E7"], [1, C["up"]]],
            zmin=-1, zmax=1, colorbar=dict(title="ρ", tickfont=dict(color=C["muted"])),
            hovertemplate="%{y} / %{x}<br>ρ = %{z:.2f}<extra></extra>",
        )
    )
    fig.update_layout(title=title, height=height)
    return fig


# ═══════════════════════════ Portefeuille ═══════════════════════════


def donut(weights: Dict[str, float], title: str = "Allocation", height: int = 400) -> go.Figure:
    items = [(k, v) for k, v in weights.items() if v and v > 0.001]
    if not items:
        return _base(go.Figure(), "Aucune allocation définie", 300)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    fig = go.Figure(
        go.Pie(
            labels=labels, values=values, hole=0.62,
            marker=dict(colors=PALETTE[: len(labels)], line=dict(color=C["bg"], width=2)),
            textinfo="label+percent", textfont=dict(size=11),
            hovertemplate="<b>%{label}</b><br>Poids : %{percent}<extra></extra>",
        )
    )
    fig.update_layout(title=title, height=height, showlegend=False,
                      annotations=[dict(text="Portefeuille", x=0.5, y=0.5, showarrow=False,
                                        font=dict(size=13, color=C["muted"]))])
    return fig


def stacked_allocation(current: Dict[str, float], recommended: Dict[str, float],
                       height: int = 420) -> go.Figure:
    keys = [k for k in set(list(current) + list(recommended)) if (current.get(k, 0) + recommended.get(k, 0)) > 0.001]
    cur = [current.get(k, 0) for k in keys]
    rec = [recommended.get(k, 0) for k in keys]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=["Allocation actuelle"], y=[1], name="", marker_color="rgba(0,0,0,0)",
                         hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Bar(x=["Allocation cible"], y=[1], name="", marker_color="rgba(0,0,0,0)",
                         hoverinfo="skip", showlegend=False))
    fig.data = []
    for i, k in enumerate(keys):
        fig.add_trace(go.Bar(x=["Allocation actuelle"], y=[cur[i]], name=k,
                             marker_color=PALETTE[i % len(PALETTE)],
                             hovertemplate=f"{k}<br>%{{y:.1%}}<extra></extra>"))
    for i, k in enumerate(keys):
        fig.add_trace(go.Bar(x=["Allocation cible"], y=[rec[i]], name=k, showlegend=False,
                             marker_color=PALETTE[i % len(PALETTE)],
                             hovertemplate=f"{k}<br>%{{y:.1%}}<extra></extra>"))
    fig.update_layout(barmode="stack", title="Actuelle vs cible", height=height,
                      yaxis_tickformat=".0%", yaxis_range=[0, 1], legend_title="Classe d'actifs")
    return fig


def efficient_frontier_chart(
    portfolios: pd.DataFrame,
    frontier: Optional[pd.DataFrame] = None,
    best: Optional[Dict[str, Any]] = None,
    current: Optional[Dict[str, float]] = None,
    height: int = 500,
) -> go.Figure:
    fig = go.Figure()
    if portfolios is not None and not portfolios.empty:
        sample = portfolios.sample(min(len(portfolios), 4000), random_state=1)
        fig.add_trace(
            go.Scatter(
                x=sample["vol"], y=sample["return"], mode="markers", name="Portefeuilles simulés",
                marker=dict(size=4, color=sample["sharpe"],
                            colorscale=[[0, "#EDE8DD"], [0.5, C["accent"]], [1, C["primary"]]],
                            opacity=0.55, colorbar=dict(title="Sharpe", tickfont=dict(color=C["muted"]))),
                hovertemplate="Volatilité %{x:.2%}<br>Rendement %{y:.2%}<extra></extra>",
            )
        )
    if frontier is not None and not frontier.empty:
        fig.add_trace(
            go.Scatter(x=frontier["vol"], y=frontier["return"], mode="lines", name="Frontière efficiente",
                       line=dict(color="white", width=2, dash="dot"))
        )
    if best:
        fig.add_trace(
            go.Scatter(x=[best.get("volatility")], y=[best.get("expected_return")],
                       mode="markers+text", name="Optimum (Sharpe max)",
                       text=["★"], textposition="middle center",
                       textfont=dict(size=18, color="white"),
                       marker=dict(size=20, color=C["primary"], symbol="star",
                                   line=dict(color="white", width=1.4)),
                       hovertemplate="Optimum<br>Volatilité %{x:.2%}<br>Rendement %{y:.2%}<extra></extra>")
        )
    if current:
        fig.add_trace(
            go.Scatter(x=[current.get("volatility")], y=[current.get("expected_return")],
                       mode="markers+text", name="Votre portefeuille",
                       text=["Vous"], textposition="top center",
                       textfont=dict(size=11, color=C["warning"]),
                       marker=dict(size=15, color=C["warning"], symbol="diamond",
                                   line=dict(color="white", width=1.2)))
        )
    fig.update_layout(
        title="Frontière efficiente — univers des allocations possibles",
        xaxis_title="Volatilité attendue", yaxis_title="Rendement attendu",
        xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=height,
    )
    return fig


def fan_chart(
    months: Sequence[int],
    percentiles: Dict[str, Sequence[float]],
    invested: Optional[Sequence[float]] = None,
    target: Optional[float] = None,
    height: int = 480,
    title: str = "Projection Monte-Carlo du patrimoine",
) -> go.Figure:
    fig = go.Figure()
    order = [("p10", "rgba(141,162,192,.06)"), ("p25", "rgba(91,141,239,.10)"),
             ("p50", "rgba(0,0,0,0)"), ("p75", "rgba(34,211,166,.10)"), ("p90", "rgba(141,162,192,.06)")]
    if "p10" in percentiles and "p90" in percentiles:
        fig.add_trace(go.Scatter(x=list(months), y=list(percentiles["p90"]), name="90ᵉ percentile",
                                 line=dict(color="rgba(141,162,192,.5)", width=1), mode="lines"))
        fig.add_trace(go.Scatter(x=list(months), y=list(percentiles["p10"]), name="10ᵉ percentile",
                                 line=dict(color="rgba(141,162,192,.5)", width=1),
                                 fill="tonexty", fillcolor="rgba(141,162,192,.10)"))
    if "p75" in percentiles and "p25" in percentiles:
        fig.add_trace(go.Scatter(x=list(months), y=list(percentiles["p75"]), name="75ᵉ percentile",
                                 line=dict(color="rgba(91,141,239,.7)", width=1.2)))
        fig.add_trace(go.Scatter(x=list(months), y=list(percentiles["p25"]), name="25ᵉ percentile",
                                 line=dict(color="rgba(91,141,239,.7)", width=1.2),
                                 fill="tonexty", fillcolor="rgba(91,141,239,.14)"))
    if "p50" in percentiles:
        fig.add_trace(go.Scatter(x=list(months), y=list(percentiles["p50"]), name="Médiane",
                                 line=dict(color=C["primary"], width=3)))
    if invested is not None:
        fig.add_trace(go.Scatter(x=list(months), y=list(invested), name="Capital versé",
                                 line=dict(color=C["warning"], width=2, dash="dash")))
    if target:
        fig.add_hline(y=target, line_dash="dot", line_color=C["accent2"],
                      annotation_text="Objectif", annotation_font_color=C["accent2"])
    fig.update_layout(title=title, height=height, xaxis_title="Mois",
                      yaxis_title="Valeur du portefeuille (MAD)")
    return fig


def waterfall_cashflows(labels: Sequence[str], values: Sequence[float], height: int = 400,
                        title: str = "Flux de trésorerie") -> go.Figure:
    fig = go.Figure(
        go.Waterfall(
            x=list(labels), y=list(values), measure=["absolute"] + ["relative"] * (len(values) - 1),
            increasing=dict(marker_color=C["up"]), decreasing=dict(marker_color=C["down"]),
            connector=dict(line=dict(color="rgba(141,162,192,.4)")),
            textposition="outside",
        )
    )
    fig.update_layout(title=title, height=height)
    return fig


def heatmap_valuations(df: pd.DataFrame, height: int = 460,
                       title: str = "Carte valorisation / qualité") -> go.Figure:
    """Positionne les valeurs selon P/E et ROE (taille = capitalisation)."""
    sub = df.dropna(subset=["r_per", "r_roe"]).copy() if df is not None else pd.DataFrame()
    if sub.empty:
        return _base(go.Figure(), "Renseignez les données fondamentales pour afficher cette carte", 320)
    sub = sub[(sub["r_per"] > 0) & (sub["r_per"] < 60)]
    if sub.empty:
        return _base(go.Figure(), "Données insuffisantes", 320)
    sizes = np.sqrt(sub["cap"].fillna(1e9) / max(sub["cap"].max(), 1)) * 40 + 8
    fig = go.Figure(
        go.Scatter(
            x=sub["r_per"], y=sub["r_roe"], mode="markers+text", text=sub["symbol"],
            textposition="top center", textfont=dict(size=9, color=C["muted"]),
            marker=dict(size=sizes, color=sub["composite_score"].fillna(50),
                        colorscale=[[0, C["danger"]], [0.5, C["warning"]], [1, C["primary"]]],
                        cmin=20, cmax=80, line=dict(color="rgba(11,37,69,.18)", width=1), opacity=0.9),
            customdata=np.stack([sub["name"], sub["sector"]], axis=-1),
            hovertemplate=("<b>%{text}</b> — %{customdata[0]}<br>%{customdata[1]}<br>"
                           "P/E : %{x:.1f}x<br>ROE : %{y:.1%}<extra></extra>"),
        )
    )
    fig.update_layout(title=title, xaxis_title="P/E (cours / bénéfice)", yaxis_title="ROE",
                      yaxis_tickformat=".0%", height=height, showlegend=False)
    fig.add_vrect(x0=0, x1=15, fillcolor=C["primary"], opacity=0.05,
                  annotation_text="Zone bon marché", annotation_font_size=10)
    fig.add_hline(y=0.12, line_dash="dot", line_color="rgba(141,162,192,.5)",
                  annotation_text="ROE 12 %", annotation_font_size=10)
    return fig


def ratio_evolution(dates: Sequence[Any], series: Dict[str, Sequence[float]],
                    height: int = 400, title: str = "Évolution des ratios") -> go.Figure:
    fig = go.Figure()
    for i, (label, values) in enumerate(series.items()):
        fig.add_trace(go.Scatter(x=list(dates), y=list(values), name=label, mode="lines+markers",
                                 line=dict(color=PALETTE[i % len(PALETTE)], width=2.2)))
    fig.update_layout(title=title, height=height, hovermode="x unified")
    return fig
