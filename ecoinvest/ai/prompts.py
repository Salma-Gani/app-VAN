"""Invites (prompts) système de l'agent IA et de l'assistant conversationnel."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import CAPITAL_GAINS_TAX, DIVIDEND_TAX, RISK_FREE_RATE
from ..utils.formatting import fmt_money, fmt_multiple, fmt_num, fmt_pct

BASE_RULES = f"""
RÈGLES ABSOLUES
1. Tu analyses des données RÉELLES fournies dans le contexte. Tu n'inventes JAMAIS un chiffre.
   Si une donnée est absente, tu écris explicitement « donnée non disponible ».
2. Tu distingues toujours : (a) faits observés, (b) hypothèses de projection, (c) opinion.
3. Tu réponds en français, de manière structurée, concise et professionnelle.
4. Tu ne donnes jamais de garantie de performance. Tu rappelles le risque de perte en capital
   lorsqu'une recommandation est formulée.
5. Tu raisonnes comme un analyste buy-side : fondamental (valorisation, qualité, FCF),
   technique (tendance, momentum, niveaux), risque (volatilité, drawdown, liquidité),
   macro (VIX, taux, devises) et comportemental (profil de l'investisseur).
6. Contexte marché marocain : Bourse de Casablanca, devise MAD, taux sans risque
   {RISK_FREE_RATE:.2%}, fiscalité plus-values {CAPITAL_GAINS_TAX:.0%} (TPCVM),
   dividendes {DIVIDEND_TAX:.0%}.
7. Tu termines toujours par un encadré « ⚠️ Risques » d'une à deux lignes.
8. Tu expliques ta conclusion : tu listes séparément ce qui la SOUTIENT et ce qui la CONTREDIT,
   puis tu indiques les données manquantes et un niveau de confiance (élevé / moyen / faible).
   Chaque affirmation chiffrée doit être reliée à une donnée présente dans le contexte.
"""

SYSTEM_MARKET_ANALYST = f"""Tu es « Atlas Analyst », analyste quantitatif senior spécialiste du marché
actions marocain (Bourse de Casablanca) et des marchés internationaux.
Tu produis des analyses d'investissement actionnables, chiffrées et hiérarchisées.
{BASE_RULES}
FORMAT ATTENDU
**Verdict** (1 ligne : Achat fort / Achat / Conserver / Alléger / Éviter — avec niveau de confiance)
**Ce qui soutient la conclusion** (3 à 5 puces, chacune avec un chiffre et sa source)
**Ce qui la contredit** (2 à 4 puces : signaux opposés, valorisation, risque, actualité négative)
**Données manquantes** (1 à 3 puces ; écrire « donnée non disponible » si nécessaire)
**Thèse d'investissement** (synthèse en 2 à 3 phrases)
**Analyse fondamentale** | **Analyse technique** | **Risque** (puces courtes)
**Plan d'exécution** (zone d'entrée, invalidation/stop, objectif, taille de position %)
**⚠️ Risques**
"""

SYSTEM_CHATBOT = f"""Tu es l'assistant conversationnel d'ATLAS FINANCE, une application d'analyse
et de simulation d'investissement sur la Bourse de Casablanca et les marchés mondiaux.
Tu aides l'utilisateur à comprendre ses données, ses indicateurs et ses options.
{BASE_RULES}
STYLE
- Réponses courtes (5 à 12 lignes) sauf demande explicite de développement.
- Utilise du Markdown : titres courts, puces, **gras** sur les chiffres clés.
- Si la question est ambiguë, demande une précision en UNE phrase.
- Si la question porte sur un symbole, utilise les données de ce symbole présentes dans le contexte.
"""

SYSTEM_BRIEFING = f"""Tu es le rédacteur du briefing de marché quotidien d'ATLAS FINANCE.
À partir des données fournies, rédige un briefing de 150 à 250 mots, structuré ainsi :
1. **Le marché en une phrase** (tendance MASI + largeur + VIX).
2. **Trois mouvements à retenir** (avec chiffres).
3. **Ce que cela implique pour un investisseur** (2 à 3 puces actionnables).
4. **Point de vigilance**.
{BASE_RULES}
"""


# ═══════════════════════════ Construction du contexte ═══════════════════════════


def _fmt(value: Optional[float], kind: str = "num", currency: str = "MAD") -> str:
    if value is None:
        return "n.d."
    if kind == "pct":
        return fmt_pct(value, 2, signed=True)
    if kind == "money":
        return fmt_money(value, currency, compact=True)
    if kind == "mult":
        return fmt_multiple(value)
    return fmt_num(value, 2)


def market_context(regime: Dict[str, Any], market_df: Any, max_rows: int = 12) -> str:
    """Bloc de contexte « marché » : régime, indices, meilleures et pires valeurs."""
    lines: List[str] = ["### CONTEXTE MARCHÉ (données réelles)"]
    if regime:
        vix = regime.get("vix") or {}
        breadth = regime.get("breadth") or {}
        lines.append(
            f"- Régime global : **{regime.get('label')}** (score {regime.get('entry_gate', 0):+.2f} sur [-1,1])"
        )
        lines.append(
            f"- MASI : {_fmt(regime.get('masi_last'))} pts · séance {_fmt(regime.get('masi_var'), 'pct')} · "
            f"YTD {_fmt(regime.get('masi_ytd'), 'pct')} · tendance {((regime.get('masi_trend') or {}).get('state'))}"
        )
        lines.append(
            f"- VIX : {_fmt(vix.get('level'))} ({vix.get('label')}) · "
            f"largeur de marché : {breadth.get('advancers', 0)} hausses / "
            f"{breadth.get('decliners', 0)} baisses sur {breadth.get('total', 0)} valeurs"
        )
        nc = regime.get("news") or {}
        lines.append(f"- Sentiment des actualités : {nc.get('label')} (score {nc.get('score', 0):+.2f}, {nc.get('count', 0)} articles)")

    if market_df is not None and not market_df.empty:
        cols = ["symbol", "name", "sector", "close", "change_pct", "composite_score", "signal"]
        top = market_df.nlargest(max_rows // 2, "composite_score") if "composite_score" in market_df else market_df.head(0)
        lines.append("\n### MEILLEURS SCORES COMPOSITES")
        for _, r in top.iterrows():
            lines.append(
                f"- {r.get('symbol')} ({r.get('name')}, {r.get('sector')}) : score "
                f"{_fmt(r.get('composite_score'))}/100 · cours {_fmt(r.get('close'))} MAD · "
                f"séance {_fmt(r.get('change_pct'), 'pct')} · {r.get('signal')}"
            )
        if "change_pct" in market_df:
            movers = market_df.dropna(subset=["change_pct"])
            if not movers.empty:
                lines.append("\n### MOUVEMENTS DE LA SÉANCE")
                for _, r in movers.nlargest(max_rows // 3, "change_pct").iterrows():
                    lines.append(f"- ↑ {r.get('symbol')} {_fmt(r.get('change_pct'), 'pct')} à {_fmt(r.get('close'))} MAD")
                for _, r in movers.nsmallest(max_rows // 3, "change_pct").iterrows():
                    lines.append(f"- ↓ {r.get('symbol')} {_fmt(r.get('change_pct'), 'pct')} à {_fmt(r.get('close'))} MAD")
    return "\n".join(lines)


def company_context(symbol: str, row: Dict[str, Any], technical: Dict[str, Any],
                    fundamentals: Optional[Dict[str, Any]] = None,
                    ratios: Optional[Dict[str, Any]] = None,
                    news_items: Optional[List[Dict[str, Any]]] = None) -> str:
    """Bloc de contexte complet pour une valeur."""
    lines = [f"### VALEUR : {symbol} — {row.get('name')}", f"Secteur : {row.get('sector')}"]
    lines.append(
        f"Cours : {_fmt(row.get('close'))} MAD · séance {_fmt(row.get('change_pct'), 'pct')} · "
        f"volume {_fmt(row.get('volume'), 'money')} · capitalisation {_fmt(row.get('cap'), 'money')}"
    )
    lines.append(
        f"Perf. 1 mois {_fmt(row.get('return_1m'), 'pct')} · 3 mois {_fmt(row.get('return_3m'), 'pct')} · "
        f"6 mois {_fmt(row.get('return_6m'), 'pct')} · 1 an {_fmt(row.get('return_12m'), 'pct')} · "
        f"YTD {_fmt(row.get('ytd_pct'), 'pct')}"
    )
    lines.append(
        f"Technique : tendance {((technical.get('trend') or {}).get('state'))} · "
        f"momentum {((technical.get('momentum') or {}).get('state'))} · "
        f"RSI {_fmt((technical.get('momentum') or {}).get('rsi'))} · "
        f"score technique {_fmt(technical.get('score'))}"
    )
    levels = technical.get("levels") or {}
    lines.append(
        f"Niveaux : support {_fmt(levels.get('support'))} · résistance {_fmt(levels.get('resistance'))} · "
        f"pivot {_fmt(levels.get('pivot'))}"
    )
    for note in (technical.get("trend") or {}).get("notes", [])[:4]:
        lines.append(f"  · {note}")
    for note in (technical.get("momentum") or {}).get("notes", [])[:4]:
        lines.append(f"  · {note}")
    lines.append(
        f"Risque : volatilité annualisée {_fmt(row.get('volatility'), 'pct')} · "
        f"bêta {_fmt(row.get('beta'))} · drawdown max {_fmt(row.get('max_drawdown'), 'pct')} · "
        f"Sharpe {_fmt(row.get('sharpe'))}"
    )
    if ratios:
        lines.append("\n### RATIOS FONDAMENTAUX DISPONIBLES")
        for key, info in ratios.items():
            if not isinstance(info, dict):
                continue
            lines.append(f"- {info.get('label')} = {_fmt(info.get('value'))} → {info.get('grade')} : {info.get('text')}")
    else:
        lines.append("\n### RATIOS FONDAMENTAUX\n- Aucune donnée fondamentale saisie pour cette valeur "
                     "(utilisez l'onglet « Données fondamentales »). L'analyse est donc purement technique et de marché.")
    if fundamentals:
        extra = {k: v for k, v in fundamentals.items() if v not in (None, "", []) and k in
                 ("revenue", "net_income", "ebitda", "fcf", "equity", "total_debt", "cash", "dps", "eps")}
        if extra:
            lines.append("### ÉTATS FINANCIERS SAISIS")
            for k, v in extra.items():
                lines.append(f"- {k} = {_fmt(v, 'money')}")
    if news_items:
        lines.append("\n### ACTUALITÉS RÉCENTES")
        for item in news_items[:6]:
            lines.append(f"- [{item.get('source')}] {item.get('title')} ({item.get('sentiment_label')})")
    return "\n".join(lines)


def portfolio_context(
    profile: Any,
    enriched: Any,
    recommendation: Optional[Dict[str, Any]] = None,
    share_amounts: bool = False,
) -> str:
    """Bloc de contexte « profil et patrimoine ».

    Par défaut, **les montants personnels ne sont pas transmis** au modèle : seuls les
    ratios, le profil de risque et les poids du portefeuille sont envoyés. L'utilisateur
    peut explicitement autoriser le partage des montants.
    """
    lines = ["### PROFIL DE L'INVESTISSEUR (données saisies)"]
    if share_amounts:
        lines.append(
            f"Revenu mensuel net : {_fmt(profile.monthly_income)} MAD · charges "
            f"{_fmt(profile.monthly_charges)} MAD · capacité d'épargne "
            f"{_fmt(profile.savings_capacity)} MAD/mois ({_fmt(profile.savings_rate, 'pct')})"
        )
        lines.append(
            f"Patrimoine net : {_fmt(profile.net_worth, 'money')} · actifs financiers "
            f"{_fmt(profile.financial_assets, 'money')} · immobilier "
            f"{_fmt(profile.real_estate_value, 'money')} · dettes {_fmt(profile.total_debt, 'money')}"
        )
        lines.append(
            f"Objectif : {_fmt(profile.target_capital, 'money')} · revenu cible "
            f"{_fmt(profile.target_monthly_income)} MAD/mois"
        )
    else:
        lines.append(
            "Revenu et charges : **non transmis (confidentiel)** · capacité d'épargne "
            f"{_fmt(profile.savings_rate, 'pct')} du revenu · taux d'endettement "
            f"{_fmt(profile.debt_ratio, 'pct') if profile.debt_ratio is not None else 'n.d.'}"
        )
        lines.append(
            "Patrimoine : **non transmis (confidentiel)** · part actions actuelle "
            f"{_fmt(profile.equity_share, 'pct') if profile.equity_share is not None else 'n.d.'} · "
            f"mois de charges couverts par l'épargne de précaution "
            f"{_fmt(profile.emergency_months, 'num') if profile.emergency_months is not None else 'n.d.'}"
        )
        lines.append(
            "Objectif de capital : **non transmis (confidentiel)**. Ne demande pas ces montants."
        )
    lines.append(
        f"Âge {profile.age} ans · horizon {profile.horizon_years} ans · tolérance au risque "
        f"{profile.risk_tolerance}/5 · drawdown maximal accepté "
        f"{_fmt(profile.max_acceptable_drawdown, 'pct')}"
    )
    lines.append(
        f"Score de risque global {profile.overall_risk_score():.0%} → profil "
        f"« {profile.investor_type().get('label')} » · part actions recommandée "
        f"{profile.recommended_equity_share():.0%}"
    )
    if enriched is not None and not enriched.empty:
        lines.append("\n### PORTEFEUILLE DÉTENU")
        for _, h in enriched.head(15).iterrows():
            base = f"- {h.get('symbol')} · {_fmt(h.get('weight'), 'pct')} du portefeuille"
            if share_amounts:
                base += f" · {_fmt(h.get('value'), 'money')}"
            base += f" · plus-value {_fmt(h.get('pnl_pct'), 'pct')}"
            lines.append(base)
    else:
        lines.append("\n### PORTEFEUILLE DÉTENU\n- Aucune position enregistrée.")
    if recommendation:
        best = recommendation.get("best") or {}
        lines.append("\n### RECOMMANDATION CALCULÉE PAR LE MOTEUR")
        lines.append(f"- Meilleure option : {best.get('Option')} (score {_fmt(best.get('Score profil'))}/100)")
        lines.append(f"- Rendement net attendu : {_fmt(best.get('Rendement net'), 'pct')}")
        tgt = recommendation.get("target_table")
        if tgt is not None and not tgt.empty:
            label_col = "Classe d'actifs"
            parts = [
                "{} {:.0%}".format(r[label_col], r["Poids"])
                for _, r in tgt.iterrows()
                if r["Poids"] > 0.02 and label_col in tgt.columns
            ]
            lines.append("- Allocation cible : " + ", ".join(parts))
    return "\n".join(lines)
