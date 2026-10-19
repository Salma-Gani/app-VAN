"""États financiers normalisés des sociétés cotées (bilan, CPC, trésorerie).

Objectif : donner à MARKET MIND une base comptable **réelle et traçable**,
sans jamais inventer un chiffre. Chaque enregistrement porte sa source, la date
de référence, la devise, l'unité, l'exercice et un statut explicite
(``official``, ``api``, ``manual``, ``preview``).

Trois voies d'alimentation :

1. **Jeu de données vérifié** (``data/seed/bvc_statements.json``) — chiffres
   repris des rapports financiers annuels publiés par l'AMMC, avec l'URL du
   document. Sert aussi de référence de contrôle pour les autres voies.
2. **API externes** — EODHD, Financial Modeling Prep et Yahoo Finance
   (clés dans ``.env`` ; aucune clé n'est codée en dur). La couverture des
   valeurs marocaines dépend du fournisseur : elle est signalée telle quelle.
3. **Documents officiels AMMC** — la liste publique des états financiers est
   lue, les PDF sont proposés au téléchargement et un extracteur de secours
   (``pypdf``) peut pré-remplir les principaux postes, sous validation
   humaine. Un PDF n'est pas une API : l'automatisation dépend des droits
   d'utilisation accordés par l'émetteur.

Aucune donnée n'est fabriquée : un champ absent ressort à ``None`` et s'affiche
« — » dans l'interface.
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from ..config import (
    HTTP_HEADERS,
    HTTP_TIMEOUT,
    STATEMENTS_SEED,
    TTL,
    USER_STATEMENTS_FILE,
)
from ..utils import cache
from .http import ProviderError, request_json

NS = "statements"
AMMC_BASE = "https://www.ammc.ma"
AMMC_LIST = f"{AMMC_BASE}/fr/liste-etats-financiers-emetteurs"


class StatementError(RuntimeError):
    """Erreur lisible liée à l'acquisition ou à la validation des états financiers."""


# ═══════════════════════════ Schéma des postes ═══════════════════════════
# Chaque couple (clé, libellé) alimente l'affichage et la dérivation des
# fondamentaux. Les banques et assurances n'utilisent pas tous les postes :
# les champs absents restent ``None``.
LINE_DEFS: Dict[str, List[Tuple[str, str]]] = {
    "income": [
        ("revenue", "Chiffre d'affaires"),
        ("gross_profit", "Marge brute"),
        ("operating_income", "Résultat d'exploitation (EBIT)"),
        ("ebitda", "EBITDA / Excédent brut d'exploitation"),
        ("depreciation", "Dotations aux amortissements"),
        ("interest_expense", "Charges d'intérêts"),
        ("taxes", "Impôts sur les résultats"),
        ("net_income", "Résultat net"),
        ("eps", "Résultat par action (MAD)"),
    ],
    "balance": [
        ("non_current_assets", "Actif immobilisé"),
        ("current_assets", "Actif circulant"),
        ("inventory", "Stocks"),
        ("receivables", "Créances clients"),
        ("cash", "Trésorerie & équivalents (actif)"),
        ("total_assets", "Total du bilan"),
        ("equity", "Capitaux propres"),
        ("total_debt", "Dettes de financement"),
        ("current_liabilities", "Passif circulant"),
        ("net_debt", "Dette nette"),
        ("shares", "Nombre de titres"),
    ],
    "cashflow": [
        ("operating_cf", "Capacité d'autofinancement (CAF)"),
        ("capex", "Acquisitions d'immobilisations"),
        ("free_cash_flow", "Free Cash-Flow (CAF − Capex)"),
        ("dividends_paid", "Distributions de bénéfices"),
        ("net_cash_change", "Variation de trésorerie"),
    ],
}

CANONICAL_KEYS: Dict[str, List[str]] = {
    block: [key for key, _ in defs] for block, defs in LINE_DEFS.items()
}

# Postes de bilan qui ne s'appliquent pas aux établissements de crédit :
# la valeur d'entreprise (EV/EBITDA) n'est pas une méthode pertinente pour eux.
EV_METHOD_EXCLUDED_SECTORS = ("banque", "assurance", "finance", "holding financière")

# Répartition actif / passif utilisée quand l'enregistrement ne fournit pas de
# lignes détaillées (import CSV/Excel, API) : sans cela, l'onglet Bilan restait
# vide alors que `record["balance"]` contenait bien les montants.
ASSET_KEYS = ["non_current_assets", "current_assets", "inventory", "receivables",
              "cash", "total_assets"]
LIABILITY_KEYS = ["equity", "total_debt", "current_liabilities", "net_debt", "shares"]

PERIOD_ORDER = {"FY": 0, "S1": 1, "S2": 2, "T1": 3, "T2": 4, "T3": 5, "T4": 6}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _num(value: Any) -> Optional[float]:
    """Convertit une valeur (nombre, chaîne comptable) en float, sinon ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return None if out != out else out  # filtre NaN
    text = str(value).strip()
    if not text or text in {"-", "—", "n/a", "N/A", "None"}:
        return None
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace(" ", "")
    text = re.sub(r"[^0-9.,\-+()]", "", text)
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    # Conventions : « 1 234,56 » (français), « 1.234.567,89 » (points milliers),
    # « 1234.56 » (anglo-saxon). On normalise avant conversion.
    if "." in text and "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif text.count(".") == 1:
        integer, _, decimals = text.partition(".")
        if len(decimals) == 3 and len(integer.lstrip("-+")) <= 3:
            text = text.replace(".", "")
    try:
        out = float(text)
    except ValueError:
        return None
    return -out if negative else out


def _read_json(path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _record_key(record: Dict[str, Any]) -> Tuple[int, str, bool]:
    try:
        year = int(record.get("fiscal_year") or 0)
    except (TypeError, ValueError):
        year = 0
    return (year, str(record.get("period") or "FY").upper(), bool(record.get("consolidated")))


# ═══════════════════════════ Persistance ═══════════════════════════

def load_store() -> Dict[str, List[Dict[str, Any]]]:
    """Fusionne le jeu vérifié et les enregistrements utilisateur.

    Clé de fusion : ``(exercice, période, consolidé)``. Une saisie utilisateur
    écrase toujours la ligne correspondante du jeu vérifié.
    """
    seed = _read_json(STATEMENTS_SEED, {})
    if isinstance(seed, dict) and "companies" in seed:
        seed = seed["companies"]
    user = _read_json(USER_STATEMENTS_FILE, {})
    merged: Dict[str, Dict[Tuple[int, str, bool], Dict[str, Any]]] = {}
    for source in (seed, user):
        if not isinstance(source, dict):
            continue
        for symbol, records in source.items():
            symbol = str(symbol).strip().upper()
            bucket = merged.setdefault(symbol, {})
            if isinstance(records, dict):
                records = [records]
            for record in records or []:
                if isinstance(record, dict):
                    bucket[_record_key(record)] = record
    return {
        symbol: sorted(records.values(), key=_record_key, reverse=True)
        for symbol, records in merged.items()
    }


def get_statements(symbol: str) -> List[Dict[str, Any]]:
    """Tous les états connus d'une valeur, du plus récent au plus ancien."""
    return list(load_store().get(symbol.strip().upper(), []))


def covered_symbols() -> List[str]:
    """Symboles disposant d'au moins un état financier enregistré."""
    return sorted(symbol for symbol, records in load_store().items() if records)


def get_statement(symbol: str, fiscal_year: Optional[int] = None,
                  period: str = "FY") -> Optional[Dict[str, Any]]:
    records = get_statements(symbol)
    if not records:
        return None
    if fiscal_year is None:
        return records[0]
    for record in records:
        if int(record.get("fiscal_year") or 0) == int(fiscal_year) and \
                str(record.get("period") or "FY").upper() == period.upper():
            return record
    return None


def latest_statement(symbol: str) -> Optional[Dict[str, Any]]:
    records = get_statements(symbol)
    return records[0] if records else None


def previous_statement(symbol: str, record: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """État de même période, exercice précédent (pour les variations)."""
    records = get_statements(symbol)
    if not records:
        return None
    record = record or records[0]
    period = str(record.get("period") or "FY").upper()
    year = int(record.get("fiscal_year") or 0)
    for candidate in records:
        if str(candidate.get("period") or "FY").upper() != period:
            continue
        try:
            cand_year = int(candidate.get("fiscal_year") or 0)
        except (TypeError, ValueError):
            continue
        if cand_year < year:
            return candidate
    return None


def _sanitize(record: Dict[str, Any]) -> Dict[str, Any]:
    """Ne conserve que les postes connus, convertis en nombres."""
    raw_year = record.get("fiscal_year")
    try:
        fiscal_year = int(float(raw_year)) if str(raw_year).strip() else None
    except (TypeError, ValueError):
        fiscal_year = None
    out: Dict[str, Any] = {
        "symbol": str(record.get("symbol") or "").strip().upper(),
        "issuer": record.get("issuer"),
        "period": str(record.get("period") or "FY").upper(),
        "fiscal_year": fiscal_year,
        "period_end": record.get("period_end"),
        "currency": record.get("currency") or "MAD",
        "unit": record.get("unit") or "MAD",
        "consolidated": bool(record.get("consolidated")),
        "source": record.get("source") or "non renseignée",
        "source_url": record.get("source_url") or "",
        "as_of": record.get("as_of") or _now(),
        "status": record.get("status") or "manual",
        "provider": record.get("provider") or "saisie",
    }
    for block, keys in CANONICAL_KEYS.items():
        payload = record.get(block) or {}
        out[block] = {key: _num(payload.get(key)) for key in keys}
    if out["balance"].get("net_debt") is None:
        debt = out["balance"].get("total_debt")
        cash = out["balance"].get("cash")
        if debt is not None and cash is not None:
            out["balance"]["net_debt"] = debt - cash
    cashflow = out["cashflow"]
    if cashflow.get("free_cash_flow") is None:
        operating = cashflow.get("operating_cf")
        capex = cashflow.get("capex")
        if operating is not None and capex is not None:
            cashflow["free_cash_flow"] = operating - capex
    lines = record.get("lines")
    if isinstance(lines, dict):
        out["lines"] = {
            block: [dict(item) for item in items or [] if isinstance(item, dict)]
            for block, items in lines.items()
        }
    return out


def save_statement(record: Dict[str, Any]) -> Dict[str, Any]:
    """Enregistre un état dans le magasin utilisateur et invalide le cache."""
    cleaned = _sanitize(record)
    if not cleaned["symbol"]:
        raise StatementError("Symbole manquant : impossible d'enregistrer l'état financier.")
    store = _read_json(USER_STATEMENTS_FILE, {})
    if not isinstance(store, dict):
        store = {}
    records = store.get(cleaned["symbol"])
    if isinstance(records, dict):
        records = [records]
    records = list(records or [])
    key = _record_key(cleaned)
    records = [r for r in records if _record_key(r) != key]
    records.append(cleaned)
    records.sort(key=_record_key, reverse=True)
    store[cleaned["symbol"]] = records
    _write_json(USER_STATEMENTS_FILE, store)
    cache.clear(NS)
    return cleaned


def save_many(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    saved, errors = 0, []
    for record in records or []:
        try:
            save_statement(record)
            saved += 1
        except StatementError as exc:
            errors.append(str(exc))
    return {"saved": saved, "errors": errors}


def delete_statement(symbol: str, fiscal_year: Optional[int] = None,
                     period: str = "FY") -> bool:
    symbol = symbol.strip().upper()
    store = _read_json(USER_STATEMENTS_FILE, {})
    if not isinstance(store, dict) or symbol not in store:
        return False
    records = store.get(symbol)
    if isinstance(records, dict):
        records = [records]
    records = list(records or [])
    if fiscal_year is None:
        store.pop(symbol, None)
    else:
        target = (int(fiscal_year), str(period).upper(), False)
        store[symbol] = [r for r in records if _record_key(r)[:2] != target[:2]]
        if not store[symbol]:
            store.pop(symbol, None)
    _write_json(USER_STATEMENTS_FILE, store)
    cache.clear(NS)
    return True


# ═══════════════════════════ Dérivation des fondamentaux ═══════════════════════════

def _metric(record: Optional[Dict[str, Any]], block: str, key: str) -> Optional[float]:
    if not record:
        return None
    return _num((record.get(block) or {}).get(key))


def to_fundamentals(record: Dict[str, Any],
                    previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convertit un état financier en champs fondamentaux attendus par l'app.

    Les métadonnées de traçabilité (source, exercice, URL, statut) sont
    propagées pour que l'interface affiche toujours la provenance du chiffre.
    """
    income = record.get("income") or {}
    balance = record.get("balance") or {}
    cashflow = record.get("cashflow") or {}

    shares = _num(balance.get("shares"))
    net_income = _num(income.get("net_income"))
    eps = _num(income.get("eps"))
    if eps is None and net_income is not None and shares:
        eps = net_income / shares
    fcf = _num(cashflow.get("free_cash_flow"))
    if fcf is None:
        operating = _num(cashflow.get("operating_cf"))
        capex = _num(cashflow.get("capex"))
        if operating is not None and capex is not None:
            fcf = operating - capex

    out: Dict[str, Any] = {
        "revenue": _num(income.get("revenue")),
        "ebitda": _num(income.get("ebitda")),
        "ebit": _num(income.get("operating_income")),
        "net_income": net_income,
        "eps": eps,
        "fcf": fcf,
        "operating_cf": _num(cashflow.get("operating_cf")),
        "capex": _num(cashflow.get("capex")),
        "equity": _num(balance.get("equity")),
        "total_debt": _num(balance.get("total_debt")),
        "cash": _num(balance.get("cash")),
        "total_assets": _num(balance.get("total_assets")),
        "current_assets": _num(balance.get("current_assets")),
        "current_liabilities": _num(balance.get("current_liabilities")),
        "shares": shares,
        "fiscal_year": str(record.get("fiscal_year") or ""),
        "source": record.get("source"),
        "as_of": record.get("as_of"),
        "statement_status": record.get("status"),
        "statement_source": record.get("source"),
        "statement_url": record.get("source_url"),
        "statement_fiscal_year": record.get("fiscal_year"),
        "statement_period": record.get("period"),
        "statement_provider": record.get("provider"),
        "statement_currency": record.get("currency"),
        "statement_unit": record.get("unit"),
    }
    if previous:
        pairs = (
            ("revenue", "revenue_growth"),
            ("net_income", "net_income_growth"),
            ("fcf", "fcf_growth"),
        )
        for key, target in pairs:
            current_value = _num(out.get(key))
            prev_value = _num((previous.get("income") or {}).get(key))
            if key == "fcf":
                prev_value = _num((previous.get("cashflow") or {}).get("free_cash_flow"))
                if prev_value is None:
                    op = _num((previous.get("cashflow") or {}).get("operating_cf"))
                    capex = _num((previous.get("cashflow") or {}).get("capex"))
                    prev_value = op - capex if op is not None and capex is not None else None
            if current_value is not None and prev_value not in (None, 0):
                out[target] = current_value / prev_value - 1.0
    return {key: value for key, value in out.items() if value not in (None, "")}


def fundamentals_for(symbol: str) -> Dict[str, Any]:
    """Champs fondamentaux issus du dernier état connu (avec variations)."""
    record = latest_statement(symbol)
    if not record:
        return {}
    return to_fundamentals(record, previous_statement(symbol, record))


def detect_unit(text: str) -> str:
    """Devine l'unité annoncée dans un rapport (indicatif, à confirmer).

    La détection ne sert qu'à pré-remplir un brouillon importable ; elle ne
    modifie jamais un montant et n'est jamais appliquée automatiquement.
    """
    sample = _normalise((text or "")[:200000])
    if "milliards de dirhams" in sample or "milliards mad" in sample:
        return "milliards MAD"
    if "millions de dirhams" in sample or "mdh" in sample.split() or "millions mad" in sample:
        return "millions MAD"
    if "milliers de dirhams" in sample or "kmad" in sample.split() or "milliers mad" in sample:
        return "milliers MAD"
    return "MAD"


def unit_multiplier(unit: Optional[str]) -> float:
    """Facteur de conversion d'une unité comptable vers l'unité de base (MAD).

    ``MAD`` → 1 ; ``milliers`` → 1 000 ; ``millions`` / ``MDH`` → 1 000 000 ;
    ``milliards`` → 1 000 000 000. Une unité inconnue est traitée comme 1 et
    signalée par l'appelant, jamais devinée silencieusement.
    """
    text = _normalise(str(unit or ""))
    if not text or text in {"mad", "dirham", "dirhams", "unite", "unites", "units", "unit"}:
        return 1.0
    if "milliard" in text or "billion" in text or text in {"bn", "mdh milliards"}:
        return 1e9
    if "million" in text or text in {"mdh", "mmad", "m mad"}:
        return 1e6
    if "millier" in text or "thousand" in text or text in {"kmad", "k mad"}:
        return 1e3
    return 1.0


def ratios_for(record: Dict[str, Any], market: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Ratios calculables à partir de l'état financier et, si fourni, du cours.

    Chaque ligne expose sa **formule**, son statut et, en cas d'impossibilité,
    la raison exacte (donnée manquante, dénominateur nul, méthode non pertinente).
    Aucun ratio n'est calculé sur des données incompatibles ou inventées.
    """
    income = record.get("income") or {}
    balance = record.get("balance") or {}
    cashflow = record.get("cashflow") or {}
    market = market or {}
    factor = unit_multiplier(record.get("unit"))
    sector = str(market.get("sector") or "").lower()

    price = _num(market.get("close"))
    cap = _num(market.get("cap"))
    price_native = price / factor if price is not None else None
    cap_native = cap / factor if cap is not None else None
    shares = _num(balance.get("shares"))
    net_income = _num(income.get("net_income"))
    equity = _num(balance.get("equity"))
    ebitda = _num(income.get("ebitda"))
    net_debt = _num(balance.get("net_debt"))
    if net_debt is None:
        total_debt = _num(balance.get("total_debt"))
        cash = _num(balance.get("cash"))
        if total_debt is not None and cash is not None:
            net_debt = total_debt - cash
    eps = _num(income.get("eps"))
    if eps is None and net_income is not None and shares:
        eps = net_income / shares

    rows: List[Dict[str, Any]] = []

    def add(label: str, numerator: Optional[float], denominator: Optional[float],
            formula: str, unit: str = "%", scale: float = 100.0,
            numerator_name: str = "numérateur", denominator_name: str = "dénominateur",
            note: str = "", status: Optional[str] = None) -> None:
        if status:
            rows.append({"Indicateur": label, "Valeur": None, "Unité": unit,
                         "Formule": formula, "Statut": status, "Note": note})
            return
        missing = []
        if numerator is None:
            missing.append(numerator_name)
        if denominator is None:
            missing.append(denominator_name)
        if missing:
            rows.append({"Indicateur": label, "Valeur": None, "Unité": unit,
                         "Formule": formula, "Statut": "Impossible",
                         "Note": "donnée manquante : " + ", ".join(missing)})
            return
        if denominator == 0:
            rows.append({"Indicateur": label, "Valeur": None, "Unité": unit,
                         "Formule": formula, "Statut": "Impossible",
                         "Note": "dénominateur nul"})
            return
        rows.append({"Indicateur": label, "Valeur": (numerator / denominator) * scale,
                     "Unité": unit, "Formule": formula, "Statut": "Calculé",
                     "Note": note})

    add("Marge brute", _num(income.get("gross_profit")), _num(income.get("revenue")),
        "marge brute / chiffre d'affaires", numerator_name="marge brute",
        denominator_name="chiffre d'affaires")
    add("Marge d'exploitation", _num(income.get("operating_income")), _num(income.get("revenue")),
        "résultat d'exploitation / chiffre d'affaires", numerator_name="résultat d'exploitation",
        denominator_name="chiffre d'affaires")
    add("Marge nette", net_income, _num(income.get("revenue")),
        "résultat net / chiffre d'affaires", numerator_name="résultat net",
        denominator_name="chiffre d'affaires")

    if equity is not None and equity <= 0:
        add("ROE", None, None, "résultat net / capitaux propres", status="Impossible",
            note="capitaux propres négatifs ou nuls : ratio non significatif")
    else:
        add("ROE", net_income, equity, "résultat net / capitaux propres",
            numerator_name="résultat net", denominator_name="capitaux propres")
    add("ROA", net_income, _num(balance.get("total_assets")),
        "résultat net / total actif", numerator_name="résultat net",
        denominator_name="total actif")
    add("Levier financier", _num(balance.get("total_debt")), equity,
        "dettes de financement / capitaux propres", unit="x", scale=1.0,
        numerator_name="dettes de financement", denominator_name="capitaux propres")
    add("Liquidité générale", _num(balance.get("current_assets")),
        _num(balance.get("current_liabilities")),
        "actif circulant / passif circulant", unit="x", scale=1.0,
        numerator_name="actif circulant", denominator_name="passif circulant")
    add("Couverture des intérêts", _num(income.get("operating_income")),
        _num(income.get("interest_expense")),
        "résultat d'exploitation / charges d'intérêts", unit="x", scale=1.0,
        numerator_name="résultat d'exploitation", denominator_name="charges d'intérêts")
    add("FCF / chiffre d'affaires", _num(cashflow.get("free_cash_flow")),
        _num(income.get("revenue")), "free cash-flow / chiffre d'affaires",
        numerator_name="free cash-flow", denominator_name="chiffre d'affaires")
    add("Distribution (payout)", _num(cashflow.get("dividends_paid")), net_income,
        "dividendes versés / résultat net", numerator_name="dividendes versés",
        denominator_name="résultat net")

    excluded = any(word in sector for word in EV_METHOD_EXCLUDED_SECTORS)
    if excluded:
        add("EV / EBITDA", None, None, "(capitalisation + dette nette) / EBITDA", unit="x",
            status="Non pertinent",
            note=f"secteur « {market.get('sector')} » : la valeur d'entreprise n'est pas une méthode adaptée")
    elif ebitda is not None and ebitda <= 0:
        add("EV / EBITDA", None, None, "(capitalisation + dette nette) / EBITDA", unit="x",
            status="Impossible", note="EBITDA négatif ou nul")
    elif cap_native is None or net_debt is None:
        add("EV / EBITDA", None, None, "(capitalisation + dette nette) / EBITDA", unit="x",
            status="Impossible",
            note="donnée manquante : " + ", ".join(
                x for x in (
                    "capitalisation (BVC)" if cap_native is None else "",
                    "dette nette" if net_debt is None else "",
                ) if x))
    else:
        add("EV / EBITDA", cap_native + net_debt, ebitda,
            "(capitalisation + dette nette) / EBITDA", unit="x", scale=1.0,
            numerator_name="valeur d'entreprise", denominator_name="EBITDA")

    # PER et P/B restent pertinents pour les banques et assurances : seul
    # l'EV/EBITDA est écarté pour ces secteurs.
    # PER = capitalisation / résultat net, strictement équivalent à cours / BPA
    # lorsque le nombre de titres est cohérent. Cette forme est plus robuste aux
    # unités d'import (milliers, millions) que le rapport cours / BPA.
    if net_income is not None and net_income <= 0:
        add("PER", None, None, "capitalisation / résultat net (≡ cours / BPA)", unit="x",
            status="Impossible", note="résultat net négatif ou nul : PER non significatif")
    elif cap_native is not None:
        add("PER", cap_native, net_income, "capitalisation / résultat net (≡ cours / BPA)",
            unit="x", scale=1.0, numerator_name="capitalisation",
            denominator_name="résultat net")
    elif price_native is not None and eps is not None:
        add("PER", price_native, eps, "cours / BPA", unit="x", scale=1.0,
            numerator_name="cours", denominator_name="BPA")
    else:
        add("PER", None, None, "capitalisation / résultat net (≡ cours / BPA)", unit="x",
            status="Impossible",
            note="donnée manquante : capitalisation et cours/BPA")

    if equity is not None and equity <= 0:
        add("P/B", None, None, "capitalisation / capitaux propres", unit="x",
            status="Impossible", note="capitaux propres négatifs ou nuls")
    elif cap_native is None:
        add("P/B", None, None, "capitalisation / capitaux propres", unit="x",
            status="Impossible", note="donnée manquante : capitalisation (BVC)")
    else:
        add("P/B", cap_native, equity, "capitalisation / capitaux propres", unit="x",
            scale=1.0, numerator_name="capitalisation", denominator_name="capitaux propres")

    dividends = _num(cashflow.get("dividends_paid"))
    if dividends is not None and shares and price_native:
        add("Rendement du dividende", dividends / shares, price_native,
            "(dividendes versés / nombre de titres) / cours", note="estimation sur le dividende total")
    else:
        add("Rendement du dividende", None, None,
            "(dividendes versés / nombre de titres) / cours", status="Impossible",
            note="donnée manquante : dividende total, nombre de titres ou cours")

    return pd.DataFrame(rows)


def coverage(market_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Couverture comptable par valeur : exercices disponibles, source, statut."""
    store = load_store()
    rows: List[Dict[str, Any]] = []
    symbols = list(store.keys())
    if market_df is not None and not market_df.empty and "symbol" in market_df.columns:
        for symbol in market_df["symbol"].astype(str):
            if symbol not in symbols:
                symbols.append(symbol)
    names: Dict[str, str] = {}
    if market_df is not None and not market_df.empty and "symbol" in market_df.columns:
        names = dict(zip(market_df["symbol"].astype(str), market_df.get("name", pd.Series(dtype=str))))
    for symbol in symbols:
        records = get_statements(symbol)
        if records:
            latest = records[0]
            rows.append({
                "Symbole": symbol,
                "Société": names.get(symbol) or latest.get("issuer") or symbol,
                "Exercices": ", ".join(str(r.get("fiscal_year")) for r in records),
                "Dernier exercice": latest.get("fiscal_year"),
                "Statut": latest.get("status"),
                "Source": latest.get("source"),
                "Mise à jour": latest.get("as_of"),
            })
        elif market_df is not None and not market_df.empty:
            rows.append({
                "Symbole": symbol,
                "Société": names.get(symbol) or symbol,
                "Exercices": "—",
                "Dernier exercice": None,
                "Statut": "non couvert",
                "Source": "—",
                "Mise à jour": "—",
            })
    if not rows:
        return pd.DataFrame(columns=["Symbole", "Société", "Exercices", "Dernier exercice",
                                     "Statut", "Source", "Mise à jour"])
    return pd.DataFrame(rows).sort_values(
        ["Dernier exercice"], ascending=False, na_position="last"
    ).reset_index(drop=True)


# ═══════════════════════════ Affichage ═══════════════════════════

def _fallback_keys(block: str) -> List[str]:
    if block == "balance_assets":
        return ASSET_KEYS
    if block == "balance_liabilities":
        return LIABILITY_KEYS
    return CANONICAL_KEYS.get(block, [])


def block_table(record: Dict[str, Any], block: str) -> pd.DataFrame:
    """Tableau prêt à afficher pour un bloc (``income``, ``balance``, ``cashflow``).

    ``balance_assets`` et ``balance_liabilities`` acceptent soit des lignes
    détaillées (``record["lines"]``), soit un repli sur le dictionnaire
    ``record["balance"]`` : un import CSV/Excel n'a pas de lignes détaillées.
    """
    if not record:
        return pd.DataFrame(columns=["Poste", "Exercice", "Exercice précédent"])
    lines = (record.get("lines") or {}).get(block)
    rows: List[Dict[str, Any]] = []
    if lines:
        for item in lines:
            value = _num(item.get("value"))
            prior = _num(item.get("prior"))
            if value is None and prior is None:
                continue
            rows.append({"Poste": item.get("label") or "", "Exercice": value,
                         "Exercice précédent": prior})
    else:
        payload = record.get("balance" if block.startswith("balance") else block) or {}
        label_map = dict(LINE_DEFS.get("balance" if block.startswith("balance") else block, []))
        for key in _fallback_keys(block):
            value = _num(payload.get(key))
            if value is None:
                continue
            rows.append({"Poste": label_map.get(key, key), "Exercice": value,
                         "Exercice précédent": None})
    return pd.DataFrame(rows)


# ═══════════════════════════ Import CSV / JSON ═══════════════════════════

CSV_COLUMNS = ["symbol", "issuer", "fiscal_year", "period", "period_end", "currency",
               "unit", "consolidated", "source", "source_url", "as_of", "status"]
CSV_COLUMNS += [f"income_{k}" for k in CANONICAL_KEYS["income"]]
CSV_COLUMNS += [f"balance_{k}" for k in CANONICAL_KEYS["balance"]]
CSV_COLUMNS += [f"cashflow_{k}" for k in CANONICAL_KEYS["cashflow"]]


def template_csv() -> str:
    header = ",".join(CSV_COLUMNS)
    example = ",".join([
        "EXEMPLE", "Société Exemple", "2024", "FY", "2024-12-31", "MAD", "MAD", "false",
        "Rapport annuel 2024 — à remplacer", "https://…", "2025-04-30", "manual",
    ] + ["123000000"] * (len(CSV_COLUMNS) - 12))
    return header + "\n" + example + "\n"


def import_csv(content: bytes) -> Dict[str, Any]:
    """Importe un ou plusieurs états financiers depuis un CSV multi-colonnes."""
    import csv
    import io

    text = content.decode("utf-8-sig", errors="replace")
    dialect = ";" if text.count(";") > text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=dialect)
    fields = [str(name or "").strip() for name in (reader.fieldnames or [])]
    if not fields or ("symbol" not in fields and "Symbole" not in fields):
        raise StatementError(
            "En-tête CSV invalide : la colonne « symbol » est obligatoire. "
            "Téléchargez le modèle CSV pour voir le format attendu."
        )
    records, errors = [], []
    seen = 0
    for row in reader:
        if not any(str(v or "").strip() for v in row.values()):
            continue
        seen += 1
        symbol = str(row.get("symbol") or row.get("Symbole") or "").strip().upper()
        if not symbol or symbol == "EXEMPLE":
            continue
        if not str(row.get("fiscal_year") or "").strip():
            errors.append(f"{symbol}: exercice (fiscal_year) manquant")
            continue
        record: Dict[str, Any] = {
            "symbol": symbol,
            "issuer": row.get("issuer"),
            "fiscal_year": row.get("fiscal_year"),
            "period": row.get("period") or "FY",
            "period_end": row.get("period_end"),
            "currency": row.get("currency") or "MAD",
            "unit": row.get("unit") or "MAD",
            "consolidated": str(row.get("consolidated") or "").strip().lower() in {"1", "true", "oui", "yes"},
            "source": row.get("source") or "import CSV",
            "source_url": row.get("source_url") or "",
            "as_of": row.get("as_of"),
            "status": row.get("status") or "manual",
            "provider": "import CSV",
        }
        for block, keys in CANONICAL_KEYS.items():
            record[block] = {}
            for key in keys:
                raw = row.get(f"{block}_{key}")
                value = _num(raw)
                if value is not None:
                    record[block][key] = value
        if not any(record[block] for block in CANONICAL_KEYS):
            errors.append(f"{symbol} {row.get('fiscal_year')}: aucun montant numérique reconnu")
            continue
        try:
            records.append(_sanitize(record))
        except StatementError as exc:
            errors.append(f"{symbol}: {exc}")
    if seen == 0:
        raise StatementError("Le fichier ne contient aucune ligne de données.")
    result = save_many(records)
    return {"imported": result["saved"], "errors": errors + result["errors"]}


def import_excel(content: bytes) -> Dict[str, Any]:
    """Importe un classeur Excel (.xlsx/.xlsm) via pandas + openpyxl.

    Le classeur doit contenir une feuille avec les mêmes colonnes que le modèle
    CSV. Les valeurs sont converties en texte puis passées au même validateur,
    afin qu'un import Excel et un import CSV aient exactement les mêmes règles.
    """
    import io

    try:
        frame = pd.read_excel(io.BytesIO(content), dtype=str)
    except ImportError as exc:
        raise StatementError(
            "Lecture Excel indisponible : installez openpyxl (`pip install openpyxl`) "
            "ou exportez le classeur au format CSV."
        ) from exc
    except Exception as exc:  # classeur corrompu, format inattendu
        raise StatementError(f"Classeur Excel illisible : {exc}") from exc
    if frame is None or frame.empty:
        raise StatementError("Le classeur ne contient aucune ligne exploitable.")
    frame = frame.fillna("")
    return import_csv(frame.to_csv(index=False).encode("utf-8"))


def import_table(content: bytes, filename: str = "") -> Dict[str, Any]:
    """Point d'entrée unique d'import : CSV ou Excel selon l'extension."""
    name = str(filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return import_excel(content)
    return import_csv(content)


# ═══════════════════════════ Fournisseurs externes ═══════════════════════════

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "eodhd": {
        "label": "EODHD",
        "env": "EODHD_API_KEY",
        "note": "États financiers annuels et trimestriels, couverture mondiale. "
                "Suffixe de place configurable via EODHD_EXCHANGE (ex. MA).",
    },
    "fmp": {
        "label": "Financial Modeling Prep",
        "env": "FMP_API_KEY",
        "note": "Compte de résultat, bilan et trésorerie normalisés. "
                "Couverture des places africaines à vérifier selon le titre.",
    },
    "yahoo": {
        "label": "Yahoo Finance (yfinance)",
        "env": "",
        "note": "Sans clé. Pertinent surtout pour les valeurs internationales ; "
                "la couverture des valeurs marocaines est limitée.",
    },
    "ammc": {
        "label": "AMMC — documents officiels",
        "env": "",
        "note": "Liste publique des états financiers + PDF des émetteurs. "
                "Ce n'est pas une API : vérifiez les droits de réutilisation.",
    },
    "manual": {
        "label": "Saisie / import CSV",
        "env": "",
        "note": "Toujours disponible, sans dépendance externe.",
    },
}


def provider_status() -> List[Dict[str, Any]]:
    out = []
    for key, meta in PROVIDERS.items():
        env = meta.get("env") or ""
        out.append({
            "key": key,
            "label": meta["label"],
            "env": env,
            "configured": (not env) or bool(os.getenv(env)),
            "note": meta["note"],
        })
    return out


def _http_json(url: str, params: Optional[Dict[str, Any]] = None,
               provider: str = "API états financiers") -> Any:
    try:
        return request_json(url, provider=provider, params=params, allow_empty=False)
    except ProviderError as exc:
        raise StatementError(exc.user_message) from exc


def _pick(payload: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key in payload:
            value = _num(payload.get(key))
            if value is not None:
                return value
    return None


def _blank_record(symbol: str, provider: str, source: str) -> Dict[str, Any]:
    return {
        "symbol": symbol, "period": "FY", "fiscal_year": None, "period_end": None,
        "currency": "MAD", "unit": "MAD", "consolidated": False,
        "source": source, "source_url": "", "as_of": datetime.now().strftime("%Y-%m-%d"),
        "status": "api", "provider": provider,
        "income": {}, "balance": {}, "cashflow": {},
    }


def fetch_eodhd(symbol: str, api_key: Optional[str] = None, exchange: Optional[str] = None,
                limit: int = 5) -> List[Dict[str, Any]]:
    """Récupère les états financiers annuels chez EODHD."""
    api_key = api_key or os.getenv("EODHD_API_KEY")
    if not api_key:
        raise StatementError("Clé EODHD absente : définissez EODHD_API_KEY dans l'environnement.")
    exchange = exchange or os.getenv("EODHD_EXCHANGE") or "MA"
    ticker = symbol.strip().upper()
    if "." not in ticker:
        ticker = f"{ticker}.{exchange}"
    payload = _http_json(f"https://eodhd.com/api/v1.1/fundamentals/{ticker}",
                         {"api_token": api_key, "fmt": "json"}, provider="EODHD")
    if not isinstance(payload, dict) or "Financials" not in payload:
        raise StatementError(f"EODHD : aucune donnée financière pour {ticker}.")
    general = payload.get("General") or {}
    financials = payload.get("Financials") or {}
    currency = general.get("CurrencyCode") or "MAD"
    balance = (financials.get("Balance_Sheet") or {}).get("yearly") or {}
    income = (financials.get("Income_Statement") or {}).get("yearly") or {}
    cash = (financials.get("Cash_Flow") or {}).get("yearly") or {}
    years = sorted(set(balance) | set(income) | set(cash), reverse=True)[:limit]

    records = []
    for year in years:
        inc = income.get(year) or {}
        bal = balance.get(year) or {}
        cf = cash.get(year) or {}
        record = _blank_record(ticker, "EODHD", f"EODHD — états annuels {year[:4]}")
        record.update({
            "symbol": ticker, "currency": currency,
            "fiscal_year": year[:4], "period_end": year,
            "source_url": f"https://eodhd.com/financial-summary/{ticker}",
            "income": {
                "revenue": _pick(inc, "totalRevenue", "revenue"),
                "gross_profit": _pick(inc, "grossProfit"),
                "operating_income": _pick(inc, "operatingIncome", "ebit"),
                "ebitda": _pick(inc, "ebitda"),
                "depreciation": _pick(inc, "depreciationAndAmortization"),
                "interest_expense": _pick(inc, "interestExpense"),
                "taxes": _pick(inc, "incomeTaxExpense", "taxProvision"),
                "net_income": _pick(inc, "netIncome"),
                "eps": _pick(inc, "eps", "earningsPerShare", "epsActual"),
            },
            "balance": {
                "non_current_assets": _pick(bal, "totalNonCurrentAssets", "nonCurrentAssets"),
                "current_assets": _pick(bal, "totalCurrentAssets"),
                "inventory": _pick(bal, "inventory"),
                "receivables": _pick(bal, "netReceivables", "receivables"),
                "cash": _pick(bal, "cashAndCashEquivalents", "cash"),
                "total_assets": _pick(bal, "totalAssets"),
                "equity": _pick(bal, "totalStockholderEquity", "totalStockholdersEquity"),
                "total_debt": _pick(bal, "totalDebt", "shortLongTermDebtTotal"),
                "current_liabilities": _pick(bal, "totalCurrentLiabilities"),
                "net_debt": _pick(bal, "netDebt"),
                "shares": _pick(bal, "commonStockSharesOutstanding", "shares"),
            },
            "cashflow": {
                "operating_cf": _pick(cf, "totalCashFromOperatingActivities", "operatingCashFlow"),
                "capex": _pick(cf, "capitalExpenditures", "capitalExpenditure"),
                "free_cash_flow": _pick(cf, "freeCashFlow"),
                "dividends_paid": _pick(cf, "dividendsPaid", "commonStockDividendPaid"),
                "net_cash_change": _pick(cf, "changeInCash", "netChangeInCash"),
            },
        })
        records.append(_sanitize(record))
    if not records:
        raise StatementError(f"EODHD : aucun exercice exploitable pour {ticker}.")
    return records


def fetch_fmp(symbol: str, api_key: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Récupère les états financiers annuels chez Financial Modeling Prep."""
    api_key = api_key or os.getenv("FMP_API_KEY")
    if not api_key:
        raise StatementError("Clé FMP absente : définissez FMP_API_KEY dans l'environnement.")
    ticker = symbol.strip().upper()
    base = "https://financialmodelingprep.com/api/v3"
    params = {"period": "annual", "limit": limit, "apikey": api_key}

    def endpoint(name: str) -> Dict[str, Dict[str, Any]]:
        rows = _http_json(f"{base}/{name}/{ticker}", params, provider="FMP")
        if not isinstance(rows, list):
            raise StatementError(f"FMP : réponse inattendue pour {ticker} ({name}).")
        out = {}
        for item in rows:
            key = str(item.get("date") or item.get("fiscalYear") or "")
            if key:
                out[key] = item
        return out

    income = endpoint("income-statement")
    balance = endpoint("balance-sheet-statement")
    cash = endpoint("cash-flow-statement")
    years = sorted(set(income) | set(balance) | set(cash), reverse=True)[:limit]
    if not years:
        raise StatementError(f"FMP : aucun état financier retourné pour {ticker}.")

    records = []
    for year in years:
        inc = income.get(year) or {}
        bal = balance.get(year) or {}
        cf = cash.get(year) or {}
        fiscal_year = str(inc.get("fiscalYear") or bal.get("fiscalYear")
                          or cf.get("calendarYear") or year[:4])
        record = _blank_record(ticker, "FMP", f"Financial Modeling Prep — états annuels {fiscal_year}")
        record.update({
            "symbol": ticker, "fiscal_year": fiscal_year, "period_end": year,
            "source_url": f"https://financialmodelingprep.com/financial-statements/{ticker}",
            "income": {
                "revenue": _pick(inc, "revenue"),
                "gross_profit": _pick(inc, "grossProfit"),
                "operating_income": _pick(inc, "operatingIncome"),
                "ebitda": _pick(inc, "ebitda"),
                "depreciation": _pick(inc, "depreciationAndAmortization"),
                "interest_expense": _pick(inc, "interestExpense"),
                "taxes": _pick(inc, "incomeTaxExpense"),
                "net_income": _pick(inc, "netIncome"),
                "eps": _pick(inc, "eps", "epsdiluted"),
            },
            "balance": {
                "non_current_assets": _pick(bal, "totalNonCurrentAssets"),
                "current_assets": _pick(bal, "totalCurrentAssets"),
                "inventory": _pick(bal, "inventory"),
                "receivables": _pick(bal, "netReceivables", "accountsReceivables"),
                "cash": _pick(bal, "cashAndCashEquivalents"),
                "total_assets": _pick(bal, "totalAssets"),
                "equity": _pick(bal, "totalStockholdersEquity", "totalEquity"),
                "total_debt": _pick(bal, "totalDebt"),
                "current_liabilities": _pick(bal, "totalCurrentLiabilities"),
                "net_debt": _pick(bal, "netDebt"),
                "shares": _pick(bal, "commonStockSharesOutstanding", "weightedAverageShsOut"),
            },
            "cashflow": {
                "operating_cf": _pick(cf, "operatingCashFlow"),
                "capex": _pick(cf, "capitalExpenditure"),
                "free_cash_flow": _pick(cf, "freeCashFlow"),
                "dividends_paid": _pick(cf, "dividendsPaid", "netDividendsPaid"),
                "net_cash_change": _pick(cf, "netChangeInCash"),
            },
        })
        records.append(_sanitize(record))
    return records


def fetch_yahoo(symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Récupère les états financiers annuels via yfinance (valeurs internationales)."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - dépendance optionnelle à l'installation
        raise StatementError("yfinance n'est pas disponible dans cet environnement.") from exc

    ticker = symbol.strip().upper()
    handle = yf.Ticker(ticker)
    try:
        income_df = handle.financials
        balance_df = handle.balance_sheet
        cash_df = handle.cashflow
    except Exception as exc:
        raise StatementError(f"Yahoo Finance : récupération impossible pour {ticker} ({exc}).") from exc
    if income_df is None or getattr(income_df, "empty", True):
        raise StatementError(f"Yahoo Finance : aucun état financier pour {ticker}.")

    columns = list(income_df.columns)[:limit]

    def value(frame, *labels) -> Optional[float]:
        if frame is None or getattr(frame, "empty", True):
            return None
        for label in labels:
            if label in frame.index:
                series = frame.loc[label]
                for column in columns:
                    if column in series.index:
                        out = _num(series[column])
                        if out is not None:
                            return out
        return None

    def value_at(frame, column, *labels) -> Optional[float]:
        if frame is None or getattr(frame, "empty", True):
            return None
        for label in labels:
            if label in frame.index and column in frame.columns:
                out = _num(frame.loc[label, column])
                if out is not None:
                    return out
        return None

    records = []
    for column in columns:
        year = str(pd.Timestamp(column).year)
        record = _blank_record(ticker, "Yahoo Finance", f"Yahoo Finance — états annuels {year}")
        record.update({
            "symbol": ticker, "fiscal_year": year,
            "period_end": pd.Timestamp(column).strftime("%Y-%m-%d"),
            "source_url": f"https://finance.yahoo.com/quote/{ticker}/financials",
            "income": {
                "revenue": value_at(income_df, column, "Total Revenue", "TotalRevenue"),
                "gross_profit": value_at(income_df, column, "Gross Profit"),
                "operating_income": value_at(income_df, column, "Operating Income", "EBIT"),
                "ebitda": value_at(income_df, column, "EBITDA", "Normalized EBITDA"),
                "net_income": value_at(income_df, column, "Net Income", "Net Income Common Stockholders"),
                "eps": value_at(income_df, column, "Basic EPS", "Diluted EPS"),
            },
            "balance": {
                "non_current_assets": value_at(balance_df, column, "Total Non Current Assets"),
                "current_assets": value_at(balance_df, column, "Current Assets", "Total Current Assets"),
                "inventory": value_at(balance_df, column, "Inventory"),
                "receivables": value_at(balance_df, column, "Accounts Receivable", "Receivables"),
                "cash": value_at(balance_df, column, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
                "total_assets": value_at(balance_df, column, "Total Assets"),
                "equity": value_at(balance_df, column, "Stockholders Equity", "Total Equity Gross Minority Interest"),
                "total_debt": value_at(balance_df, column, "Total Debt"),
                "current_liabilities": value_at(balance_df, column, "Current Liabilities", "Total Current Liabilities"),
                "net_debt": value_at(balance_df, column, "Net Debt"),
                "shares": value_at(balance_df, column, "Ordinary Shares Number", "Share Issued"),
            },
            "cashflow": {
                "operating_cf": value_at(cash_df, column, "Operating Cash Flow", "Total Cash From Operating Activities"),
                "capex": value_at(cash_df, column, "Capital Expenditure"),
                "free_cash_flow": value_at(cash_df, column, "Free Cash Flow"),
                "dividends_paid": value_at(cash_df, column, "Dividends Paid", "Common Stock Dividend Paid"),
                "net_cash_change": value_at(cash_df, column, "Changes In Cash", "Change In Cash"),
            },
        })
        records.append(_sanitize(record))
    if not records:
        raise StatementError(f"Yahoo Finance : aucun exercice exploitable pour {ticker}.")
    return records


FETCHERS = {"eodhd": fetch_eodhd, "fmp": fetch_fmp, "yahoo": fetch_yahoo}


def fetch_provider(provider: str, symbol: str, **kwargs: Any) -> List[Dict[str, Any]]:
    fetcher = FETCHERS.get((provider or "").lower())
    if fetcher is None:
        raise StatementError(f"Fournisseur inconnu : {provider}.")
    return fetcher(symbol, **kwargs)


# ═══════════════════════════ Documents officiels AMMC ═══════════════════════════

_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_DETAIL_RE = re.compile(r'href="(/fr/espace-emetteurs/etats-financiers/[^"#?]+)"', re.I)
_PDF_RE = re.compile(r'href="(/sites/default/files/[^"#?]+\.pdf)"', re.I)

# Correspondances entre tickers BVC et libellés AMMC, quand ils diffèrent.
# Elles servent uniquement à retrouver le bon émetteur dans la liste officielle ;
# aucun chiffre n'en est déduit.
AMMC_ISSUER_ALIASES = {
    "IAM": "MAROC TELECOM",
    "ATW": "ATTIJARIWAFA BANK",
    "BCP": "BANQUE CENTRALE POPULAIRE",
    "BOA": "BANK OF AFRICA",
    "TMA": "TOTALENERGIES MARKETING MAROC",
    "MOX": "MAGHREB OXYGENE",
    "LBV": "LABEL VIE",
    "CSR": "COSUMAR",
    "MNG": "MANAGEM",
    "MSA": "MARSA MAROC",
    "TGCC": "TGCC",
}


def _issuer_options(force: bool = False) -> List[Tuple[str, str]]:
    """Liste officielle (identifiant, nom) des émetteurs AMMC.

    La page publique expose un filtre « Émetteur » ; utiliser cet identifiant
    évite de parcourir des centaines de pages sans jamais trouver la société.
    """
    key = "ammc:issuers"
    if not force:
        hit = cache.get(NS, key, TTL["ammc"])
        if hit is not None:
            return [tuple(item) for item in hit]
    markup = _fetch_html(AMMC_LIST)
    start = markup.find('name="field_emetteur_target_id_verf"')
    end = markup.find("</select>", start)
    segment = markup[start:end] if start >= 0 else markup
    options = [
        (value, html.unescape(name).strip())
        for value, name in re.findall(r'<option value="(\d+)"[^>]*>([^<]*)</option>', segment, re.I)
    ]
    cache.set(NS, key, options)
    return options


def _resolve_issuer(issuer: str, symbol: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Retrouve (identifiant, nom officiel) d'un émetteur dans la liste AMMC."""
    options = _issuer_options()
    candidates: List[str] = []
    alias = AMMC_ISSUER_ALIASES.get(str(symbol or "").strip().upper())
    if alias:
        candidates.append(alias)
    candidates.append(issuer)
    for candidate in candidates:
        query = _normalise(candidate)
        if not query:
            continue
        for option_id, name in options:
            if _normalise(name) == query:
                return option_id, name
        tokens = [token for token in query.split() if len(token) > 2]
        if tokens:
            matches = [
                (option_id, name) for option_id, name in options
                if all(token in _normalise(name) for token in tokens)
            ]
            if len(matches) == 1:
                return matches[0]
    return None


def resolve_issuer(issuer: str, symbol: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """API publique : identifiant et libellé AMMC d'un émetteur, si trouvé."""
    return _resolve_issuer(issuer, symbol)


def ammc_documents(issuer: str, max_pages: int = 10, limit: int = 12,
                   with_pdf: bool = True, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Liste les états financiers publiés par l'AMMC pour un émetteur.

    La recherche utilise d'abord le **filtre émetteur officiel** de la page
    AMMC (identifiant stable), puis, seulement en repli, un parcours de pages.
    Lecture de la page de détail pour récupérer l'URL du PDF. Cache 24 h.
    """
    query = _normalise(issuer)
    if not query:
        return []
    cache_key = f"ammc:{query}:{symbol or ''}:{max_pages}:{limit}:{int(with_pdf)}"
    hit = cache.get(NS, cache_key, TTL["ammc"])
    if hit is not None:
        return hit

    resolved = _resolve_issuer(issuer, symbol)
    tokens = [tok for tok in query.split() if len(tok) > 2]

    # (url, filtre_serveur_fiable)
    sources: List[Tuple[str, bool]] = []
    if resolved:
        sources.append((f"{AMMC_LIST}?field_emetteur_target_id_verf={resolved[0]}", True))
    for page in range(max_pages):
        url = AMMC_LIST if page == 0 else f"{AMMC_LIST}?page={page}"
        sources.append((url, False))

    found: List[Dict[str, Any]] = []
    seen_urls: set = set()
    for url, trusted in sources:
        try:
            markup = _fetch_html(url)
        except StatementError:
            break
        page_rows = _ROW_RE.findall(markup)
        page_found = 0
        for row in page_rows:
            detail = _DETAIL_RE.search(row)
            if not detail:
                continue
            text = _normalise(_strip_tags(row))
            if tokens and not all(token in text for token in tokens):
                # La page filtrée est fiable : le libellé AMMC peut différer du
                # nom BVC (ex. IAM → MAROC TELECOM), on ne rejette donc pas.
                if not trusted:
                    continue
            clean = _strip_tags(row)
            link = f"{AMMC_BASE}{detail.group(1)}"
            if link in seen_urls:
                continue
            seen_urls.add(link)
            year = re.search(r"(20\d{2})", clean)
            found.append({
                "title": clean,
                "year": year.group(1) if year else None,
                "url": link,
                "pdf_url": None,
                "issuer_id": resolved[0] if resolved else None,
                "issuer_name": resolved[1] if resolved else None,
            })
            page_found += 1
            if len(found) >= limit:
                break
        # Si le filtre serveur a fonctionné, inutile de parcourir les pages.
        if trusted and page_found:
            break
        if len(found) >= limit:
            break

    if with_pdf:
        for item in found:
            try:
                detail_html = _fetch_html(item["url"])
            except StatementError:
                continue
            pdfs = _PDF_RE.findall(detail_html)
            if pdfs:
                item["pdf_url"] = f"{AMMC_BASE}{pdfs[0]}"
    cache.set(NS, cache_key, found)
    return found


def _strip_tags(fragment: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", fragment or ""))
    return re.sub(r"\s+", " ", text).strip()


def _normalise(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _fetch_html(url: str) -> str:
    try:
        response = requests.get(url, headers={**HTTP_HEADERS, "Accept": "text/html,*/*"},
                                timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        raise StatementError(f"AMMC injoignable ({url}) : {exc}") from exc


# ═══════════════════════════ Extraction PDF (secours) ═══════════════════════════

def fetch_bytes(url: str) -> bytes:
    """Télécharge un document (PDF AMMC) avec les en-têtes et le cache applicatifs."""
    key = f"doc:{url}"
    hit = cache.get(NS, key, TTL["ammc"])
    if isinstance(hit, (bytes, bytearray)):
        return bytes(hit)
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT * 3)
        response.raise_for_status()
        content = response.content
    except requests.RequestException as exc:
        raise StatementError(f"Téléchargement impossible ({url}) : {exc}") from exc
    cache.set(NS, key, content)
    return content


def extract_pdf_text(content: bytes) -> str:
    """Extrait le texte d'un PDF financier via ``pypdf`` (dépendance optionnelle)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise StatementError(
            "pypdf n'est pas installé : impossible d'extraire le texte du PDF. "
            "Installez-le avec « pip install pypdf » ou saisissez les postes manuellement."
        ) from exc
    import io

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise StatementError(f"PDF illisible : {exc}") from exc
    chunks = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(chunks)


# Motifs de reconnaissance (comptes sociaux, modèle normal marocain).
_PATTERNS: Dict[str, Dict[str, str]] = {
    "income": {
        "revenue": r"chiffres?\s*d[’']?\s*affaires",
        "operating_income": r"r[ée]sultat\s*d[’']?\s*exploitation",
        "ebitda": r"(ex[ée]dent\s*brut\s*d[’']?\s*exploitation|ebe\b)",
        "net_income": r"r[ée]sultat\s*net(\s*de\s*l[’']?\s*exercice)?",
        "taxes": r"imp[oô]ts?\s*sur\s*les\s*r[ée]sultats?",
    },
    "balance": {
        "total_assets": r"total\s*g[ée]n[ée]ral",
        "equity": r"(total\s*des\s*capitaux\s*propres|capitaux\s*propres\s*\(a\))",
        "total_debt": r"dettes?\s*de\s*financements?",
        "cash": r"(tr[ée]sorerie\s*[-–]?\s*actif|banques,?\s*t\.?\s*g)",
        "current_assets": r"total\s*ii\s*\(\s*f\s*\+\s*g\s*\+\s*h\s*\+\s*i\s*\)",
        "current_liabilities": r"total\s*ii\s*\(\s*f\s*\+\s*g\s*\+\s*h\s*\)",
    },
    "cashflow": {
        "operating_cf": r"capacit[ée]\s*d[’']?\s*autofinancement",
        "capex": r"acquisitions?\s*et\s*augmentations?\s*d[’']?\s*immobilisations",
        "dividends_paid": r"distributions?\s*de\s*b[ée]n[ée]fices",
    },
}

_AMOUNT_RE = re.compile(r"^[-+]?\(?\d[\d\s]*(?:[.,]\d+)?\)?$")


def _split_columns(line: str) -> List[str]:
    normalised = line.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    return [part.strip() for part in re.split(r"\s{2,}", normalised) if part.strip()]


def _amount(text: str) -> Optional[float]:
    if not _AMOUNT_RE.match(text.strip()):
        return None
    return _num(text)


def _first_amount(columns: List[str]) -> Optional[float]:
    for column in columns:
        value = _amount(column)
        if value is not None:
            return value
    return None


def key_lines(text: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Renvoyé les lignes brutes correspondant aux postes clés d'un PDF AMMC.

    Aucune valeur n'est choisie ni enregistrée : l'utilisateur voit la ligne
    d'origine (preuve) et saisit lui-même le chiffre. C'est la seule façon
    honnête de traiter des mises en page comptables hétérogènes.
    """
    compiled = {
        block: {field: re.compile(pattern, re.I) for field, pattern in patterns.items()}
        for block, patterns in _PATTERNS.items()
    }
    out: List[Dict[str, Any]] = []
    counts: Dict[Tuple[str, str], int] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or len(line) > 300:
            continue
        for block, patterns in compiled.items():
            for field, regex in patterns.items():
                key = (block, field)
                if counts.get(key, 0) >= limit or not regex.search(line):
                    continue
                counts[key] = counts.get(key, 0) + 1
                out.append({"block": block, "field": field, "line": line})
    return out


def parse_social_statements(text: str) -> Dict[str, Any]:
    """Heuristique de pré-remplissage **indicative** depuis un PDF AMMC.

    ATTENTION : la mise en page des rapports est hétérogène et des tableaux de
    commentaire peuvent ressembler aux états financiers. Ce résultat ne doit
    jamais être enregistré sans vérification humaine ligne à ligne. L'interface
    l'affiche comme simple aide, à côté des lignes brutes (``key_lines``).
    """
    result: Dict[str, Any] = {"income": {}, "balance": {}, "cashflow": {}, "matches": []}
    compiled = {
        block: {field: re.compile(pattern, re.I) for field, pattern in patterns.items()}
        for block, patterns in _PATTERNS.items()
    }
    seen: set = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or len(line) > 260:
            continue
        columns = _split_columns(line)
        if len(columns) < 2:
            continue
        label = columns[0]
        for block, patterns in compiled.items():
            for field, regex in patterns.items():
                if (block, field) in seen or not regex.search(label):
                    continue
                value = _first_amount(columns[1:])
                if value is None:
                    continue
                result[block][field] = value
                seen.add((block, field))
                result["matches"].append({
                    "block": block, "field": field, "label": label, "value": value,
                })
    return result
