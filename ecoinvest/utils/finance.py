"""Mathématiques financières : actualisation, TRI/XIRR, DCF, CAPM, WACC.

Toutes les fonctions sont pures (sans dépendance Streamlit) et testables.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# ═══════════════════════════ Actualisation ═══════════════════════════


def van(invest: float, cashflows: Sequence[float], taux: float) -> float:
    """Valeur Actuelle Nette : −I₀ + Σ CFₜ/(1+r)ᵗ."""
    cf = np.asarray(cashflows, dtype=float)
    if cf.size == 0:
        return float(-invest)
    t = np.arange(1, cf.size + 1)
    return float(-invest + np.sum(cf / (1.0 + taux) ** t))


def npv(taux: float, cashflows: Sequence[float], invest: float = 0.0) -> float:
    return van(invest, cashflows, taux)


def tri(invest: float, cashflows: Sequence[float]) -> Optional[float]:
    """Taux de Rendement Interne par bissection sur [−99,99 % ; +1000 %]."""
    if not cashflows:
        return None

    def f(r: float) -> float:
        if r <= -1:
            return float("inf")
        t = np.arange(1, len(cashflows) + 1)
        return float(-invest + np.sum(np.asarray(cashflows, dtype=float) / (1 + r) ** t))

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < 1e-7:
            return float(mid)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return float((lo + hi) / 2.0)


def xirr(cashflows_par_date: Sequence[Tuple[object, float]], guess: float = 0.1) -> Optional[float]:
    """TRI d'un flux irrégulier (dates quelconques), par Newton + repli bissection."""
    if len(cashflows_par_date) < 2:
        return None
    try:
        import pandas as pd

        dates = pd.to_datetime([d for d, _ in cashflows_par_date])
        amounts = np.asarray([a for _, a in cashflows_par_date], dtype=float)
        t0 = dates[0]
        years = np.asarray([(d - t0).days / 365.25 for d in dates], dtype=float)
    except Exception:
        return None

    def f(r: float) -> float:
        if r <= -1:
            return 1e18
        return float(np.sum(amounts / (1.0 + r) ** years))

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < 1e-6:
            return float(mid)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return float((lo + hi) / 2.0)


def payback(invest: float, cashflows: Sequence[float], taux: Optional[float] = None) -> Tuple[Optional[float], List[float]]:
    """Délai de récupération (années) et cumul. `taux=None` -> payback simple."""
    cumul: List[float] = []
    cum = float(-invest)
    for i, cf in enumerate(cashflows, start=1):
        v = float(cf) if taux is None else float(cf) / (1.0 + taux) ** i
        prev = cum
        cum += v
        cumul.append(cum)
        if cum >= 0 and v != 0:
            frac = (0.0 - prev) / v
            return (i - 1 + frac, cumul)
    return (None, cumul)


def flux_actualises(cashflows: Sequence[float], taux: float) -> List[float]:
    return [float(cf) / (1.0 + taux) ** i for i, cf in enumerate(cashflows, start=1)]


def cagr(start: Optional[float], end: Optional[float], years: float) -> Optional[float]:
    """Taux de croissance annuel composé."""
    try:
        if not start or not end or years <= 0 or float(start) <= 0 or float(end) <= 0:
            return None
        return float((float(end) / float(start)) ** (1.0 / years) - 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def moic(invested: float, value: float) -> Optional[float]:
    """Multiple sur capital investi."""
    if not invested:
        return None
    return float(value) / float(invested)


# ═══════════════════════════ Coût du capital ═══════════════════════════


def capm_cost_of_equity(
    risk_free: float,
    beta: float,
    equity_risk_premium: float,
) -> float:
    """Modèle d'évaluation des actifs financiers : Rf + β × PRM."""
    return float(risk_free + float(beta) * equity_risk_premium)


def wacc(
    equity_value: float,
    debt_value: float,
    cost_of_equity: float,
    cost_of_debt: float,
    tax_rate: float = 0.20,
) -> Optional[float]:
    """Coût moyen pondéré du capital."""
    v = float(equity_value or 0) + float(debt_value or 0)
    if v <= 0:
        return None
    we, wd = float(equity_value or 0) / v, float(debt_value or 0) / v
    return float(we * cost_of_equity + wd * cost_of_debt * (1 - tax_rate))


# ═══════════════════════════ Valorisation ═══════════════════════════


def dcf(
    fcf_forecast: Sequence[float],
    discount_rate: float,
    terminal_growth: float = 0.02,
    net_debt: float = 0.0,
    shares: Optional[float] = None,
    mid_year: bool = True,
) -> Dict[str, Optional[float]]:
    """Flux de trésorerie disponibles actualisés + valeur terminale (Gordon-Shapiro).

    Retourne la valeur d'entreprise, la valeur des fonds propres et le prix par action.
    """
    fcf = np.asarray(fcf_forecast, dtype=float)
    n = fcf.size
    if n == 0 or discount_rate is None:
        return {"enterprise_value": None, "equity_value": None, "price_per_share": None,
                "pv_explicit": None, "pv_terminal": None, "terminal_value": None}

    t = np.arange(1, n + 1)
    discount = 1.0 / (1.0 + discount_rate) ** (t - (0.5 if mid_year else 0.0))
    pv_explicit = float(np.sum(fcf * discount))

    tv: Optional[float] = None
    pv_terminal: Optional[float] = None
    if discount_rate > terminal_growth:
        tv = float(fcf[-1] * (1.0 + terminal_growth) / (discount_rate - terminal_growth))
        expo = n + (0.5 if mid_year else 0.0)
        pv_terminal = float(tv / (1.0 + discount_rate) ** expo)

    ev = pv_explicit + (pv_terminal or 0.0)
    equity = ev - float(net_debt or 0.0)
    price = (equity / float(shares)) if shares else None
    return {
        "enterprise_value": ev,
        "equity_value": equity,
        "price_per_share": price,
        "pv_explicit": pv_explicit,
        "pv_terminal": pv_terminal,
        "terminal_value": tv,
    }


def ddm_next(dividend_next: float, discount_rate: float, growth: float) -> Optional[float]:
    """Modèle de Gordon-Shapiro appliqué aux dividendes."""
    if discount_rate <= growth:
        return None
    return float(dividend_next / (discount_rate - growth))


def graham_value(eps: float, growth: float = 0.0, aaa_yield: float = 0.05) -> Optional[float]:
    """Formule de Benjamin Graham : V = EPS × (8,5 + 2g) × 4,4 / Y."""
    try:
        return float(float(eps) * (8.5 + 2 * float(growth) * 100) * 4.4 / (float(aaa_yield) * 100))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def margin_of_safety(fair_value: Optional[float], price: Optional[float]) -> Optional[float]:
    """Marge de sécurité = (valeur − prix) / valeur."""
    try:
        if not fair_value or price is None:
            return None
        return float((float(fair_value) - float(price)) / float(fair_value))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def monte_carlo_dcf(
    fcf_base: float,
    growth_mean: float,
    growth_std: float,
    margin_std: float,
    discount_rate: float,
    terminal_growth: float,
    years: int = 5,
    n_sims: int = 2000,
    shares: Optional[float] = None,
    net_debt: float = 0.0,
    seed: int = 7,
) -> Dict[str, object]:
    """Simulation Monte-Carlo d'une valorisation DCF (croissance et marge aléatoires)."""
    rng = np.random.default_rng(seed)
    growth = rng.normal(growth_mean, max(growth_std, 1e-4), size=(n_sims, years))
    margins = rng.normal(1.0, max(margin_std, 1e-4), size=(n_sims, years))
    fcf = np.zeros((n_sims, years))
    prev = np.full(n_sims, float(fcf_base))
    for y in range(years):
        prev = prev * (1.0 + growth[:, y]) * margins[:, y]
        fcf[:, y] = prev
    t = np.arange(1, years + 1)
    disc = 1.0 / (1.0 + discount_rate) ** (t - 0.5)
    pv_explicit = (fcf * disc).sum(axis=1)
    tv = fcf[:, -1] * (1.0 + terminal_growth) / max(discount_rate - terminal_growth, 1e-4)
    pv_terminal = tv / (1.0 + discount_rate) ** (years + 0.5)
    ev = pv_explicit + pv_terminal
    equity = ev - float(net_debt or 0.0)
    per_share = (equity / float(shares)) if shares else equity
    return {
        "values": per_share,
        "p10": float(np.percentile(per_share, 10)),
        "p25": float(np.percentile(per_share, 25)),
        "median": float(np.percentile(per_share, 50)),
        "p75": float(np.percentile(per_share, 75)),
        "p90": float(np.percentile(per_share, 90)),
        "mean": float(np.mean(per_share)),
        "prob_undervalued": None,
    }


def perpetuity_growth(current: float, growth: float, years: int) -> float:
    """Projette une grandeur à un taux de croissance constant."""
    return float(current) * (1.0 + float(growth)) ** int(years)


def build_fcf_forecast(
    fcf_base: float,
    growth_rates: Sequence[float],
    margin_adjustments: Optional[Sequence[float]] = None,
) -> List[float]:
    """Construit une projection de FCF à partir de taux de croissance annuels."""
    out: List[float] = []
    cur = float(fcf_base)
    for i, g in enumerate(growth_rates):
        m = 1.0 if not margin_adjustments else float(margin_adjustments[i])
        cur = cur * (1.0 + float(g)) * m
        out.append(cur)
    return out


def future_value(initial: float, monthly: float, annual_return: float, years: float) -> float:
    """Capitalisation d'un versement initial + versements mensuels."""
    months = int(round(years * 12))
    r = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0 if annual_return > -1 else 0.0
    fv_init = float(initial) * (1.0 + r) ** months
    if abs(r) < 1e-12:
        return fv_init + float(monthly) * months
    fv_contrib = float(monthly) * (((1.0 + r) ** months - 1.0) / r)
    return float(fv_init + fv_contrib)


def required_monthly(target: float, initial: float, annual_return: float, years: float) -> Optional[float]:
    """Versement mensuel nécessaire pour atteindre un objectif de capital."""
    months = int(round(years * 12))
    if months <= 0:
        return None
    r = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0 if annual_return > -1 else 0.0
    gap = float(target) - float(initial) * (1.0 + r) ** months
    if gap <= 0:
        return 0.0
    if abs(r) < 1e-12:
        return gap / months
    return float(gap * r / ((1.0 + r) ** months - 1.0))


def irr_scenarios(
    invest: float,
    base_cashflows: Sequence[float],
    shock: float,
    taux: float,
) -> Dict[str, float]:
    """VAN en scénarios pessimiste / base / optimiste."""
    pes = [c * (1 - shock) for c in base_cashflows]
    opt = [c * (1 + shock) for c in base_cashflows]
    return {
        "van_pessimiste": van(invest, pes, taux),
        "van_base": van(invest, base_cashflows, taux),
        "van_optimiste": van(invest, opt, taux),
    }


def bond_price(
    face: float,
    coupon_rate: float,
    ytm: float,
    years: float,
    freq: int = 1,
) -> float:
    """Prix d'une obligation à coupons constants."""
    n = int(round(years * freq))
    c = face * coupon_rate / freq
    r = ytm / freq
    if r <= -1 or n <= 0:
        return float("nan")
    pv_coupons = sum(c / (1 + r) ** k for k in range(1, n + 1))
    pv_face = face / (1 + r) ** n
    return float(pv_coupons + pv_face)


def real_estate_yield(annual_rent: float, price: float, charges_rate: float = 0.20) -> Optional[float]:
    """Rendement locatif net d'un bien."""
    if not price:
        return None
    return float(annual_rent * (1 - charges_rate) / price)


def annualize_return(returns: Iterable[float], periods_per_year: int = 252) -> Optional[float]:
    r = np.asarray(list(returns), dtype=float)
    if r.size == 0:
        return None
    growth = float(np.prod(1.0 + r))
    if growth <= 0:
        return None
    return float(growth ** (periods_per_year / r.size) - 1.0)
