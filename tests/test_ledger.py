"""Tests du journal d'opérations (coût moyen, réalisé/latent, trésorerie)."""
from __future__ import annotations

import pathlib
import tempfile
import unittest

import pandas as pd

from ecoinvest.portfolio import ledger


def tx(kind, **kwargs):
    base = {"kind": kind, "date": "2024-01-01", "fees": 0.0, "currency": "MAD"}
    base.update(kwargs)
    return base


class TestValidation(unittest.TestCase):
    def test_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ledger.LedgerError):
            ledger.validate({"kind": "transfer"})

    def test_requires_symbol_for_security(self) -> None:
        with self.assertRaises(ledger.LedgerError):
            ledger.validate(tx("buy", quantity=10, price=100))

    def test_rejects_negative_quantity_and_price(self) -> None:
        with self.assertRaises(ledger.LedgerError):
            ledger.validate(tx("buy", symbol="ATW", quantity=-1, price=100))
        with self.assertRaises(ledger.LedgerError):
            ledger.validate(tx("buy", symbol="ATW", quantity=1, price=-5))

    def test_rejects_bad_date_and_negative_fees(self) -> None:
        with self.assertRaises(ledger.LedgerError):
            ledger.validate(tx("buy", symbol="ATW", quantity=1, price=10, date="31/12/2024"))
        with self.assertRaises(ledger.LedgerError):
            ledger.validate(tx("buy", symbol="ATW", quantity=1, price=10, fees=-1))

    def test_accepts_deposit_and_dividend(self) -> None:
        self.assertEqual(ledger.validate(tx("deposit", amount=10000))["kind"], "deposit")
        self.assertAlmostEqual(
            ledger.validate(tx("dividend", symbol="ATW", amount=250))["amount"], 250.0
        )


class TestPositions(unittest.TestCase):
    def test_average_cost_includes_buy_fees(self) -> None:
        txs = [
            ledger.validate(tx("buy", symbol="ATW", quantity=10, price=100, fees=6, date="2024-01-01")),
            ledger.validate(tx("buy", symbol="ATW", quantity=10, price=120, fees=6, date="2024-02-01")),
        ]
        position = ledger.compute_positions(txs)["ATW"]
        self.assertAlmostEqual(position["quantity"], 20.0)
        self.assertAlmostEqual(position["avg_cost"], (1006 + 1206) / 20.0)

    def test_realized_pnl_on_sale(self) -> None:
        txs = [
            ledger.validate(tx("buy", symbol="ATW", quantity=10, price=100, fees=0, date="2024-01-01")),
            ledger.validate(tx("sell", symbol="ATW", quantity=4, price=150, fees=2, date="2024-03-01")),
        ]
        position = ledger.compute_positions(txs)["ATW"]
        self.assertAlmostEqual(position["quantity"], 6.0)
        self.assertAlmostEqual(position["realized_pnl"], 4 * 150 - 2 - 4 * 100)
        self.assertAlmostEqual(position["avg_cost"], 100.0)

    def test_oversell_is_flagged_not_hidden(self) -> None:
        txs = [
            ledger.validate(tx("buy", symbol="ATW", quantity=5, price=100)),
            ledger.validate(tx("sell", symbol="ATW", quantity=9, price=110)),
        ]
        position = ledger.compute_positions(txs)["ATW"]
        self.assertEqual(position["quantity"], 0.0)
        self.assertTrue(position["issues"])
        self.assertIn("supérieure", position["issues"][0])

    def test_dividends_accumulate(self) -> None:
        txs = [
            ledger.validate(tx("buy", symbol="TMA", quantity=10, price=1000)),
            ledger.validate(tx("dividend", symbol="TMA", amount=500, date="2024-06-01")),
        ]
        self.assertAlmostEqual(ledger.compute_positions(txs)["TMA"]["dividends"], 500.0)


class TestCashAndSummary(unittest.TestCase):
    def _txs(self):
        return [
            ledger.validate(tx("deposit", amount=10000, date="2024-01-01")),
            ledger.validate(tx("buy", symbol="ATW", quantity=10, price=100, fees=6, date="2024-01-02")),
            ledger.validate(tx("sell", symbol="ATW", quantity=2, price=150, fees=2, date="2024-02-01")),
            ledger.validate(tx("dividend", symbol="ATW", amount=30, date="2024-03-01")),
            ledger.validate(tx("fee", amount=5, date="2024-03-02")),
        ]

    def test_cash_is_reconstructed_from_flows(self) -> None:
        # 10000 - 1006 + (300-2) + 30 - 5
        self.assertAlmostEqual(ledger.cash_from_flows(self._txs()), 10000 - 1006 + 298 + 30 - 5)

    def test_summary_reports_missing_prices(self) -> None:
        report = ledger.summary(self._txs(), prices={})
        self.assertIn("ATW", report["missing_prices"])
        self.assertEqual(report["market_value"], 0.0)
        self.assertAlmostEqual(report["dividends"], 30.0)

    def test_summary_with_price(self) -> None:
        report = ledger.summary(self._txs(), prices={"ATW": 200.0})
        self.assertEqual(report["missing_prices"], [])
        self.assertAlmostEqual(report["market_value"], 8 * 200.0)
        # Coût de revient moyen = 1006 / 10 = 100,60 → investi 8 × 100,60.
        self.assertAlmostEqual(report["unrealized_pnl"], 8 * 200.0 - 8 * 100.6)

    def test_positions_frame_keeps_missing_value_empty(self) -> None:
        positions = ledger.compute_positions(self._txs())
        frame = ledger.positions_frame(positions, prices={})
        row = frame[frame["Symbole"] == "ATW"].iloc[0]
        self.assertTrue(pd.isna(row["Valeur"]))
        self.assertTrue(pd.isna(row["Plus-value latente"]))


class TestPersistence(unittest.TestCase):
    def test_roundtrip_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "transactions.json"
            saved = ledger.add_transaction(
                tx("deposit", amount=5000), path=path,
            )
            ledger.add_transaction(tx("buy", symbol="IAM", quantity=3, price=100), path=path)
            loaded = ledger.load_transactions(path)
            self.assertEqual(len(loaded), 2)
            self.assertTrue(ledger.delete_transaction(saved["id"], path=path))
            self.assertEqual(len(ledger.load_transactions(path)), 1)

    def test_corrupted_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "transactions.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(ledger.load_transactions(path), [])


if __name__ == "__main__":
    unittest.main()
