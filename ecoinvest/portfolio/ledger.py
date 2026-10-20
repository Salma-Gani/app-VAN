"""Journal d'opérations de portefeuille (achats, ventes, frais, dividendes, trésorerie).

Ce module comble un manque du modèle historique, qui ne conservait qu'une
position agrégée (quantité, prix d'achat, date). Il fournit :

- un **journal d'opérations** persisté (JSON local) et validé ;
- le calcul des **positions** (coût de revient moyen pondéré) ;
- les **plus-values réalisées** (ventes) et **latentes** (cours fournis) ;
- le **solde de trésorerie** reconstitué à partir des flux ;
- les **dividendes** et **frais** cumulés.

Conventions explicites :

- méthode du **coût moyen pondéré** (pas de FIFO) ;
- les frais d'une opération d'achat sont **inclus** dans le coût de revient ;
- une vente supérieure à la position détenue est **signalée**, jamais masquée ;
- un cours manquant n'est jamais remplacé : la plus-value latente devient
  indisponible pour ce titre, et le total le précise.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..config import USER_LEDGER_FILE

KINDS = ("buy", "sell", "dividend", "fee", "deposit", "withdrawal")

KIND_LABELS: Dict[str, str] = {
    "buy": "Achat",
    "sell": "Vente",
    "dividend": "Dividende",
    "fee": "Frais",
    "deposit": "Apport",
    "withdrawal": "Retrait",
}

# Opérations qui portent un titre.
SECURITY_KINDS = ("buy", "sell", "dividend")


class LedgerError(Exception):
    """Opération invalide ou fichier illisible."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path, default: Any) -> Any:
    import json

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    import json
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _new_id() -> str:
    return f"tx_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


def validate(transaction: Dict[str, Any]) -> Dict[str, Any]:
    """Nettoie et valide une opération. Lève ``LedgerError`` si invalide."""
    kind = str(transaction.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise LedgerError(
            f"Type d'opération inconnu : « {kind} ». Types acceptés : {', '.join(KINDS)}."
        )
    symbol = str(transaction.get("symbol") or "").strip().upper()
    if kind in SECURITY_KINDS and not symbol:
        raise LedgerError(f"Le type « {KIND_LABELS[kind]} » exige un symbole.")
    quantity = _num(transaction.get("quantity"))
    price = _num(transaction.get("price"))
    fees = _num(transaction.get("fees")) or 0.0
    amount = _num(transaction.get("amount"))

    if kind in ("buy", "sell"):
        if quantity is None or quantity <= 0:
            raise LedgerError("La quantité doit être strictement positive.")
        if price is None or price < 0:
            raise LedgerError("Le prix doit être renseigné et positif.")
    if kind in ("dividend",):
        if amount is None and (quantity is None or price is None):
            raise LedgerError("Un dividende exige un montant, ou une quantité et un prix.")
        if amount is None:
            amount = quantity * price
    if kind in ("fee", "deposit", "withdrawal"):
        if amount is None or amount <= 0:
            raise LedgerError(f"Le type « {KIND_LABELS[kind]} » exige un montant positif.")
    if fees < 0:
        raise LedgerError("Les frais ne peuvent pas être négatifs.")

    date = str(transaction.get("date") or "").strip() or _now()[:10]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise LedgerError(f"Date invalide « {date} » (format attendu AAAA-MM-JJ).") from exc

    return {
        "id": str(transaction.get("id") or _new_id()),
        "date": date,
        "kind": kind,
        "symbol": symbol,
        "quantity": quantity if kind in SECURITY_KINDS else None,
        "price": price if kind in ("buy", "sell") else None,
        "amount": amount if amount is not None else (
            quantity * price if kind in ("buy", "sell") and quantity and price else None
        ),
        "fees": fees,
        "currency": str(transaction.get("currency") or "MAD").upper(),
        "note": str(transaction.get("note") or "").strip(),
        "created_at": str(transaction.get("created_at") or _now()),
    }


def load_transactions(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Opérations enregistrées, triées par date puis date de création."""
    payload = _read_json(path or USER_LEDGER_FILE, [])
    if isinstance(payload, dict):
        payload = payload.get("transactions") or []
    if not isinstance(payload, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            cleaned.append(validate(item))
        except LedgerError:
            continue
    cleaned.sort(key=lambda tx: (tx["date"], tx["created_at"], tx["id"]))
    return cleaned


def save_transactions(transactions: List[Dict[str, Any]], path: Optional[Path] = None) -> None:
    _write_json(path or USER_LEDGER_FILE, [validate(tx) for tx in transactions])


def add_transaction(transaction: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    transaction = validate(transaction)
    transactions = load_transactions(path)
    transactions.append(transaction)
    save_transactions(transactions, path)
    return transaction


def delete_transaction(transaction_id: str, path: Optional[Path] = None) -> bool:
    transactions = load_transactions(path)
    remaining = [tx for tx in transactions if tx["id"] != transaction_id]
    if len(remaining) == len(transactions):
        return False
    save_transactions(remaining, path)
    return True


# ═══════════════════════════ Calculs ═══════════════════════════

def transactions_frame(transactions: List[Dict[str, Any]]) -> pd.DataFrame:
    columns = ["Date", "Opération", "Symbole", "Quantité", "Prix", "Montant", "Frais", "Devise", "Note"]
    rows = []
    for tx in transactions:
        rows.append({
            "Date": tx.get("date"),
            "Opération": KIND_LABELS.get(tx.get("kind"), tx.get("kind")),
            "Symbole": tx.get("symbol") or "—",
            "Quantité": tx.get("quantity"),
            "Prix": tx.get("price"),
            "Montant": tx.get("amount"),
            "Frais": tx.get("fees"),
            "Devise": tx.get("currency"),
            "Note": tx.get("note"),
        })
    return pd.DataFrame(rows, columns=columns)


def compute_positions(transactions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Coût de revient moyen, quantités, dividendes, frais et réalisé par titre.

    Une vente supérieure à la position détenue est signalée dans ``issues``
    (jamais corrigée en silence).
    """
    positions: Dict[str, Dict[str, Any]] = {}
    for tx in sorted(transactions, key=lambda t: (t["date"], t["created_at"], t["id"])):
        kind = tx["kind"]
        symbol = tx.get("symbol")
        if kind not in SECURITY_KINDS or not symbol:
            continue
        position = positions.setdefault(symbol, {
            "symbol": symbol, "quantity": 0.0, "avg_cost": 0.0,
            "invested": 0.0, "realized_pnl": 0.0, "dividends": 0.0,
            "fees": 0.0, "issues": [],
        })
        fees = float(tx.get("fees") or 0.0)
        position["fees"] += fees
        if kind == "buy":
            quantity = float(tx["quantity"])
            cost = quantity * float(tx["price"]) + fees
            new_quantity = position["quantity"] + quantity
            position["avg_cost"] = (
                (position["quantity"] * position["avg_cost"] + cost) / new_quantity
                if new_quantity else 0.0
            )
            position["quantity"] = new_quantity
        elif kind == "sell":
            quantity = float(tx["quantity"])
            if quantity > position["quantity"] + 1e-9:
                position["issues"].append(
                    f"Vente de {quantity:g} {symbol} supérieure à la position "
                    f"détenue ({position['quantity']:g}) au {tx['date']}."
                )
                quantity = position["quantity"]
            proceeds = quantity * float(tx["price"]) - fees
            position["realized_pnl"] += proceeds - quantity * position["avg_cost"]
            position["quantity"] -= quantity
            if position["quantity"] <= 1e-9:
                position["quantity"] = 0.0
                position["avg_cost"] = 0.0
        elif kind == "dividend":
            position["dividends"] += float(tx.get("amount") or 0.0)
        position["invested"] = position["quantity"] * position["avg_cost"]
    return positions


def cash_from_flows(transactions: List[Dict[str, Any]]) -> float:
    """Solde de trésorerie reconstitué à partir des seuls flux enregistrés."""
    balance = 0.0
    for tx in transactions:
        kind = tx["kind"]
        fees = float(tx.get("fees") or 0.0)
        if kind == "deposit":
            balance += float(tx.get("amount") or 0.0)
        elif kind == "withdrawal":
            balance -= float(tx.get("amount") or 0.0)
        elif kind == "buy":
            balance -= float(tx["quantity"]) * float(tx["price"]) + fees
        elif kind == "sell":
            balance += float(tx["quantity"]) * float(tx["price"]) - fees
        elif kind == "dividend":
            balance += float(tx.get("amount") or 0.0)
        elif kind == "fee":
            balance -= float(tx.get("amount") or 0.0)
    return balance


def positions_frame(positions: Dict[str, Dict[str, Any]], prices: Optional[Dict[str, float]] = None) -> pd.DataFrame:
    """Tableau des positions, avec plus-value latente si un cours est fourni."""
    prices = prices or {}
    columns = ["Symbole", "Quantité", "Coût de revient moyen", "Investi",
               "Cours", "Valeur", "Plus-value latente", "Dividendes", "Frais",
               "Plus-value réalisée"]
    rows = []
    for symbol, position in positions.items():
        price = _num(prices.get(symbol))
        quantity = position["quantity"]
        invested = position["invested"]
        value = quantity * price if price is not None else None
        unrealized = value - invested if value is not None else None
        rows.append({
            "Symbole": symbol,
            "Quantité": quantity,
            "Coût de revient moyen": position["avg_cost"] or None,
            "Investi": invested or None,
            "Cours": price,
            "Valeur": value,
            "Plus-value latente": unrealized,
            "Dividendes": position["dividends"] or None,
            "Frais": position["fees"] or None,
            "Plus-value réalisée": position["realized_pnl"],
        })
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame = frame.sort_values("Valeur", ascending=False, na_position="last").reset_index(drop=True)
    return frame


def summary(transactions: List[Dict[str, Any]], prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Synthèse chiffrée du portefeuille, avec les manques explicités."""
    prices = prices or {}
    positions = compute_positions(transactions)
    invested = sum(p["invested"] for p in positions.values())
    realized = sum(p["realized_pnl"] for p in positions.values())
    dividends = sum(p["dividends"] for p in positions.values())
    fees = sum(float(tx.get("fees") or 0.0) for tx in transactions) + \
        sum(float(tx.get("amount") or 0.0) for tx in transactions if tx["kind"] == "fee")
    cash = cash_from_flows(transactions)

    market_value = 0.0
    missing_prices: List[str] = []
    unrealized = 0.0
    for symbol, position in positions.items():
        if position["quantity"] <= 1e-9:
            continue
        price = _num(prices.get(symbol))
        if price is None:
            if symbol not in missing_prices:
                missing_prices.append(symbol)
            continue
        value = position["quantity"] * price
        market_value += value
        unrealized += value - position["invested"]

    net_deposits = sum(float(tx.get("amount") or 0.0) for tx in transactions if tx["kind"] == "deposit") - \
        sum(float(tx.get("amount") or 0.0) for tx in transactions if tx["kind"] == "withdrawal")

    return {
        "positions": len([p for p in positions.values() if p["quantity"] > 1e-9]),
        "invested": invested,
        "market_value": market_value,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "dividends": dividends,
        "fees": fees,
        "cash": cash,
        "net_deposits": net_deposits,
        "total_value": market_value + cash,
        "missing_prices": missing_prices,
    }


__all__ = [
    "KINDS", "KIND_LABELS", "LedgerError", "add_transaction", "cash_from_flows",
    "compute_positions", "delete_transaction", "load_transactions", "positions_frame",
    "save_transactions", "summary", "transactions_frame", "validate",
]
