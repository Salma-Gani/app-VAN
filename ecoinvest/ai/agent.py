"""Agent IA d'analyse de marché et assistant conversationnel.

Deux modes, transparents pour l'utilisateur :

* **mode LLM** — si une clé d'API est détectée, les données réelles de
  l'application sont injectées dans le prompt et le modèle rédige l'analyse.
* **mode analyste local** — sinon, un moteur de règles déterministe répond
  à partir des mêmes données, hors-ligne et sans clé.

Dans les deux cas, l'agent ne dispose QUE des données réelles chargées par
l'application : aucun chiffre n'est inventé.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..analytics import scoring, technical, valuation_lab
from ..data import bvc, fundamentals, macro as macro_mod
from ..utils.formatting import fmt_money, fmt_multiple, fmt_num, fmt_pct
from . import llm as llm_mod
from . import prompts

# ═══════════════════════════ Contexte applicatif ═══════════════════════════


def _fmt_date(value: Any) -> str:
    """Date lisible JJ/MM/AAAA, ou chaîne vide si indisponible."""
    if value is None:
        return ""
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return ""
        return ts.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(value)


@dataclass
class AppContext:
    """Instantané des données de l'application, partagé avec l'agent."""

    market_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    regime: Dict[str, Any] = field(default_factory=dict)
    profile: Any = None
    enriched_holdings: Optional[pd.DataFrame] = None
    recommendation: Optional[Dict[str, Any]] = None
    universe: Optional[pd.DataFrame] = None

    def symbol_lookup(self) -> Dict[str, str]:
        table: Dict[str, str] = {}
        if self.universe is not None and not self.universe.empty:
            for _, row in self.universe.iterrows():
                sym = str(row["symbol"]).strip().upper()
                table[sym.lower()] = sym
                name = str(row.get("name") or "").strip().lower()
                if name:
                    table[name] = sym
                    table[name.split()[0]] = sym
        if not self.market_df.empty:
            for _, row in self.market_df.iterrows():
                table[str(row["symbol"]).lower()] = str(row["symbol"])
        return table

    def find_symbol(self, text: str) -> Optional[str]:
        table = self.symbol_lookup()
        low = " " + re.sub(r"[^a-z0-9à-ÿ ]", " ", text.lower()) + " "
        # 1) symbole exact (majuscules ou mot isolé)
        for token in re.findall(r"[a-z0-9]{2,8}", low):
            if token in table:
                return table[token]
        # 2) nom de société (correspondance la plus longue)
        best, best_len = None, 0
        for key, sym in table.items():
            if len(key) >= 4 and key in low and len(key) > best_len:
                best, best_len = sym, len(key)
        return best

    def row_for(self, symbol: str) -> Optional[pd.Series]:
        if self.market_df.empty:
            return None
        sub = self.market_df[self.market_df["symbol"] == symbol]
        return None if sub.empty else sub.iloc[0]


# ═══════════════════════════ Agent ═══════════════════════════


class MarketAgent:
    """Agent unique : analyses d'entreprise, briefing de marché, conversation."""

    def __init__(self, context: AppContext, provider: Optional[str] = None,
                 share_amounts: bool = False) -> None:
        self.ctx = context
        self.client = llm_mod.get_client(provider)
        self.provider = provider
        # Par défaut, aucun montant patrimonial n'est transmis au fournisseur LLM.
        self.share_amounts = bool(share_amounts)

    @property
    def mode(self) -> str:
        return "llm" if self.client else "local"

    @property
    def label(self) -> str:
        return self.client.label if self.client else "Analyste local (hors-ligne)"

    # ─── Contexte ───
    def _market_block(self) -> str:
        return prompts.market_context(self.ctx.regime, self.ctx.market_df)

    def _company_block(self, symbol: str) -> Tuple[str, Dict[str, Any]]:
        row = self.ctx.row_for(symbol)
        if row is None:
            return f"### VALEUR : {symbol}\nDonnées de marché indisponibles.", {}
        hist = bvc.stock_history(symbol, days=400)
        summary = technical.technical_summary(hist) if hist is not None and not hist.empty else {}
        f = fundamentals.get_fundamentals(symbol, row)
        ratios_raw = fundamentals.compute_ratios(f, price=row.get("close"), cap=row.get("cap"))
        ratios = {k: fundamentals.interpret_ratio(k, v) for k, v in ratios_raw.items()}
        news_items: List[Dict[str, Any]] = []
        try:
            from ..data import news as news_mod

            df = news_mod.company_news(str(row.get("name")), symbol, limit=6)
            if not df.empty:
                news_items = df.head(6).to_dict("records")
        except Exception:
            pass
        methods = valuation_lab.method_catalog(f, price=row.get("close"), cap=row.get("cap"))
        try:
            macro_data = macro_mod.morocco_indicators()
        except Exception:
            macro_data = {"indicators": {}, "available": False, "source": "World Bank Open Data"}
        block = prompts.company_context(symbol, row.to_dict(), summary, f, ratios, news_items)
        block += "\n\n" + prompts.valuation_context(methods)
        block += "\n\n" + prompts.morocco_macro_context(macro_data)
        payload = {
            "symbol": symbol,
            "row": row.to_dict(),
            "technical": summary,
            "ratios": ratios,
            "fundamentals": f,
            "news": news_items,
            "macro": macro_data,
            "valuation_methods": methods,
            "sources": [
                "Bourse de Casablanca (cours, volumes, historiques)",
                "Référentiel BVC (nombre de titres, dividende)",
                "Yahoo Finance (VIX, indices internationaux, devises)",
                "Flux RSS publics (actualités)",
                "World Bank Open Data (macro Maroc, séries annuelles différées)",
            ],
            "as_of": _fmt_date(row.get("last_date")),
            "fundamentals_source": str(f.get("source") or ""),
        }
        return block, payload

    def _portfolio_block(self) -> str:
        return prompts.portfolio_context(
            self.ctx.profile,
            self.ctx.enriched_holdings,
            self.ctx.recommendation,
            share_amounts=self.share_amounts,
        )

    # ─── Analyses ───
    def analyse_company(self, symbol: str) -> Dict[str, Any]:
        """Analyse complète d'une valeur (fondamental + technique + risque + plan)."""
        symbol = symbol.strip().upper()
        block, payload = self._company_block(symbol)
        if not payload:
            return {"mode": self.mode, "symbol": symbol, "text": f"Données indisponibles pour {symbol}.",
                    "provider": self.label}

        generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
        if self.client is None:
            text = self._local_company_analysis(symbol, payload)
            return {"mode": "local", "symbol": symbol, "text": text, "provider": self.label,
                    "payload": payload, "generated_at": generated_at}

        system = prompts.SYSTEM_MARKET_ANALYST
        user = (
            f"{self._market_block()}\n\n{block}\n\n"
            f"{self._portfolio_block() if self.ctx.profile else ''}\n\n"
            f"Rédige l'analyse d'investissement complète de {symbol} en suivant le format imposé. "
            "Adapte la taille de position au profil de l'investisseur si celui-ci est fourni."
        )
        try:
            text = self.client.chat([{"role": "user", "content": user}], system=system, temperature=0.25)
            return {"mode": "llm", "symbol": symbol, "text": text, "provider": self.label,
                    "payload": payload, "generated_at": generated_at}
        except llm_mod.LLMError as exc:
            fallback = self._local_company_analysis(symbol, payload)
            return {"mode": "local", "symbol": symbol, "provider": self.label,
                    "payload": payload, "generated_at": generated_at,
                    "text": f"> ⚠️ Erreur du fournisseur IA ({exc}). Réponse de l'analyste local :\n\n{fallback}"}

    def analyse_titre(self, symbol: str) -> Dict[str, Any]:
        """Analyse « en direct » : tendance, niveaux, scénarios et conclusion expliquée.

        Le prompt reprend la structure demandée (tendance/niveaux, scénarios haussier
        et baissier, conclusion) tout en conservant les garde-fous : sources, données
        manquantes, facteurs contradictoires et absence de garantie.
        """
        symbol = symbol.strip().upper()
        block, payload = self._company_block(symbol)
        generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
        if not payload:
            return {"mode": self.mode, "symbol": symbol, "provider": self.label,
                    "generated_at": generated_at, "payload": {},
                    "text": f"Données indisponibles pour {symbol}."}

        if self.client is None:
            return {"mode": "local", "symbol": symbol,
                    "text": self._local_direct_analysis(symbol, payload),
                    "provider": self.label, "payload": payload, "generated_at": generated_at}

        user = (
            f"{self._market_block()}\n\n{block}\n\n"
            f"{self._portfolio_block() if self.ctx.profile else ''}\n\n"
            f"Rédige l'analyse en direct de {symbol}. Utilise exclusivement les données ci-dessus. "
            "Les scénarios doivent être conditionnels et les niveaux doivent être des prix observables. "
            "Termine par les sources, les données manquantes et les risques."
        )
        try:
            text = self.client.chat(
                [{"role": "user", "content": user}],
                system=prompts.SYSTEM_DIRECT_ANALYST,
                temperature=0.3,
                max_tokens=1800,
            )
            return {"mode": "llm", "symbol": symbol, "text": text,
                    "provider": self.label, "payload": payload, "generated_at": generated_at}
        except llm_mod.LLMError as exc:
            fallback = self._local_direct_analysis(symbol, payload)
            return {"mode": "local", "symbol": symbol, "provider": self.label,
                    "payload": payload, "generated_at": generated_at,
                    "text": f"> ⚠️ Fournisseur IA indisponible ({exc}). Réponse de l'analyste local :\n\n{fallback}"}

    def briefing(self) -> Dict[str, Any]:
        """Briefing de marché."""
        block = self._market_block()
        if self.client is None:
            return {"mode": "local", "text": self._local_briefing(), "provider": self.label}
        user = f"{block}\n\n{self._portfolio_block() if self.ctx.profile else ''}\n\nRédige le briefing du jour."
        try:
            text = self.client.chat([{"role": "user", "content": user}],
                                    system=prompts.SYSTEM_BRIEFING, temperature=0.35)
            return {"mode": "llm", "text": text, "provider": self.label}
        except llm_mod.LLMError as exc:
            return {"mode": "local", "provider": self.label,
                    "text": f"> ⚠️ Fournisseur IA indisponible ({exc}).\n\n{self._local_briefing()}"}

    def chat(self, question: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """Répond à une question libre."""
        history = history or []
        symbol = self.ctx.find_symbol(question)
        if self.client is None:
            return {"mode": "local", "text": self._local_chat(question, symbol), "provider": self.label,
                    "symbol": symbol}

        parts = [self._market_block()]
        if symbol:
            block, _ = self._company_block(symbol)
            parts.append(block)
        if self.ctx.profile is not None:
            parts.append(self._portfolio_block())
        context = "\n\n".join(p for p in parts if p)

        messages = history[-8:] + [
            {"role": "user", "content": f"CONTEXTE (données réelles)\n{context}\n\n---\nQUESTION : {question}"}
        ]
        try:
            text = self.client.chat(messages, system=prompts.SYSTEM_CHATBOT, temperature=0.3)
            return {"mode": "llm", "text": text, "provider": self.label, "symbol": symbol}
        except llm_mod.LLMError as exc:
            return {"mode": "local", "provider": self.label, "symbol": symbol,
                    "text": f"> ⚠️ Fournisseur IA indisponible ({exc}).\n\n{self._local_chat(question, symbol)}"}

    # ═══════════════ Analyste local (hors-ligne) ═══════════════

    def _local_company_analysis(self, symbol: str, payload: Dict[str, Any]) -> str:
        row = payload["row"]
        tech = payload.get("technical") or {}
        ratios = payload.get("ratios") or {}
        trend = tech.get("trend") or {}
        momentum = tech.get("momentum") or {}
        levels = tech.get("levels") or {}
        score = None
        if not self.ctx.market_df.empty and "composite_score" in self.ctx.market_df.columns:
            sub = self.ctx.market_df[self.ctx.market_df["symbol"] == symbol]
            if not sub.empty:
                score = sub.iloc[0].get("composite_score")

        verdict = _verdict_from(score, tech.get("score"))
        lines = [f"## {symbol} — {row.get('name')}", f"*Secteur : {row.get('sector')}*", ""]
        lines.append(f"**Lecture : {verdict}** — score composite {fmt_num(score, 0)}/100, "
                     f"score technique {fmt_num(tech.get('score'), 2)} sur [-1 ; 1]")
        lines.append("")
        lines.append("### Chiffres clés")
        lines.append(
            f"- Cours : **{fmt_num(row.get('close'))} MAD** ({fmt_pct(row.get('change_pct'), 2, signed=True)} sur la séance)\n"
            f"- Capitalisation : {fmt_money(row.get('cap'), 'MAD', compact=True)} · volume {fmt_money(row.get('volume'), 'MAD', compact=True)}\n"
            f"- Perf. 1 an : {fmt_pct(row.get('return_12m'), 2, signed=True)} · YTD {fmt_pct(row.get('ytd_pct'), 2, signed=True)}\n"
            f"- 52 semaines : {fmt_num(row.get('low_52w'))} — {fmt_num(row.get('high_52w'))} MAD"
        )
        positives, negatives, missing = _signal_factors(payload, score)
        confidence = _confidence(payload)
        lines.append("")
        lines.append(f"### Ce qui soutient la conclusion ({confidence})")
        lines.extend(f"- {item}" for item in positives) if positives else lines.append(
            "- Aucun facteur favorable net identifié sur les données disponibles."
        )
        lines.append("")
        lines.append("### Ce qui la contredit")
        lines.extend(f"- {item}" for item in negatives) if negatives else lines.append(
            "- Aucun signal contradictoire majeur détecté, mais l'absence de données reste un risque."
        )
        lines.append("")
        lines.append("### Données manquantes et confiance")
        if missing:
            lines.extend(f"- {item}" for item in missing)
        else:
            lines.append("- Couverture de données satisfaisante sur les dimensions analysées.")
        lines.append(f"- **Niveau de confiance : {confidence}** — fondé uniquement sur les données "
                     "chargées par l'application, sans extrapolation.")
        lines.append("")
        lines.append("### Analyse technique")
        lines.append(f"- Tendance : **{trend.get('state')}**")
        for note in (trend.get("notes") or [])[:3]:
            lines.append(f"  - {note}")
        lines.append(f"- Momentum : **{momentum.get('state')}** · RSI(14) = {fmt_num(momentum.get('rsi'), 1)}")
        for note in (momentum.get("notes") or [])[:3]:
            lines.append(f"  - {note}")
        lines.append(
            f"- Niveaux : support **{fmt_num(levels.get('support'))}** · pivot **{fmt_num(levels.get('pivot'))}** · "
            f"résistance **{fmt_num(levels.get('resistance'))}**"
        )
        signals = tech.get("signals") or []
        if signals:
            lines.append("- Signaux actifs : " + " · ".join(s.get("signal", "") for s in signals[:4]))

        lines.append("")
        lines.append("### Analyse fondamentale")
        usable = {k: v for k, v in ratios.items() if isinstance(v, dict) and v.get("value") is not None}
        if usable:
            for key in ("per", "pb", "roe", "net_margin", "dividend_yield", "debt_to_equity", "ev_ebitda", "fcf_yield"):
                info = usable.get(key)
                if not info:
                    continue
                lines.append(
                    f"- **{info.get('label')}** = {fmt_multiple(info.get('value')) if info.get('unit') == 'x' else fmt_pct(info.get('value'))} "
                    f"— *{info.get('grade')}*. {info.get('text')}"
                )
        else:
            lines.append(
                "- ⚠️ Aucune donnée fondamentale n'est renseignée pour cette valeur. Rendez-vous dans "
                "**Données fondamentales** pour saisir le chiffre d'affaires, le résultat net, les fonds "
                "propres et le dividende : les ratios (P/E, ROE, rendement, endettement) seront alors calculés "
                "automatiquement et l'analyse deviendra complète."
            )

        lines.append("")
        lines.append("### Risque")
        lines.append(
            f"- Volatilité annualisée {fmt_pct(row.get('volatility'))} · bêta {fmt_num(row.get('beta'))} · "
            f"drawdown maximal {fmt_pct(row.get('max_drawdown'))} · ratio de Sharpe {fmt_num(row.get('sharpe'))}"
        )
        risk_lvl = _risk_level(row.get("volatility"), row.get("beta"))
        lines.append(f"- Appréciation : **{risk_lvl}**")

        support = levels.get("support")
        resistance = levels.get("resistance")
        if support is not None or resistance is not None:
            lines.append("")
            lines.append("### Niveaux observés")
            if support is not None:
                lines.append(f"- Support technique calculé sur l'historique : **{fmt_num(support)} MAD**")
            if resistance is not None:
                lines.append(f"- Résistance technique calculée sur l'historique : **{fmt_num(resistance)} MAD**")
            lines.append(
                "- Ces niveaux sont des repères statistiques, ni un objectif de cours, ni une "
                "consigne d'entrée, de sortie ou de taille de position."
            )
        lines.append("")
        lines.append("> ⚠️ **Risques** : ceci est une analyse quantitative automatisée, pas un conseil "
                     "d'investissement ni une consigne d'action. Risque de perte en capital, risque de "
                     "liquidité sur les petites capitalisations et risque de concentration. Vérifiez les "
                     "publications officielles de la société avant toute décision.")
        return "\n".join(lines)

    def _local_direct_analysis(self, symbol: str, payload: Dict[str, Any]) -> str:
        row = payload.get("row") or {}
        tech = payload.get("technical") or {}
        ratios = payload.get("ratios") or {}
        trend = tech.get("trend") or {}
        momentum = tech.get("momentum") or {}
        levels = tech.get("levels") or {}
        macro = payload.get("macro") or {}
        methods = payload.get("valuation_methods") or []
        close = row.get("close")
        score = None
        if not self.ctx.market_df.empty and "composite_score" in self.ctx.market_df.columns:
            found = self.ctx.market_df[self.ctx.market_df["symbol"] == symbol]
            if not found.empty:
                score = found.iloc[0].get("composite_score")
        base_verdict = _verdict_from(score, tech.get("score"))
        rsi = (momentum.get("rsi") if momentum.get("rsi") is not None else row.get("rsi14"))
        if base_verdict in ("Signaux très favorables", "Signaux favorables"):
            direct_verdict = "Biais positif"
        elif base_verdict == "Signaux mitigés":
            direct_verdict = "Biais neutre"
        elif base_verdict == "Signaux insuffisants":
            direct_verdict = "Signal insuffisant"
        else:
            direct_verdict = "Biais négatif"
        try:
            rsi_value = float(rsi) if rsi is not None else None
        except (TypeError, ValueError):
            rsi_value = None
        if rsi_value is not None and rsi_value <= 30 and "baissi" not in str(trend.get("state", "")).lower():
            direct_verdict = "Rebond technique possible, à confirmer"
        confidence = _confidence(payload)
        positives, negatives, missing = _signal_factors(payload, score)

        support = levels.get("support")
        resistance = levels.get("resistance")
        low52 = row.get("low_52w")
        high52 = row.get("high_52w")
        bull_target = resistance if resistance is not None else high52
        bear_target = support if support is not None else low52

        lines = [f"## {symbol} — {row.get('name') or symbol}", ""]
        lines.append(
            f"*Analyse générée le {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
            f"{self.label} · données de clôture {payload.get('as_of') or 'date non disponible'}*"
        )
        lines.append("")
        lines.append("### Tendance & niveaux clés")
        lines.append(
            f"- Cours **{fmt_num(close)} MAD** · séance **{fmt_pct(row.get('change_pct'), 2, signed=True)}** · "
            f"volume **{fmt_money(row.get('volume'), 'MAD', compact=True)}**."
        )
        lines.append(
            f"- Tendance **{trend.get('state') or 'indéterminée'}**, momentum "
            f"**{momentum.get('state') or 'indéterminé'}**, RSI(14) **{fmt_num(rsi, 1)}**."
        )
        lines.append(
            f"- Support 120 j **{fmt_num(support)} MAD** · pivot **{fmt_num(levels.get('pivot'))} MAD** · "
            f"résistance 120 j **{fmt_num(resistance)} MAD**."
        )
        lines.append(
            f"- Plus bas / plus haut 52 semaines : **{fmt_num(low52)} / {fmt_num(high52)} MAD**."
        )
        for note in (trend.get("notes") or [])[:2]:
            lines.append(f"- {note}")
        for note in (momentum.get("notes") or [])[:2]:
            lines.append(f"- {note}")

        lines.append("")
        lines.append("### Scénarios haussier / baissier")
        if bull_target is not None:
            lines.append(
                f"- **Haussier** : si le cours franchit **{fmt_num(resistance or bull_target)} MAD** "
                f"avec un volume supérieur à la moyenne, le premier objectif observable est "
                f"**{fmt_num(high52 or bull_target)} MAD**. Scénario invalidé sous "
                f"**{fmt_num(support or close)} MAD**."
            )
        else:
            lines.append("- **Haussier** : objectif indisponible faute de résistance calculable.")
        if support is not None and low52 is not None and abs(float(support) - float(low52)) / max(float(close or 1), 1) < 0.01:
            lines.append(
                f"- **Baissier** : si le cours casse **{fmt_num(support)} MAD**, il passera sous son "
                f"plus bas 52 semaines (**{fmt_num(low52)} MAD**). Il n'existe alors plus de support "
                f"historique proche dans la fenêtre observée ; le risque d'accélération baissière augmente. "
                f"Scénario invalidé au-dessus de **{fmt_num(resistance or close)} MAD**."
            )
        elif bear_target is not None:
            lines.append(
                f"- **Baissier** : si le cours casse **{fmt_num(support or bear_target)} MAD**, "
                f"la zone de vigilance devient **{fmt_num(low52 or bear_target)} MAD**. "
                f"Scénario invalidé au-dessus de **{fmt_num(resistance or close)} MAD**."
            )
        else:
            lines.append("- **Baissier** : support indisponible faute d'historique suffisant.")
        lines.append(
            "- Ces scénarios sont conditionnels et ne constituent pas des prévisions de prix. "
            "Aucune probabilité n'est calculée sans modèle validé."
        )

        lines.append("")
        lines.append("### Lecture d'ensemble")
        lines.append(
            f"**{direct_verdict}** — niveau de confiance **{confidence}**. "
            f"Score composite {fmt_num(score, 0)}/100 · score technique {fmt_num(tech.get('score'), 2)} "
            "sur [-1 ; 1]."
        )
        lines.append(
            "Cette lecture est une synthèse des données disponibles, pas un conseil personnalisé, "
            "ni une consigne d'action, ni une garantie de performance."
        )

        lines.append("")
        lines.append("### Ce qui soutient cette lecture")
        lines.extend(f"- {item}" for item in positives[:5]) if positives else lines.append(
            "- Aucun facteur favorable net identifié."
        )
        lines.append("")
        lines.append("### Ce qui la contredit")
        lines.extend(f"- {item}" for item in negatives[:4]) if negatives else lines.append(
            "- Aucun signal contradictoire majeur détecté, mais l'absence de données reste un risque."
        )
        lines.append("")
        lines.append("### Données manquantes")
        if missing:
            lines.extend(f"- {item}" for item in missing[:3])
        else:
            lines.append("- Couverture satisfaisante sur les dimensions analysées ; d'autres risques "
                         "peuvent rester non mesurés.")
        lines.append("")
        lines.append("### Valorisation et fondamentaux")
        usable = [m for m in methods if m.get("available")]
        if usable:
            for method in usable[:6]:
                current = method.get("current_ratio")
                if method.get("target_kind") == "yield":
                    rendered = fmt_pct(current, 2) if current is not None else "n.d."
                else:
                    rendered = fmt_multiple(current) if current is not None else "n.d."
                lines.append(
                    f"- **{method.get('label')}** : ratio actuel {rendered} · métrique "
                    f"{method.get('metric')} = {fmt_num(method.get('metric_value'))}."
                )
            lines.append(
                "- Aucun prix cible n'est calculé ici : ouvrez **Valorisation** pour saisir un multiple "
                "cible et une marge de sécurité. Le prix théorique restera conditionnel à vos hypothèses."
            )
        else:
            lines.append(
                "- Aucune métrique fondamentale exploitable (BPA, EBITDA, fonds propres, ventes ou "
                "dividende) n'est disponible. L'analyse est donc technique et de marché. "
                "Renseignez les états financiers dans « Données fondamentales »."
            )

        lines.append("")
        lines.append("### Macro et actualités")
        macro_lines = [line for line in prompts.morocco_macro_context(macro).splitlines() if line.startswith("- ")]
        lines.extend(macro_lines[:3])
        news_items = payload.get("news") or []
        if news_items:
            lines.append("- Actualités utilisées :")
            for item in news_items[:3]:
                lines.append(
                    f"  - [{item.get('source')}] {item.get('title')} "
                    f"({_fmt_date(item.get('published')) or 'date n.d.'})"
                )
        else:
            lines.append("- Aucune actualité récente exploitable n'a été chargée.")

        lines.append("")
        lines.append("### Sources et dates")
        for source in payload.get("sources") or []:
            lines.append(f"- {source}.")
        lines.append(f"- Date de référence des cours : {payload.get('as_of') or 'non disponible'}.")
        lines.append("")
        lines.append("> **⚠️ Risques** : analyse automatisée sur données publiques. Risque de perte en "
                     "capital, de liquidité sur les petites capitalisations et de concentration. "
                     "Vérifiez les publications officielles de la société et de la Bourse de Casablanca.")
        return "\n".join(lines)

    def _local_briefing(self) -> str:
        regime = self.ctx.regime or {}
        vix = regime.get("vix") or {}
        breadth = regime.get("breadth") or {}
        nc = regime.get("news") or {}
        lines = [f"## Briefing de marché — {regime.get('label', 'Indéterminé')}", ""]
        lines.append(
            f"Le MASI cote **{fmt_num(regime.get('masi_last'))} points** "
            f"({fmt_pct(regime.get('masi_var'), 2, signed=True)} sur la séance, "
            f"{fmt_pct(regime.get('masi_ytd'), 2, signed=True)} depuis le 1ᵉʳ janvier), avec une tendance "
            f"**{(regime.get('masi_trend') or {}).get('state', 'indéterminée')}**. "
            f"La largeur de marché est de **{breadth.get('advancers', 0)} hausses pour "
            f"{breadth.get('decliners', 0)} baisses** sur {breadth.get('total', 0)} valeurs cotées. "
            f"Le VIX s'établit à **{fmt_num(vix.get('level'))}** ({vix.get('label')})."
        )
        lines.append("")
        if not self.ctx.market_df.empty and "change_pct" in self.ctx.market_df.columns:
            movers = self.ctx.market_df.dropna(subset=["change_pct"])
            if not movers.empty:
                lines.append("### Trois mouvements à retenir")
                for _, r in movers.nlargest(3, "change_pct").iterrows():
                    lines.append(
                        f"- **{r.get('symbol')}** {fmt_pct(r.get('change_pct'), 2, signed=True)} à "
                        f"{fmt_num(r.get('close'))} MAD ({r.get('name')})"
                    )
                for _, r in movers.nsmallest(2, "change_pct").iterrows():
                    lines.append(
                        f"- **{r.get('symbol')}** {fmt_pct(r.get('change_pct'), 2, signed=True)} à "
                        f"{fmt_num(r.get('close'))} MAD ({r.get('name')})"
                    )
        lines.append("")
        lines.append("### Implications pour l'investisseur")
        lines.append(f"- {regime.get('advice', '')}")
        lines.append(
            f"- Sentiment des actualités : **{nc.get('label', 'Neutre')}** "
            f"({nc.get('count', 0)} articles analysés sur les derniers jours)."
        )
        gate = regime.get("entry_gate", 0)
        if gate > 0.1:
            lines.append("- Les conditions plaident pour des entrées échelonnées sur les meilleurs scores composites.")
        else:
            lines.append("- Privilégiez la préservation du capital et les entrées très fractionnées.")
        if self.ctx.market_df is not None and not self.ctx.market_df.empty and "composite_score" in self.ctx.market_df.columns:
            top = self.ctx.market_df.nlargest(3, "composite_score")
            if not top.empty:
                lines.append("")
                lines.append("### Meilleurs scores composites du moment")
                for _, r in top.iterrows():
                    lines.append(
                        f"- **{r.get('symbol')}** ({r.get('sector')}) — score {fmt_num(r.get('composite_score'), 0)}/100 · "
                        f"{r.get('signal')}"
                    )
        lines.append("")
        lines.append("> ⚠️ **Risques** : analyse automatisée sur données de marché publiques. "
                     "Aucune garantie de performance ; le risque de perte en capital est réel.")
        return "\n".join(lines)

    def _local_chat(self, question: str, symbol: Optional[str]) -> str:
        q = question.lower()
        ctx = self.ctx

        # 1) Définition d'un ratio / d'un concept
        definition = _match_definition(q)
        if definition:
            return definition

        # 2) Analyse d'une valeur citée
        if symbol and not any(k in q for k in ("compare", "meilleur", "allocation", "répartition", "portefeuille")):
            payload = self._company_payload(symbol)
            if payload:
                return self._local_company_analysis(symbol, payload)

        # 3) Comparaison / meilleur choix
        if any(k in q for k in ("compare", "meilleur", "meilleure", "optimal", "allocation", "répartition", "où investir", "ou investir")):
            return self._local_allocation_answer()

        # 4) Portefeuille / patrimoine
        if any(k in q for k in ("portefeuille", "patrimoine", "profil", "mon risque", "objectif", "retraite")):
            return self._local_profile_answer()

        # 5) Marché / régime / vix
        if any(k in q for k in ("marché", "marche", "régime", "regime", "vix", "masi", "tendance", "volatilité", "volatilite", "sentiment")):
            return self._local_briefing()

        # 6) Actualités
        if any(k in q for k in ("actualité", "actualite", "news", "information")):
            return self._local_news_answer()

        # 7) Ratios / fondamentaux
        if any(k in q for k in ("ratio", "fondamental", "per", "roe", "dividende", "bénéfice", "benefice", "fcf", "cash-flow", "valuation")):
            return self._local_fundamentals_answer()

        # 8) Aide par défaut
        return self._local_help()

    def _company_payload(self, symbol: str) -> Dict[str, Any]:
        _, payload = self._company_block(symbol)
        return payload

    def _local_allocation_answer(self) -> str:
        rec = self.ctx.recommendation
        lines = ["## Comparaison de vos options d'investissement", ""]
        if not rec:
            return self._local_help()
        best = rec.get("best") or {}
        lines.append(
            f"Pour un montant de **{fmt_money(rec.get('amount'), 'MAD', compact=True)}** sur "
            f"**{rec.get('years')} ans**, avec votre profil "
            f"« {(rec.get('investor_type') or {}).get('label')} » :"
        )
        lines.append("")
        df = rec.get("options")
        if df is not None and not df.empty:
            lines.append("| Option | Score profil | Rendement net | Valeur nette finale | Verdict |")
            lines.append("|---|---|---|---|---|")
            for _, r in df.head(7).iterrows():
                lines.append(
                    f"| {r['Option']} | {fmt_num(r['Score profil'], 0)}/100 | {fmt_pct(r['Rendement net'])} | "
                    f"{fmt_money(r['Valeur nette finale'], 'MAD', compact=True)} | {r['Verdict']} |"
                )
            lines.append("")
            lines.append(f"### 🏆 Meilleur choix : {best.get('Option')}")
            lines.append(
                f"Rendement net estimé **{fmt_pct(best.get('Rendement net'))}** par an "
                f"(**{fmt_pct(best.get('Rendement réel net'))}** en pouvoir d'achat constant), "
                f"pour une volatilité de {fmt_pct(best.get('Volatilité'))}. "
                f"Valeur nette finale : **{fmt_money(best.get('Valeur nette finale'), 'MAD', compact=True)}**."
            )
        tgt = rec.get("target_table")
        if tgt is not None and not tgt.empty:
            lines.append("")
            lines.append("### Allocation cible recommandée")
            for _, r in tgt.iterrows():
                if r["Poids"] > 0.02:
                    label = r["Classe d'actifs"]
                    lines.append(
                        f"- **{label}** : {fmt_pct(r['Poids'], 0)} "
                        f"(contribution au rendement {fmt_pct(r['Contribution rendement'])})"
                    )
            lines.append("")
            lines.append(
                f"Portefeuille attendu : **{fmt_pct(rec.get('portfolio_return'))}** brut par an pour une "
                f"volatilité de **{fmt_pct(rec.get('portfolio_volatility'))}** "
                f"(Sharpe {fmt_num(rec.get('portfolio_sharpe'))})."
            )
        picks = rec.get("stock_picks") or []
        if picks:
            lines.append("")
            lines.append("### Valeurs BVC les mieux notées par le moteur")
            for p in picks[:5]:
                lines.append(
                    f"- **{p.get('symbol')}** ({p.get('sector')}) — score {fmt_num(p.get('score'), 0)}/100 · "
                    f"{p.get('signal')} · cours {fmt_num(p.get('close'))} MAD"
                )
        lines.append("")
        lines.append("> ⚠️ **Risques** : projections basées sur des hypothèses de rendement et de volatilité. "
                     "Les rendements passés ne préjugent pas des rendements futurs.")
        return "\n".join(lines)

    def _local_profile_answer(self) -> str:
        p = self.ctx.profile
        if p is None:
            return self._local_help()
        itype = p.investor_type()
        lines = ["## Votre profil et votre patrimoine", ""]
        lines.append(f"- Revenu mensuel net : **{fmt_money(p.monthly_income)}** · charges **{fmt_money(p.monthly_charges)}**")
        lines.append(f"- Capacité d'épargne : **{fmt_money(p.savings_capacity)}**/mois ({fmt_pct(p.savings_rate)})")
        lines.append(f"- Patrimoine net : **{fmt_money(p.net_worth, 'MAD', compact=True)}** "
                     f"(actifs financiers {fmt_money(p.financial_assets, 'MAD', compact=True)})")
        lines.append(f"- Score de risque global : **{p.overall_risk_score():.0%}** → profil **{itype.get('label')}**")
        lines.append(f"- Part actions recommandée : **{p.recommended_equity_share():.0%}** "
                     f"(actuelle : {fmt_pct(p.equity_share) if p.equity_share is not None else 'n.d.'})")
        lines.append("")
        lines.append("### Diagnostics")
        for d in p.diagnostics():
            icon = {"good": "✅", "info": "ℹ️", "warn": "⚠️", "danger": "⛔"}.get(d["level"], "•")
            lines.append(f"- {icon} **{d['title']}** — {d['text']}")
        lines.append("")
        lines.append("> 🔒 **Confidentialité** : cette réponse a été produite localement ; aucun montant "
                     "n'a été transmis à un modèle externe.")
        lines.append("")
        lines.append("> ⚠️ **Risques** : ces diagnostics reposent sur les informations que vous avez saisies. "
                     "Une épargne de précaution de 3 à 6 mois de charges reste la priorité avant tout investissement risqué.")
        return "\n".join(lines)

    def _local_news_answer(self) -> str:
        try:
            from ..data import news as news_mod

            df = news_mod.fetch_all_news()
        except Exception:
            df = pd.DataFrame()
        lines = ["## Actualités et sentiment", ""]
        if df is None or df.empty:
            return lines[0] + "\n\nAucune actualité n'a pu être chargée (connexion indisponible)."
        summary = news_mod.aggregate_sentiment(df, days=5)
        lines.append(f"Sentiment global sur 5 jours : **{summary['label']}** "
                     f"(score {summary['score']:+.2f}, {summary['count']} articles) — "
                     f"{summary['positive']} positifs / {summary['negative']} négatifs.")
        lines.append("")
        lines.append("### Derniers titres marquants")
        for _, r in df.head(8).iterrows():
            lines.append(f"- **{r.get('source')}** — {r.get('title')} *({r.get('sentiment_label')})*")
        lines.append("")
        lines.append("> ⚠️ **Risques** : le sentiment mesuré est un indicateur statistique de langage, "
                     "pas une évaluation de la solidité financière des entreprises citées.")
        return "\n".join(lines)

    def _local_fundamentals_answer(self) -> str:
        lines = ["## Comment lire les ratios fondamentaux", ""]
        for key in ("per", "pb", "roe", "dividend_yield", "debt_to_equity", "net_margin", "ev_ebitda", "fcf_yield"):
            guide = fundamentals.RATIO_GUIDE.get(key)
            if not guide:
                continue
            lines.append(f"### {guide['label']}")
            lines.append(f"{guide['meaning']}")
            for limit, label, _color, text in guide["bands"][:4]:
                lines.append(f"- *{label}* — {text}")
            lines.append("")
        lines.append("> ⚠️ **Risques** : un ratio isolé ne suffit jamais. Croisez toujours valorisation, "
                     "rentabilité, endettement et génération de trésorerie.")
        return "\n".join(lines)

    def _local_help(self) -> str:
        regime = self.ctx.regime or {}
        lines = ["## Market Mind Intelligence — mode analyste local", ""]
        lines.append(
            f"Le moteur fonctionne actuellement **sans LLM** : les réponses sont produites par un moteur "
            f"de règles à partir des données réelles chargées. Régime de marché : **{regime.get('label', 'indisponible')}**."
        )
        lines.append("")
        lines.append("Voici ce que je sais faire :")
        lines.append("- **Analyser une valeur** : « analyse ATW », « que penses-tu de Bank of Africa ? »")
        lines.append("- **Comparer vos options** : « où investir 100 000 MAD sur 10 ans ? »")
        lines.append("- **Votre profil** : « quel est mon profil de risque ? », « comment atteindre mon objectif ? »")
        lines.append("- **Le marché** : « quel est le régime de marché ? », « que dit le VIX ? »")
        lines.append("- **Les actualités** : « quelles sont les dernières nouvelles ? »")
        lines.append("- **La pédagogie** : « c'est quoi le PER ? », « explique le ROE »")
        lines.append("")
        lines.append(
            "💡 Pour des réponses rédigées par un modèle de langage, renseignez une clé d'API "
            "(OpenAI, Anthropic, DeepSeek, Groq, Gemini, Mistral) ou lancez **Ollama** en local — "
            "l'application la détecte automatiquement."
        )
        return "\n".join(lines)


# ═══════════════════════════ Utilitaires ═══════════════════════════


def _signal_factors(payload: Dict[str, Any], score: Optional[float]) -> Tuple[List[str], List[str], List[str]]:
    """Facteurs favorables, défavorables et données manquantes d'une valeur."""
    row = payload.get("row") or {}
    tech = payload.get("technical") or {}
    ratios = payload.get("ratios") or {}
    positives: List[str] = []
    negatives: List[str] = []
    missing: List[str] = []

    def add(condition: bool, target: List[str], text: str) -> None:
        if condition:
            target.append(text)

    trend = str(row.get("trend_state") or (tech.get("trend") or {}).get("state") or "")
    momentum = str(row.get("momentum_state") or (tech.get("momentum") or {}).get("state") or "")
    rsi = row.get("rsi14")
    ret12 = row.get("return_12m")
    vol = row.get("volatility")
    beta = row.get("beta")
    drawdown = row.get("max_drawdown")
    sharpe = row.get("sharpe")

    add("haussi" in trend.lower(), positives, f"Tendance **{trend}** : structure de prix favorable.")
    add("baissi" in trend.lower(), negatives, f"Tendance **{trend}** : la structure de prix reste dégradée.")
    add("positif" in momentum.lower(), positives, f"Momentum **{momentum}**, RSI(14) = {fmt_num(rsi, 1)}.")
    add("négatif" in momentum.lower() or "negatif" in momentum.lower(), negatives,
        f"Momentum **{momentum}**, RSI(14) = {fmt_num(rsi, 1)}.")
    if rsi is not None:
        try:
            rsi_f = float(rsi)
            add(rsi_f >= 70, negatives, f"RSI à {fmt_num(rsi_f, 0)} : zone de surachat, risque de consolidation.")
            add(rsi_f <= 30, positives, f"RSI à {fmt_num(rsi_f, 0)} : zone de survente, rebond possible mais à confirmer.")
        except (TypeError, ValueError):
            pass
    if ret12 is not None:
        try:
            r = float(ret12)
            add(r > 0.10, positives, f"Performance 12 mois **{fmt_pct(r, 1, signed=True)}**.")
            add(r < -0.10, negatives, f"Performance 12 mois **{fmt_pct(r, 1, signed=True)}**.")
        except (TypeError, ValueError):
            pass
    if score is not None:
        try:
            sc = float(score)
            add(sc >= 60, positives, f"Score composite **{sc:.0f}/100**, au-dessus du seuil d'achat.")
            add(sc < 40, negatives, f"Score composite **{sc:.0f}/100**, sous le seuil de prudence.")
        except (TypeError, ValueError):
            pass
    if vol is not None:
        try:
            v = float(vol)
            add(v >= 0.35, negatives, f"Volatilité annualisée élevée : **{fmt_pct(v)}**.")
            add(v < 0.20, positives, f"Volatilité contenue : **{fmt_pct(v)}**.")
        except (TypeError, ValueError):
            pass
    if beta is not None:
        try:
            b = float(beta)
            add(b > 1.2, negatives, f"Bêta **{fmt_num(b, 2)}** : amplification des mouvements du marché.")
            add(b < 0.8, positives, f"Bêta défensif **{fmt_num(b, 2)}**.")
        except (TypeError, ValueError):
            pass
    if drawdown is not None:
        try:
            dd = float(drawdown)
            add(dd < -0.30, negatives, f"Drawdown maximal historique **{fmt_pct(dd)}**.")
        except (TypeError, ValueError):
            pass
    if sharpe is not None:
        try:
            sh = float(sharpe)
            add(sh > 0.8, positives, f"Ratio de Sharpe **{fmt_num(sh, 2)}** : rendement correctement rémunéré.")
            add(sh < 0, negatives, f"Ratio de Sharpe négatif (**{fmt_num(sh, 2)}**) sur la période.")
        except (TypeError, ValueError):
            pass

    usable = {k: v for k, v in ratios.items() if isinstance(v, dict) and v.get("value") is not None}
    core_keys = ("per", "pb", "roe", "net_margin", "ev_ebitda", "fcf_yield")
    has_core = any((usable.get(k) or {}).get("value") is not None for k in core_keys)
    if not has_core:
        missing.append(
            "États financiers complets non renseignés : P/E, ROE, marges et endettement ne sont "
            "pas calculables. L'analyse fondamentale reste partielle."
        )
    if usable:
        ys = (usable.get("dividend_yield") or {}).get("value")
        if ys is not None and float(ys) >= 0.04:
            positives.append(f"Rendement du dividende **{fmt_pct(ys)}**.")
        per = (usable.get("per") or {}).get("value")
        if per is not None:
            if float(per) <= 12:
                positives.append(f"P/E de **{float(per):.1f}x**, inférieur à la moyenne du marché.")
            elif float(per) >= 25:
                negatives.append(f"P/E de **{float(per):.1f}x**, prime de valorisation exigeante.")
        roe = (usable.get("roe") or {}).get("value")
        if roe is not None:
            if float(roe) >= 0.15:
                positives.append(f"ROE **{fmt_pct(roe)}**, rentabilité des fonds propres solide.")
            elif float(roe) < 0.05:
                negatives.append(f"ROE faible : **{fmt_pct(roe)}**.")
        dte = (usable.get("debt_to_equity") or {}).get("value")
        if dte is not None:
            if float(dte) > 2:
                negatives.append(f"Endettement élevé : dette/fonds propres **{float(dte):.2f}x**.")
            elif float(dte) < 0.8:
                positives.append(f"Levier maîtrisé : dette/fonds propres **{float(dte):.2f}x**.")
    if not usable:
        missing.append("Aucun ratio fondamental exploitable n'est disponible pour cette valeur.")
    if not tech:
        missing.append("Historique de cours insuffisant pour les indicateurs techniques.")
    if not row.get("volume"):
        missing.append("Volume de la séance non disponible : liquidité non évaluée.")
    return positives, negatives, missing


def _confidence(payload: Dict[str, Any]) -> str:
    """Niveau de confiance fondé sur la complétude des données, pas sur la conviction."""
    row = payload.get("row") or {}
    tech = payload.get("technical") or {}
    ratios = payload.get("ratios") or {}
    usable = [v for v in ratios.values() if isinstance(v, dict) and v.get("value") is not None]
    core_keys = ("per", "pb", "roe", "net_margin", "ev_ebitda", "fcf_yield")
    has_core = any((ratios.get(k) or {}).get("value") is not None for k in core_keys)
    tech_rsi = (tech.get("momentum") or {}).get("rsi") if tech else None
    checks = [
        has_core,
        bool(tech),
        row.get("return_12m") is not None,
        tech_rsi is not None,
        row.get("max_drawdown") is not None,
    ]
    count = sum(1 for c in checks if c)
    if has_core and count >= 4:
        return "élevé"
    if count >= 3:
        return "moyen"
    return "faible"


def _verdict_from(composite: Optional[float], tech_score: Optional[float]) -> str:
    score = composite if composite is not None else (50 + 50 * (tech_score or 0))
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "Indéterminé"
    if score >= 72:
        return "Signaux très favorables"
    if score >= 62:
        return "Signaux favorables"
    if score >= 52:
        return "Signaux mitigés"
    if score >= 42:
        return "Signaux insuffisants"
    if score >= 32:
        return "Signaux défavorables"
    return "Signaux très défavorables"


def _risk_level(volatility: Optional[float], beta: Optional[float]) -> str:
    v = volatility or 0
    if v >= 0.40:
        return "Risque très élevé (volatilité > 40 %)"
    if v >= 0.28:
        return "Risque élevé"
    if v >= 0.18:
        return "Risque modéré"
    if v >= 0.10:
        return "Risque faible à modéré"
    return "Risque faible"


def _match_definition(question: str) -> Optional[str]:
    q = question.lower()
    if not any(k in q for k in ("c'est quoi", "c est quoi", "définition", "definition", "explique", "signifie", "que veut dire", "comment lire", "à quoi sert", "a quoi sert")):
        return None
    aliases = {
        "per": "per", "p/e": "per", "price earnings": "per",
        "p/b": "pb", "pb": "pb", "price to book": "pb", "actif net": "pb",
        "roe": "roe", "rentabilité des fonds propres": "roe",
        "roa": "roa", "marge nette": "net_margin", "net margin": "net_margin",
        "dividende": "dividend_yield", "rendement": "dividend_yield", "yield": "dividend_yield",
        "dette": "debt_to_equity", "endettement": "debt_to_equity", "levier": "debt_to_equity",
        "ev/ebitda": "ev_ebitda", "ebitda": "ev_ebitda",
        "fcf": "fcf_yield", "cash-flow": "fcf_yield", "free cash": "fcf_yield",
        "payout": "payout", "distribution": "payout",
        "liquidité": "current_ratio", "current ratio": "current_ratio",
        "croissance": "revenue_growth",
    }
    for alias, key in sorted(aliases.items(), key=lambda x: -len(x[0])):
        if alias in q:
            guide = fundamentals.RATIO_GUIDE.get(key)
            if not guide:
                continue
            lines = [f"## {guide['label']}", "", guide["meaning"], "", "### Grille de lecture"]
            for limit, label, _color, text in guide["bands"]:
                lines.append(f"- **{label}** — {text}")
            lines.append("")
            lines.append("> ⚠️ **Risques** : un ratio doit toujours être comparé à la médiane de son secteur "
                         "et à l'historique de l'entreprise.")
            return "\n".join(lines)
    return None


def build_agent(
    market_df: Optional[pd.DataFrame] = None,
    regime: Optional[Dict[str, Any]] = None,
    profile: Any = None,
    enriched_holdings: Optional[pd.DataFrame] = None,
    recommendation: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
    lazy: bool = True,
    share_amounts: bool = False,
) -> MarketAgent:
    """Construit l'agent en chargeant (paresseusement) les données de contexte."""
    ctx = AppContext()
    if market_df is not None:
        ctx.market_df = market_df
    elif not lazy:
        ctx.market_df = scoring.build_market_table()
    if regime is not None:
        ctx.regime = regime
    elif not lazy:
        ctx.regime = scoring.market_regime()
    ctx.profile = profile
    ctx.enriched_holdings = enriched_holdings
    ctx.recommendation = recommendation
    if ctx.universe is None:
        try:
            ctx.universe = bvc.universe()
        except Exception:
            ctx.universe = pd.DataFrame()
    return MarketAgent(ctx, provider=provider, share_amounts=share_amounts)


def agent_status() -> Dict[str, Any]:
    return llm_mod.provider_status()
