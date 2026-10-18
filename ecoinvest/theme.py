"""Thème visuel Streamlit + template Plotly « terminal financier »."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from .config import COLORS, PALETTE

FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)


def register_plotly_template() -> str:
    """Enregistre et active un template Plotly sombre cohérent avec l'UI."""
    name = "ecoinvest"
    layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, size=12.5, color=COLORS["text"]),
        title=dict(font=dict(size=15, color=COLORS["text"]), x=0.01, xanchor="left"),
        colorway=PALETTE,
        margin=dict(l=48, r=24, t=52, b=42),
        xaxis=dict(
            gridcolor="rgba(141,162,192,0.13)",
            zerolinecolor="rgba(141,162,192,0.22)",
            linecolor=COLORS["border"],
            tickfont=dict(color=COLORS["muted"], size=11),
            title=dict(font=dict(color=COLORS["muted"], size=12)),
        ),
        yaxis=dict(
            gridcolor="rgba(141,162,192,0.13)",
            zerolinecolor="rgba(141,162,192,0.22)",
            linecolor=COLORS["border"],
            tickfont=dict(color=COLORS["muted"], size=11),
            title=dict(font=dict(color=COLORS["muted"], size=12)),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=COLORS["muted"], size=11),
        ),
        hoverlabel=dict(
            bgcolor=COLORS["surface2"],
            bordercolor=COLORS["border"],
            font=dict(family=FONT_STACK, size=12, color=COLORS["text"]),
        ),
        hovermode="x unified",
        separators=", ",
    )
    pio.templates[name] = go.layout.Template(layout=layout)
    pio.templates.default = name
    return name


def inject_css() -> None:
    """Injecte la feuille de style globale de l'application."""
    c = COLORS
    st.markdown(
        f"""
        <style>
        /* ── Base ───────────────────────────────────────────── */
        .stApp {{
            background:
                radial-gradient(1100px 620px at 12% -12%, rgba(34,211,166,0.10), transparent 60%),
                radial-gradient(900px 560px at 100% 0%, rgba(91,141,239,0.10), transparent 55%),
                {c['bg']};
            color: {c['text']};
            font-family: {FONT_STACK};
        }}
        header[data-testid="stHeader"] {{ background: transparent; }}
        #MainMenu, footer {{ visibility: hidden; }}

        /* ── Typographie ────────────────────────────────────── */
        h1, h2, h3, h4 {{ color: {c['text']} !important; letter-spacing: -0.015em; }}
        h1 {{ font-weight: 800; }}
        h2 {{ font-weight: 750; margin-top: 1.1rem; }}
        h3 {{ font-weight: 700; }}
        p, li, span, label {{ color: {c['text']}; }}
        .ei-muted {{ color: {c['muted']}; }}

        /* ── Sidebar ────────────────────────────────────────── */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #0A1220 0%, #0B1526 100%);
            border-right: 1px solid {c['border']};
        }}
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {{ color: {c['text']} !important; }}
        section[data-testid="stSidebar"] .stRadio label {{ color: {c['text']}; }}

        /* ── Conteneurs / cartes ────────────────────────────── */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: linear-gradient(180deg, {c['surface']} 0%, rgba(14,23,41,0.75) 100%);
            border: 1px solid {c['border']} !important;
            border-radius: 16px !important;
            padding: 4px 6px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.35);
        }}
        .ei-card {{
            background: linear-gradient(180deg, {c['surface']} 0%, rgba(14,23,41,0.6) 100%);
            border: 1px solid {c['border']};
            border-radius: 16px;
            padding: 16px 18px;
            box-shadow: 0 10px 26px rgba(0,0,0,0.30);
            height: 100%;
        }}
        .ei-card.accent {{ border-top: 3px solid {c['primary']}; }}
        .ei-card.blue   {{ border-top: 3px solid {c['accent']}; }}
        .ei-card.info   {{ border-top: 3px solid {c['accent']}; }}
        .ei-card.up     {{ border-top: 3px solid {c['up']}; }}
        .ei-card.down   {{ border-top: 3px solid {c['down']}; }}
        .ei-card.warn   {{ border-top: 3px solid {c['warning']}; }}
        .ei-card.danger {{ border-top: 3px solid {c['danger']}; }}

        .ei-kpi-label {{
            font-size: .72rem; font-weight: 700; letter-spacing: .09em;
            text-transform: uppercase; color: {c['muted']};
        }}
        .ei-kpi-value {{ font-size: 1.62rem; font-weight: 800; margin: .18rem 0 .1rem; line-height: 1.15; }}
        .ei-kpi-sub {{ font-size: .78rem; color: {c['muted']}; }}

        .ei-hero {{
            background: linear-gradient(120deg, rgba(34,211,166,.16), rgba(91,141,239,.14) 55%, rgba(167,139,250,.12));
            border: 1px solid {c['border']};
            border-radius: 20px; padding: 22px 26px; margin-bottom: 6px;
        }}
        .ei-hero h1 {{ margin: 0; font-size: 1.85rem; }}
        .ei-hero p {{ margin: .35rem 0 0; color: {c['muted']}; }}

        /* ── Badges / puces ─────────────────────────────────── */
        .ei-badge {{
            display: inline-block; padding: 2px 9px; border-radius: 999px;
            font-size: .72rem; font-weight: 700; letter-spacing: .03em;
            border: 1px solid transparent; white-space: nowrap;
        }}
        .ei-up    {{ color: {c['up']};    background: rgba(34,211,166,.13); border-color: rgba(34,211,166,.35); }}
        .ei-down  {{ color: {c['down']};  background: rgba(244,91,105,.13); border-color: rgba(244,91,105,.35); }}
        .ei-flat  {{ color: {c['flat']};  background: rgba(141,162,192,.13); border-color: rgba(141,162,192,.3); }}
        .ei-info  {{ color: {c['accent']}; background: rgba(91,141,239,.14); border-color: rgba(91,141,239,.35); }}
        .ei-blue  {{ color: {c['accent']}; background: rgba(91,141,239,.14); border-color: rgba(91,141,239,.35); }}
        .ei-warn  {{ color: {c['warning']}; background: rgba(245,181,71,.14); border-color: rgba(245,181,71,.35); }}
        .ei-good  {{ color: {c['primary']}; background: rgba(34,211,166,.13); border-color: rgba(34,211,166,.35); }}
        .ei-accent {{ color: {c['primary']}; background: rgba(34,211,166,.13); border-color: rgba(34,211,166,.35); }}

        .ei-verdict {{
            border-radius: 18px; padding: 18px 22px; border: 1px solid {c['border']};
            background: linear-gradient(120deg, rgba(34,211,166,.12), rgba(14,23,41,.7));
        }}
        .ei-verdict h3 {{ margin: 0 0 .3rem; }}
        .ei-note {{
            border-left: 3px solid {c['accent']}; background: rgba(91,141,239,.08);
            padding: 10px 14px; border-radius: 0 10px 10px 0; font-size: .88rem;
        }}
        .ei-note.warn {{ border-left-color: {c['warning']}; background: rgba(245,181,71,.08); }}
        .ei-note.danger {{ border-left-color: {c['danger']}; background: rgba(244,91,105,.08); }}
        .ei-note.down {{ border-left-color: {c['danger']}; background: rgba(244,91,105,.08); }}
        .ei-note.good {{ border-left-color: {c['primary']}; background: rgba(34,211,166,.08); }}
        .ei-note.up {{ border-left-color: {c['primary']}; background: rgba(34,211,166,.08); }}
        .ei-note.info {{ border-left-color: {c['accent']}; background: rgba(91,141,239,.08); }}

        /* ── Tableaux ───────────────────────────────────────── */
        div[data-testid="stDataFrame"] {{ border-radius: 12px; border: 1px solid {c['border']}; }}
        .ei-mono {{ font-variant-numeric: tabular-nums; font-family: "SF Mono", ui-monospace, Menlo, monospace; }}

        /* ── Widgets ────────────────────────────────────────── */
        .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
            background: linear-gradient(135deg, {c['primary']} 0%, {c['primary_dark']} 100%);
            color: #04140F; border: none; border-radius: 11px;
            font-weight: 750; padding: .5rem 1.15rem; transition: transform .12s ease, filter .12s ease;
        }}
        .stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {{
            transform: translateY(-1px); filter: brightness(1.07); color: #04140F;
        }}
        div[data-baseweb="input"] input, div[data-baseweb="select"] > div, textarea {{
            background: {c['surface2']} !important; color: {c['text']} !important;
            border-color: {c['border']} !important; border-radius: 10px !important;
        }}
        div[data-testid="stMetricValue"] {{ color: {c['text']}; font-weight: 800; }}
        div[data-testid="stMetric"] {{
            background: {c['surface']}; border: 1px solid {c['border']};
            border-radius: 14px; padding: 12px 14px;
        }}
        .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
        .stTabs [data-baseweb="tab"] {{
            background: {c['surface']}; border: 1px solid {c['border']};
            border-radius: 10px 10px 0 0; padding: 6px 14px; color: {c['muted']};
        }}
        .stTabs [aria-selected="true"] {{ color: {c['primary']} !important; border-bottom-color: {c['primary']} !important; }}
        div[data-testid="stExpander"] {{
            border: 1px solid {c['border']}; border-radius: 12px; background: rgba(14,23,41,.55);
        }}
        .stProgress > div > div > div > div {{ background: {c['primary']}; }}
        code {{ color: {c['primary']}; background: rgba(34,211,166,.08); }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def setup_page(title: str, icon: str = "📈") -> None:
    """Configuration de page + thème. À appeler une seule fois dans app.py."""
    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    register_plotly_template()
    inject_css()
