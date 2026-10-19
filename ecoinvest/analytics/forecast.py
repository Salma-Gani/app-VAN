"""Prévisions financières : projection de cash-flows, DCF, scénarios, Monte-Carlo."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..config import EQUITY_RISK_PREMIUM, RISK_FREE_RATE
from ..utils import finance
from ..utils.formatting import as_float, safe_div


def base_fcf(f: Dict[str, Any]) -> Optional[float]:
    """Détermine le FCF de départ : FCF déclaré, sinon CFO − Capex, sinon estimation."""
    fcf = as_float(f.get("fcf"))
    if fcf:
        return fcf
    ocf, capex = as_float(f.get("operating_cf")), as_float(f.get("capex"))
    if ocf is not None and capex is not None:
        return ocf - abs(capex)
    ebitda = as_float(f.get("ebitda"))
    if ebitda:
        return ebitda * 0.55  # approximation : EBITDA moins impôts, capex et variation du BFR
    net_income = as_float(f.get("net_income"))
    if net_income:
        return net_income * 1.15
    return None


def default_assumptions(f: Dict[str, Any], beta: Optional[float] = None) -> Dict[str, float]:
    """Hypothèses de valorisation par défaut, dérivées des données disponibles."""
    growth = as_float(f.get("fcf_growth")) or as_float(f.get("net_income_growth")) or as_float(f.get("revenue_growth")) or 0.05
    growth = float(max(-0.10, min(0.30, growth)))
    b = as_float(beta) or as_float(f.get("beta")) or 1.0
    cost_equity = RISK_FREE_RATE + float(b) * EQUITY_RISK_PREMIUM
    debt = as_float(f.get("total_debt")) or 0.0
    cash = as_float(f.get("cash")) or 0.0
    net_debt = debt - cash
    equity = as_float(f.get("equity")) or 0.0
    cap = as_float(f.get("market_cap"))
    if equity and debt:
        disc = finance.wacc(equity, debt, cost_equity, RISK_FREE_RATE + 0.025) or cost_equity
    else:
        disc = cost_equity
    return {
        "growth": growth,
        "growth_terminal": 0.02,
        "discount_rate": float(max(0.06, min(0.25, disc))),
        "net_debt": float(net_debt),
        "shares": as_float(f.get("shares")),
        "beta": float(b),
        "cost_of_equity": float(cost_equity),
        "market_cap": cap,
    }


def build_projection(
    fcf_start: float,
    growth: float,
    years: int = 5,
    terminal_growth: float = 0.02,
    fade: bool = True,
) -> List[float]:
    """Projette les FCF avec atténuation progressive de la croissance (fade)."""
    out: List[float] = []
    cur = float(fcf_start)
    for y in range(years):
        g = growth
        if fade and years > 1:
            # La croissance converge vers la croissance terminale
            weight = y / (years - 1)
            g = growth * (1 - weight) + terminal_growth * weight
        cur = cur * (1 + g)
        out.append(cur)
    return out


def valuation(
    f: Dict[str, Any],
    price: Optional[float] = None,
    assumptions: Optional[Dict[str, float]] = None,
    years: int = 5,
) -> Dict[str, Any]:
    """Valorisation DCF complète d'une entreprise à partir de sa fiche fondamentale."""
    fcf_start = base_fcf(f)
    if not fcf_start or fcf_start <= 0:
        return {
            "available": False,
            "reason": ("FCF non disponible : renseignez le Free Cash-Flow (ou le cash-flow "
                       "d'exploitation et les capex) dans l'onglet « Données fondamentales »."),
        }

    a = dict(default_assumptions(f, beta=as_float(f.get("beta"))))
    if assumptions:
        a.update({k: v for k, v in assumptions.items() if v is not None})

    projection = build_projection(
        fcf_start, a["growth"], years=years, terminal_growth=a["growth_terminal"]
    )
    res = finance.dcf(
        projection,
        discount_rate=a["discount_rate"],
        terminal_growth=a["growth_terminal"],
        net_debt=a["net_debt"],
        shares=a["shares"],
        mid_year=True,
    )

    share_price = res.get("price_per_share")
    mos = finance.margin_of_safety(share_price, price) if share_price else None
    per_share_equity = safe_div(res.get("equity_value"), a["shares"]) if a["shares"] else None

    return {
        "available": True,
        "fcf_start": fcf_start,
        "projection": projection,
        "assumptions": a,
        "enterprise_value": res.get("enterprise_value"),
        "equity_value": res.get("equity_value"),
        "fair_value": share_price,
        "fair_value_equity": per_share_equity,
        "price": price,
        "margin_of_safety": mos,
        "pv_explicit": res.get("pv_explicit"),
        "pv_terminal": res.get("pv_terminal"),
        "terminal_share": safe_div(res.get("pv_terminal"), res.get("enterprise_value")),
        "upside": safe_div((share_price - price), price) if (share_price and price) else None,
        "ev_ebitda_implied": None,
    }


def sensitivity_table(
    fcf_start: float,
    growth: float,
    discount_rates: Sequence[float],
    terminal_growths: Sequence[float],
    years: int = 5,
    net_debt: float = 0.0,
    shares: Optional[float] = None,
) -> pd.DataFrame:
    """Matrice de sensibilité du prix par action (taux d'actualisation × croissance terminale)."""
    rows = []
    for g in terminal_growths:
        row = {"g terminal": g}
        for r in discount_rates:
            projection = build_projection(fcf_start, growth, years=years, terminal_growth=g)
            res = finance.dcf(projection, discount_rate=r, terminal_growth=g,
                              net_debt=net_debt, shares=shares)
            row[r] = res.get("price_per_share")
        rows.append(row)
    df = pd.DataFrame(rows).set_index("g terminal")
    df.columns = [f"{c:.1%}" for c in df.columns]
    df.index = [f"{i:.1%}" for i in df.index]
    return df


def scenario_analysis(
    fcf_start: float,
    base_growth: float,
    discount_rate: float,
    net_debt: float,
    shares: Optional[float] = None,
    years: int = 5,
    terminal_growth: float = 0.02,
) -> pd.DataFrame:
    """Trois scénarios (pessimiste / base / optimiste) de valorisation."""
    scenarios = [
        ("Pessimiste", base_growth - 0.06, discount_rate + 0.02, terminal_growth - 0.005),
        ("Base", base_growth, discount_rate, terminal_growth),
        ("Optimiste", base_growth + 0.06, max(discount_rate - 0.015, 0.05), terminal_growth + 0.005),
    ]
    rows = []
    for name, g, r, tg in scenarios:
        projection = build_projection(fcf_start, g, years=years, terminal_growth=tg)
        res = finance.dcf(projection, discount_rate=r, terminal_growth=tg,
                          net_debt=net_debt, shares=shares)
        rows.append(
            {
                "Scénario": name,
                "Croissance FCF": g,
                "Taux d'actualisation": r,
                "Croissance terminale": tg,
                "Valeur des fonds propres": res.get("equity_value"),
                "Valeur par action": res.get("price_per_share"),
                "FCF année 1": projection[0] if projection else None,
                "FCF année finale": projection[-1] if projection else None,
            }
        )
    return pd.DataFrame(rows)


def monte_carlo_valuation(
    fcf_start: float,
    growth_mean: float,
    discount_rate: float,
    net_debt: float,
    shares: Optional[float] = None,
    years: int = 5,
    terminal_growth: float = 0.02,
    n_sims: int = 3000,
    price: Optional[float] = None,
    seed: int = 11,
    growth_sigma: float = 0.05,
    discount_sigma: float = 0.012,
) -> Dict[str, Any]:
    """Distribution Monte-Carlo de la valeur intrinsèque (croissance et taux incertains).

    Le tirage est reproductible (``seed``), ce qui rend les tests et la démonstration
    vérifiables. Chaque paramètre incertain est documenté dans ``assumptions``.
    """
    rng = np.random.default_rng(int(seed))
    growth = rng.normal(growth_mean, growth_sigma, size=(n_sims, years))
    growth = np.clip(growth, -0.25, 0.45)
    disc = np.clip(rng.normal(discount_rate, discount_sigma, size=(n_sims, 1)), 0.04, 0.30)
    tg = np.clip(rng.normal(terminal_growth, 0.005, size=(n_sims, 1)), 0.0, 0.04)

    fcf = np.zeros((n_sims, years))
    prev = np.full(n_sims, float(fcf_start))
    for y in range(years):
        prev = prev * (1 + growth[:, y])
        fcf[:, y] = prev

    t = np.arange(1, years + 1)
    pv_explicit = (fcf / (1 + disc) ** (t - 0.5)).sum(axis=1)
    tv = fcf[:, -1] * (1 + tg[:, 0]) / np.maximum(disc[:, 0] - tg[:, 0], 1e-4)
    pv_terminal = tv / (1 + disc[:, 0]) ** (years + 0.5)
    equity = pv_explicit + pv_terminal - float(net_debt or 0)
    per_share = equity / float(shares) if shares else equity

    out: Dict[str, Any] = {
        "available": True,
        "median": float(np.median(per_share)),
        "mean": float(np.mean(per_share)),
        "p5": float(np.percentile(per_share, 5)),
        "p10": float(np.percentile(per_share, 10)),
        "p25": float(np.percentile(per_share, 25)),
        "p50": float(np.percentile(per_share, 50)),
        "p75": float(np.percentile(per_share, 75)),
        "p90": float(np.percentile(per_share, 90)),
        "p95": float(np.percentile(per_share, 95)),
        "values": per_share,
        "prob_undervalued": None,
        "seed": int(seed),
        "n_sims": int(n_sims),
        "assumptions": {
            "model": "DCF : croissance et taux d'actualisation tirés (loi normale)",
            "fcf_start": float(fcf_start),
            "growth_mean": float(growth_mean),
            "growth_sigma": float(growth_sigma),
            "discount_rate": float(discount_rate),
            "discount_sigma": float(discount_sigma),
            "terminal_growth": float(terminal_growth),
            "years": int(years),
            "n_sims": int(n_sims),
            "seed": int(seed),
        },
    }
    if price:
        out["prob_undervalued"] = float((per_share > price).mean())
        out["expected_upside"] = float(np.median(per_share) / price - 1)
    return out


# ═══════════════════════════ Trajectoires de prix ═══════════════════════════

TRADING_DAYS = 252
MIN_MC_OBSERVATIONS = 60


def price_monte_carlo(
    prices: Any,
    horizon_days: int = 252,
    n_sims: int = 2000,
    seed: int = 7,
    drift: Optional[float] = None,
    volatility: Optional[float] = None,
    sample_paths: int = 60,
) -> Dict[str, Any]:
    """Trajectoires de cours simulées par mouvement brownien géométrique (GBM).

    Le modèle est calibré sur les rendements log réels de l'historique fourni :
    dérive et volatilité annualisées (252 séances). La simulation est reproductible
    (``seed``) et toutes les hypothèses sont renvoyées pour affichage. Aucun prix
    n'est inventé : le point de départ est la dernière clôture observée.
    """
    series = pd.Series(prices).astype(float).dropna()
    series = series[series > 0]
    n = int(len(series))
    if n < MIN_MC_OBSERVATIONS:
        return {"available": False,
                "reason": f"Historique insuffisant ({n} séances, minimum {MIN_MC_OBSERVATIONS}) "
                          f"pour calibrer un modèle de prix."}

    horizon_days = max(int(horizon_days), 1)
    n_sims = max(int(n_sims), 1)
    log_returns = np.log(series / series.shift(1)).dropna()
    estimated_drift = float(log_returns.mean()) * TRADING_DAYS
    estimated_vol = float(log_returns.std(ddof=1)) * float(np.sqrt(TRADING_DAYS))
    mu = float(drift) if drift is not None else estimated_drift
    sigma = float(volatility) if volatility is not None else estimated_vol
    sigma = max(sigma, 1e-6)

    dt = 1.0 / TRADING_DAYS
    rng = np.random.default_rng(int(seed))
    shocks = rng.normal((mu - 0.5 * sigma ** 2) * dt, sigma * float(np.sqrt(dt)),
                        size=(n_sims, horizon_days))
    start = float(series.iloc[-1])
    paths = start * np.exp(np.cumsum(shocks, axis=1))
    paths = np.concatenate([np.full((n_sims, 1), start), paths], axis=1)

    percentiles = {f"p{p}": np.percentile(paths, p, axis=0) for p in (5, 25, 50, 75, 95)}
    final = paths[:, -1]
    return {
        "available": True,
        "model": "Mouvement brownien géométrique (GBM)",
        "start": start,
        "horizon_days": horizon_days,
        "n_sims": n_sims,
        "seed": int(seed),
        "drift_annual": mu,
        "volatility_annual": sigma,
        "estimated_drift": estimated_drift,
        "estimated_volatility": estimated_vol,
        "drift_source": "paramètre utilisateur" if drift is not None else "estimé sur l'historique",
        "volatility_source": "paramètre utilisateur" if volatility is not None else "estimée sur l'historique",
        "observations": n,
        "period_start": series.index[0] if isinstance(series.index, pd.DatetimeIndex) else None,
        "period_end": series.index[-1] if isinstance(series.index, pd.DatetimeIndex) else None,
        "percentiles": percentiles,
        "sample": paths[:max(int(sample_paths), 0)],
        "final": final,
        "median_final": float(np.median(final)),
        "p5_final": float(np.percentile(final, 5)),
        "p95_final": float(np.percentile(final, 95)),
        "prob_above": float((final > start).mean()),
        "prob_below": float((final < start).mean()),
        "expected_return": float(np.median(final) / start - 1) if start else None,
    }


# ═══════════════════════════ Simulation de portefeuille ═══════════════════════════


def portfolio_fan_chart(
    initial: float,
    monthly: float,
    expected_return: float,
    volatility: float,
    years: int = 10,
    n_sims: int = 2000,
    seed: int = 3,
) -> Dict[str, Any]:
    """Trajectoires Monte-Carlo d'un portefeuille (éventail de percentiles)."""
    rng = np.random.default_rng(seed)
    months = years * 12
    monthly_mu = (1 + expected_return) ** (1 / 12) - 1
    monthly_sigma = volatility / np.sqrt(12)

    shocks = rng.normal(monthly_mu, monthly_sigma, size=(n_sims, months))
    paths = np.zeros((n_sims, months + 1))
    paths[:, 0] = float(initial)
    for m in range(months):
        paths[:, m + 1] = paths[:, m] * (1 + shocks[:, m]) + float(monthly)
    # Croissance composée du versement (approximation discrète mensuelle)

    percentiles = {
        "p5": np.percentile(paths, 5, axis=0),
        "p10": np.percentile(paths, 10, axis=0),
        "p25": np.percentile(paths, 25, axis=0),
        "p50": np.percentile(paths, 50, axis=0),
        "p75": np.percentile(paths, 75, axis=0),
        "p90": np.percentile(paths, 90, axis=0),
        "p95": np.percentile(paths, 95, axis=0),
    }
    invested = np.array([float(initial) + float(monthly) * m for m in range(months + 1)])
    return {
        "months": np.arange(months + 1),
        "percentiles": percentiles,
        "invested": invested,
        "final": paths[:, -1],
        "final_median": float(np.median(paths[:, -1])),
        "final_p5": float(np.percentile(paths[:, -1], 5)),
        "final_p10": float(np.percentile(paths[:, -1], 10)),
        "final_p90": float(np.percentile(paths[:, -1], 90)),
        "final_p95": float(np.percentile(paths[:, -1], 95)),
        "total_invested": float(invested[-1]),
        "prob_loss": float((paths[:, -1] < invested[-1]).mean()),
        "prob_target": None,
    }


def projection_table(
    initial: float,
    monthly: float,
    annual_return: float,
    years: int = 10,
    inflation: float = 0.02,
) -> pd.DataFrame:
    """Tableau de projection annuelle : capital, versements cumulés, gain, valeur réelle."""
    rows = []
    total_invested = float(initial)
    for y in range(1, years + 1):
        total_invested += float(monthly) * 12
        fv = finance.future_value(initial, monthly, annual_return, y)
        gain = fv - total_invested
        rows.append(
            {
                "Année": y,
                "Capital projeté": fv,
                "Versements cumulés": total_invested,
                "Plus-value latente": gain,
                "Valeur en dirhams constants": fv / (1 + inflation) ** y,
                "Rendement cumulé": safe_div(gain, total_invested),
            }
        )
    return pd.DataFrame(rows)


def income_projection(
    capital: float,
    monthly_contribution: float,
    annual_return: float,
    years: int,
    target_income: float,
    withdrawal_rate: float = 0.04,
) -> Dict[str, Any]:
    """Rente future générée par le capital accumulé."""
    fv = finance.future_value(capital, monthly_contribution, annual_return, years)
    annual_income = fv * withdrawal_rate
    return {
        "capital_final": fv,
        "revenu_annuel": annual_income,
        "revenu_mensuel": annual_income / 12,
        "taux_retrait": withdrawal_rate,
        "atteint": annual_income >= target_income if target_income else None,
        "ecart": (annual_income - target_income) if target_income else None,
        "capital_necessaire": safe_div(target_income, withdrawal_rate) if target_income else None,
    }


def goal_gap(
    target_capital: float,
    current_capital: float,
    monthly: float,
    annual_return: float,
    years: int,
) -> Dict[str, Any]:
    """Écart à l'objectif patrimonial et versement nécessaire pour le combler."""
    fv = finance.future_value(current_capital, monthly, annual_return, years)
    required = finance.required_monthly(target_capital, current_capital, annual_return, years)
    return {
        "capital_projete": fv,
        "objectif": target_capital,
        "ecart": fv - target_capital,
        "atteint": fv >= target_capital,
        "versement_necessaire": required,
        "effort_supplementaire": (required - monthly) if required is not None else None,
    }
