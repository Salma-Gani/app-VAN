"""Simulation d'investissement et comparaison « mon placement vs la meilleure option »."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..config import (
    BROKERAGE_FEE,
    CAPITAL_GAINS_TAX,
    DIVIDEND_TAX,
    INFLATION_RATE,
    RISK_FREE_RATE,
)
from ..utils import finance
from ..utils.formatting import as_float, safe_div
from . import optimize


def net_return(
    gross_return: float,
    years: float,
    tax: float = CAPITAL_GAINS_TAX,
    entry_fee: float = BROKERAGE_FEE,
    dividend_share: float = 0.0,
    dividend_tax: float = DIVIDEND_TAX,
) -> float:
    """Rendement net d'impôts et de frais, décomposé entre plus-value et dividendes."""
    total_value = (1 + gross_return) ** years
    dividends = total_value * dividend_share
    capital_gain = (total_value - 1) - dividends
    net = (
        1
        - entry_fee
        + capital_gain * (1 - tax)
        + dividends * (1 - dividend_tax)
        - entry_fee
    )
    return float(net ** (1 / years) - 1) if years > 0 else 0.0


def simulate_option(
    name: str,
    amount: float,
    years: float,
    expected_return: float,
    volatility: float,
    tax: float = CAPITAL_GAINS_TAX,
    liquidity: str = "Moyenne",
    notes: str = "",
    dividend_share: float = 0.0,
    is_real: bool = False,
) -> Dict[str, Any]:
    """Simule une option de placement sur un horizon donné."""
    gross_value = finance.future_value(amount, 0.0, expected_return, years)
    nr = net_return(expected_return, years, tax=tax, dividend_share=dividend_share)
    net_value = finance.future_value(amount, 0.0, nr, years)
    real_value = net_value / (1 + INFLATION_RATE) ** years
    # Intervalle de confiance approximatif (log-normal)
    sigma_t = volatility * np.sqrt(max(years, 0.1))
    low = gross_value * float(np.exp(-1.28 * sigma_t))
    high = gross_value * float(np.exp(1.28 * sigma_t))
    return {
        "Option": name,
        "Montant investi": amount,
        "Horizon (ans)": years,
        "Rendement brut": expected_return,
        "Rendement net": nr,
        "Rendement réel net": (1 + nr) / (1 + INFLATION_RATE) - 1,
        "Valeur brute finale": gross_value,
        "Valeur nette finale": net_value,
        "Valeur en dirhams constants": real_value,
        "Gain net": net_value - amount,
        "Scénario défavorable (-1,28σ)": low,
        "Scénario favorable (+1,28σ)": high,
        "Volatilité": volatility,
        "Ratio de Sharpe": safe_div(nr - RISK_FREE_RATE, volatility),
        "Liquidité": liquidity,
        "Impôt appliqué": tax,
        "Notes": notes,
        "Statistiques réelles": is_real,
    }


def compare_investments(
    amount: float,
    years: float,
    classes: Optional[Sequence[Any]] = None,
    include_custom: Optional[List[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """Compare un montant placé sur l'ensemble des classes d'actifs disponibles."""
    classes = list(classes or optimize.asset_classes())
    rows: List[Dict[str, Any]] = []
    for c in classes:
        div_share = 0.5 if "BVC" in c.code or c.code in ("GLOBAL_EQ",) else 0.0
        rows.append(
            simulate_option(
                c.label,
                amount,
                years,
                c.expected_return,
                c.volatility,
                tax=c.tax,
                liquidity=c.liquidity,
                notes=c.note,
                dividend_share=div_share,
                is_real=c.real_stats,
            )
        )
    for custom in include_custom or []:
        rows.append(
            simulate_option(
                custom.get("name", "Option personnalisée"),
                amount,
                years,
                float(custom.get("expected_return", 0.05)),
                float(custom.get("volatility", 0.15)),
                tax=float(custom.get("tax", CAPITAL_GAINS_TAX)),
                liquidity=custom.get("liquidity", "—"),
                notes=custom.get("notes", ""),
                dividend_share=float(custom.get("dividend_share", 0.0)),
            )
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("Valeur nette finale", ascending=False).reset_index(drop=True)


def score_option(row: Dict[str, Any], profile: Any) -> Dict[str, Any]:
    """Note une option de placement selon le profil de l'investisseur."""
    risk = float(profile.overall_risk_score())
    horizon = max(1, int(profile.horizon_years))

    ret = as_float(row.get("Rendement réel net")) or 0.0
    vol = as_float(row.get("Volatilité")) or 0.0
    sharpe = as_float(row.get("Ratio de Sharpe")) or 0.0

    # Rendement : 0 → -1 ; 12 % réel net → +1
    s_return = float(np.clip(ret / 0.12, -1, 1) * 2 - 1)
    # Risque : toléré jusqu'à 2× le niveau confortable du profil
    comfort_vol = 0.05 + 0.22 * risk
    s_risk = float(np.clip(1 - (vol / (comfort_vol * 2)), -1, 1))
    # Sharpe
    s_sharpe = float(np.clip(sharpe / 0.8, -1, 1))
    # Liquidité
    liquidity_map = {"Immédiate": 1.0, "Très bonne": 0.85, "Bonne": 0.7,
                     "Moyenne": 0.45, "Variable": 0.35, "Faible": 0.2, "Très faible": 0.05}
    s_liq = float(liquidity_map.get(str(row.get("Liquidité")), 0.4)) * 2 - 1
    # Horizon (une classe illiquide est pénalisée sur horizon court)
    s_horizon = 0.0

    weights = {"return": 0.38, "risk": 0.27, "sharpe": 0.20, "liq": 0.15}
    score = (
        s_return * weights["return"]
        + s_risk * weights["risk"]
        + s_sharpe * weights["sharpe"]
        + s_liq * weights["liq"]
    )
    final = float(np.clip(50 + 50 * score / sum(weights.values()) * 2, 0, 100))
    if final >= 72:
        verdict, color = "Excellent choix pour votre profil", "#22D3A6"
    elif final >= 60:
        verdict, color = "Bon choix", "#22D3A6"
    elif final >= 48:
        verdict, color = "Acceptable", "#5B8DEF"
    elif final >= 36:
        verdict, color = "Peu adapté", "#F5B547"
    else:
        verdict, color = "Inadapté à votre profil", "#F45B69"
    return {
        "score": final,
        "verdict": verdict,
        "color": color,
        "détail": {"rendement": s_return, "risque": s_risk, "sharpe": s_sharpe, "liquidité": s_liq},
        "horizon": horizon,
    }


def rank_options(df: pd.DataFrame, profile: Any) -> pd.DataFrame:
    """Classe les options selon leur adéquation au profil."""
    out = df.copy()
    scores, verdicts, colors = [], [], []
    for _, row in out.iterrows():
        s = score_option(row.to_dict(), profile)
        scores.append(s["score"])
        verdicts.append(s["verdict"])
        colors.append(s["color"])
    out["Score profil"] = scores
    out["Verdict"] = verdicts
    out["_color"] = colors
    return out.sort_values("Score profil", ascending=False).reset_index(drop=True)


def recommend(
    profile: Any,
    market_df: Optional[pd.DataFrame] = None,
    amount: Optional[float] = None,
    years: Optional[int] = None,
    candidates: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Recommandation complète : allocation cible, options classées et argumentaire.

    C'est le cœur de la promesse « comparez votre investissement au meilleur choix ».
    """
    amount = float(amount if amount is not None else max(profile.monthly_investment * 12, 10_000))
    years = int(years if years is not None else profile.horizon_years)

    classes = optimize.asset_classes()
    options = compare_investments(amount, years, classes=classes)
    ranked = rank_options(options, profile)

    target = optimize.target_allocation(profile, classes)
    target_df = optimize.allocation_table(target, classes)
    portfolio_return, portfolio_vol, portfolio_sharpe = optimize.portfolio_risk(target, classes)

    best = ranked.iloc[0].to_dict() if not ranked.empty else None
    second = ranked.iloc[1].to_dict() if len(ranked) > 1 else None

    # Meilleure sélection de valeurs BVC si un tableau de marché est disponible
    stock_picks: List[Dict[str, Any]] = []
    if market_df is not None and not market_df.empty and "composite_score" in market_df.columns:
        sub = market_df[market_df["composite_score"].notna()].nlargest(8, "composite_score")
        for _, row in sub.iterrows():
            stock_picks.append(
                {
                    "symbol": row.get("symbol"),
                    "name": row.get("name"),
                    "sector": row.get("sector"),
                    "close": row.get("close"),
                    "score": row.get("composite_score"),
                    "signal": row.get("signal"),
                    "dividend_yield": row.get("r_dividend_yield"),
                    "per": row.get("r_per"),
                    "entry_plan": row.get("entry_plan"),
                }
            )

    return {
        "amount": amount,
        "years": years,
        "options": ranked,
        "best": best,
        "second": second,
        "target_allocation": target,
        "target_table": target_df,
        "portfolio_return": portfolio_return,
        "portfolio_volatility": portfolio_vol,
        "portfolio_sharpe": portfolio_sharpe,
        "stock_picks": stock_picks,
        "risk_score": profile.overall_risk_score(),
        "investor_type": profile.investor_type(),
    }


def narrative_recommendation(rec: Dict[str, Any], profile: Any) -> Dict[str, str]:
    """Texte argumenté expliquant la recommandation et le classement."""
    best = rec.get("best")
    second = rec.get("second")
    itype = rec.get("investor_type") or {}
    if not best:
        return {"title": "Données insuffisantes", "body": "Aucune option n'a pu être évaluée.", "color": "#8DA2C0"}

    lines: List[str] = []
    lines.append(
        f"Pour un profil **{itype.get('label', '—')}** (score de risque {rec['risk_score']:.0%}) "
        f"et un horizon de **{rec['years']} ans**, sur un montant de "
        f"**{rec['amount']:,.0f} MAD** :".replace(",", " ")
    )
    lines.append(
        f"• **Meilleure option : {best['Option']}** — score d'adéquation **{best['Score profil']:.0f}/100**, "
        f"rendement net estimé **{best['Rendement net']:.2%}** par an, "
        f"valeur nette finale **{best['Valeur nette finale']:,.0f} MAD** "
        f"({best['Rendement réel net']:.2%} en pouvoir d'achat constant)."
    )
    if second:
        lines.append(
            f"• **Alternative : {second['Option']}** — score **{second['Score profil']:.0f}/100**, "
            f"écart de valeur finale de **{(best['Valeur nette finale'] - second['Valeur nette finale']):,.0f} MAD** "
            f"sur l'horizon."
        )
    target_parts = []
    for _, row in rec["target_table"].iterrows():
        if row["Poids"] > 0.02:
            target_parts.append("{label} {poids:.0%}".format(
                label=row["Classe d'actifs"], poids=row["Poids"]
            ))
    lines.append("• **Allocation cible recommandée** : " + ", ".join(target_parts) + ".")
    lines.append(
        f"• **Portefeuille diversifié** attendu : {rec['portfolio_return']:.2%} brut par an pour une "
        f"volatilité estimée de {rec['portfolio_volatility']:.2%} "
        f"(Sharpe {rec['portfolio_sharpe']:.2f}).".replace("Sharpe nan", "Sharpe —")
    )
    lines.append(
        f"• Rappel fiscal : plus-values taxées à {CAPITAL_GAINS_TAX:.0%} (TPCVM), dividendes à "
        f"{DIVIDEND_TAX:.0%}. Frais de courtage estimés à {BROKERAGE_FEE:.2%} par aller-retour."
    )
    return {
        "title": f"Recommandation : {best['Option']}",
        "body": "\n\n".join(lines),
        "color": best.get("_color", "#22D3A6"),
    }


def holding_comparison(
    profile: Any,
    enriched: Optional[pd.DataFrame],
    market_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Compare chaque ligne détenue aux meilleures opportunités du marché."""
    if enriched is None or enriched.empty:
        return pd.DataFrame()
    rows = []
    for _, h in enriched.iterrows():
        symbol = str(h["symbol"])
        row = market_df[market_df["symbol"] == symbol] if market_df is not None and not market_df.empty else pd.DataFrame()
        m = row.iloc[0] if not row.empty else None
        opportunity = None
        if market_df is not None and not market_df.empty and "composite_score" in market_df.columns:
            pool = market_df[market_df["symbol"] != symbol]
            if not pool.empty:
                opportunity = pool.loc[pool["composite_score"].idxmax()] if pool["composite_score"].notna().any() else None
        rows.append(
            {
                "Symbole": symbol,
                "Société": h.get("name"),
                "Valeur (MAD)": h.get("value"),
                "Poids": h.get("weight"),
                "Plus-value": h.get("pnl_pct"),
                "Score composite": None if m is None else m.get("composite_score"),
                "Signal actuel": None if m is None else m.get("signal"),
                "Meilleure opportunité": None if opportunity is None else opportunity.get("symbol"),
                "Score meilleure": None if opportunity is None else opportunity.get("composite_score"),
                "Écart de score": (
                    None if (m is None or opportunity is None)
                    else (opportunity.get("composite_score") or 0) - (m.get("composite_score") or 0)
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("Écart de score", ascending=False, na_position="last").reset_index(drop=True)


def objective_plan(profile: Any, monthly: Optional[float] = None, years: Optional[int] = None) -> Dict[str, Any]:
    """Plan d'atteinte d'objectif patrimonial, comparé à plusieurs rendements."""
    monthly = float(monthly if monthly is not None else profile.monthly_investment)
    years = int(years if years is not None else profile.horizon_years)
    scenarios = {"Prudent (3 %)": 0.03, "Équilibré (6 %)": 0.06, "Dynamique (9 %)": 0.09, "Offensif (12 %)": 0.12}
    rows = []
    for label, rate in scenarios.items():
        fv = finance.future_value(profile.equities_value + profile.savings, monthly, rate, years)
        rows.append(
            {
                "Scénario": label,
                "Rendement annuel": rate,
                "Capital projeté": fv,
                "Objectif": profile.target_capital,
                "Écart": fv - profile.target_capital,
                "Atteint": fv >= profile.target_capital,
                "Versement nécessaire": finance.required_monthly(profile.target_capital,
                                                                 profile.equities_value + profile.savings, rate, years),
            }
        )
    return {"table": pd.DataFrame(rows), "monthly": monthly, "years": years}
