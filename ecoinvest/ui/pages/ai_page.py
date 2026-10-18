"""Agent IA : assistant conversationnel, briefing de marché et analyse de société."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from ...ai import llm as llm_mod
from ...config import COLORS
from ...utils.formatting import fmt_num
from .. import components as ui
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
        "Agent IA EcoInvest",
        "Un analyste qui ne travaille qu'avec les données réelles chargées par l'application : "
        "aucun chiffre inventé, aucune recommandation déconnectée du marché.",
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

    tabs = st.tabs(["💬 Assistant", "📰 Briefing", "🔎 Analyse d'une valeur", "⚙️ Configuration"])
    with tabs[0]:
        _chat()
    with tabs[1]:
        _briefing()
    with tabs[2]:
        _company()
    with tabs[3]:
        _configuration(status)

    ui.disclaimer()


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
        agent = shared.build_agent()
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
            agent = shared.build_agent()
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
            agent = shared.build_agent()
            st.session_state["ai_company_result"] = agent.analyse_company(symbol)

    result = st.session_state.get("ai_company_result")
    if result:
        st.caption(f"Moteur : {result.get('provider') or '—'} · valeur : {result.get('symbol') or symbol}")
        st.markdown(result.get("text") or "")
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
