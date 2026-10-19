#!/usr/bin/env python3
"""Préchauffage des données Market Mind.

Ce script télécharge et met en cache toutes les sources réelles utilisées par
l'application (BVC, Yahoo Finance, flux RSS) puis affiche un rapport de
couverture. Il est utile pour :

* préparer une démonstration sans attendre les premiers chargements ;
* vérifier que les sources sont joignables avant de lancer Streamlit ;
* régénérer les fichiers de référence dans ``data/seed/``.

Usage :
    python scripts/refresh_data.py
    python scripts/refresh_data.py --force --days 750
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecoinvest.analytics import scoring  # noqa: E402
from ecoinvest.data import bvc, fundamentals, market, news  # noqa: E402


def _step(name: str, func: Callable[[], Any], show: Optional[Callable[[Any], str]] = None) -> Any:
    print(f"→ {name:<42}", end=" ", flush=True)
    started = time.time()
    try:
        result = func()
    except Exception as exc:  # pragma: no cover - dépend du réseau
        print(f"ÉCHEC ({time.time() - started:.1f} s) — {exc}")
        return None
    elapsed = time.time() - started
    detail = ""
    if show is not None:
        try:
            detail = " · " + show(result)
        except Exception:
            detail = ""
    print(f"OK ({elapsed:.1f} s){detail}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Préchauffe les données d'Market Mind.")
    parser.add_argument("--force", action="store_true", help="Ignore les caches existants.")
    parser.add_argument("--days", type=int, default=500, help="Profondeur d'historique (jours).")
    parser.add_argument("--skip-news", action="store_true", help="Ne pas interroger les flux RSS.")
    args = parser.parse_args()

    print("═" * 72)
    print("  Market Mind — rafraîchissement des données réelles")
    print("═" * 72)

    universe = _step(
        "Univers des valeurs (BVC)",
        lambda: bvc.universe(force=args.force),
        lambda df: f"{len(df)} valeurs",
    )
    indices = _step(
        "Indices (BVC)",
        lambda: bvc.index_table(force=args.force),
        lambda df: f"{len(df)} indices",
    )
    reference = _step(
        "Référentiel + dividendes (BVC)",
        lambda: bvc.reference_data(force=args.force),
        lambda d: f"{len(d)} sociétés · {sum(1 for v in d.values() if v.get('dps'))} dividendes",
    )
    snapshot = _step(
        "Cours et volumes (BVC)",
        lambda: bvc.snapshot(force=args.force, days=args.days),
        lambda df: f"{len(df)} lignes",
    )
    table = _step(
        "Tableau enrichi (technique, risque, scores)",
        lambda: scoring.build_market_table(force=args.force),
        lambda df: f"{df.shape[0]} × {df.shape[1]}",
    )
    regime = _step(
        "Régime de marché (MASI, VIX, largeur)",
        lambda: scoring.market_regime(force=args.force),
        lambda r: f"{r.get('label', '—')} · porte {r.get('entry_gate', 0):+.2f}",
    )
    if not args.skip_news:
        _step(
            "Actualités (RSS publics)",
            lambda: news.fetch_all_news(force=args.force),
            lambda df: f"{len(df)} articles",
        )
    quotes = _step(
        "Marchés internationaux (Yahoo Finance)",
        lambda: market.global_quotes(force=args.force),
        lambda df: f"{len(df)} instruments",
    )

    if table is not None and not table.empty:
        coverage = fundamentals.coverage_report(table)
        out = ROOT / "data" / "seed" / "fundamentals_coverage.csv"
        coverage.to_csv(out, index=False, encoding="utf-8-sig")
        filled = int((coverage["% complétion"] > 0).sum())
        print(f"\n→ Rapport de couverture fondamentale : {out}")
        print(f"  {filled}/{len(coverage)} sociétés couvertes "
              f"(nombre de titres + dividende BVC inclus).")

    print("\n" + "═" * 72)
    print("  Terminé. Lancez :  streamlit run app.py")
    print("═" * 72)

    ok = all(x is not None for x in (universe, indices, reference, snapshot, table, regime, quotes))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
