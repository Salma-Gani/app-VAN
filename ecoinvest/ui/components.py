"""Composants d'interface réutilisables (HTML + Streamlit)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..config import COLORS
from ..utils.formatting import color_of, fmt_money, fmt_num, fmt_pct, delta_badge

# ═══════════════════════════ Blocs de texte ═══════════════════════════


def _inline_md(text: str) -> str:
    """Convertit le Markdown inline minimal en HTML (les blocs HTML ne parsent pas le Markdown)."""
    if not text:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", str(text))
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    return text.replace("`", "")


def hero(title: str, subtitle: str = "", badge: str = "") -> None:
    extra = f'<div style="margin-top:.5rem">{badge}</div>' if badge else ""
    st.markdown(
        f"""
        <div class="ei-hero">
          <h1>{title}</h1>
          <p>{_inline_md(subtitle)}</p>
          {extra}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title: str, subtitle: str = "") -> None:
    st.markdown(f"### {title}")
    if subtitle:
        st.markdown(
            f'<p class="ei-muted" style="margin:-.35rem 0 .75rem;font-size:.88rem">{_inline_md(subtitle)}</p>',
            unsafe_allow_html=True,
        )


def note(text: str, tone: str = "info", icon: str = "ℹ️") -> None:
    st.markdown(
        f'<div class="ei-note {tone if tone != "info" else ""}"><b>{icon}</b> {_inline_md(text)}</div>',
        unsafe_allow_html=True,
    )


def verdict(title: str, body: str, color: Optional[str] = None) -> None:
    c = color or COLORS["primary"]
    st.markdown(
        f"""
        <div class="ei-verdict" style="border-color:{c};">
          <h3 style="color:{c} !important">{title}</h3>
          <div style="font-size:.92rem;line-height:1.55">{_inline_md(body)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, tone: str = "info") -> str:
    return f'<span class="ei-badge ei-{tone}">{text}</span>'


def badge_for_delta(value: Optional[float], decimals: int = 2) -> str:
    return delta_badge(value, decimals)


def source_note(sources: Sequence[str], as_of: str = "", detail: str = "") -> None:
    """Ligne de provenance : sources, date de référence et statut de la donnée."""
    parts = [s for s in sources if s]
    text = " · ".join(parts)
    if as_of:
        text = f"{text} — {as_of}" if text else as_of
    if detail:
        text = f"{text}. {detail}" if text else detail
    st.caption(f"Sources : {text}" if text else detail)


def data_badge(label: str, tone: str = "info") -> str:
    """Petit badge de statut de donnée (clôture, différé, saisi, estimé)."""
    return badge(label, tone)


# ═══════════════════════════ Cartes KPI ═══════════════════════════


def kpi_html(
    label: str,
    value: str,
    sub: str = "",
    tone: str = "",
    color: Optional[str] = None,
) -> str:
    style = f' style="color:{color}"' if color else ""
    return (
        f'<div class="ei-card {tone}">'
        f'<div class="ei-kpi-label">{label}</div>'
        f'<div class="ei-kpi-value"{style}>{value}</div>'
        f'<div class="ei-kpi-sub">{sub}</div>'
        f"</div>"
    )


def kpi_card(label: str, value: str, sub: str = "", tone: str = "",
             color: Optional[str] = None) -> None:
    st.markdown(kpi_html(label, value, sub, tone, color), unsafe_allow_html=True)


def kpi_row(items: Sequence[Dict[str, Any]], per_row: int = 4) -> None:
    """Affiche une grille de cartes KPI."""
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        cols = st.columns(len(chunk))
        for col, item in zip(cols, chunk):
            with col:
                kpi_card(**item)


def metric_delta(label: str, value: str, delta: Optional[float] = None,
                 help_text: str = "") -> None:
    st.metric(label, value, None if delta is None else fmt_pct(delta, 2, signed=True),
              delta_color="normal", help=help_text or None)


# ═══════════════════════════ Graphiques ═══════════════════════════


def _supports_width(func: Any) -> bool:
    try:
        import inspect

        return "width" in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


_PLOTLY_HAS_WIDTH = _supports_width(st.plotly_chart)


def plot(fig: go.Figure, key: Optional[str] = None, height: Optional[int] = None) -> None:
    """Affiche une figure Plotly en gérant les différences de version de Streamlit."""
    if height:
        fig.update_layout(height=height)
    if _PLOTLY_HAS_WIDTH:
        st.plotly_chart(fig, width="stretch", key=key)
    else:
        st.plotly_chart(fig, use_container_width=True, key=key)


# ═══════════════════════════ Tableaux ═══════════════════════════


def table(
    df: pd.DataFrame,
    columns: Optional[Dict[str, Any]] = None,
    height: Optional[int] = None,
    hide_index: bool = True,
    key: Optional[str] = None,
) -> None:
    """Affiche un DataFrame avec configuration de colonnes si disponible."""
    if df is None or df.empty:
        st.info("Aucune donnée à afficher.")
        return
    kwargs: Dict[str, Any] = {"hide_index": hide_index}
    if height:
        kwargs["height"] = height
    if columns:
        try:
            kwargs["column_config"] = columns
        except Exception:
            pass
    try:
        st.dataframe(df, width="stretch", key=key, **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, key=key, **kwargs)


_DATA_EDITOR_HAS_WIDTH = _supports_width(st.data_editor)


def data_editor(df: pd.DataFrame, key: Optional[str] = None, **kwargs: Any) -> Any:
    """Éditeur de données compatible avec les différentes versions de Streamlit."""
    if _DATA_EDITOR_HAS_WIDTH:
        return st.data_editor(df, width="stretch", key=key, **kwargs)
    return st.data_editor(df, use_container_width=True, key=key, **kwargs)


def number_column(label: str, fmt: str = "%.2f", help_text: str = "") -> Any:
    try:
        return st.column_config.NumberColumn(label, format=fmt, help=help_text or None)
    except Exception:
        return label


def progress_column(label: str, min_value: float = 0, max_value: float = 100) -> Any:
    try:
        return st.column_config.ProgressColumn(label, min_value=min_value, max_value=max_value,
                                               format="%.0f")
    except Exception:
        return label


# ═══════════════════════════ Divers ═══════════════════════════


def empty_state(message: str, icon: str = "🔍") -> None:
    st.markdown(
        f"""
        <div class="ei-card" style="text-align:center;padding:36px 20px">
          <div style="font-size:2.2rem">{icon}</div>
          <div class="ei-muted" style="margin-top:.5rem">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def data_source_caption(*parts: str) -> None:
    st.caption(" · ".join(p for p in parts if p))


def disclaimer() -> None:
    from ..config import DISCLAIMER

    note(DISCLAIMER, "warn", "⚠️")


def download_row(df: pd.DataFrame, filename: str, label: str = "⬇️ Exporter en CSV",
                 key: Optional[str] = None) -> None:
    if df is None or df.empty:
        return
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, csv, filename, "text/csv", key=key)


def signal_pill(signal: str) -> str:
    tone = "info"
    if "Achat" in signal:
        tone = "up"
    elif "Éviter" in signal or "vendre" in signal.lower():
        tone = "down"
    elif "Attendre" in signal or "Alléger" in signal:
        tone = "warn"
    elif "Conserver" in signal or "Consolider" in signal:
        tone = "info"
    return badge(signal, tone)


def score_ring(score: Optional[float], label: str = "Score composite") -> str:
    """Petit indicateur visuel de score (0–100)."""
    if score is None:
        return badge("n.d.", "flat")
    v = max(0.0, min(100.0, float(score)))
    color = COLORS["primary"] if v >= 65 else COLORS["warning"] if v >= 45 else COLORS["danger"]
    return (
        f'<div style="display:flex;align-items:center;gap:.6rem">'
        f'<div style="position:relative;width:56px;height:56px;border-radius:50%;'
        f'background:conic-gradient({color} {v * 3.6}deg, rgba(141,162,192,.18) 0deg);">'
        f'<div style="position:absolute;inset:6px;border-radius:50%;background:{COLORS["surface"]};'
        f'display:flex;align-items:center;justify-content:center;font-weight:800;font-size:.9rem">'
        f"{v:.0f}</div></div>"
        f'<div><div class="ei-kpi-label">{label}</div>'
        f'<div class="ei-muted" style="font-size:.75rem">sur 100</div></div></div>'
    )


def stat_line(items: Sequence[tuple], per_row: int = 3) -> None:
    """Petite grille de statistiques texte."""
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        cols = st.columns(len(chunk))
        for col, (label, value) in zip(cols, chunk):
            with col:
                st.markdown(
                    f'<div class="ei-card" style="padding:10px 12px">'
                    f'<div class="ei-kpi-label">{label}</div>'
                    f'<div style="font-weight:700;font-size:1.05rem">{value}</div></div>',
                    unsafe_allow_html=True,
                )


def spinner_text(text: str = "Chargement des données de marché…"):
    return st.spinner(text)


def refresh_button(label: str = "🔄 Rafraîchir les données", key: str = "refresh") -> bool:
    return st.button(label, key=key, help="Force le rechargement depuis les sources (BVC, Yahoo, RSS).")
