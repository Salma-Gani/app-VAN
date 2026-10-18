"""Profil de l'investisseur : revenus, patrimoine, capacité et tolérance au risque."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..config import (
    CAPITAL_GAINS_TAX,
    DIVIDEND_TAX,
    INFLATION_RATE,
    USER_PROFILE_FILE,
)
from ..utils.formatting import as_float, safe_div

NS = "profile"

DEFAULT_HOLDINGS: List[Dict[str, Any]] = []


@dataclass
class InvestorProfile:
    """Profil patrimonial complet de l'utilisateur."""

    # Revenus
    salary_monthly: float = 12000.0
    other_income_monthly: float = 0.0
    bonus_annual: float = 0.0
    # Charges
    monthly_expenses: float = 7000.0
    rent_monthly: float = 0.0
    loan_monthly: float = 0.0
    # Situation
    age: int = 35
    dependents: int = 0
    horizon_years: int = 10
    # Patrimoine
    cash: float = 30000.0
    savings: float = 50000.0
    equities_value: float = 60000.0
    real_estate_value: float = 0.0
    real_estate_debt: float = 0.0
    other_assets: float = 0.0
    consumer_debt: float = 0.0
    # Objectifs
    target_capital: float = 1_000_000.0
    target_monthly_income: float = 8000.0
    # Comportement
    risk_tolerance: int = 3          # 1 = très prudent … 5 = très offensif
    experience: int = 2              # 1 = débutant … 5 = expert
    max_acceptable_drawdown: float = 0.20
    monthly_investment: float = 2000.0
    holdings: List[Dict[str, Any]] = field(default_factory=list)

    # ─────────── Dérivés ───────────
    @property
    def monthly_income(self) -> float:
        return float(self.salary_monthly) + float(self.other_income_monthly) + float(self.bonus_annual) / 12.0

    @property
    def monthly_charges(self) -> float:
        return float(self.monthly_expenses) + float(self.rent_monthly) + float(self.loan_monthly)

    @property
    def savings_capacity(self) -> float:
        return max(0.0, self.monthly_income - self.monthly_charges)

    @property
    def savings_rate(self) -> Optional[float]:
        return safe_div(self.savings_capacity, self.monthly_income)

    @property
    def financial_assets(self) -> float:
        return float(self.cash) + float(self.savings) + float(self.equities_value) + float(self.other_assets)

    @property
    def gross_assets(self) -> float:
        return self.financial_assets + float(self.real_estate_value)

    @property
    def total_debt(self) -> float:
        return float(self.real_estate_debt) + float(self.consumer_debt)

    @property
    def net_worth(self) -> float:
        return self.gross_assets - self.total_debt

    @property
    def debt_ratio(self) -> Optional[float]:
        """Taux d'endettement mensuel (charges de dette / revenu)."""
        return safe_div(float(self.loan_monthly), self.monthly_income)

    @property
    def emergency_months(self) -> Optional[float]:
        return safe_div(float(self.cash) + float(self.savings), self.monthly_charges)

    @property
    def equity_share(self) -> Optional[float]:
        return safe_div(self.equities_value, self.financial_assets)

    # ─────────── Scores ───────────
    def risk_capacity_score(self) -> float:
        """Capacité *objective* de prise de risque (0–1), indépendante des préférences."""
        parts: List[Tuple[float, float]] = []
        horizon = max(1, int(self.horizon_years))
        parts.append((min(horizon / 20.0, 1.0), 0.30))
        if self.emergency_months is not None:
            parts.append((min(self.emergency_months / 9.0, 1.0), 0.25))
        if self.savings_rate is not None:
            parts.append((min(max(self.savings_rate, 0) / 0.35, 1.0), 0.20))
        if self.debt_ratio is not None:
            parts.append((1.0 - min(self.debt_ratio / 0.40, 1.0), 0.15))
        age_factor = 1.0 - min(max((self.age - 25) / 40.0, 0.0), 1.0)
        parts.append((age_factor, 0.10))
        total_w = sum(w for _, w in parts)
        return float(sum(p * w for p, w in parts) / total_w) if total_w else 0.5

    def risk_tolerance_score(self) -> float:
        """Tolérance *psychologique* déclarée (0–1)."""
        tol = min(max(int(self.risk_tolerance), 1), 5) / 5.0
        exp = min(max(int(self.experience), 1), 5) / 5.0
        dd = 1.0 - min(max(float(self.max_acceptable_drawdown), 0.02), 0.60) / 0.60
        return float(0.5 * tol + 0.25 * exp + 0.25 * (1 - dd))

    def overall_risk_score(self) -> float:
        """Score de risque global = min(capacité, tolérance) — la contrainte la plus stricte."""
        return float(min(self.risk_capacity_score(), self.risk_tolerance_score()))

    def investor_type(self) -> Dict[str, str]:
        s = self.overall_risk_score()
        if s < 0.25:
            return {"label": "Prudent / défensif", "color": "#5B8DEF",
                    "desc": "Priorité à la préservation du capital. Volatilité faible acceptée uniquement."}
        if s < 0.45:
            return {"label": "Modéré", "color": "#22D3A6",
                    "desc": "Équilibre entre revenu et croissance, avec une exposition actions limitée."}
        if s < 0.68:
            return {"label": "Équilibré / dynamique", "color": "#22D3A6",
                    "desc": "Exposition actions majoritaire, tolérance aux corrections temporaires."}
        if s < 0.85:
            return {"label": "Offensif", "color": "#F5B547",
                    "desc": "Recherche de performance, accepte des drawdowns significatifs."}
        return {"label": "Très offensif", "color": "#F45B69",
                "desc": "Recherche de rendement maximal, forte tolérance à la volatilité."}

    def recommended_equity_share(self) -> float:
        """Part actions recommandée, dérivée du score de risque global."""
        return float(0.15 + 0.70 * self.overall_risk_score())

    def diagnostics(self) -> List[Dict[str, str]]:
        """Alertes et conseils sur la situation patrimoniale."""
        out: List[Dict[str, str]] = []
        em = self.emergency_months
        if em is None:
            pass
        elif em < 3:
            out.append({"level": "danger", "title": "Épargne de précaution insuffisante",
                        "text": f"Vous disposez de {em:.1f} mois de charges en liquidités. "
                                "Constituez 3 à 6 mois de charges avant d'investir en actions."})
        elif em < 6:
            out.append({"level": "warn", "title": "Épargne de précaution à renforcer",
                        "text": f"{em:.1f} mois de charges couverts. Visez 6 mois."})
        else:
            out.append({"level": "good", "title": "Sécurité financière solide",
                        "text": f"{em:.1f} mois de charges en épargne de précaution."})

        dr = self.debt_ratio
        if dr is not None and dr > 0.35:
            out.append({"level": "danger", "title": "Endettement élevé",
                        "text": f"Vos mensualités de crédit représentent {dr:.0%} de votre revenu. "
                                "Au-delà de 35 %, la capacité d'investissement est fragilisée."})
        elif dr is not None and dr > 0.20:
            out.append({"level": "warn", "title": "Endettement modéré",
                        "text": f"Mensualités à {dr:.0%} du revenu : restez vigilant avant d'augmenter le levier."})

        sr = self.savings_rate
        if sr is not None:
            if sr < 0.10:
                out.append({"level": "warn", "title": "Taux d'épargne faible",
                            "text": f"Vous épargnez {sr:.0%} de vos revenus. Viser 15–20 % accélère "
                                    "significativement la constitution du patrimoine."})
            else:
                out.append({"level": "good", "title": "Taux d'épargne satisfaisant",
                            "text": f"{sr:.0%} de vos revenus épargnés — moteur principal de votre patrimoine futur."})

        es = self.equity_share
        rec = self.recommended_equity_share()
        if es is not None:
            if es < rec - 0.20:
                out.append({"level": "info", "title": "Exposition actions inférieure au profil",
                            "text": f"{es:.0%} en actions contre {rec:.0%} recommandé : potentiel de "
                                    "rendement sous-exploité sur votre horizon."})
            elif es > rec + 0.25:
                out.append({"level": "warn", "title": "Exposition actions supérieure au profil",
                            "text": f"{es:.0%} en actions contre {rec:.0%} recommandé : risque de "
                                    "drawdown supérieur à votre tolérance déclarée."})
        if self.horizon_years < 5:
            out.append({"level": "warn", "title": "Horizon court",
                        "text": "Avec moins de 5 ans d'horizon, privilégiez les supports peu volatils : "
                                "le risque de devoir vendre au mauvais moment augmente."})
        return out

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_profile() -> InvestorProfile:
    try:
        with open(USER_PROFILE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return InvestorProfile()
    fields = set(InvestorProfile.__dataclass_fields__.keys())  # type: ignore[attr-defined]
    clean = {k: v for k, v in (data or {}).items() if k in fields}
    try:
        return InvestorProfile(**clean)
    except TypeError:
        return InvestorProfile()


def save_profile(profile: InvestorProfile) -> None:
    with open(USER_PROFILE_FILE, "w", encoding="utf-8") as fh:
        json.dump(profile.to_dict(), fh, ensure_ascii=False, indent=1)


# ═══════════════════════════ Portefeuille détenu ═══════════════════════════

def holdings_frame(profile: InvestorProfile) -> pd.DataFrame:
    df = pd.DataFrame(profile.holdings or DEFAULT_HOLDINGS)
    if df.empty:
        return pd.DataFrame(columns=["symbol", "name", "quantity", "purchase_price", "purchase_date"])
    for col in ("quantity", "purchase_price"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def enrich_holdings(profile: InvestorProfile, market_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Valorise le portefeuille détenu aux cours du marché et calcule les plus-values."""
    df = holdings_frame(profile)
    if df.empty:
        return df
    if market_df is None:
        from ..data import bvc

        market_df = bvc.snapshot()

    prices = dict(zip(market_df["symbol"], market_df["close"])) if not market_df.empty else {}
    names = dict(zip(market_df["symbol"], market_df["name"])) if not market_df.empty else {}
    sectors = dict(zip(market_df["symbol"], market_df["sector"])) if not market_df.empty else {}

    rows = []
    for _, h in df.iterrows():
        symbol = str(h.get("symbol") or "").strip().upper()
        qty = as_float(h.get("quantity")) or 0.0
        ppr = as_float(h.get("purchase_price")) or 0.0
        price = as_float(prices.get(symbol)) or ppr
        cost = qty * ppr
        value = qty * price
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol) or h.get("name") or symbol,
                "sector": sectors.get(symbol) or "Autres",
                "quantity": qty,
                "purchase_price": ppr,
                "price": price,
                "cost": cost,
                "value": value,
                "pnl": value - cost,
                "pnl_pct": safe_div(value - cost, cost),
                "weight": None,
                "purchase_date": h.get("purchase_date"),
            }
        )
    out = pd.DataFrame(rows)
    total = out["value"].sum()
    if total:
        out["weight"] = out["value"] / total
    return out.sort_values("value", ascending=False).reset_index(drop=True)


def portfolio_summary(enriched: pd.DataFrame, profile: InvestorProfile) -> Dict[str, Any]:
    """Synthèse chiffrée du portefeuille détenu."""
    if enriched is None or enriched.empty:
        return {
            "value": 0.0, "cost": 0.0, "pnl": 0.0, "pnl_pct": None,
            "positions": 0, "sectors": 0, "best": None, "worst": None,
            "concentration": None, "herfindahl": None,
        }
    total_value = float(enriched["value"].sum())
    total_cost = float(enriched["cost"].sum())
    weights = enriched["weight"].fillna(0)
    return {
        "value": total_value,
        "cost": total_cost,
        "pnl": total_value - total_cost,
        "pnl_pct": safe_div(total_value - total_cost, total_cost),
        "positions": int(len(enriched)),
        "sectors": int(enriched["sector"].nunique()),
        "best": enriched.loc[enriched["pnl_pct"].idxmax()].to_dict() if enriched["pnl_pct"].notna().any() else None,
        "worst": enriched.loc[enriched["pnl_pct"].idxmin()].to_dict() if enriched["pnl_pct"].notna().any() else None,
        "concentration": float(weights.max()) if not weights.empty else None,
        "herfindahl": float((weights ** 2).sum()) if not weights.empty else None,
        "taxes_latentes": float(max(total_value - total_cost, 0) * CAPITAL_GAINS_TAX),
    }


def net_income_after_tax(gross_income: float, is_dividend: bool = False) -> float:
    """Rendement net d'impôt (TPCVM sur plus-values, retenue sur dividendes)."""
    rate = DIVIDEND_TAX if is_dividend else CAPITAL_GAINS_TAX
    return float(gross_income * (1 - rate))


def real_return(nominal: float, inflation: float = INFLATION_RATE) -> float:
    """Rendement réel (pouvoir d'achat) à partir d'un rendement nominal."""
    return float((1 + nominal) / (1 + inflation) - 1)
