"""Connecteur de données de la Bourse de Casablanca (BVC).

S'appuie sur l'API publique du site officiel ``casablanca-bourse.com``
(espace ``/api/boursenova``) :

* ``/indices``                     — tous les indices (MASI, MASI 20, sectoriels…)
* ``/indices/historical``          — série historique d'un ou plusieurs indices
* ``/indices/composition``         — composition d'un indice (valeur, secteur, capitalisation)
* ``/stock-historical``            — OHLCV quotidien d'une valeur

Aucune clé d'API n'est requise. Toutes les requêtes sont mises en cache
(SQLite + mémoire) et réessayées en cas d'échec réseau. En cas d'indisponibilité
totale, la dernière copie locale est restituée (mode hors-ligne).
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import pandas as pd
import requests

from ..config import (
    BVC_API_BASE,
    BVC_SITE,
    HTTP_HEADERS,
    HTTP_MAX_WORKERS,
    HTTP_RETRIES,
    HTTP_TIMEOUT,
    SEED_DIR,
    TTL,
)
from ..utils import cache
from .http import ProviderError, classify_status, record_error, record_exception, record_success

# ═══════════════════════════ Noms de cache ═══════════════════════════
NS_API = "bvc_api"
NS_HIST = "bvc_hist"
NS_SNAP = "bvc_snapshot"

LOCAL = threading.local()
UNIVERSE_SEED = SEED_DIR / "bvc_universe.json"


def _session() -> requests.Session:
    """Une session HTTP par thread (évite les problèmes de concurrence)."""
    s = getattr(LOCAL, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(HTTP_HEADERS)
        LOCAL.session = s
    return s


class BVCError(RuntimeError):
    """Erreur de communication avec l'API de la Bourse de Casablanca."""


# ═══════════════════════════ Appel brut + cache ═══════════════════════════

def _api(path: str, params: Optional[Dict[str, Any]] = None, force: bool = False) -> Any:
    """GET sur l'API BVC avec cache disque, réessais et repli hors-ligne."""
    key = cache.make_key(path, params or {})
    if not force:
        hit = cache.get(NS_API, key, TTL["snapshot"])
        if hit is not None:
            return hit

    url = f"{BVC_API_BASE}/{path.lstrip('/')}"
    last_error: Optional[Exception] = None
    for attempt in range(HTTP_RETRIES):
        try:
            resp = _session().get(url, params=params or {}, timeout=HTTP_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                cache.set(NS_API, key, data)
                try:
                    record_success("BVC", len(data) if isinstance(data, list) else 1, 200)
                except Exception:
                    pass
                return data
            kind = classify_status(resp.status_code)
            record_error("BVC", ProviderError(
                "BVC", resp.status_code, kind, f"HTTP {resp.status_code} sur {path}",
                kind in {"rate_limit", "server", "timeout", "network"},
            ))
            last_error = BVCError(f"HTTP {resp.status_code} sur {path}")
        except (requests.RequestException, ValueError) as exc:  # pragma: no cover - réseau
            record_error("BVC", ProviderError("BVC", None, "network", str(exc), True))
            last_error = exc
        if attempt < HTTP_RETRIES - 1:
            threading.Event().wait(0.6 * (attempt + 1))

    stale = cache.get(NS_API, key, None)
    if stale is not None:
        # Repli explicite : la copie locale est datée par le cache, pas présentée comme du temps réel.
        record_error("BVC", ProviderError("BVC", None, "network",
                                          f"API injoignable, copie locale utilisée pour {path}", True))
        return stale
    raise BVCError(f"API BVC injoignable ({path}) : {last_error}")


# ═══════════════════════════ Univers des valeurs ═══════════════════════════

def _parse_universe_from_html(html: str) -> List[Dict[str, str]]:
    """Extrait la liste des instruments depuis le drupalSettings du site BVC."""
    match = re.search(
        r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        return []
    try:
        cfg = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    actions = (cfg.get("boursenova", {}) or {}).get("instruments", {}).get("actions", []) or []
    out: List[Dict[str, str]] = []
    for item in actions:
        label = item.get("label", {}) or {}
        symbol = (item.get("symbol") or "").strip()
        if symbol:
            out.append(
                {
                    "symbol": symbol,
                    "name": (label.get("fr") or symbol).strip(),
                    "name_en": (label.get("en") or "").strip(),
                    "name_ar": (label.get("ar") or "").strip(),
                }
            )
    return out


def fetch_universe_live() -> List[Dict[str, str]]:
    """Récupère l'univers des valeurs depuis le site officiel (mode « live »)."""
    try:
        resp = _session().get(f"{BVC_API_BASE.replace('/api/boursenova', '')}/market-data/cours", timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            parsed = _parse_universe_from_html(resp.text)
            if parsed:
                cache.set(NS_API, "universe", parsed)
                with open(UNIVERSE_SEED, "w", encoding="utf-8") as fh:
                    json.dump(
                        {"source": "casablanca-bourse.com/market-data/cours",
                         "generated_at": datetime.now().isoformat(timespec="seconds"),
                         "instruments": parsed},
                        fh, ensure_ascii=False, indent=1,
                    )
                return parsed
    except requests.RequestException as exc:
        record_exception("Bourse de Casablanca (univers)", exc)
    return []


# ═══════════════════════════ Pages HTML : référentiel et dividendes ═══════════════════════════

_DRUPAL_RE = re.compile(
    r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>',
    re.S,
)


def _parse_drupal_settings(html: str) -> Dict[str, Any]:
    """Extrait l'objet ``drupalSettings`` embarqué dans une page du site BVC."""
    match = _DRUPAL_RE.search(html or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _page_settings(path: str, force: bool = False) -> Dict[str, Any]:
    """Charge et met en cache les données embarquées d'une page publique du site BVC."""
    key = cache.make_key("page_settings", path)
    if not force:
        hit = cache.get(NS_API, key, TTL["history"])
        if hit:
            return hit
    try:
        resp = _session().get(f"{BVC_SITE}{path}", timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            settings = _parse_drupal_settings(resp.text)
            if settings:
                cache.set(NS_API, key, settings)
                return settings
    except requests.RequestException:
        pass
    stale = cache.get(NS_API, key, None)
    return stale or {}


def _to_number(value: Any) -> Optional[float]:
    """Convertit « 215 140 839 », « 22,00 MAD » ou 22.0 en nombre."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        return None if v != v else v
    text = str(value).replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _norm_name(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9 ]", " ", str(value or "").upper())
    return re.sub(r"\s+", " ", text).strip()


def market_profile(force: bool = False) -> pd.DataFrame:
    """Référentiel officiel des actions : ISIN, nombre de titres, compartiment, secteur.

    Source : page ``/marches-produits/actions`` (drupalSettings ``boursenova.actions``).
    """
    settings = _page_settings("/marches-produits/actions", force=force)
    actions = ((settings.get("boursenova") or {}).get("actions") or []) if settings else []
    rows: List[Dict[str, Any]] = []
    for item in actions:
        symbol = str(item.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "issuer": str(item.get("emetteur") or "").strip(),
                "isin": str(item.get("codeISIN") or "").strip(),
                "shares": _to_number(item.get("nombreTitres")),
                "compartment": str(item.get("compartiment") or "").strip(),
                "category": str(item.get("categorie") or "").strip(),
                "sector": str(item.get("secteur") or "").strip(),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    return df


def dividends(force: bool = False) -> pd.DataFrame:
    """Historique des dividendes par émetteur (montant, détachement, paiement).

    Source : page ``/emetteurs/calendrier-financier`` (drupalSettings ``dividendesData``).
    """
    settings = _page_settings("/emetteurs/calendrier-financier", force=force)
    data = ((settings.get("boursenova") or {}).get("dividendesData") or {}) if settings else {}
    rows: List[Dict[str, Any]] = []
    for year, items in (data or {}).items():
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            continue
        try:
            year_int = int(str(year)[:4])
        except (TypeError, ValueError):
            year_int = None
        for item in items:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "year": year_int,
                    "issuer": str(item.get("emetteur") or "").strip(),
                    "dps": _to_number(item.get("dividende")),
                    "type": str(item.get("typeDividende") or "").strip(),
                    "ex_date": pd.to_datetime(item.get("dateDetachement"), errors="coerce"),
                    "payment_date": pd.to_datetime(item.get("datePaiement"), errors="coerce"),
                }
            )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["dps"]).sort_values(
            ["ex_date", "year"], ascending=[False, False], na_position="last"
        ).reset_index(drop=True)
    return df


def latest_dividends(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Dernier dividende connu par émetteur, indexé par nom normalisé."""
    df = dividends(force=force)
    if df.empty:
        return {}
    latest = df.drop_duplicates(subset=["issuer"], keep="first")
    out: Dict[str, Dict[str, Any]] = {}
    for _, row in latest.iterrows():
        key = _norm_name(row.get("issuer"))
        if not key:
            continue
        out[key] = {
            "dps": float(row["dps"]),
            "year": int(row["year"]) if pd.notna(row.get("year")) else None,
            "type": row.get("type") or "",
            "ex_date": row.get("ex_date"),
        }
    return out


def reference_data(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Référentiel consolidé par symbole : titres, ISIN, DPS et année du dividende."""
    profile = market_profile(force=force)
    if profile.empty:
        return {}
    divs = latest_dividends(force=force)
    out: Dict[str, Dict[str, Any]] = {}
    for _, row in profile.iterrows():
        symbol = str(row["symbol"])
        div = divs.get(_norm_name(row.get("issuer"))) or {}
        out[symbol] = {
            "issuer": row.get("issuer"),
            "isin": row.get("isin") or None,
            "shares": row.get("shares"),
            "compartment": row.get("compartment") or None,
            "category": row.get("category") or None,
            "dps": div.get("dps"),
            "dps_year": div.get("year"),
            "dps_type": div.get("type"),
        }
    return out


def universe(force: bool = False) -> pd.DataFrame:
    """Univers des 81 valeurs cotées : symbole, raison sociale, secteur.

    Ordre de résolution : cache → site officiel → fichier de référence local.
    """
    if not force:
        hit = cache.get(NS_API, "universe", TTL["fundamentals"])
        if hit:
            df = pd.DataFrame(hit)
            return _finalize_universe(df)

    data: List[Dict[str, str]] = []
    if force:
        data = fetch_universe_live()
    else:
        data = fetch_universe_live()

    if not data and UNIVERSE_SEED.exists():
        try:
            with open(UNIVERSE_SEED, encoding="utf-8") as fh:
                payload = json.load(fh)
            data = payload.get("instruments", payload) if isinstance(payload, dict) else payload
        except (OSError, json.JSONDecodeError):
            data = []

    if not data:
        # Dernier recours : univers minimal embarqué (les grandes capitalisations BVC).
        data = [{"symbol": s, "name": n, "name_en": "", "name_ar": ""} for s, n in _FALLBACK_UNIVERSE]

    cache.set(NS_API, "universe", data)
    return _finalize_universe(pd.DataFrame(data))


def _finalize_universe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["symbol", "name", "name_en", "name_ar", "sector"])
    df = df.copy()
    for col in ("name", "name_en", "name_ar"):
        if col not in df.columns:
            df[col] = ""
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    df = df.drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    if "sector" not in df.columns:
        sector_map = sector_mapping()
        df["sector"] = df["symbol"].map(sector_map).fillna("Autres")
    return df


_FALLBACK_UNIVERSE: List[tuple] = [
    ("ATW", "Attijariwafa Bank"), ("BCP", "BCP"), ("IAM", "Itissalat Al-Maghrib"),
    ("BOA", "Bank Of Africa"), ("CDM", "CDM"), ("ADH", "Douja Prom Addoha"),
    ("CMA", "Ciments Du Maroc"), ("LHM", "Holcim Maroc"), ("CSR", "Cosumar"),
    ("MNG", "Managem"), ("TMA", "Totalenergies Marketing Maroc"), ("LBV", "Label Vie"),
    ("MSA", "Sodep-Marsa Maroc"), ("AKT", "Akdital"), ("CIH", "CIH"), ("SID", "Sonasid"),
    ("TQM", "Taqa Morocco"), ("GAZ", "Afriquia Gaz"), ("WAA", "Wafa Assurance"),
    ("HPS", "HPS"), ("SOT", "Sothema"), ("RIS", "Risma"),
    ("MUT", "Mutandis SCA"), ("LES", "Lesieur Cristal"), ("OUL", "Oulmes"),
    ("SBM", "Societe Des Boissons Du Maroc"), ("CTM", "CTM"), ("TGC", "TGCC S.A"),
    ("ADI", "Alliances"), ("NKL", "Ennakl"), ("SAH", "Sanlam Maroc"),
    ("ARD", "Aradei Capital"), ("IMO", "Immorente Invest"), ("AGM", "Agma"),
    ("AFM", "Afma"), ("MIC", "Microdata"), ("DWY", "Disway"), ("M2M", "M2M Group"),
    ("DYT", "Disty Technologies"), ("INV", "Involys"), ("EQD", "Eqdom"),
    ("SLF", "Salafin"), ("MAB", "Maghrebail"), ("MLE", "Maroc Leasing"),
    ("SMI", "SMI"), ("CMT", "Miniere Touissit"), ("ZDJ", "Zellidja S.A"),
    ("SNA", "Stokvis Nord Afrique"), ("SNP", "Snep"), ("GTM", "SGTM S.A"),
    ("SRM", "Realisations Mecaniques"), ("ALM", "Aluminium Du Maroc"),
    ("FBR", "Fenie Brossette"), ("COL", "Colorado"), ("CRS", "Cartier Saada"),
    ("DHO", "Delta Holding"), ("DLM", "Delattre Levivier Maroc"), ("PRO", "Promopharm S.A."),
    ("T2S", "T2S Group Holding"), ("VCN", "Vicenne"), ("CAP", "Cash Plus S.A"),
    ("ATH", "Auto Hall"), ("NEJ", "Auto Nejma"), ("MDP", "Med Paper"),
    ("MOX", "Maghreb Oxygene"), ("UMR", "Unimer"), ("IBC", "Ib Maroc.Com"),
    ("BCI", "BMCI"), ("STR", "Stroc Industrie"), ("JET", "Jet Contractors"),
    ("AFI", "Afric Industries Sa"), ("S2M", "S.M Monetique"), ("RDS", "Residences Dar Saada"),
    ("MCS", "Mcs"), ("REB", "Rebab Company"),
    ("SAM", "Samir"), ("CMG", "CMGP Group"),
]


# ═══════════════════════════ Indices ═══════════════════════════

def index_table(force: bool = False) -> pd.DataFrame:
    """Tableau de tous les indices BVC (principaux, sectoriels, devises, rentabilité)."""
    raw = _api("indices", force=force) or []
    rows: List[Dict[str, Any]] = []
    for item in raw:
        label = item.get("label", {}) or {}
        type_label = item.get("type_label", {}) or {}
        rows.append(
            {
                "code": item.get("code"),
                "name": (label.get("fr") or item.get("code") or "").strip(),
                "kind": (type_label.get("fr") or "").strip(),
                "value": item.get("value"),
                "prev_close": item.get("previous_close"),
                "change_pct": item.get("change_pct"),
                "ytd_pct": item.get("change_ytd"),
                "high": item.get("high"),
                "low": item.get("low"),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        # Les API renvoient des pourcentages déjà multipliés : on normalise en fraction.
        for col in ("change_pct", "ytd_pct"):
            df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0
        for col in ("value", "prev_close", "high", "low"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def sector_indices(force: bool = False) -> pd.DataFrame:
    """Indices sectoriels uniquement (MASI Banques, MASI Mines…)."""
    df = index_table(force=force)
    if df.empty:
        return df
    return df[df["kind"].str.contains("Sectoriel", case=False, na=False)].reset_index(drop=True)


def main_indices(force: bool = False) -> pd.DataFrame:
    """Indices principaux (MASI, MASI 20, MASI Mid & Small Cap…)."""
    df = index_table(force=force)
    if df.empty:
        return df
    mask = df["kind"].str.contains("Principal", case=False, na=False)
    return df[mask].reset_index(drop=True)


def index_history(code: str = "MASI", period: str = "1Y", force: bool = False) -> pd.DataFrame:
    """Série historique d'un indice.

    ``period`` : 5D, 1M, 3M, 6M, 1Y, 3Y, 5Y, MAX.
    Retourne un DataFrame ``date, value, variation, high, low, ytd``.
    """
    key = cache.make_key("idx_hist", code, period)
    if not force:
        hit = cache.get(NS_HIST, key, TTL["history"])
        if hit is not None:
            return hit
    raw = _api("indices/historical", params={"code": code, "period": period}, force=force)
    items = (raw or {}).get("items", []) if isinstance(raw, dict) else (raw or [])
    rows: List[Dict[str, Any]] = []
    for item in items:
        bloc = (item.get("indices") or {}).get(code) or {}
        if not bloc:
            continue
        rows.append(
            {
                "date": pd.to_datetime(item.get("seance"), format="%d/%m/%Y", errors="coerce"),
                "value": bloc.get("valeur"),
                "variation": bloc.get("variation"),
                "high": bloc.get("plusHaut"),
                "low": bloc.get("plusBas"),
                "ytd": bloc.get("variationYTD"),
                "volume": item.get("volume"),
                "transactions": item.get("transactions"),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        for col in ("value", "high", "low", "volume", "transactions"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("variation", "ytd"):
            df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0
        cache.set(NS_HIST, key, df)
    return df


def index_composition(code: str, force: bool = False) -> pd.DataFrame:
    """Composition d'un indice : valeur, secteur, quantité, cours, capitalisation."""
    key = cache.make_key("idx_comp", code)
    if not force:
        hit = cache.get(NS_API, key, TTL["history"])
        if hit is not None:
            return hit
    raw = _api("indices/composition", params={"code": code}, force=force) or []
    rows: List[Dict[str, Any]] = []
    for item in raw:
        instr = item.get("instrument", {}) or {}
        sect = item.get("sector", {}) or {}
        rows.append(
            {
                "symbol": (instr.get("fr") or "").strip(),
                "sector": (sect.get("fr") or "").strip(),
                "quantity": item.get("quantity"),
                "price": item.get("price"),
                "cap": item.get("cap"),
                "index": code,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[df["symbol"] != ""].reset_index(drop=True)
        for col in ("quantity", "price", "cap"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        cache.set(NS_API, key, df)
    return df


def sector_mapping(force: bool = False) -> Dict[str, str]:
    """Correspondance symbole -> secteur officiel, issue des compositions d'indices.

    La Bourse de Casablanca n'expose la composition (avec le secteur de chaque
    valeur) que pour les indices principaux — MASI, MASI 20, MASI Mid & Small Cap
    et MASI ESG — ce qui couvre l'ensemble des valeurs cotées.
    """
    key = "sector_map"
    if not force:
        hit = cache.get(NS_API, key, TTL["fundamentals"])
        if hit:
            return hit
    mapping: Dict[str, str] = {}
    for code in ("MASI", "MSI20", "MASIMS", "ESGI"):
        try:
            comp = index_composition(code, force=force)
        except BVCError:
            continue
        for _, row in comp.iterrows():
            symbol = str(row["symbol"]).strip()
            sector = str(row["sector"]).strip()
            if symbol and sector and symbol not in mapping:
                mapping[symbol] = sector
    if mapping:
        cache.set(NS_API, key, mapping)
    return mapping


# ═══════════════════════════ Historique des valeurs ═══════════════════════════

def stock_history(
    symbol: str,
    days: int = 750,
    end: Optional[date] = None,
    force: bool = False,
) -> pd.DataFrame:
    """OHLCV quotidien d'une valeur (marché au comptant).

    Colonnes : ``date, open, close, high, low, volume, transactions, cap, ref``.
    """
    symbol = symbol.strip().upper()
    end_d = end or date.today()
    start_d = end_d - timedelta(days=int(days))
    key = cache.make_key("stock_hist", symbol, start_d.isoformat(), end_d.isoformat())
    if not force:
        hit = cache.get(NS_HIST, key, TTL["history"])
        if hit is not None:
            return hit

    params = {
        "instrument": symbol,
        "market": "comptant",
        "type": "actions",
        "startDate": start_d.strftime("%Y-%m-%d"),
        "endDate": end_d.strftime("%Y-%m-%d"),
        "pageNumber": 1,
        "pageSize": 1000,
        # Indispensable : lisse les fractionnements et attributions d'actions
        "isCoursAjuste": "true",
    }
    raw = _api("stock-historical", params=params, force=force)
    items = raw.get("items", []) if isinstance(raw, dict) else (raw or [])
    rows: List[Dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "date": pd.to_datetime(item.get("seance"), format="%d/%m/%Y", errors="coerce"),
                "open": item.get("ouverture"),
                "close": item.get("dernierCours"),
                "high": item.get("plusHaut"),
                "low": item.get("plusBas"),
                "volume": item.get("volumeEchanges"),
                "shares": item.get("titresEchanges"),
                "transactions": item.get("nbTransactions"),
                "cap": item.get("capitalisation"),
                "ref": item.get("coursReference"),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for col in ("open", "close", "high", "low", "volume", "shares", "transactions", "cap", "ref"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    cache.set(NS_HIST, key, df)
    return df


def load_histories(
    symbols: Optional[Sequence[str]] = None,
    days: int = 750,
    force: bool = False,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, pd.DataFrame]:
    """Charge en parallèle l'historique de plusieurs valeurs.

    ``progress_cb(done, total, symbol)`` permet d'alimenter une barre de progression.
    """
    if symbols is None:
        symbols = universe(force=force)["symbol"].tolist()
    symbols = [s for s in symbols if s]
    out: Dict[str, pd.DataFrame] = {}
    total = len(symbols)
    done = 0
    with ThreadPoolExecutor(max_workers=HTTP_MAX_WORKERS) as pool:
        futures = {pool.submit(stock_history, s, days, None, force): s for s in symbols}
        for fut in as_completed(futures):
            symbol = futures[fut]
            done += 1
            try:
                df = fut.result()
                if df is not None and not df.empty:
                    out[symbol] = df
            except Exception:
                pass
            if progress_cb:
                progress_cb(done, total, symbol)
    return out


# ═══════════════════════════ Photo du marché ═══════════════════════════

def snapshot(
    force: bool = False,
    days: int = 400,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """Tableau de bord de toutes les valeurs cotées : cours, variation, volumes, cap.

    Les colonnes sont brutes (aucun indicateur technique) ; l'enrichissement
    se fait dans :mod:`ecoinvest.analytics.screener`.
    """
    key = cache.make_key("snapshot", days)
    if not force:
        hit = cache.get(NS_SNAP, key, TTL["snapshot"])
        if hit is not None and not hit.empty:
            return hit

    uni = universe(force=False)
    histories = load_histories(uni["symbol"].tolist(), days=days, force=force, progress_cb=progress_cb)
    sectors = sector_mapping()

    rows: List[Dict[str, Any]] = []
    for _, u in uni.iterrows():
        symbol = str(u["symbol"])
        hist = histories.get(symbol)
        name = str(u.get("name") or symbol)
        sector = sectors.get(symbol) or str(u.get("sector") or "Autres")
        if hist is None or hist.empty:
            rows.append(
                {
                    "symbol": symbol, "name": name, "sector": sector,
                    "close": None, "prev_close": None, "change_pct": None,
                    "open": None, "high": None, "low": None,
                    "volume": None, "transactions": None, "cap": None,
                    "high_52w": None, "low_52w": None, "n_obs": 0,
                    "last_date": None, "sma20": None, "sma50": None, "sma200": None,
                    "return_1m": None, "return_3m": None, "return_6m": None,
                    "return_12m": None, "ytd_pct": None, "volatility": None,
                    "series": None,
                }
            )
            continue

        hist = hist.sort_values("date")
        last = hist.iloc[-1]
        prev_close = float(hist.iloc[-2]["close"]) if len(hist) > 1 else float(last["ref"] or last["close"])
        close = float(last["close"])
        change = (close / prev_close - 1.0) if prev_close else None
        window = hist.tail(252)

        def _ret(n_days: int) -> Optional[float]:
            sub = hist[hist["date"] <= (last["date"] - pd.Timedelta(days=n_days))]
            if sub.empty:
                return None
            base = float(sub.iloc[-1]["close"])
            return (close / base - 1.0) if base else None

        year_start = hist[hist["date"] >= pd.Timestamp(date(last["date"].year, 1, 1))]
        base_ytd = float(year_start.iloc[0]["close"]) if not year_start.empty else None

        closes = window["close"].astype(float)
        rets = closes.pct_change().dropna().clip(lower=-0.45, upper=0.45)
        vol = float(rets.std() * (252 ** 0.5)) if len(rets) > 20 else None

        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "close": close,
                "prev_close": prev_close,
                "change_pct": change,
                "open": float(last["open"]) if pd.notna(last["open"]) else None,
                "high": float(last["high"]) if pd.notna(last["high"]) else None,
                "low": float(last["low"]) if pd.notna(last["low"]) else None,
                "volume": float(last["volume"]) if pd.notna(last["volume"]) else None,
                "transactions": float(last["transactions"]) if pd.notna(last["transactions"]) else None,
                "cap": float(last["cap"]) if pd.notna(last["cap"]) else None,
                "high_52w": float(window["high"].max()) if not window.empty else None,
                "low_52w": float(window["low"].min()) if not window.empty else None,
                "n_obs": int(len(hist)),
                "last_date": last["date"],
                "sma20": float(closes.tail(20).mean()) if len(closes) >= 20 else None,
                "sma50": float(closes.tail(50).mean()) if len(closes) >= 50 else None,
                "sma200": float(closes.tail(200).mean()) if len(closes) >= 200 else None,
                "return_1m": _ret(30),
                "return_3m": _ret(91),
                "return_6m": _ret(182),
                "return_12m": _ret(365),
                "ytd_pct": (close / base_ytd - 1.0) if base_ytd else None,
                "volatility": vol,
                "series": hist[["date", "close", "high", "low", "volume"]].tail(260),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("cap", ascending=False, na_position="last").reset_index(drop=True)
        cache.set(NS_SNAP, key, df)
    return df


def market_breadth(force: bool = False) -> Dict[str, Any]:
    """Statistiques de largeur de marché : hausses / baisses / stabilité."""
    snap = snapshot(force=force)
    sub = snap.dropna(subset=["change_pct"])
    if sub.empty:
        return {"advancers": 0, "decliners": 0, "unchanged": 0, "breadth": None, "total": 0}
    up = int((sub["change_pct"] > 0.002).sum())
    down = int((sub["change_pct"] < -0.002).sum())
    flat = int(len(sub) - up - down)
    return {
        "advancers": up,
        "decliners": down,
        "unchanged": flat,
        "breadth": (up - down) / len(sub),
        "total": int(len(sub)),
    }


def top_movers(n: int = 5, force: bool = False) -> Dict[str, pd.DataFrame]:
    """Meilleures et pires performances de la séance."""
    snap = snapshot(force=force).dropna(subset=["change_pct"])
    snap = snap[snap["volume"].fillna(0) > 0] if "volume" in snap else snap
    cols = ["symbol", "name", "sector", "close", "change_pct", "volume", "cap"]
    return {
        "hausses": snap.nlargest(n, "change_pct")[cols].reset_index(drop=True),
        "baisses": snap.nsmallest(n, "change_pct")[cols].reset_index(drop=True),
        "volumes": snap.nlargest(n, "volume")[cols].reset_index(drop=True),
    }


def cache_info() -> Dict[str, Any]:
    """Informations sur l'état du cache de données."""
    return cache.stats()
