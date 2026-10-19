"""Actions de téléchargement des rapports d'analyse."""
from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from ..ai import report


def download_analysis(result: Dict[str, Any], symbol: Optional[str] = None,
                      key: str = "analysis_report") -> None:
    """Propose un PDF, avec repli Markdown si reportlab est absent."""
    if not result or not result.get("text"):
        return
    sym = str(symbol or result.get("symbol") or "valeur").upper()
    filename = f"marketmind_{sym.lower()}_analyse"
    pdf = report.build_analysis_pdf(result, sym)
    if pdf:
        st.download_button(
            "⬇️ Télécharger le rapport PDF",
            data=pdf,
            file_name=filename + ".pdf",
            mime="application/pdf",
            key=key + "_pdf",
            help="Rapport complet : données, analyse, sources, limites et avertissement.",
        )
    else:
        text = report.build_markdown_report(result, sym)
        st.download_button(
            "⬇️ Télécharger le rapport Markdown",
            data=text.encode("utf-8"),
            file_name=filename + ".md",
            mime="text/markdown",
            key=key + "_md",
            help="Reportlab n'est pas installé : un rapport texte structuré est proposé.",
        )


def report_available() -> bool:
    return report.reportlab_available()
