"""Données fondamentales, ratios comptables et leur interprétation.

Trois niveaux de provenance, clairement distingués dans l'interface :

1. **Calculé depuis le marché** (toujours réel) — capitalisation, nombre de titres,
   fourchette 52 semaines, dividend yield si le DPA est connu.
2. **Live** — pour les valeurs internationales via Yahoo Finance.
3. **Saisi / importé** — l'utilisateur complète les états financiers (résultat net,
   chiffre d'affaires, fonds propres, FCF, DPA) via le formulaire ou un CSV.
   Persisté dans ``data/user/fundamentals_overrides.json``.

Aucune donnée fondamentale n'est inventée : toute valeur non renseignée ressort
à ``None`` et s'affiche « — ».
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from ..config import SEED_DIR, TTL, USER_FUNDAMENTALS_FILE
from ..utils import cache
from ..utils.formatting import as_float, safe_div
from .http import record_exception

NS = "fundamentals"
STORE_SEED = SEED_DIR / "bvc_fundamentals.json"

# Secteurs pour lesquels les multiples d'entreprise et le levier ne sont pas
# pertinents (bilan bancaire / assurantiel).
FINANCIAL_SECTOR_KEYWORDS = (
    "banque", "assurance", "finance", "société de financement",
    "sociétés de financement", "holding financière",
)


def is_financial_sector(sector: Optional[str]) -> bool:
    """Vrai pour les banques, assurances et sociétés de financement."""
    low = (sector or "").lower()
    return any(word in low for word in FINANCIAL_SECTOR_KEYWORDS)

# ═══════════════════════════ Schéma des champs ═══════════════════════════
FIELD_SCHEMA: List[Dict[str, Any]] = [
    {"key": "revenue", "label": "Chiffre d'affaires", "unit": "MAD", "group": "Compte de résultat", "hint": "Ventes nettes du dernier exercice"},
    {"key": "ebitda", "label": "EBITDA", "unit": "MAD", "group": "Compte de résultat", "hint": "Résultat d'exploitation avant amortissements"},
    {"key": "ebit", "label": "Résultat d'exploitation", "unit": "MAD", "group": "Compte de résultat", "hint": "EBIT"},
    {"key": "net_income", "label": "Résultat net", "unit": "MAD", "group": "Compte de résultat", "hint": "Résultat net part du groupe"},
    {"key": "eps", "label": "BPA (résultat par action)", "unit": "MAD/action", "group": "Compte de résultat", "hint": "Calculé automatiquement si le nombre de titres est connu"},
    {"key": "fcf", "label": "Free Cash-Flow", "unit": "MAD", "group": "Trésorerie", "hint": "Flux de trésorerie disponible après investissements"},
    {"key": "operating_cf", "label": "Cash-flow d'exploitation", "unit": "MAD", "group": "Trésorerie", "hint": "Capacité d'autofinancement"},
    {"key": "capex", "label": "Investissements (Capex)", "unit": "MAD", "group": "Trésorerie", "hint": "Acquisitions d'immobilisations"},
    {"key": "equity", "label": "Capitaux propres", "unit": "MAD", "group": "Bilan", "hint": "Fonds propres part du groupe"},
    {"key": "total_debt", "label": "Dette financière", "unit": "MAD", "group": "Bilan", "hint": "Dette brute (court + long terme)"},
    {"key": "cash", "label": "Trésorerie & équivalents", "unit": "MAD", "group": "Bilan", "hint": "Disponibilités"},
    {"key": "total_assets", "label": "Total du bilan", "unit": "MAD", "group": "Bilan", "hint": "Total actif"},
    {"key": "current_assets", "label": "Actif circulant", "unit": "MAD", "group": "Bilan", "hint": "Actif à court terme"},
    {"key": "current_liabilities", "label": "Passif circulant", "unit": "MAD", "group": "Bilan", "hint": "Dettes à court terme"},
    {"key": "shares", "label": "Nombre de titres", "unit": "titres", "group": "Marché", "hint": "Déduit de la capitalisation si laissé vide"},
    {"key": "dps", "label": "Dividende par action", "unit": "MAD/action", "group": "Actionnariat", "hint": "Montant brut distribué"},
    {"key": "payout", "label": "Taux de distribution", "unit": "%", "group": "Actionnariat", "hint": "Part du résultat net versée"},
    {"key": "revenue_growth", "label": "Croissance du CA", "unit": "%", "group": "Historique", "hint": "Variation sur le dernier exercice"},
    {"key": "net_income_growth", "label": "Croissance du résultat net", "unit": "%", "group": "Historique", "hint": "Variation sur le dernier exercice"},
    {"key": "fcf_growth", "label": "Croissance du FCF", "unit": "%", "group": "Historique", "hint": "Taux de croissance moyen"},
    {"key": "beta", "label": "Bêta", "unit": "x", "group": "Marché", "hint": "Sensibilité au MASI (calculée si vide)"},
    {"key": "fiscal_year", "label": "Exercice de référence", "unit": "", "group": "Métadonnées", "hint": "Ex. 2024"},
    {"key": "source", "label": "Source", "unit": "", "group": "Métadonnées", "hint": "Ex. rapport annuel 2024, Investing, BVC"},
    {"key": "as_of", "label": "Date de mise à jour", "unit": "", "group": "Métadonnées", "hint": "AAAA-MM-JJ"},
]

FIELD_KEYS = [f["key"] for f in FIELD_SCHEMA]
FIELD_LABELS = {f["key"]: f["label"] for f in FIELD_SCHEMA}

NUMERIC_FIELDS = {
    "revenue", "ebitda", "ebit", "net_income", "eps", "fcf", "operating_cf", "capex",
    "equity", "total_debt", "cash", "total_assets", "current_assets", "current_liabilities",
    "shares", "dps", "payout", "revenue_growth", "net_income_growth", "fcf_growth", "beta",
}

# Champs exprimés en pourcentage : stockés en fraction (0,08 = 8 %).
PERCENT_FIELDS = {"payout", "revenue_growth", "net_income_growth", "fcf_growth"}

# ═══════════════════════════ Persistance ═══════════════════════════

def _read_json(path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def load_store() -> Dict[str, Dict[str, Any]]:
    """Charge le magasin fondamental (seed + saisies utilisateur fusionnées)."""
    seed = _read_json(STORE_SEED, {})
    if isinstance(seed, dict) and "companies" in seed:
        seed = seed["companies"]
    if not isinstance(seed, dict):
        seed = {}
    user = _read_json(USER_FUNDAMENTALS_FILE, {})
    if not isinstance(user, dict):
        user = {}
    merged = {k: dict(v) for k, v in seed.items()}
    for symbol, record in user.items():
        merged.setdefault(symbol, {})
        merged[symbol].update(record or {})
    return merged


def save_override(symbol: str, record: Dict[str, Any]) -> None:
    """Enregistre les données saisies pour une valeur."""
    symbol = symbol.strip().upper()
    cleaned: Dict[str, Any] = {}
    for key, value in (record or {}).items():
        if key not in FIELD_KEYS:
            continue
        if key in NUMERIC_FIELDS:
            cleaned[key] = as_float(value)
        else:
            cleaned[key] = value
    cleaned["as_of"] = cleaned.get("as_of") or datetime.now().strftime("%Y-%m-%d")
    store = _read_json(USER_FUNDAMENTALS_FILE, {})
    if not isinstance(store, dict):
        store = {}
    store[symbol] = {**store.get(symbol, {}), **{k: v for k, v in cleaned.items() if v is not None}}
    with open(USER_FUNDAMENTALS_FILE, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=1)
    cache.clear(NS)


def delete_override(symbol: str) -> None:
    store = _read_json(USER_FUNDAMENTALS_FILE, {})
    if isinstance(store, dict) and symbol.strip().upper() in store:
        store.pop(symbol.strip().upper())
        with open(USER_FUNDAMENTALS_FILE, "w", encoding="utf-8") as fh:
            json.dump(store, fh, ensure_ascii=False, indent=1)
        cache.clear(NS)


def import_csv(content: bytes) -> Dict[str, Any]:
    """Importe un CSV de fondamentaux (une ligne par société).

    Colonnes attendues : ``symbol`` puis tout ou partie des champs du schéma.
    """
    text = content.decode("utf-8-sig", errors="replace")
    dialect = ";" if text.count(";") > text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=dialect)
    imported, errors = 0, []
    for row in reader:
        symbol = (row.get("symbol") or row.get("Symbole") or row.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        record: Dict[str, Any] = {}
        for field in FIELD_SCHEMA:
            raw = row.get(field["key"])
            if raw in (None, ""):
                continue
            if field["key"] in NUMERIC_FIELDS:
                val = as_float(str(raw).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                if val is not None:
                    # Tolère « 8 » (pour 8 %) comme « 0,08 ».
                    if field["key"] in PERCENT_FIELDS and abs(val) > 1:
                        val = val / 100.0
                    record[field["key"]] = val
            else:
                record[field["key"]] = str(raw).strip()
        if record:
            try:
                save_override(symbol, record)
                imported += 1
            except OSError as exc:
                errors.append(f"{symbol}: {exc}")
    return {"imported": imported, "errors": errors}


def template_csv() -> str:
    """CSV vierge prêt à compléter."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["symbol"] + FIELD_KEYS)
    writer.writerow(["ATW"] + [""] * len(FIELD_KEYS))
    return buf.getvalue()


# ═══════════════════════════ Construction d'un dossier ═══════════════════════════

def get_record(symbol: str) -> Dict[str, Any]:
    """Fiche fondamentale brute d'une valeur (sans enrichissement marché).

    Les états financiers vérifiés/importés servent de base ; une saisie manuelle
    de l'utilisateur reste toujours prioritaire (elle est fusionnée par-dessus).
    """
    symbol = symbol.strip().upper()
    manual = dict(load_store().get(symbol, {}))
    try:
        from . import statements

        derived = statements.fundamentals_for(symbol)
    except Exception:
        derived = {}
    if not derived:
        return manual
    merged = dict(derived)
    merged.update(manual)
    return merged


def market_reference(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Référentiel officiel BVC : nombre de titres, ISIN et dernier dividende par action.

    Ces données sont publiques et réelles (pages « marchés-produits/actions » et
    « calendrier financier » de la Bourse de Casablanca). Elles ne sont **pas** des
    états financiers : elles servent à calculer le rendement du dividende et à valider
    le nombre de titres.
    """
    key = "market_reference"
    if not force:
        hit = cache.get(NS, key, TTL["fundamentals"])
        if hit is not None:
            return hit
    try:
        from . import bvc

        ref = bvc.reference_data(force=force)
    except Exception as exc:
        record_exception("Référentiel BVC", exc)
        ref = {}
    cache.set(NS, key, ref)
    return ref


def get_fundamentals(symbol: str, market_row: Optional[pd.Series] = None) -> Dict[str, Any]:
    """Fiche fondamentale enrichie : données saisies + référentiel BVC + métriques dérivées.

    ``market_row`` : ligne du snapshot BVC (cours, capitalisation, volatilité…).
    """
    symbol = symbol.strip().upper()
    rec = get_record(symbol)
    out: Dict[str, Any] = dict(rec)

    # ─── Référentiel officiel BVC (titres, ISIN, DPS) ───
    ref = market_reference().get(symbol, {}) or {}
    if ref:
        if ref.get("isin"):
            out.setdefault("isin", ref.get("isin"))
        if as_float(out.get("shares")) is None and as_float(ref.get("shares")) is not None:
            out["shares"] = float(ref["shares"])
        if as_float(out.get("dps")) is None and as_float(ref.get("dps")) is not None:
            out["dps"] = float(ref["dps"])
            out["dps_year"] = ref.get("dps_year")
            out["dps_type"] = ref.get("dps_type")
        if ref.get("compartment"):
            out.setdefault("compartment", ref.get("compartment"))

    price = None
    cap = None
    if market_row is not None:
        price = as_float(market_row.get("close"))
        cap = as_float(market_row.get("cap"))
        out["beta"] = out.get("beta") or None
    if price is None:
        price = as_float(rec.get("last_price"))
    if cap is not None and price:
        out.setdefault("market_cap", cap)
        if not out.get("shares"):
            out["shares"] = cap / price

    shares = as_float(out.get("shares"))
    if shares and not out.get("eps") and out.get("net_income") is not None:
        out["eps"] = out["net_income"] / shares
    if shares and not out.get("bvps") and out.get("equity") is not None:
        out["bvps"] = out["equity"] / shares
    if shares and not out.get("fcf_per_share") and out.get("fcf") is not None:
        out["fcf_per_share"] = out["fcf"] / shares
    if not out.get("dps") and out.get("net_income") and out.get("payout"):
        out["dps"] = out["net_income"] * as_float(out["payout"], ) / shares if shares else None

    out["price"] = price
    bvc_data = bool(as_float(ref.get("shares")) is not None or as_float(ref.get("dps")) is not None)
    out["_bvc"] = bvc_data
    manual_record = load_store().get(symbol) or {}
    manual = bool(manual_record)
    # Rendre explicites les champs saisis à la main : ils ne doivent jamais
    # être présentés comme issus d'un état financier vérifié.
    out["manual_fields"] = sorted(
        key for key in manual_record.keys() if key not in {"as_of", "updated_at"}
    )
    has_statement = bool(rec.get("statement_source"))
    if has_statement and manual:
        out["_source"] = "états financiers + saisie utilisateur"
    elif has_statement and bvc_data:
        out["_source"] = "états financiers (source documentée) + référentiel BVC"
    elif has_statement:
        out["_source"] = "états financiers (source documentée)"
    elif manual and bvc_data:
        out["_source"] = "saisie + référentiel BVC"
    elif manual:
        out["_source"] = "saisie/import"
    elif bvc_data:
        out["_source"] = "BVC (titres, dividende)"
    else:
        out["_source"] = "non renseigné"
    return out


# ═══════════════════════════ Ratios ═══════════════════════════

def compute_ratios(f: Dict[str, Any], price: Optional[float] = None, cap: Optional[float] = None,
                   sector: Optional[str] = None) -> Dict[str, Optional[float]]:
    """Calcule l'ensemble des ratios à partir d'une fiche fondamentale.

    ``sector`` permet de neutraliser les multiples d'entreprise et le levier
    pour les banques et assurances. Aucune donnée manquante n'est remplacée par
    zéro : un EV ou un levier non calculable reste ``None``.
    """
    price = as_float(price) or as_float(f.get("price"))
    cap = as_float(cap) or as_float(f.get("market_cap"))
    # Champs de calcul : certains postes utiles aux ratios (charges d'intérêts,
    # marge brute, impôts) ne font pas partie du formulaire de saisie, mais
    # doivent rester disponibles lorsqu'ils proviennent d'un état financier.
    calc_fields = set(NUMERIC_FIELDS) | {
        "market_cap", "bvps", "eps", "fcf_per_share",
        "interest_expense", "gross_profit", "depreciation", "taxes",
    }
    rec = {k: as_float(v) for k, v in f.items() if k in calc_fields}
    shares = rec.get("shares")
    net_income = rec.get("net_income")
    revenue = rec.get("revenue")
    ebitda = rec.get("ebitda")
    equity = rec.get("equity")
    debt = rec.get("total_debt")
    cash = rec.get("cash")
    dps = rec.get("dps")
    bvps = rec.get("bvps") or (safe_div(equity, shares) if shares and equity else None)
    fcf = rec.get("fcf")
    eps = rec.get("eps")
    financial = is_financial_sector(sector)

    # La dette nette n'est calculée que si la dette ET la trésorerie sont
    # renseignées : une donnée absente n'est jamais assimilée à zéro.
    net_debt = (debt - cash) if (debt is not None and cash is not None) else None
    ev = (cap + net_debt) if (cap is not None and net_debt is not None) else None

    ratios: Dict[str, Optional[float]] = {}
    # Les ratios de valorisation ne sont calculés que si le dénominateur est
    # strictement positif : un PER ou un EV/EBITDA négatif n'a pas de sens économique.
    ratios["per"] = safe_div(price, eps) if (eps is not None and eps > 0) else None
    ratios["pb"] = safe_div(price, bvps) if (bvps is not None and bvps > 0) else None
    ratios["ps"] = safe_div(cap, revenue) if (revenue is not None and revenue > 0) else None
    ratios["ev_ebitda"] = safe_div(ev, ebitda) if (ebitda is not None and ebitda > 0) else None
    ratios["ev_sales"] = safe_div(ev, revenue) if (revenue is not None and revenue > 0) else None
    ratios["dividend_yield"] = safe_div(dps, price) if (dps is not None and dps > 0) else None
    ratios["payout"] = rec.get("payout") if rec.get("payout") is not None else (
        safe_div((dps * shares) if (dps and shares) else None, net_income)
        if (net_income is not None and net_income > 0) else None
    )
    ratios["roe"] = safe_div(net_income, equity)
    ratios["roa"] = safe_div(net_income, rec.get("total_assets"))
    ratios["net_margin"] = safe_div(net_income, revenue)
    ratios["operating_margin"] = safe_div(rec.get("ebit"), revenue)
    ratios["ebitda_margin"] = safe_div(ebitda, revenue)
    ratios["gross_margin"] = safe_div(rec.get("gross_profit"), revenue)
    ratios["debt_to_equity"] = safe_div(debt, equity)
    ratios["net_debt_to_ebitda"] = safe_div(net_debt, ebitda)
    ratios["current_ratio"] = safe_div(rec.get("current_assets"), rec.get("current_liabilities"))
    ratios["interest_coverage"] = safe_div(rec.get("ebit"), rec.get("interest_expense"))
    ratios["fcf_yield"] = safe_div(fcf, cap) if (cap is not None and cap > 0) else None
    ratios["earnings_yield"] = safe_div(eps, price) if (eps is not None and eps > 0) else None
    ratios["book_to_price"] = safe_div(bvps, price) if (bvps is not None and bvps > 0) else None
    ratios["asset_turnover"] = safe_div(revenue, rec.get("total_assets"))
    ratios["revenue_growth"] = rec.get("revenue_growth")
    ratios["net_income_growth"] = rec.get("net_income_growth")
    ratios["fcf_growth"] = rec.get("fcf_growth")
    if financial:
        # Multiples d'entreprise et levier non pertinents : le bilan d'une
        # banque n'a pas la même structure qu'un bilan industriel.
        for key in ("ev_ebitda", "ev_sales", "net_debt_to_ebitda", "debt_to_equity",
                    "current_ratio", "interest_coverage"):
            ratios[key] = None
    return {k: (None if v is None or (isinstance(v, float) and v != v) else float(v)) for k, v in ratios.items()}


RATIO_KEYS_ORDER = [
    "per", "pb", "ps", "ev_ebitda", "dividend_yield", "payout", "roe", "roa",
    "net_margin", "operating_margin", "ebitda_margin", "debt_to_equity",
    "net_debt_to_ebitda", "current_ratio", "interest_coverage", "fcf_yield",
    "earnings_yield", "revenue_growth", "net_income_growth",
]


def _band(value: float, bands: Sequence[tuple]) -> tuple:
    """Retourne (libellé, couleur, texte) de la première tranche satisfaite."""
    for limit, label, color, text in bands:
        if value <= limit:
            return label, color, text
    return bands[-1][1], bands[-1][2], bands[-1][3]


# Grilles d'interprétation : seuils de marché marocain / émergent
RATIO_GUIDE: Dict[str, Dict[str, Any]] = {
    "per": {
        "label": "P/E — Cours / Bénéfice",
        "unit": "x",
        "higher_better": False,
        "bands": [
            (0, "Très bon marché", "#0F766E", "Le marché paie moins de fois les bénéfices : valorisation attractante. Vérifier qu'il ne s'agit pas d'un « value trap » (bénéfices en déclin)."),
            (8, "Bon marché", "#123B6D", "En dessous de la moyenne historique du MASI (~15x). Potentiel de revalorisation si les bénéfices se maintiennent."),
            (15, "Moyenne", "#64748B", "Valorisation conforme au marché marocain. Le titre est correctement apprécié."),
            (22, "Cher", "#B45309", "Prime de valorisation. Justifiée uniquement par une croissance supérieure et durable des bénéfices."),
            (10**9, "Très cher", "#B42318", "Multiple élevé : attentes très optimistes déjà intégrées. Risque de correction si la croissance déçoit."),
        ],
        "meaning": "Nombre d'années de bénéfices actuels que l'investisseur accepte de payer. Plus il est bas, plus le titre est « bon marché » — à qualité comparable.",
    },
    "pb": {
        "label": "P/B — Cours / Actif net",
        "unit": "x",
        "higher_better": False,
        "bands": [
            (0.7, "Décote forte", "#0F766E", "Le titre cote nettement sous sa valeur comptable. Attention à la qualité des actifs et à la rentabilité (ROE)."),
            (1.2, "Sous la valeur comptable", "#123B6D", "Zone de décote, fréquente chez les banques marocaines."),
            (2.5, "Normal", "#64748B", "Prime modérée liée à la rentabilité des fonds propres."),
            (4.0, "Élevé", "#B45309", "Le marché valorise fortement le capital : il faut un ROE élevé pour le justifier."),
            (10**9, "Très élevé", "#B42318", "Valorisation portée par les actifs immatériels ou une forte croissance attendue."),
        ],
        "meaning": "Prix payé par dirham de capitaux propres. Le croiser avec le ROE : P/B élevé + ROE élevé = création de valeur.",
    },
    "ps": {
        "label": "P/S — Capitalisation / Chiffre d'affaires",
        "unit": "x",
        "higher_better": False,
        "bands": [
            (0.5, "Très bas", "#0F766E", "Le marché valorise peu les ventes : marge faible ou activité cyclique au creux."),
            (1.5, "Bas", "#123B6D", "Valorisation modérée du chiffre d'affaires."),
            (3.0, "Moyen", "#64748B", "Cohérent avec une entreprise à bonne marge nette."),
            (6.0, "Élevé", "#B45309", "Attentes de croissance forte."),
            (10**9, "Très élevé", "#B42318", "Typique des sociétés à très forte marge attendue ou croissance spéculative."),
        ],
        "meaning": "Utile sur les sociétés peu rentables ou cycliques, là où le P/E devient inexploitable.",
    },
    "ev_ebitda": {
        "label": "EV/EBITDA",
        "unit": "x",
        "higher_better": False,
        "bands": [
            (5, "Bon marché", "#0F766E", "Multiple faible en absolu : la dette est prise en compte, la valorisation paraît raisonnable."),
            (10, "Moyen", "#123B6D", "Fourchette habituelle pour une entreprise mature."),
            (15, "Élevé", "#B45309", "Il faut une croissance ou une expansion de marge pour justifier ce niveau."),
            (10**9, "Très élevé", "#B42318", "Multiple de croissance : risque important si le scénario se dégrade."),
        ],
        "meaning": "Multiple neutre vis-à-vis de la structure financière : permet de comparer des sociétés endettées différemment.",
    },
    "dividend_yield": {
        "label": "Rendement du dividende",
        "unit": "%",
        "higher_better": True,
        "bands": [
            (0.0, "Aucun dividende", "#B45309", "Aucune distribution : la société réinvestit tout (croissance) — ou traverse une période difficile."),
            (0.02, "Faible", "#B45309", "Rendement sous le taux sans risque marocain : l'essentiel du rendement doit venir de la plus-value."),
            (0.05, "Correct", "#123B6D", "Rendement en ligne avec le marché."),
            (0.09, "Attractif", "#0F766E", "Rendement supérieur aux bons du Trésor : profil « revenu » intéressant, vérifier la soutenabilité du payout."),
            (10**9, "Exceptionnel", "#0F766E", "Rendement très élevé : peut signaler un cours déprimé (piège) ou une distribution exceptionnelle."),
        ],
        "meaning": "Revenu annuel versé en cash par rapport au prix payé. À croiser avec le taux de distribution et la génération de trésorerie.",
    },
    "roe": {
        "label": "ROE — Rentabilité des fonds propres",
        "unit": "%",
        "higher_better": True,
        "bands": [
            (0.05, "Faible", "#B42318", "L'entreprise détruit de la valeur pour l'actionnaire : le rendement est inférieur au coût des fonds propres."),
            (0.10, "Moyen", "#B45309", "Rentabilité juste correcte, proche du coût du capital."),
            (0.15, "Bon", "#123B6D", "Création de valeur : au-dessus du coût des fonds propres marocain (~10-12 %)."),
            (0.25, "Très bon", "#0F766E", "Rentabilité supérieure au marché : signal de qualité durable (moat)."),
            (10**9, "Exceptionnel", "#0F766E", "Rentabilité exceptionnelle : vérifier qu'elle n'est pas dopée par l'effet de levier."),
        ],
        "meaning": "Bénéfice généré par dirham de capital investi. C'est l'un des meilleurs indicateurs de la qualité d'une entreprise.",
    },
    "roa": {
        "label": "ROA — Rentabilité de l'actif",
        "unit": "%",
        "higher_better": True,
        "bands": [
            (0.02, "Faible", "#B42318", "Les actifs génèrent peu de profit."),
            (0.05, "Moyen", "#B45309", "Performance moyenne."),
            (0.10, "Bon", "#0F766E", "Bonne efficacité de l'actif économique."),
            (10**9, "Excellent", "#0F766E", "Rendement élevé de l'actif : modèle peu intensif en capital."),
        ],
        "meaning": "Efficacité de l'ensemble des actifs, indépendamment du financement.",
    },
    "net_margin": {
        "label": "Marge nette",
        "unit": "%",
        "higher_better": True,
        "bands": [
            (0.0, "Négative", "#B42318", "L'entreprise perd de l'argent : surveillance rapprochée du besoin de financement."),
            (0.03, "Faible", "#B45309", "Marge très fine : sensibilité élevée aux coûts."),
            (0.08, "Correcte", "#123B6D", "Marge nette dans la moyenne des entreprises marocaines."),
            (0.15, "Bonne", "#0F766E", "Pouvoir de fixation des prix significatif."),
            (10**9, "Excellente", "#0F766E", "Marge de très grande qualité, souvent liée à un avantage concurrentiel structurel."),
        ],
        "meaning": "Part du chiffre d'affaires qui devient bénéfice net : mesure la qualité de l'activité.",
    },
    "debt_to_equity": {
        "label": "Dette / Fonds propres",
        "unit": "x",
        "higher_better": False,
        "bands": [
            (0.3, "Très faible", "#0F766E", "Bilan très peu endetté : grande résilience, capacité de rebond."),
            (1.0, "Sain", "#123B6D", "Endettement maîtrisé, adapté à la plupart des activités."),
            (2.0, "Élevé", "#B45309", "Levier significatif : surveiller la couverture des intérêts et les échéances."),
            (10**9, "Très élevé", "#B42318", "Structure financière fragile en cas de choc de taux ou d'activité (hors banques/assurances)."),
        ],
        "meaning": "Levier financier. À interpréter différemment selon le secteur : les banques sont structurellement plus endettées.",
    },
    "net_debt_to_ebitda": {
        "label": "Dette nette / EBITDA",
        "unit": "x",
        "higher_better": False,
        "bands": [
            (0.0, "Trésorerie nette", "#0F766E", "La société dispose plus de cash que de dette : marge de manœuvre maximale."),
            (2.0, "Faible", "#123B6D", "Désendettement rapide possible avec l'EBITDA courant."),
            (3.5, "Modéré", "#B45309", "Zone à surveiller, surtout si les taux montent."),
            (10**9, "Élevé", "#B42318", "Au-delà de 3,5x, la structure financière devient un risque central."),
        ],
        "meaning": "Nombre d'années d'EBITDA nécessaires pour rembourser la dette nette. Indicateur de solidité très suivi par les analystes.",
    },
    "current_ratio": {
        "label": "Ratio de liquidité générale",
        "unit": "x",
        "higher_better": True,
        "bands": [
            (1.0, "Tension", "#B42318", "Le passif court terme excède l'actif circulant : risque de liquidité."),
            (1.5, "Correct", "#B45309", "Équilibre court terme acceptable."),
            (2.5, "Sain", "#0F766E", "Bonne capacité à honorer les échéances à moins d'un an."),
            (10**9, "Très élevé", "#B45309", "Excès de liquidité : actif circulant potentiellement peu productif."),
        ],
        "meaning": "Capacité à payer les dettes à court terme avec les actifs à court terme.",
    },
    "fcf_yield": {
        "label": "Rendement du Free Cash-Flow",
        "unit": "%",
        "higher_better": True,
        "bands": [
            (0.0, "Négatif", "#B42318", "Consommation de trésorerie : la croissance est financée par de la dette ou des fonds propres."),
            (0.03, "Faible", "#B45309", "Génération de cash limitée."),
            (0.06, "Correct", "#123B6D", "Cash-flow disponible significatif au regard de la capitalisation."),
            (0.10, "Attractif", "#0F766E", "Génération de trésorerie élevée : capacité d'autofinancement remarquable."),
            (10**9, "Exceptionnel", "#0F766E", "Niveau rare : vérifier la récurrence des investissements."),
        ],
        "meaning": "Trésorerie disponible par dirham de valeur de marché. Le meilleur proxy de la « vraie » rentabilité économique.",
    },
    "revenue_growth": {
        "label": "Croissance du chiffre d'affaires",
        "unit": "%",
        "higher_better": True,
        "bands": [
            (-0.10, "En recul marqué", "#B42318", "Activité en contraction : analyser les causes (cycle, perte de parts de marché)."),
            (0.0, "Stagnation", "#B45309", "Croissance nulle : l'entreprise doit prouver sa capacité à rebondir."),
            (0.08, "Modérée", "#123B6D", "Croissance proche de la moyenne du marché marocain."),
            (0.20, "Forte", "#0F766E", "Dynamique commerciale soutenue."),
            (10**9, "Très forte", "#0F766E", "Croissance exceptionnelle : à confirmer sur plusieurs exercices."),
        ],
        "meaning": "Dynamique de l'activité. Croissance durable + marges stables = création de valeur composée.",
    },
    "payout": {
        "label": "Taux de distribution",
        "unit": "%",
        "higher_better": True,
        "bands": [
            (0.10, "Prudent", "#123B6D", "La société conserve l'essentiel des bénéfices pour financer sa croissance."),
            (0.50, "Équilibré", "#0F766E", "Bon compromis entre rémunération de l'actionnaire et réinvestissement."),
            (0.80, "Généreux", "#B45309", "Peu de marge de manœuvre si les bénéfices baissent."),
            (10**9, "Soutenu", "#B42318", "Distribution supérieure au bénéfice : non soutenable durablement."),
        ],
        "meaning": "Part du bénéfice net reversée aux actionnaires.",
    },
}

RATIO_MEANING = {k: v["meaning"] for k, v in RATIO_GUIDE.items()}


def interpret_ratio(key: str, value: Optional[float]) -> Dict[str, Any]:
    """Interprète un ratio selon les grilles de marché."""
    guide = RATIO_GUIDE.get(key)
    if not guide:
        return {"label": key, "value": value, "text": "Pas de grille d'interprétation.", "color": "#64748B", "grade": "—"}
    if value is None:
        return {"label": guide["label"], "value": None, "grade": "non calculable",
                "text": "Donnée insuffisante pour calculer ce ratio.", "color": "#64748B",
                "meaning": guide["meaning"], "higher_better": guide["higher_better"]}
    # Pour un ratio où « plus haut = mieux », on inverse les bornes
    bands = guide["bands"]
    if guide["higher_better"]:
        v = -float(value)
        inverted = [(-b[0], b[1], b[2], b[3]) for b in bands]
        inverted = sorted(inverted, key=lambda x: x[0])
        grade, color, text = _band(v, inverted)
    else:
        grade, color, text = _band(float(value), bands)
    return {
        "label": guide["label"], "value": float(value), "grade": grade,
        "text": text, "color": color, "meaning": guide["meaning"],
        "higher_better": guide["higher_better"], "unit": guide["unit"],
    }


def ratio_table(f: Dict[str, Any], price: Optional[float] = None, cap: Optional[float] = None) -> pd.DataFrame:
    """Tableau des ratios avec libellé, valeur, appréciation et interprétation."""
    ratios = compute_ratios(f, price=price, cap=cap)
    rows = []
    for key in RATIO_KEYS_ORDER:
        info = interpret_ratio(key, ratios.get(key))
        rows.append(
            {
                "key": key,
                "Ratio": info["label"],
                "Valeur": info["value"],
                "Unit": info.get("unit", "x"),
                "Appréciation": info["grade"],
                "Interprétation": info["text"],
                "higher_better": info.get("higher_better"),
            }
        )
    return pd.DataFrame(rows)


# ═══════════════════════════ Comparaison sectorielle ═══════════════════════════

def sector_median_ratios(sector: str, market_df: pd.DataFrame, ratio_key: str) -> Optional[float]:
    """Médiane d'un ratio au sein d'un secteur, calculée sur les données disponibles."""
    if market_df is None or market_df.empty:
        return None
    sub = market_df[market_df["sector"] == sector]
    if sub.empty:
        return None
    values = []
    for _, row in sub.iterrows():
        f = get_fundamentals(str(row["symbol"]), row)
        r = compute_ratios(f, price=as_float(row.get("close")), cap=as_float(row.get("cap")))
        v = r.get(ratio_key)
        if v is not None and pd.notna(v):
            values.append(float(v))
    if not values:
        return None
    return float(pd.Series(values).median())


def coverage_report(market_df: pd.DataFrame) -> pd.DataFrame:
    """Taux de complétion des données fondamentales, par valeur.

    Compte les champs issus des états financiers (vérifiés, importés ou via API),
    des saisies utilisateur **et** les deux champs récupérés automatiquement
    depuis la BVC (nombre de titres et dividende par action).
    """
    refs = market_reference()
    rows = []
    for _, row in market_df.iterrows():
        symbol = str(row["symbol"])
        rec = get_record(symbol)
        ref = refs.get(symbol, {}) or {}
        filled = 0
        for key in NUMERIC_FIELDS:
            if rec.get(key) not in (None, ""):
                filled += 1
            elif key in ("shares", "dps") and ref.get(key) not in (None, ""):
                filled += 1
        loaded_from_bvc = (ref.get("shares") is not None) or (ref.get("dps") is not None)
        source = rec.get("statement_source") or rec.get("source")
        if not source and loaded_from_bvc:
            source = "BVC (titres, dividende)"
        rows.append(
            {
                "Symbole": symbol,
                "Société": row.get("name"),
                "Secteur": row.get("sector"),
                "Champs renseignés": filled,
                "% complétion": filled / max(len(NUMERIC_FIELDS), 1),
                "Source": source or "—",
                "Mise à jour": rec.get("as_of") or (
                    f"dividende {ref.get('dps_year')}" if ref.get("dps_year") else "—"
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("% complétion", ascending=False).reset_index(drop=True)
