"""Formatage des nombres, montants et pourcentages (conventions marocaines)."""
from __future__ import annotations

from typing import Any, Optional

from ..config import CURRENCIES, FX_FALLBACK


def _clean(x: str) -> str:
    return x.replace("\u202f", " ").replace("\xa0", " ")


def fmt_num(x: Optional[float], decimals: int = 2, suffix: str = "") -> str:
    """Nombre formaté à la française : « 1 234 567,89 »."""
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:  # NaN
        return "—"
    s = f"{v:,.{decimals}f}"
    return _clean(s).replace(",", "\u00a0").replace(".", ",") + suffix


def fmt_money(
    x: Optional[float],
    currency: str = "MAD",
    decimals: int = 2,
    compact: bool = False,
) -> str:
    """Montant monétaire avec séparateurs français."""
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    sign = "-" if v < 0 else ""
    av = abs(v)
    if compact:
        for limit, unit in ((1e12, "T"), (1e9, "Md"), (1e6, "M"), (1e3, "k")):
            if av >= limit:
                return f"{sign}{fmt_num(av / limit, 2)} {unit} {currency}"
    return f"{sign}{fmt_num(av, decimals)} {currency}"


def fmt_pct(x: Optional[float], decimals: int = 2, signed: bool = False) -> str:
    """Pourcentage. `x` est attendu en fraction (0.12 -> 12,00 %)."""
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    out = f"{v * 100:+.{decimals}f} %" if signed else f"{v * 100:.{decimals}f} %"
    return out.replace(".", ",")


def fmt_multiple(x: Optional[float], decimals: int = 2, suffix: str = "x") -> str:
    """Multiple (P/E, P/B, EV/EBITDA…)."""
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v or v <= 0:
        return "n.s."
    return f"{v:.{decimals}f}{suffix}".replace(".", ",")


def fmt_signed(x: Optional[float], decimals: int = 2, suffix: str = "") -> str:
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    return f"{v:+.{decimals}f}{suffix}".replace(".", ",")


def fmt_compact_num(x: Optional[float]) -> str:
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    a = abs(v)
    for limit, unit in ((1e9, "Md"), (1e6, "M"), (1e3, "k")):
        if a >= limit:
            return fmt_num(v / limit, 1) + " " + unit
    return fmt_num(v, 0)


def fmt_volume(x: Optional[float]) -> str:
    return fmt_compact_num(x)


def convert_from_mad(amount: Optional[float], currency: str, fx_mad_per_unit: Optional[dict] = None) -> Optional[float]:
    """Convertit un montant en MAD vers la devise cible."""
    if amount is None:
        return None
    if currency == "MAD":
        return float(amount)
    rates = dict(FX_FALLBACK)
    if fx_mad_per_unit:
        rates.update({k: v for k, v in fx_mad_per_unit.items() if v})
    rate = rates.get(currency)
    if not rate:
        return float(amount)
    return float(amount) / float(rate)


def convert_to_mad(amount: Optional[float], currency: str, fx_mad_per_unit: Optional[dict] = None) -> Optional[float]:
    if amount is None:
        return None
    if currency == "MAD":
        return float(amount)
    rates = dict(FX_FALLBACK)
    if fx_mad_per_unit:
        rates.update({k: v for k, v in fx_mad_per_unit.items() if v})
    rate = rates.get(currency)
    if not rate:
        return float(amount)
    return float(amount) * float(rate)


def fmt_money_cur(
    x: Optional[float],
    currency: str = "MAD",
    fx: Optional[dict] = None,
    compact: bool = False,
) -> str:
    """Montant exprimé en MAD converti dans la devise d'affichage."""
    if x is None:
        return "—"
    if currency not in CURRENCIES:
        currency = "MAD"
    return fmt_money(convert_from_mad(x, currency, fx), currency, compact=compact)


def delta_badge(value: Optional[float], decimals: int = 2) -> str:
    """Renvoie le HTML d'un badge coloré (vert/rouge) pour une variation."""
    if value is None:
        return '<span class="ei-badge ei-flat">—</span>'
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '<span class="ei-badge ei-flat">—</span>'
    if v != v:
        return '<span class="ei-badge ei-flat">—</span>'
    cls = "ei-up" if v > 0 else "ei-down" if v < 0 else "ei-flat"
    arrow = "▲" if v > 0 else "▼" if v < 0 else "■"
    return f'<span class="ei-badge {cls}">{arrow} {fmt_pct(v, decimals, signed=True).replace(" +", "+").replace(" -", "-")}</span>'


def color_of(value: Optional[float]) -> str:
    if value is None:
        return "#64748B"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "#64748B"
    if v != v:
        return "#64748B"
    return "#0F766E" if v > 0 else "#B42318" if v < 0 else "#64748B"


def safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    try:
        if a is None or b in (None, 0):
            return None
        fa, fb = float(a), float(b)
        if fb == 0 or fa != fa or fb != fb:
            return None
        return fa / fb
    except (TypeError, ValueError):
        return None


def as_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None
