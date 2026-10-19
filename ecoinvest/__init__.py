"""MARKET MIND — écosystème d'analyse et de simulation d'investissement.

Modules
-------
config      : paramètres globaux, chemins, palette, endpoints
data        : connecteurs de données (BVC Casablanca, Yahoo, World Bank, news, fondamentaux)
analytics   : indicateurs techniques, ratios, risque, prévisions, scoring
portfolio   : profil investisseur, simulation, optimisation d'allocation
ai          : agent d'analyse et chatbot (multi-fournisseur + analyste local)
ui          : composants, graphiques et pages Streamlit
"""

from __future__ import annotations

__version__ = "3.2.0"
__app_name__ = "MARKET MIND"

__all__ = ["__version__", "__app_name__"]
