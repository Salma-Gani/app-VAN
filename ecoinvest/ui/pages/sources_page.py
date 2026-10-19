"""Sources, statut des données, méthodologie et limites de Market Mind."""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from ...ai import llm as llm_mod
from ...data import macro
from .. import components as ui
from . import shared


def render() -> None:
    ui.hero(
        "Sources, méthodologie & limites",
        "Ce que l'application sait, d'où viennent les chiffres, à quelle date ils se réfèrent et "
        "ce qu'elle ne peut pas faire. Aucune donnée n'est inventée pour combler un manque.",
        badge=ui.badge("Traçabilité", "info"),
    )

    _status_table()
    st.divider()
    _macro_snapshot()
    st.divider()
    _methodology()
    st.divider()
    _limits()
    ui.disclaimer()


def _status_table() -> None:
    ui.section(
        "Statut des données",
        "Chaque source est classée selon sa fraîcheur et son mode d'accès. « Différé » ne signifie "
        "pas « temps réel » : vérifiez la date de référence avant toute décision.",
    )
    rows: List[Dict[str, Any]] = [
        {
            "Donnée": "Cours, volumes, OHLC, capitalisation BVC",
            "Source": "Bourse de Casablanca — API publique Boursenova",
            "Devise / unité": "MAD, actions, MAD",
            "Période / date": "Dernière séance disponible",
            "Statut": "Différé / cache 15 min",
            "Limite": "Cours ajusté ; peut être indisponible ou retardé. Vérifier les conditions BVC.",
        },
        {
            "Donnée": "Nombre de titres, ISIN, compartiment, DPS",
            "Source": "Pages publiques BVC (actions, calendrier financier)",
            "Devise / unité": "actions, MAD/action",
            "Période / date": "Référentiel et dernier dividende détaché",
            "Statut": "Quotidien / annuel",
            "Limite": "La BVC ne publie pas P/E, résultat net, EBITDA, fonds propres ni ventes.",
        },
        {
            "Donnée": "VIX, indices internationaux, or, pétrole, EUR/MAD, USD/MAD",
            "Source": "Yahoo Finance (yfinance)",
            "Devise / unité": "points, USD, MAD",
            "Période / date": "Dernière cotation",
            "Statut": "Temps réel/différé selon Yahoo",
            "Limite": "Le VIX mesure la volatilité implicite des options S&P 500, pas celle du MASI.",
        },
        {
            "Donnée": "Actualités et sentiment",
            "Source": "Flux RSS publics (BVC, presse économique)",
            "Devise / unité": "texte",
            "Période / date": "Date de publication de l'article",
            "Statut": "Cache 15 min",
            "Limite": "Sentiment par lexique indicatif ; ne remplace pas une lecture éditoriale.",
        },
        {
            "Donnée": "Macro Maroc : PIB, inflation, chômage",
            "Source": "World Bank Open Data",
            "Devise / unité": "%",
            "Période / date": "Année de l'observation",
            "Statut": "Annuel différé",
            "Limite": "Ne remplace ni le HCP trimestriel ni les taux de Bank Al-Maghrib.",
        },
        {
            "Donnée": "BPA, EBITDA, EBIT, fonds propres, ventes, FCF",
            "Source": "Saisie utilisateur / import CSV (rapports annuels, AMMC)",
            "Devise / unité": "MAD, MAD/action, %",
            "Période / date": "Exercice fiscal renseigné (`fiscal_year`, `as_of`)",
            "Statut": "Saisi — non audité par Market Mind",
            "Limite": "Une valeur absente reste absente ; les ratios non pertinents sont désactivés.",
        },
        {
            "Donnée": "Analyse IA et rapports",
            "Source": "Fournisseur LLM configuré ou analyste local",
            "Devise / unité": "texte",
            "Période / date": "Date de génération",
            "Statut": "Généré — à vérifier",
            "Limite": "Pas de conseil personnalisé, pas de prix garanti, pas de données inventées.",
        },
    ]
    ui.table(pd.DataFrame(rows), height=520, key="sources_status")


def _macro_snapshot() -> None:
    ui.section("Macro Maroc actuellement chargée", "Séries annuelles World Bank, avec année et statut différé.")
    try:
        data = macro.morocco_indicators()
    except Exception:
        data = {"indicators": {}, "available": False}
    indicators = data.get("indicators") or {}
    if not indicators:
        ui.note("Les séries macro ne sont pas disponibles pour le moment. Aucune valeur de remplacement "
                "n'est affichée.", "warn", "⚠️")
        return
    cols = st.columns(3)
    for col, key in zip(cols, ("gdp_growth", "inflation", "unemployment")):
        item = indicators.get(key) or {}
        value = item.get("value")
        with col:
            st.metric(
                item.get("label") or key,
                f"{value:.2f} %" if value is not None else "—",
                help=(f"World Bank Open Data · année {item.get('year') or 'n.d.'} · "
                      f"mise à jour {item.get('updated') or 'n.d.'}"),
            )
    st.caption(
        "Source : [World Bank Open Data — Maroc](https://data.worldbank.org/country/morocco). "
        "Ces séries sont annuelles et différées ; elles ne constituent pas une prévision."
    )


def _methodology() -> None:
    ui.section("Formules et conventions", "Les calculs sont déterministes et testés ; les hypothèses restent visibles.")
    st.markdown(
        """
| Indicateur | Formule / convention |
|---|---|
| PER | `cours / BPA` — désactivé si BPA ≤ 0 |
| Prix théorique PER | `PER cible × BPA` |
| EV/EBITDA | `(capitalisation + dette nette) / EBITDA` ; prix = `(multiple × EBITDA − dette nette) / actions` |
| EV/EBIT | même passage EV → capitaux propres, avec EBIT |
| P/B | `cours / valeur comptable par action` |
| P/S | `cours / ventes par action` |
| Rendement du dividende | `DPS / cours` ; prix théorique = `DPS / rendement exigé` |
| Marge de sécurité | `(valeur théorique − cours) / valeur théorique` |
| Prix d'entrée | `valeur théorique × (1 − marge de sécurité exigée)` |
| DCF | `Σ FCFₜ / (1 + WACC)ᵗ + valeur terminale actualisée` |
| RSI(14) | moyenne des gains/pertes sur 14 séances, borné entre 0 et 100 |
| Support / résistance | extrêmes et pivots sur les 120 dernières séances |
| Drawdown | `(cours / plus haut observé) − 1` |
        """
    )
    st.caption(
        "Conventions : MAD pour les prix marocains, pourcentages affichés avec 2 décimales, "
        "multiples avec 2 décimales. Les montants compactés (M, Md) sont arrondis à l'affichage."
    )


def _limits() -> None:
    ui.section("Ce que Market Mind ne fait pas", "Les limites sont explicites pour éviter les fausses certitudes.")
    ui.note(
        "- **Aucun accès payant** à Bloomberg, Reuters, Refinitiv ou à des données sous licence n'est supposé.\n"
        "- **Aucun scraping** de contenus protégés ; seules les API/pages publiques et les flux RSS sont utilisés.\n"
        "- **Aucune redistribution** des données brutes : l'application les affiche pour votre usage d'analyse.\n"
        "- **Aucun chiffre inventé** : les données manquantes restent vides ou sont signalées.\n"
        "- **Aucun conseil personnalisé** : les scores, alertes et scénarios sont des lectures analytiques.\n"
        "- **Aucun prix garanti** : le prix théorique dépend de vos hypothèses et de la marge de sécurité.\n"
        "- **Aucune notification push/e-mail** : les alertes sont consultées localement dans l'application.\n"
        "- **Pas encore de backtesting** avec coûts de transaction et validation hors échantillon.",
        "warn", "⚠️",
    )
    st.caption(
        "Licences et conditions : vérifiez les termes d'utilisation de la Bourse de Casablanca, de "
        "Yahoo Finance et de chaque flux RSS avant toute réutilisation. Market Mind ne réaffirme pas "
        "de droits sur ces contenus."
    )
    try:
        status = llm_mod.provider_status()
        active = next((p for p in status.get("providers", []) if p.get("forced")), None) or next(
            (p for p in status.get("providers", []) if p.get("available")), None
        )
        mode = active["label"] if active else "Analyste local (hors-ligne)"
    except Exception:
        mode = "indisponible"
    st.caption(f"Moteur d'analyse actif : **{mode}**. Les clés API ne sont jamais affichées dans cette page.")
