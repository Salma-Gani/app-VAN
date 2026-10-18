"""Cache persistant (SQLite) avec durée de vie — évite de marteler les API publiques.

Deux niveaux :
  1. ``@disk_cached`` : cache disque partagé entre sessions et redémarrages.
  2. ``st.cache_data`` (côté Streamlit) : cache mémoire par session, appliqué
     dans les modules de données pour accélérer les re-rendus.
"""
from __future__ import annotations

import functools
import hashlib
import json
import pickle
import sqlite3
import threading
import time
from typing import Any, Callable, Optional, Tuple

from ..config import CACHE_FILE

_LOCK = threading.RLock()
_INIT_DONE = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CACHE_FILE), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init() -> None:
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _LOCK:
        if _INIT_DONE:
            return
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    ns      TEXT NOT NULL,
                    key     TEXT NOT NULL,
                    ts      REAL NOT NULL,
                    payload BLOB NOT NULL,
                    PRIMARY KEY (ns, key)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_ts ON cache(ts)")
        _INIT_DONE = True


def make_key(*parts: Any) -> str:
    """Clé déterministe et lisible à partir d'arguments quelconques."""
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{digest}"


def get(ns: str, key: str, ttl: Optional[float] = None) -> Optional[Any]:
    """Récupère une valeur si présente et non expirée."""
    _init()
    try:
        with _LOCK, _connect() as conn:
            row = conn.execute(
                "SELECT ts, payload FROM cache WHERE ns=? AND key=?", (ns, key)
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    ts, payload = row
    if ttl is not None and (time.time() - ts) > ttl:
        return None
    try:
        return pickle.loads(payload)
    except Exception:
        return None


def set(ns: str, key: str, value: Any) -> None:
    """Enregistre une valeur dans le cache."""
    _init()
    try:
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        return
    try:
        with _LOCK, _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (ns, key, ts, payload) VALUES (?,?,?,?)",
                (ns, key, time.time(), blob),
            )
    except sqlite3.Error:
        pass


def age(ns: str, key: str) -> Optional[float]:
    """Âge en secondes d'une entrée, ou None si absente."""
    _init()
    try:
        with _LOCK, _connect() as conn:
            row = conn.execute("SELECT ts FROM cache WHERE ns=? AND key=?", (ns, key)).fetchone()
    except sqlite3.Error:
        return None
    return None if not row else time.time() - float(row[0])


def clear(ns: Optional[str] = None) -> int:
    """Purge tout le cache, ou seulement un namespace. Retourne le nombre d'entrées."""
    _init()
    with _LOCK, _connect() as conn:
        if ns:
            cur = conn.execute("DELETE FROM cache WHERE ns=?", (ns,))
        else:
            cur = conn.execute("DELETE FROM cache")
        return cur.rowcount


def stats() -> dict:
    """Statistiques d'occupation du cache, par namespace."""
    _init()
    try:
        with _LOCK, _connect() as conn:
            rows = conn.execute(
                "SELECT ns, COUNT(*), MAX(ts) FROM cache GROUP BY ns ORDER BY 2 DESC"
            ).fetchall()
    except sqlite3.Error:
        return {}
    now = time.time()
    return {
        ns: {"entries": n, "age_s": round(now - ts, 1) if ts else None}
        for ns, n, ts in rows
    }


def disk_cached(
    ns: str,
    ttl: float = 3600.0,
    key_fn: Optional[Callable[..., str]] = None,
) -> Callable:
    """Décorateur : met en cache disque le résultat, avec repli sur valeur périmée.

    En cas d'échec de la fonction (API indisponible), la dernière valeur connue
    est restituée, même expirée : l'application reste utilisable hors-ligne.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            force = bool(kwargs.pop("_force_refresh", False))
            key = key_fn(*args, **kwargs) if key_fn else make_key(fn.__name__, args, kwargs)
            if not force:
                hit = get(ns, key, ttl)
                if hit is not None:
                    return hit
            try:
                value = fn(*args, **kwargs)
            except Exception:
                stale = get(ns, key, None)
                if stale is not None:
                    return stale
                raise
            if value is not None:
                set(ns, key, value)
            return value

        wrapper.__wrapped_disk__ = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


def memoize(ttl: float = 300.0, ns: str = "memo") -> Callable:
    """Décorateur de cache mémoire (process) — plus léger que SQLite."""
    store: dict = {}
    lock = threading.RLock()

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = make_key(fn.__name__, args, kwargs)
            now = time.time()
            with lock:
                hit = store.get(key)
                if hit and now - hit[0] < ttl:
                    return hit[1]
            value = fn(*args, **kwargs)
            with lock:
                store[key] = (now, value)
            return value

        return wrapper

    return decorator


def last_updated(ns: str, key: str) -> Tuple[Optional[float], Optional[float]]:
    """(timestamp absolu, âge en secondes)."""
    _init()
    try:
        with _LOCK, _connect() as conn:
            row = conn.execute("SELECT ts FROM cache WHERE ns=? AND key=?", (ns, key)).fetchone()
    except sqlite3.Error:
        return None, None
    if not row:
        return None, None
    ts = float(row[0])
    return ts, time.time() - ts
