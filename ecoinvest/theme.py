"""Thème visuel institutionnel (fond clair) + template Plotly « marketmind »."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from .config import COLORS, PALETTE

FONT_STACK = (
    '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)
FONT_DISPLAY = '"Fraunces", "Iowan Old Style", "Palatino Linotype", Georgia, serif'
FONT_MONO = '"SF Mono", "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace'

# Import des polices avec repli système si le réseau est indisponible.
FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&"
    "family=Inter:wght@400;500;600;700;800&display=swap');"
)


def register_plotly_template() -> str:
    """Enregistre et active un template Plotly clair, sobre et lisible."""
    name = "marketmind"
    grid = "rgba(11,37,69,0.08)"
    zero = "rgba(11,37,69,0.18)"
    layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, size=12.5, color=COLORS["text"]),
        title=dict(font=dict(size=15, color=COLORS["text"]), x=0.01, xanchor="left"),
        colorway=PALETTE,
        margin=dict(l=48, r=24, t=52, b=42),
        xaxis=dict(
            gridcolor=grid,
            zerolinecolor=zero,
            linecolor=COLORS["border"],
            tickfont=dict(color=COLORS["muted"], size=11),
            title=dict(font=dict(color=COLORS["muted"], size=12)),
        ),
        yaxis=dict(
            gridcolor=grid,
            zerolinecolor=zero,
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
            bgcolor=COLORS["surface"],
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
    """Feuille de style globale : identité Market Mind, fond clair."""
    c = COLORS
    st.markdown(
        f"""
        <style>
        {FONT_IMPORT}

        /* ── Base ───────────────────────────────────────────── */
        .stApp {{
            background:
                radial-gradient(1100px 520px at 8% -8%, rgba(15,118,110,0.08), transparent 62%),
                radial-gradient(900px 520px at 100% 0%, rgba(18,59,109,0.06), transparent 58%),
                {c['bg']};
            color: {c['text']};
            font-family: {FONT_STACK};
        }}
        header[data-testid="stHeader"] {{ background: transparent; }}
        #MainMenu, footer, [data-testid="stAppDeployButton"], [data-testid="stToolbar"],
        [data-testid="stDecoration"] {{ display: none !important; }}

        /* ── Typographie ────────────────────────────────────── */
        h1, h2, h3, h4 {{ color: {c['text']} !important; }}
        h1 {{ font-family: {FONT_DISPLAY}; font-weight: 600; letter-spacing: -0.025em; }}
        h2 {{ font-family: {FONT_DISPLAY}; font-weight: 600; letter-spacing: -0.02em; margin-top: 1.1rem; }}
        h3 {{ font-family: {FONT_STACK}; font-weight: 700; letter-spacing: -0.01em; }}
        p, li, span, label {{ color: {c['text']}; }}
        .ei-muted {{ color: {c['muted']}; }}
        [data-testid="stCaptionContainer"] {{ color: {c['muted']}; }}
        .mm-serif {{ font-family: {FONT_DISPLAY}; }}
        .mm-mono, .ei-mono {{
            font-family: {FONT_MONO}; font-variant-numeric: tabular-nums;
            font-size: .92em; letter-spacing: -0.01em;
        }}

        /* ── Barre latérale ─────────────────────────────────── */
        section[data-testid="stSidebar"] {{
            background: {c['surface']};
            border-right: 1px solid {c['border']};
        }}
        section[data-testid="stSidebar"] > div {{ background: {c['surface']}; }}
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {{ color: {c['text']} !important; }}
        section[data-testid="stSidebar"] .stRadio label {{ color: {c['text']}; }}
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{
            border-radius: 9px; color: {c['text']};
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {{
            background: {c['surface2']};
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background: rgba(15,118,110,0.10);
            color: {c['primary']} !important; font-weight: 700;
        }}

        /* ── Conteneurs / cartes ────────────────────────────── */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: {c['surface']};
            border: 1px solid {c['border']} !important;
            border-radius: 14px !important;
            box-shadow: 0 1px 2px rgba(11,37,69,0.04), 0 10px 28px rgba(11,37,69,0.05);
        }}
        .ei-card, .mm-card {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 14px;
            padding: 18px 20px;
            box-shadow: 0 1px 2px rgba(11,37,69,0.04), 0 10px 26px rgba(11,37,69,0.05);
            height: 100%;
        }}
        .ei-card.accent, .mm-card.accent {{ border-top: 3px solid {c['primary']}; }}
        .ei-card.blue   {{ border-top: 3px solid {c['accent']}; }}
        .ei-card.info   {{ border-top: 3px solid {c['accent']}; }}
        .ei-card.up     {{ border-top: 3px solid {c['up']}; }}
        .ei-card.down   {{ border-top: 3px solid {c['down']}; }}
        .ei-card.warn   {{ border-top: 3px solid {c['warning']}; }}
        .ei-card.danger {{ border-top: 3px solid {c['danger']}; }}

        .ei-kpi-label {{
            font-size: .69rem; font-weight: 700; letter-spacing: .11em;
            text-transform: uppercase; color: {c['muted']};
        }}
        .ei-kpi-value {{
            font-family: {FONT_DISPLAY}; font-size: 1.7rem; font-weight: 600;
            margin: .2rem 0 .12rem; line-height: 1.12; color: {c['text']};
        }}
        .ei-kpi-sub {{ font-size: .78rem; color: {c['muted']}; }}

        /* ── En-tête de page interne ────────────────────────── */
        .ei-hero {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: 16px; padding: 24px 28px; margin-bottom: 10px;
            box-shadow: 0 1px 2px rgba(11,37,69,0.04), 0 12px 30px rgba(11,37,69,0.05);
            position: relative; overflow: hidden;
        }}
        .ei-hero::before {{
            content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
            background: linear-gradient(180deg, {c['primary']}, {c['accent']});
        }}
        .ei-hero h1 {{ margin: 0; font-size: 2.05rem; color: {c['text']}; }}
        .ei-hero p {{ margin: .4rem 0 0; color: {c['muted']}; max-width: 70ch; }}

        /* ── Accueil Market Mind ─────────────────────────────────── */
        .mm-brandbar {{
            display: flex; align-items: baseline; gap: 14px;
            padding: 2px 2px 14px; border-bottom: 1px solid {c['border']};
            margin-bottom: 22px;
        }}
        .mm-wordmark {{
            font-family: {FONT_DISPLAY}; font-size: 1.28rem; font-weight: 700;
            letter-spacing: .12em; color: {c['text']};
        }}
        .mm-wordmark span {{ color: {c['primary']}; }}
        .mm-brandsub {{
            font-size: .68rem; letter-spacing: .16em; text-transform: uppercase;
            color: {c['muted']}; font-weight: 600;
        }}
        .mm-hero {{
            display: grid; grid-template-columns: 1.35fr .9fr; gap: 26px;
            padding: 34px 0 26px;
        }}
        .mm-eyebrow {{
            font-size: .7rem; font-weight: 700; letter-spacing: .18em;
            text-transform: uppercase; color: {c['primary']}; margin-bottom: 12px;
        }}
        .mm-title {{
            font-family: {FONT_DISPLAY}; font-size: 3.05rem; line-height: 1.06;
            font-weight: 500; letter-spacing: -0.03em; color: {c['text']}; margin: 0 0 14px;
        }}
        .mm-title em {{ font-style: italic; color: {c['primary']}; }}
        .mm-lede {{
            font-size: 1.02rem; line-height: 1.65; color: {c['muted']};
            max-width: 60ch; margin: 0 0 18px;
        }}
        .mm-pulse {{
            background: {c['surface']}; border: 1px solid {c['border']};
            border-radius: 16px; padding: 18px 20px; height: 100%;
            box-shadow: 0 1px 2px rgba(11,37,69,0.04), 0 12px 30px rgba(11,37,69,0.06);
        }}
        .mm-pulse-head {{
            display: flex; justify-content: space-between; align-items: center;
            font-size: .68rem; font-weight: 700; letter-spacing: .14em;
            text-transform: uppercase; color: {c['muted']}; margin-bottom: 12px;
        }}
        .mm-index-row {{
            display: flex; align-items: baseline; justify-content: space-between;
            padding: 9px 0; border-bottom: 1px dashed {c['border']};
        }}
        .mm-index-row:last-child {{ border-bottom: none; }}
        .mm-index-name {{ font-weight: 600; font-size: .87rem; color: {c['text']}; }}
        .mm-index-val {{ font-family: {FONT_MONO}; font-size: .92rem; color: {c['text']}; }}
        .mm-delta {{
            font-family: {FONT_MONO}; font-size: .78rem; font-weight: 700;
            margin-left: 7px; display: inline-block;
        }}
        .mm-delta.up {{ color: {c['up']}; }}
        .mm-delta.down {{ color: {c['down']}; }}
        .mm-delta.flat {{ color: {c['muted']}; }}

        .mm-section-label {{
            font-size: .7rem; font-weight: 700; letter-spacing: .16em;
            text-transform: uppercase; color: {c['muted']};
            margin: 30px 0 14px; display: flex; align-items: center; gap: 10px;
        }}
        .mm-section-label::after {{
            content: ""; height: 1px; background: {c['border']}; flex: 1;
        }}

        .mm-category {{
            background: {c['surface']}; border: 1px solid {c['border']};
            border-radius: 14px; padding: 18px 18px 12px; height: 100%;
            transition: border-color .15s ease, transform .15s ease, box-shadow .15s ease;
        }}
        .mm-category:hover {{
            border-color: {c['primary']}; transform: translateY(-2px);
            box-shadow: 0 10px 26px rgba(11,37,69,0.09);
        }}
        .mm-cat-icon {{
            width: 38px; height: 38px; border-radius: 10px; display: flex;
            align-items: center; justify-content: center; font-size: 1.05rem;
            background: rgba(15,118,110,0.10); color: {c['primary']}; margin-bottom: 12px;
        }}
        .mm-cat-title {{ font-weight: 700; font-size: 1rem; margin-bottom: 4px; color: {c['text']}; }}
        .mm-cat-desc {{ font-size: .82rem; line-height: 1.5; color: {c['muted']}; min-height: 3.1em; }}

        .mm-steps {{
            display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 18px;
        }}
        .mm-step {{
            display: flex; align-items: center; gap: 8px; padding: 9px 14px;
            border: 1px solid {c['border']}; border-radius: 999px;
            background: {c['surface']}; color: {c['muted']}; font-size: .86rem;
        }}
        .mm-step-active {{
            border-color: {c['primary']}; color: {c['text']};
            box-shadow: 0 6px 18px rgba(15,118,110,0.12);
        }}
        .mm-step-num {{
            width: 22px; height: 22px; border-radius: 50%; display: inline-flex;
            align-items: center; justify-content: center; font-size: .74rem; font-weight: 700;
            background: rgba(15,118,110,0.12); color: {c['primary']};
        }}
        .mm-step-ico {{ font-size: .95rem; }}

        .mm-ticker {{
            display: flex; gap: 0; overflow: hidden; border: 1px solid {c['border']};
            border-radius: 12px; background: {c['surface']};
        }}
        .mm-ticker-item {{
            flex: 1; padding: 10px 14px; border-right: 1px solid {c['border']};
            min-width: 0;
        }}
        .mm-ticker-item:last-child {{ border-right: none; }}
        .mm-ticker-name {{
            font-size: .64rem; letter-spacing: .1em; text-transform: uppercase;
            color: {c['muted']}; font-weight: 700;
        }}
        .mm-ticker-val {{ font-family: {FONT_MONO}; font-size: .95rem; font-weight: 600; }}

        .mm-news-item {{
            padding: 10px 0; border-bottom: 1px solid {c['border']};
        }}
        .mm-news-item:last-child {{ border-bottom: none; }}
        .mm-news-title {{ font-size: .88rem; line-height: 1.45; font-weight: 600; color: {c['text']}; }}
        .mm-news-meta {{ font-size: .7rem; color: {c['muted']}; margin-top: 3px; }}
        .mm-news-title a {{ color: {c['text']}; text-decoration: none; }}
        .mm-news-title a:hover {{ color: {c['primary']}; }}

        .mm-ai-card {{
            background: linear-gradient(135deg, rgba(15,118,110,0.08), rgba(18,59,109,0.06));
            border: 1px solid rgba(15,118,110,0.28); border-radius: 14px; padding: 18px 20px;
        }}

        /* ── Badges / puces ─────────────────────────────────── */
        .ei-badge {{
            display: inline-block; padding: 2px 9px; border-radius: 999px;
            font-size: .71rem; font-weight: 700; letter-spacing: .03em;
            border: 1px solid transparent; white-space: nowrap;
        }}
        .ei-up    {{ color: {c['up']};    background: rgba(4,120,87,.10);  border-color: rgba(4,120,87,.28); }}
        .ei-down  {{ color: {c['down']};  background: rgba(180,35,24,.09); border-color: rgba(180,35,24,.25); }}
        .ei-flat  {{ color: {c['flat']};  background: rgba(100,116,139,.10); border-color: rgba(100,116,139,.24); }}
        .ei-info  {{ color: {c['accent']}; background: rgba(18,59,109,.08); border-color: rgba(18,59,109,.22); }}
        .ei-blue  {{ color: {c['accent']}; background: rgba(18,59,109,.08); border-color: rgba(18,59,109,.22); }}
        .ei-warn  {{ color: {c['warning']}; background: rgba(180,83,9,.10); border-color: rgba(180,83,9,.26); }}
        .ei-good  {{ color: {c['primary']}; background: rgba(15,118,110,.10); border-color: rgba(15,118,110,.26); }}
        .ei-accent {{ color: {c['primary']}; background: rgba(15,118,110,.10); border-color: rgba(15,118,110,.26); }}

        .ei-verdict {{
            border-radius: 14px; padding: 18px 22px; border: 1px solid {c['border']};
            background: linear-gradient(120deg, rgba(15,118,110,.07), {c['surface']} 62%);
        }}
        .ei-verdict h3 {{ margin: 0 0 .3rem; }}
        .ei-note {{
            border-left: 3px solid {c['accent']}; background: rgba(18,59,109,.05);
            padding: 10px 14px; border-radius: 0 10px 10px 0; font-size: .88rem;
            color: {c['text']};
        }}
        .ei-note.warn {{ border-left-color: {c['warning']}; background: rgba(180,83,9,.06); }}
        .ei-note.danger {{ border-left-color: {c['danger']}; background: rgba(180,35,24,.06); }}
        .ei-note.down {{ border-left-color: {c['danger']}; background: rgba(180,35,24,.06); }}
        .ei-note.good {{ border-left-color: {c['primary']}; background: rgba(15,118,110,.06); }}
        .ei-note.up {{ border-left-color: {c['primary']}; background: rgba(15,118,110,.06); }}
        .ei-note.info {{ border-left-color: {c['accent']}; background: rgba(18,59,109,.05); }}

        /* ── Tableaux ───────────────────────────────────────── */
        div[data-testid="stDataFrame"] {{
            border-radius: 12px; border: 1px solid {c['border']};
            background: {c['surface']};
        }}
        div[data-testid="stDataFrame"] [role="columnheader"] {{
            background: {c['surface2']} !important; color: {c['muted']} !important;
            font-weight: 700 !important;
        }}

        /* ── Widgets ────────────────────────────────────────── */
        .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
            background: {c['accent']}; color: #FFFFFF; border: 1px solid {c['accent']};
            border-radius: 9px; font-weight: 650; padding: .48rem 1.05rem;
            transition: background .15s ease, border-color .15s ease, transform .12s ease;
        }}
        .stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {{
            background: {c['primary']}; border-color: {c['primary']}; color: #FFFFFF;
            transform: translateY(-1px);
        }}
        .stButton > button[kind="secondary"] {{
            background: {c['surface']}; color: {c['accent']}; border-color: {c['border']};
        }}
        .stButton > button[kind="secondary"]:hover {{
            border-color: {c['primary']}; color: {c['primary']}; background: {c['surface']};
        }}
        div[data-baseweb="input"] input, div[data-baseweb="select"] > div, textarea {{
            background: {c['surface']} !important; color: {c['text']} !important;
            border-color: {c['border']} !important; border-radius: 9px !important;
        }}
        div[data-baseweb="input"]:focus-within, div[data-baseweb="select"] > div:focus-within {{
            border-color: {c['primary']} !important;
            box-shadow: 0 0 0 3px rgba(15,118,110,.12);
        }}
        div[data-testid="stMetricValue"] {{ color: {c['text']}; font-weight: 700; }}
        div[data-testid="stMetric"] {{
            background: {c['surface']}; border: 1px solid {c['border']};
            border-radius: 12px; padding: 12px 14px;
        }}
        .stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {c['border']}; }}
        .stTabs [data-baseweb="tab"] {{
            background: transparent; border: none; border-bottom: 2px solid transparent;
            padding: 8px 14px; color: {c['muted']}; font-weight: 600;
        }}
        .stTabs [aria-selected="true"] {{
            color: {c['primary']} !important; border-bottom-color: {c['primary']} !important;
        }}
        div[data-testid="stExpander"] {{
            border: 1px solid {c['border']}; border-radius: 12px; background: {c['surface']};
        }}
        .stProgress > div > div > div > div {{ background: {c['primary']}; }}
        code {{ color: {c['primary']}; background: rgba(15,118,110,.08); }}
        hr {{ border-color: {c['border']}; }}
        [data-testid="stForm"] {{
            background: {c['surface']}; border: 1px solid {c['border']};
            border-radius: 14px; padding: 18px 20px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def setup_page(title: str, icon: str = "🧭") -> None:
    """Configuration de page + thème. À appeler une seule fois dans app.py."""
    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    register_plotly_template()
    inject_css()
