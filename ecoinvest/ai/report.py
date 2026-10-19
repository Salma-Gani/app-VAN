"""Génération de rapports PDF à partir des analyses de Market Mind.

Le PDF reprend uniquement le texte et les données réellement fournis par
l'application. Il rappelle la source, la date et les limites de l'analyse.
``reportlab`` est une dépendance optionnelle : si elle manque, l'interface
propose le téléchargement Markdown au lieu de masquer l'erreur.
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional

from ..utils.formatting import as_float, fmt_money, fmt_multiple, fmt_num, fmt_pct

try:  # pragma: no cover - dépendance optionnelle testée à l'exécution
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    _HAS_REPORTLAB = True
except ImportError:  # pragma: no cover
    _HAS_REPORTLAB = False


NAVY = "#0B2545"
TEAL = "#0F766E"
MUTED = "#61708A"
BORDER = "#DCD7CB"
CREAM = "#F6F4EF"
WARNING = "#B45309"


def reportlab_available() -> bool:
    return _HAS_REPORTLAB


def _strip_emoji(text: str) -> str:
    """Retire les pictogrammes non rendus par les polices PDF standard."""
    return re.sub(
        "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\u2B00-\u2BFF]",
        "",
        str(text or ""),
    ).strip()


def _fmt(value: Any, kind: str = "num") -> str:
    v = as_float(value)
    if v is None:
        return "—"
    if kind == "pct":
        return fmt_pct(v, 2, signed=True)
    if kind == "money":
        return fmt_money(v, "MAD", compact=True)
    if kind == "mult":
        return fmt_multiple(v, 2)
    return fmt_num(v, 2)


def _inline(text: str) -> str:
    """Échappe le XML puis convertit le Markdown inline minimal."""
    from xml.sax.saxutils import escape

    raw = _strip_emoji(text)
    raw = escape(raw)
    raw = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", raw)
    raw = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", raw)
    raw = raw.replace("`", "")
    return raw


def _styles() -> Dict[str, Any]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "brand", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8.5,
            textColor=colors.HexColor(TEAL), leading=11, spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=21,
            textColor=colors.HexColor(NAVY), leading=25, alignment=TA_LEFT, spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=10,
            textColor=colors.HexColor(MUTED), leading=14, spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15,
            textColor=colors.HexColor(NAVY), leading=19, spaceBefore=12, spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5,
            textColor=colors.HexColor(TEAL), leading=15, spaceBefore=9, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5,
            textColor=colors.HexColor(NAVY), leading=14, spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["BodyText"], fontName="Helvetica", fontSize=9.3,
            textColor=colors.HexColor(NAVY), leading=13.5, leftIndent=12, bulletIndent=2,
            spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontName="Helvetica", fontSize=8,
            textColor=colors.HexColor(MUTED), leading=11,
        ),
        "warning": ParagraphStyle(
            "warning", parent=base["BodyText"], fontName="Helvetica", fontSize=8.8,
            textColor=colors.HexColor(WARNING), leading=12.5, backColor=colors.HexColor("#FFF7ED"),
            borderColor=colors.HexColor("#FED7AA"), borderWidth=0.5, borderPadding=7,
            spaceBefore=8, spaceAfter=8,
        ),
    }


def _markdown_flowables(text: str, st: Dict[str, Any]) -> List[Any]:
    """Convertit un Markdown simple en flowables ReportLab."""
    flow: List[Any] = []
    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flow.append(Spacer(1, 3))
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("### "):
            flow.append(Paragraph(_inline(stripped[4:]), st["h2"]))
        elif stripped.startswith("## "):
            flow.append(Paragraph(_inline(stripped[3:]), st["h1"]))
        elif stripped.startswith("# "):
            flow.append(Paragraph(_inline(stripped[2:]), st["h1"]))
        elif stripped in ("---", "***", "___"):
            flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor(BORDER),
                                   spaceBefore=5, spaceAfter=7))
        elif stripped.startswith(("- ", "* ", "• ")):
            flow.append(Paragraph(_inline(stripped[2:]), st["bullet"], bulletText="•"))
        elif stripped.startswith("> "):
            flow.append(Paragraph("<i>" + _inline(stripped[2:]) + "</i>", st["small"]))
        elif re.match(r"^\*\*.+\*\*$", stripped):
            flow.append(Paragraph(_inline(stripped), st["body"]))
        else:
            flow.append(Paragraph(_inline(stripped), st["body"]))
    return flow


def _kv_table(rows: List[tuple], st: Dict[str, Any], col_widths: Optional[List[float]] = None) -> Table:
    data = [[Paragraph(_inline(str(k)), st["small"]), Paragraph(_inline(str(v)), st["body"])]
            for k, v in rows]
    table = Table(data, colWidths=col_widths or [52 * mm, 108 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor(BORDER)),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _payload_rows(payload: Dict[str, Any]) -> List[tuple]:
    row = payload.get("row") or {}
    tech = payload.get("technical") or {}
    levels = tech.get("levels") or {}
    momentum = tech.get("momentum") or {}
    ratios = payload.get("ratios") or {}
    rsi = momentum.get("rsi")
    ratio_rows = []
    for key, label in (("per", "P/E"), ("pb", "P/B"), ("dividend_yield", "Rendement dividende"),
                       ("roe", "ROE"), ("net_margin", "Marge nette"), ("ev_ebitda", "EV/EBITDA")):
        info = ratios.get(key)
        if isinstance(info, dict) and info.get("value") is not None:
            value = info.get("value")
            if key in ("dividend_yield", "roe", "net_margin"):
                rendered = _fmt(value, "pct")
            elif key == "ev_ebitda":
                rendered = _fmt(value, "mult")
            else:
                rendered = _fmt(value)
            ratio_rows.append((label, rendered))
    rows = [
        ("Cours", f"{_fmt(row.get('close'))} MAD"),
        ("Variation séance", _fmt(row.get("change_pct"), "pct")),
        ("Volume", _fmt(row.get("volume"), "money")),
        ("Capitalisation", _fmt(row.get("cap"), "money")),
        ("Tendance", str(tech.get("trend", {}).get("state") or "—")),
        ("Momentum", str(momentum.get("state") or "—")),
        ("RSI (14)", _fmt(rsi)),
        ("Support 120 j", _fmt(levels.get("support"))),
        ("Résistance 120 j", _fmt(levels.get("resistance"))),
        ("Volatilité annualisée", _fmt(row.get("volatility"), "pct")),
        ("Drawdown maximal", _fmt(row.get("max_drawdown"), "pct")),
        ("Bêta", _fmt(row.get("beta"))),
    ]
    rows.extend(ratio_rows)
    return rows


def _sources(payload: Dict[str, Any]) -> List[str]:
    sources = payload.get("sources") or [
        "Bourse de Casablanca (cours, volumes, historiques)",
        "Référentiel BVC (nombre de titres, dividende)",
        "Yahoo Finance (indices internationaux, VIX, devises)",
        "Flux RSS publics (actualités)",
        "World Bank Open Data (macro Maroc, séries annuelles)",
    ]
    extra = payload.get("fundamentals_source") or payload.get("source")
    if extra:
        sources = list(sources) + [str(extra)]
    return sources


def build_analysis_pdf(result: Dict[str, Any], symbol: Optional[str] = None) -> Optional[bytes]:
    """Construit un rapport PDF; retourne ``None`` si reportlab est absent."""
    if not _HAS_REPORTLAB:
        return None
    payload = result.get("payload") or {}
    sym = str(symbol or result.get("symbol") or payload.get("symbol") or "Valeur").upper()
    row = payload.get("row") or {}
    name = str(row.get("name") or sym)
    generated = str(result.get("generated_at") or payload.get("generated_at") or "")
    provider = str(result.get("provider") or result.get("mode") or "Analyste local")
    text = str(result.get("text") or "").strip()
    if not text:
        text = "Aucune analyse textuelle n'a été produite."

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=17 * mm, bottomMargin=17 * mm,
        title=f"Market Mind — analyse {sym}", author="Market Mind",
        subject="Rapport d'analyse financière",
    )
    st = _styles()
    story: List[Any] = []
    story.append(Paragraph("MARKET MIND · INVESTMENT INTELLIGENCE", st["brand"]))
    story.append(Paragraph(_inline(f"Rapport d'analyse — {sym}"), st["title"]))
    story.append(Paragraph(
        _inline(f"{name} · généré le {generated or 'date non disponible'} · moteur : {provider}"),
        st["subtitle"],
    ))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor(TEAL),
                            spaceBefore=2, spaceAfter=10))

    story.append(Paragraph("Données de marché et indicateurs", st["h1"]))
    story.append(_kv_table(_payload_rows(payload), st))
    story.append(Spacer(1, 8))

    macro = payload.get("macro") or {}
    ind = macro.get("indicators") or {}
    if ind:
        story.append(Paragraph("Contexte macroéconomique marocain", st["h1"]))
        macro_rows = []
        for item in ind.values():
            if item.get("value") is None:
                macro_rows.append((item.get("label", "—"), "donnée non disponible"))
            else:
                macro_rows.append((
                    item.get("label", "—"),
                    f"{fmt_num(item.get('value'), 2)} {item.get('unit', '')} "
                    f"({item.get('year') or 'année n.d.'})",
                ))
        story.append(_kv_table(macro_rows, st))
        story.append(Paragraph(
            "Source : World Bank Open Data, séries annuelles différées. Ces données ne remplacent "
            "ni les publications du HCP ni les décisions de Bank Al-Maghrib.",
            st["small"],
        ))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Analyse de l'agent", st["h1"]))
    story.extend(_markdown_flowables(text, st))

    news = payload.get("news") or []
    if news:
        story.append(Paragraph("Actualités utilisées", st["h1"]))
        for item in news[:8]:
            title = _strip_emoji(str(item.get("title") or ""))
            source = _strip_emoji(str(item.get("source") or ""))
            date = _strip_emoji(str(item.get("published") or ""))
            story.append(Paragraph(
                f"<b>{_inline(title)}</b><br/><font size='7.5' color='{MUTED}'>{_inline(source)} · {date}</font>",
                st["body"],
            ))

    story.append(Paragraph("Sources et traçabilité", st["h1"]))
    as_of = payload.get("as_of")
    if as_of:
        story.append(Paragraph(f"Date de référence des cours : <b>{_inline(str(as_of))}</b>", st["small"]))
    for src in _sources(payload):
        story.append(Paragraph(_inline(src), st["bullet"], bulletText="•"))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Les performances passées ne préjugent pas des performances futures. Ce document est un "
        "outil d'information et d'analyse : il ne constitue ni un conseil en investissement, ni une "
        "recommandation personnalisée, ni une garantie de prix. Vérifiez les données auprès de leurs "
        "sources avant toute décision. Investir comporte un risque de perte en capital.",
        st["warning"],
    ))

    def _footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(BORDER))
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, 13 * mm, A4[0] - 18 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(18 * mm, 9 * mm, "Market Mind — document d'analyse, ne constitue pas un conseil en investissement.")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def build_markdown_report(result: Dict[str, Any], symbol: Optional[str] = None) -> str:
    """Repli lisible si reportlab n'est pas installé."""
    payload = result.get("payload") or {}
    sym = str(symbol or result.get("symbol") or payload.get("symbol") or "Valeur").upper()
    name = str((payload.get("row") or {}).get("name") or sym)
    lines = [
        f"# Market Mind — Rapport d'analyse {sym}",
        "",
        f"**{name}** · généré le {result.get('generated_at') or 'date non disponible'} · "
        f"moteur : {result.get('provider') or 'Analyste local'}",
        "",
        "## Données de marché",
    ]
    for key, value in _payload_rows(payload):
        lines.append(f"- **{key}** : {value}")
    lines += ["", "## Analyse", "", str(result.get("text") or ""), "", "## Sources"]
    lines += [f"- {s}" for s in _sources(payload)]
    lines += ["", "> Avertissement : outil d'analyse, ne constitue pas un conseil en investissement."]
    return "\n".join(lines)
