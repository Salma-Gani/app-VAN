"""Agent IA : assistant conversationnel, briefing de marché et analyse de société."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from ...ai import llm as llm_mod
from ...config import COLORS
from ...utils.formatting import fmt_money, fmt_num, fmt_pct
from .. import components as ui
from ..reporting import download_analysis
from . import shared

_SUGGESTIONS = [
    "Quel est le régime de marché aujourd'hui ?",
    "Quelles sont les meilleures opportunités de la BVC ?",
    "Comment adapter mon allocation à mon profil ?",
    "Analyse la valeur ATW",
    "Que disent les actualités récentes ?",
    "Explique-moi le ratio P/E",
]


def render() -> None:
    status = llm_mod.provider_status()
    mode_label = "Modèle de langage" if status["mode"] == "llm" else "Analyste local (hors-ligne)"
    ui.hero(
        "Market Mind AI",
        "Un analyste qui ne travaille qu'avec les données réelles chargées par l'application : "
        "aucun chiffre inventé, aucune consigne d'achat ou de vente.",
        badge=ui.badge(f"{mode_label} · {status['active']}", "up" if status["mode"] == "llm" else "info"),
    )

    if status["mode"] == "local":
        ui.note(
            "**Aucune clé d'API détectée** : l'agent fonctionne en mode analyste local. Il répond "
            "en langage naturel à partir des données de marché, de vos ratios et de votre profil, "
            "sans connexion. Ajoutez une clé dans l'onglet « Configuration » pour activer un modèle "
            "de langage (OpenAI, Anthropic, DeepSeek, Groq, Gemini, Mistral ou Ollama).",
            "info", "🤖",
        )

    st.session_state.setdefault("ai_share_amounts", False)
    st.toggle(
        "Autoriser l'envoi de mes montants au modèle de langage",
        key="ai_share_amounts",
        help="Par défaut, seuls votre profil de risque, vos ratios d'épargne et les poids de votre "
             "portefeuille sont transmis. Les montants (revenus, patrimoine, dettes) restent locaux. "
             "Ce réglage n'a aucun effet en mode analyste local.",
    )
    ui.note(
        "**Conclusions explicables** : pour chaque valeur, l'agent sépare les facteurs favorables, "
        "les facteurs défavorables, les données manquantes et le niveau de confiance. Aucun chiffre "
        "n'est inventé ; une donnée absente est signalée comme telle.",
        "info", "🧠",
    )

    tabs = st.tabs(
        ["⚡ Analyse directe", "💬 Assistant", "📰 Briefing", "🔎 Analyse complète", "⚙️ Configuration"]
    )
    with tabs[0]:
        _direct()
    with tabs[1]:
        _chat()
    with tabs[2]:
        _briefing()
    with tabs[3]:
        _company()
    with tabs[4]:
        _configuration(status)

    ui.disclaimer()


# ═══════════════════════════ Analyse directe ═══════════════════════════


def _direct() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles.", "📡")
        return
    symbols = table["symbol"].tolist()
    names = dict(zip(table["symbol"], table["name"]))
    requested = str(st.session_state.get("selected_symbol") or "").upper()
    index = symbols.index(requested) if requested in symbols else 0

    c1, c2 = st.columns([3, 1])
    with c1:
        symbol = st.selectbox(
            "Valeur à analyser en direct", symbols, index=index,
            format_func=lambda s: f"{s} — {names.get(s, s)}", key="ai_direct_symbol",
        )
    with c2:
        st.write("")
        launch = st.button("⚡ Lancer l'analyse IA", key="ai_direct_btn",
                           use_container_width=True, type="primary")

    row = table[table["symbol"] == symbol].iloc[0]
    summary = shared.technical_summary(symbol)
    levels = (summary.get("levels") or {}) if summary else {}
    momentum = (summary.get("momentum") or {}) if summary else {}
    trend = (summary.get("trend") or {}) if summary else {}
    close = row.get("close")
    ui.kpi_row(
        [
            {"label": "Cours", "value": fmt_num(close, 2) + " MAD",
             "sub": f"séance {fmt_pct(row.get('change_pct'), 2, signed=True)}", "tone": "accent"},
            {"label": "Tendance", "value": str(trend.get("state") or "—"),
             "sub": "moyennes mobiles", "tone": "blue"},
            {"label": "RSI (14)", "value": fmt_num(momentum.get("rsi"), 1),
             "sub": str(momentum.get("state") or "—"), "tone": "warn"},
            {"label": "Support 120 j", "value": fmt_num(levels.get("support"), 2) + " MAD",
             "sub": f"résistance {fmt_num(levels.get('resistance'), 2)}", "tone": "info"},
            {"label": "Volume", "value": fmt_money(row.get("volume"), "MAD", compact=True),
             "sub": f"{fmt_num(row.get('transactions'), 0)} transactions", "tone": "blue"},
        ],
        per_row=5,
    )
    ui.source_note(
        ["Bourse de Casablanca (cours, volumes, historique)", "Référentiel BVC (titres, dividende)",
         "RSS publics (actualités)", "World Bank Open Data (macro Maroc)"],
        as_of=f"clôture du {shared.last_market_date(table)}",
        detail="L'analyse combine technique, fondamentaux disponibles et macro ; les données absentes sont signalées.",
    )
    pages = st.session_state.get("_nav_pages") or {}
    if "valuation" in pages:
        if st.button("🧮 Transformer un objectif de valorisation en prix d'entrée",
                     key=f"ai_to_valuation_{symbol}", use_container_width=False):
            st.session_state["selected_symbol"] = symbol
            st.switch_page(pages["valuation"])

    with st.expander("🧾 Contexte réel transmis à l'agent", expanded=False):
        st.markdown(
            f"- **{symbol} — {row.get('name')}** · secteur {row.get('sector') or '—'}\n"
            f"- Cours **{fmt_num(close, 2)} MAD** · variation **{fmt_pct(row.get('change_pct'), 2, signed=True)}** · "
            f"volume **{fmt_money(row.get('volume'), 'MAD', compact=True)}**\n"
            f"- Tendance **{trend.get('state') or '—'}** · momentum **{momentum.get('state') or '—'}** · "
            f"RSI **{fmt_num(momentum.get('rsi'), 1)}**\n"
            f"- Support **{fmt_num(levels.get('support'))}** · pivot **{fmt_num(levels.get('pivot'))}** · "
            f"résistance **{fmt_num(levels.get('resistance'))}**\n"
            f"- Les ratios fondamentaux ne sont inclus que s'ils sont réellement renseignés ; "
            f"la macro Maroc provient de la World Bank (séries annuelles différées)."
        )

    if launch:
        with st.spinner("L'agent analyse la tendance, les niveaux, les actualités et les données disponibles…"):
            agent = shared.build_agent(share_amounts=bool(st.session_state.get("ai_share_amounts", False)))
            st.session_state["ai_direct_result"] = agent.analyse_titre(symbol)

    result = st.session_state.get("ai_direct_result")
    if result and str(result.get("symbol") or "").upper() == symbol:
        st.divider()
        st.caption(
            f"Moteur : **{result.get('provider') or '—'}** · généré le "
            f"**{result.get('generated_at') or '—'}** · mode "
            f"**{result.get('mode') or '—'}**"
        )
        st.markdown(result.get("text") or "")
        download_analysis(result, symbol, key="ai_direct_report")
        payload = result.get("payload") or {}
        news_items = payload.get("news") or []
        if news_items:
            with st.expander("📰 Actualités utilisées par l'agent", expanded=False):
                for item in news_items[:6]:
                    title = str(item.get("title") or "Sans titre")
                    link = str(item.get("link") or "").strip()
                    if not link.lower().startswith(("http://", "https://")):
                        link = ""
                    rendered = f"[{title}]({link})" if link else f"**{title}**"
                    st.markdown(
                        f"- {rendered} — *{item.get('source')}* · "
                        f"{item.get('published') or 'date n.d.'}"
                    )
        ui.note(
            "**Ce que l'agent ne fait pas** : il ne prédit pas un prix futur, n'invente pas de "
            "consensus et ne transforme pas une alerte en ordre. Le prix théorique d'entrée se "
            "configure dans **Valorisation**, avec vos hypothèses et une marge de sécurité.",
            "info", "🧠",
        )
    elif result:
        ui.note(
            f"Une analyse existe pour **{result.get('symbol')}**. Sélectionnez cette valeur ou "
            "lancez une nouvelle analyse pour la valeur courante.",
            "info", "ℹ️",
        )
    else:
        ui.note(
            "L'agent utilise uniquement le contexte réel affiché ci-dessus. Sans clé d'API, il répond "
            "en mode analyste local ; avec une clé Anthropic, OpenAI, DeepSeek ou autre, le même "
            "contexte est envoyé au modèle et le rapport PDF reste disponible.",
            "info", "⚡",
        )


# ═══════════════════════════ Chat ═══════════════════════════


def _chat() -> None:
    ui.section(
        "Posez votre question",
        "L'agent connaît le marché, les secteurs, les valeurs, votre profil et vos positions.",
    )
    messages: List[Dict[str, str]] = st.session_state.setdefault("chat_messages", [])

    if not messages:
        st.markdown("**Suggestions :**")
        cols = st.columns(2)
        for i, prompt in enumerate(_SUGGESTIONS):
            with cols[i % 2]:
                if st.button(prompt, key=f"chat_suggest_{i}", use_container_width=True):
                    _answer(prompt)
                    st.rerun()

    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    with st.form("chat_form", clear_on_submit=True):
        c1, c2 = st.columns([5, 1])
        with c1:
            question = st.text_input(
                "Votre question", placeholder="Ex. : dois-je renforcer ma position sur IAM ?",
                label_visibility="collapsed",
            )
        with c2:
            sent = st.form_submit_button("Envoyer", use_container_width=True)

    if sent and question.strip():
        _answer(question.strip())
        st.rerun()

    if messages:
        if st.button("🗑️ Effacer la conversation", key="chat_clear"):
            st.session_state["chat_messages"] = []
            st.rerun()


def _answer(question: str) -> None:
    messages: List[Dict[str, str]] = st.session_state.setdefault("chat_messages", [])
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant")
    ][-8:]
    messages.append({"role": "user", "content": question})

    with st.spinner("L'agent analyse les données…"):
        agent = shared.build_agent(share_amounts=bool(st.session_state.get("ai_share_amounts", False)))
        result = agent.chat(question, history=history)

    text = result.get("text") or "Je n'ai pas pu produire de réponse."
    messages.append({"role": "assistant", "content": text})


# ═══════════════════════════ Briefing ═══════════════════════════


def _briefing() -> None:
    ui.section(
        "Briefing de marché",
        "Synthèse quotidienne : régime, volatilité, largeur, secteurs et opportunités.",
    )
    if st.button("📰 Générer le briefing", key="ai_briefing"):
        with st.spinner("Rédaction du briefing…"):
            agent = shared.build_agent(share_amounts=bool(st.session_state.get("ai_share_amounts", False)))
            st.session_state["ai_briefing_text"] = agent.briefing()

    result = st.session_state.get("ai_briefing_text")
    if result:
        st.caption(f"Moteur : {result.get('provider') or '—'}")
        st.markdown(result.get("text") or "")
    else:
        ui.note(
            "Le briefing est construit à partir du régime de marché, de la largeur, des secteurs "
            "et des meilleures opportunités. Il est régénéré à la demande.",
            "info", "📰",
        )


# ═══════════════════════════ Analyse société ═══════════════════════════


def _company() -> None:
    table = shared.market_table()
    if table.empty:
        ui.empty_state("Données de marché indisponibles.", "📡")
        return
    symbols = table["symbol"].tolist()
    names = dict(zip(table["symbol"], table["name"]))
    requested = str(st.session_state.get("selected_symbol") or "").upper()
    index = symbols.index(requested) if requested in symbols else 0

    c1, c2 = st.columns([3, 1])
    with c1:
        symbol = st.selectbox(
            "Valeur à analyser", symbols, index=index,
            format_func=lambda s: f"{s} — {names.get(s, s)}", key="ai_company_symbol",
        )
    with c2:
        st.write("")
        launch = st.button("🤖 Analyser", key="ai_company_btn", use_container_width=True)

    if launch:
        with st.spinner("Analyse complète en cours…"):
            agent = shared.build_agent(share_amounts=bool(st.session_state.get("ai_share_amounts", False)))
            st.session_state["ai_company_result"] = agent.analyse_company(symbol)

    result = st.session_state.get("ai_company_result")
    if result:
        st.caption(f"Moteur : {result.get('provider') or '—'} · valeur : {result.get('symbol') or symbol} "
                   f"· généré le {result.get('generated_at') or '—'}")
        st.markdown(result.get("text") or "")
        download_analysis(result, result.get("symbol") or symbol, key="ai_company_report")
    else:
        ui.note(
            "L'analyse combine tendance, momentum, niveaux techniques, ratios fondamentaux "
            "disponibles, risque et plan d'entrée — puis l'adapte à votre profil.",
            "info", "🔎",
        )


# ═══════════════════════════ Configuration ═══════════════════════════


def _configuration(status: Dict[str, Any]) -> None:
    ui.section("Fournisseur de modèle de langage", "Détection automatique, stockage local, repli hors-ligne.")
    providers = status.get("providers") or []
    if providers:
        rows = []
        for p in providers:
            rows.append(
                {
                    "Fournisseur": p["label"],
                    "Disponible": "✅" if p["available"] else "—",
                    "Modèle": p["model"],
                    "Variable d'environnement": p["env_var"],
                }
            )
        ui.table(pd.DataFrame(rows), height=min(320, 60 + 34 * len(rows)), key="ai_providers")

    active = next((p for p in providers if p.get("forced")), None) or next(
        (p for p in providers if p.get("available")), None
    )
    keys = [p["key"] for p in providers]
    labels = {p["key"]: p["label"] for p in providers}

    with st.form("ai_config_form"):
        c1, c2 = st.columns([1, 1])
        with c1:
            provider_key = st.selectbox(
                "Fournisseur", keys,
                index=keys.index(active["key"]) if active and active["key"] in keys else 0,
                format_func=lambda k: labels.get(k, k),
            )
        with c2:
            model = st.text_input("Modèle (facultatif)", value="", placeholder="laisser vide = modèle par défaut")

        secret = st.text_input(
            "Clé d'API / URL du serveur", type="password",
            help="Stockée uniquement dans data/user/ai_config.json sur cette machine. "
                 "Pour Ollama, indiquez l'URL du serveur (ex. http://localhost:11434).",
        )
        saved = st.form_submit_button("💾 Enregistrer la configuration", use_container_width=True)

    if saved:
        cfg = llm_mod.load_user_config()
        provider = llm_mod.PROVIDER_BY_KEY.get(provider_key)
        if provider is None:
            st.error("Fournisseur inconnu.")
        else:
            if secret.strip():
                cfg[provider.env_var] = secret.strip()
            if model.strip():
                cfg[provider.model_env] = model.strip()
            llm_mod.save_user_config(cfg)
            st.success(f"Configuration enregistrée pour {provider.label}.")
            st.rerun()

    c3, c4 = st.columns(2)
    with c3:
        if st.button("🔌 Tester la connexion", key="ai_test"):
            with st.spinner("Test en cours…"):
                ok, message = llm_mod.test_connection(provider_key)
            (st.success if ok else st.error)(message)
    with c4:
        if st.button("🧹 Effacer les clés enregistrées", key="ai_clear"):
            llm_mod.save_user_config({})
            st.success("Clés locales effacées. L'agent repasse en mode analyste local si aucune "
                       "variable d'environnement n'est définie.")
            st.rerun()

    with st.expander("📚 Comment configurer une clé ?", expanded=False):
        st.markdown(
            "Deux méthodes, sans redémarrage :\n\n"
            "1. **Via cette page** — collez la clé ci-dessus, elle est enregistrée localement.\n"
            "2. **Via une variable d'environnement** — par exemple `export OPENAI_API_KEY=sk-…` "
            "avant de lancer Streamlit.\n\n"
            "Le fournisseur forcé se choisit avec `ECOINVEST_LLM_PROVIDER` (openai, anthropic, "
            "deepseek, groq, gemini, mistral, ollama). Sans clé, l'analyste local prend le relais "
            "automatiquement.\n\n"
            "**Aucune donnée de marché n'est envoyée à un tiers en mode local.** En mode LLM, seuls "
            "les extraits de contexte nécessaires à la réponse sont transmis au fournisseur choisi."
        )

    st.caption(
        "Les réponses de l'agent sont générées à titre informatif et ne constituent pas un conseil "
        "en investissement."
    )
