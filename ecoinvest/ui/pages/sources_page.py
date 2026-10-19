"""Sources, statut des données, méthodologie et limites de Market Mind."""
from __future__ import annotations

import os
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from ...ai import llm as llm_mod
from ...data import http, macro, statements
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
    _connectors()
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
            "Donnée": "États financiers (bilan, CPC, trésorerie)",
            "Source": "AMMC (rapports annuels PDF) · EODHD / FMP / Yahoo Finance (API) · import CSV",
            "Devise / unité": "MAD, MAD/action, %",
            "Période / date": "Exercice fiscal (`fiscal_year`, `as_of`), document source",
            "Statut": "Officiel / API / saisi — à vérifier selon la source",
            "Limite": "La BVC ne publie ni BPA, ni EBITDA, ni fonds propres. Un PDF AMMC n'est pas une API.",
        },
        {
            "Donnée": "Ratios comptables dérivés",
            "Source": "Calcul sur les états financiers et le cours",
            "Devise / unité": "x, %, MAD",
            "Période / date": "Dernier exercice disponible",
            "Statut": "Calculé — déterministe et testé",
            "Limite": "Un ratio non pertinent est désactivé plutôt qu'inventé.",
        },
        {
            "Donnée": "Thèses de valorisation et conditions de suivi",
            "Source": "Vos hypothèses (multiple cible, marge) + métrique de référence",
            "Devise / unité": "MAD, multiple",
            "Période / date": "Création, dernière mise à jour, exercice suivi",
            "Statut": "Stocké localement — jamais un conseil",
            "Limite": "Le seuil peut ne jamais être atteint ; atteindre le seuil ne prouve pas la sous-évaluation.",
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


def _connectors() -> None:
    """Diagnostic des connecteurs : ce qui est réellement branché, ce qui exige une licence."""
    ui.section(
        "Diagnostic des connecteurs",
        "État réel des intégrations. Une clé absente ou une licence manquante est indiquée "
        "explicitement : aucun fournisseur n'est simulé.",
    )

    def configured(env: str) -> str:
        if not env:
            return "—"
        return "configurée" if os.getenv(env) else "absente"

    rows: List[Dict[str, Any]] = [
        {
            "Connecteur": "Bourse de Casablanca (Boursenova)",
            "Accès": "API publique JSON", "Clé": "Non", "État": "Connecté",
            "Fraîcheur": "Dernière séance · cache 15 min",
            "Droits / limite": "Cours différés ; conditions d'utilisation BVC à vérifier.",
        },
        {
            "Connecteur": "AMMC — états financiers",
            "Accès": "Pages publiques + PDF", "Clé": "Non", "État": "Documentaire",
            "Fraîcheur": "Date de publication du rapport",
            "Droits / limite": "Pas d'API : documents officiels, vérification humaine requise.",
        },
        {
            "Connecteur": "World Bank Open Data",
            "Accès": "API publique", "Clé": "Non", "État": "Connecté",
            "Fraîcheur": "Annuelle différée",
            "Droits / limite": "Séries annuelles ; ne remplace pas HCP / Bank Al-Maghrib.",
        },
        {
            "Connecteur": "Flux RSS (presse, BVC, international)",
            "Accès": "RSS publics", "Clé": "Non", "État": "Connecté (selon disponibilité)",
            "Fraîcheur": "Date de publication de l'article · cache 15 min",
            "Droits / limite": "Titres et liens renvoyés à la source ; sentiment lexical indicatif.",
        },
        {
            "Connecteur": "EODHD", "Accès": "API commerciale", "Clé": configured("EODHD_API_KEY"),
            "État": "Configuré" if os.getenv("EODHD_API_KEY") else "Non configuré",
            "Fraîcheur": "Selon abonnement",
            "Droits / limite": "Couverture des valeurs marocaines non vérifiée sans clé.",
        },
        {
            "Connecteur": "Financial Modeling Prep (FMP)", "Accès": "API commerciale",
            "Clé": configured("FMP_API_KEY"),
            "État": "Configuré" if os.getenv("FMP_API_KEY") else "Non configuré",
            "Fraîcheur": "Selon abonnement",
            "Droits / limite": "Couverture marocaine limitée ; à tester avec une clé réelle.",
        },
        {
            "Connecteur": "Yahoo Finance (yfinance)", "Accès": "Bibliothèque non officielle",
            "Clé": "Non", "État": "Connecté (international)",
            "Fraîcheur": "Dernière cotation",
            "Droits / limite": "Pas d'états financiers marocains ; usage non officiel.",
        },
        {
            "Connecteur": "Bloomberg Data License", "Accès": "API REST / SFTP (licence)",
            "Clé": "Licence + identifiants", "État": "Non connecté",
            "Fraîcheur": "Selon contrat",
            "Droits / limite": "Accès payant ; redistribution soumise à licence. Non supposé disponible.",
        },
        {
            "Connecteur": "LSEG / Reuters", "Accès": "API sous licence",
            "Clé": "Licence + identifiants", "État": "Non connecté",
            "Fraîcheur": "Selon contrat",
            "Droits / limite": "Accès payant ; pas de scraping ni de redistribution non autorisée.",
        },
        {
            "Connecteur": "Investing.com", "Accès": "Widgets ; pas d'API publique",
            "Clé": "—", "État": "Non connecté",
            "Fraîcheur": "—",
            "Droits / limite": "Aucune API publique directe : intégration API non fabriquée.",
        },
        {
            "Connecteur": "Bank Al-Maghrib", "Accès": "Publications / API non intégrée",
            "Clé": "—", "État": "Non connecté", "Fraîcheur": "—",
            "Droits / limite": "Taux directeur et stats monétaires absents, signalés comme tels.",
        },
        {
            "Connecteur": "HCP (marocain)", "Accès": "Publications / API non intégrée",
            "Clé": "—", "État": "Non connecté", "Fraîcheur": "—",
            "Droits / limite": "Séries trimestrielles non connectées.",
        },
    ]
    ui.table(pd.DataFrame(rows), height=420, key="connector_catalog")

    st.markdown("**Derniers appels observés (journal en mémoire, sans secrets)**")
    states = http.diagnostics()
    if not states:
        st.caption(
            "Aucun appel réseau enregistré depuis le démarrage du serveur. "
            "Le journal se remplit à mesure que les modules interrogent leurs sources."
        )
        return
    live = pd.DataFrame(states)
    keep = [c for c in (
        "provider", "status", "http_status", "records", "last_success",
        "kind", "label", "last_error", "last_error_at",
    ) if c in live.columns]
    live = live[keep].rename(columns={
        "provider": "Fournisseur", "status": "État", "http_status": "HTTP",
        "records": "Enregistrements", "last_success": "Dernier succès",
        "kind": "Code", "label": "Diagnostic", "last_error": "Dernière erreur",
        "last_error_at": "Heure de l'erreur",
    })
    ui.table(live, height=260, key="connector_live")

    with st.expander("Politique de gestion des erreurs HTTP", expanded=False):
        st.markdown(
            "| Statut | Signification | Comportement de l'application |\n"
            "|---|---|---|\n"
            "| 401 | Authentification invalide | Réessai **stoppé** ; message « clé ou authentification "
            "à vérifier ». Aucune donnée de remplacement. |\n"
            "| 403 | Accès refusé | Réessai stoppé ; droits ou abonnement insuffisants signalés. |\n"
            "| 404 | Ressource absente | Réessai stoppé ; identifiant d'instrument ou URL vérifié. |\n"
            "| 429 | Limite de débit | Réessais avec délai exponentiel, puis message « réessayez plus tard ». |\n"
            "| 5xx | Panne serveur | Réessais bornés, puis repli **explicite** sur la copie datée du cache. |\n"
            "| Délai / réseau | Pas de réponse | Réessais bornés, puis état « indisponible » affiché. |\n"
            "| 200 vide | Réponse sans donnée | État « aucune donnée pour cette requête », pas de zéro inventé. |\n"
            "| JSON illisible | Réponse mal formée | Erreur « réponse illisible », jamais remplacée par une valeur simulée. |\n\n"
            "Aucune clé, aucun jeton et aucun corps de réponse brut ne sont affichés ni journalisés : "
            "les URLs sont expurgées avant enregistrement du diagnostic."
        )

    llm_status = llm_mod.provider_status()
    configured_llm = [p["label"] for p in llm_mod.available_providers() if p.get("available")]
    st.caption(
        "Moteur IA : "
        + (", ".join(configured_llm) if configured_llm else "aucun fournisseur configuré — analyste local déterministe utilisé")
        + f" · moteur actif : {llm_status.get('active') or 'local'}."
    )


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
        "- **Backtest illustratif disponible** (onglet « Backtest » de la fiche société) : coûts de "
        "transaction inclus, aucune anticipation, validation hors échantillon. Historique court, "
        "fiscalité et liquidité réelle non modélisées — aucune performance future n'est garantie.\n"
        "- **Monte-Carlo** : les percentiles (P5–P95) et probabilités décrivent la distribution **du "
        "modèle** (GBM ou DCF), pas des certitudes de marché ; la graine est affichée pour reproductibilité.\n"
        "- **Sentiment et impact des actualités** : heuristiques par mots-clés, présentées comme "
        "indicatives — elles ne remplacent pas une lecture humaine et ne prédisent rien.",
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
