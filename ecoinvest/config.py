"""Paramètres globaux, chemins, palette de couleurs et constantes de marché."""
from __future__ import annotations

import os
from pathlib import Path

# ═══════════════════════════ Identité de l'application ═══════════════════════════
APP_NAME = "MARKET MIND"
APP_TAGLINE = "Investment intelligence platform"
APP_SUBTITLE = "Votre capital. Votre stratégie. Une vision plus claire."
APP_ICON = "🧭"
VERSION = "3.5.0"

# ═══════════════════════════ Chemins ═══════════════════════════
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
SEED_DIR = DATA_DIR / "seed"
USER_DIR = DATA_DIR / "user"

for _d in (DATA_DIR, CACHE_DIR, SEED_DIR, USER_DIR):
    _d.mkdir(parents=True, exist_ok=True)

CACHE_FILE = CACHE_DIR / "ecoinvest_cache.sqlite"
USER_PROFILE_FILE = USER_DIR / "investor_profile.json"
USER_ALLOCATION_FILE = USER_DIR / "allocations.json"
USER_FUNDAMENTALS_FILE = USER_DIR / "fundamentals_overrides.json"
USER_STATEMENTS_FILE = USER_DIR / "statements.json"
USER_THESES_FILE = USER_DIR / "theses.json"
USER_AI_FILE = USER_DIR / "ai_config.json"
WATCHLIST_FILE = USER_DIR / "watchlist.json"
STATEMENTS_SEED = SEED_DIR / "bvc_statements.json"


# ═══════════════════════════ Variables d'environnement ═══════════════════════════
def _load_dotenv(path: Path) -> None:
    """Charge un fichier « .env » minimal sans dépendance externe.

    Les variables déjà présentes dans l'environnement ne sont jamais écrasées :
    un export explicite reste prioritaire sur le fichier.
    """
    if not path.exists():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv(ROOT / ".env")


# ═══════════════════════════ Sources de données ═══════════════════════════
BVC_API_BASE = "https://www.casablanca-bourse.com/api/boursenova"
BVC_SITE = "https://www.casablanca-bourse.com"
BVC_REFERER = f"{BVC_SITE}/market-data/cours"
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
HTTP_MAX_WORKERS = 10

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": BVC_REFERER,
}

# Durées de vie du cache (secondes)
TTL = {
    "quote": 180,          # 3 min  — cours temps quasi réel
    "snapshot": 900,       # 15 min — photo du marché
    "indices": 300,        # 5 min
    "history": 3600,       # 1 h    — séries historiques
    "global": 600,         # 10 min — actions/yahoo
    "fundamentals": 86400,  # 24 h
    "news": 900,           # 15 min
    "macro": 86400,        # 24 h — séries annuelles World Bank
    "statements": 86400,   # 24 h — états financiers importés / API
    "ammc": 86400,         # 24 h — liste publique des états financiers AMMC
}

# ═══════════════════════════ Palette (institutionnelle, fond clair) ═══════════════════════════
COLORS = {
    "bg": "#F6F4EF",          # blanc cassé
    "surface": "#FFFFFF",      # cartes
    "surface2": "#EFEDE6",     # champs, survols
    "border": "#DCD7CB",
    "text": "#0B2545",         # bleu marine
    "muted": "#61708A",
    "primary": "#0F766E",      # vert turquoise profond
    "primary_dark": "#115E59",
    "accent": "#123B6D",       # bleu institutionnel
    "accent2": "#7C5CBF",      # violet analytique
    "warning": "#B45309",
    "danger": "#B42318",
    "up": "#047857",
    "down": "#B42318",
    "flat": "#64748B",
    "gold": "#A16207",
    "navy": "#0B2545",
    "cream": "#F6F4EF",
}

# Palette catégorielle pour les graphiques (lisible sur fond clair)
PALETTE = [
    "#123B6D", "#0F766E", "#7C5CBF", "#B45309", "#B42318",
    "#2563EB", "#047857", "#A16207", "#64748B", "#0E7490",
]

# ═══════════════════════════ Économie / hypothèses ═══════════════════════════
DEFAULT_CURRENCY = "MAD"
CURRENCIES = ["MAD", "EUR", "USD"]

# Taux de change de secours : combien de MAD pour 1 unité de devise
FX_FALLBACK = {"MAD": 1.0, "EUR": 10.75, "USD": 9.90}
FX_TICKERS = {"EUR": "EURMAD=X", "USD": "MAD=X"}
FX_LABELS = {"MAD": "Dirham marocain", "EUR": "Euro", "USD": "Dollar US"}

# Taux sans risque annuel (Taux directeur Bank Al-Maghrib / bon du Trésor 10 ans)
RISK_FREE_RATE = float(os.getenv("ECOINVEST_RISK_FREE_RATE", "0.0275"))
# Prime de risque actions marché marocain
EQUITY_RISK_PREMIUM = 0.065
# Fiscalité marocaine sur les plus-values en bourse (TPCVM) et dividendes
CAPITAL_GAINS_TAX = 0.15
DIVIDEND_TAX = 0.13
# Frais de courtage moyens BVC (aller-retour, en %)
BROKERAGE_FEE = 0.006
# Inflation moyenne retenue pour les projections
INFLATION_RATE = 0.021
# Rendement moyen long terme du MASI (utilisé en hypothèse de projection)
MASI_LONG_TERM_RETURN = 0.095
MASI_LONG_TERM_VOL = 0.145

# ═══════════════════════════ Marchés suivis ═══════════════════════════
GLOBAL_INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^DJI": "Dow Jones",
    "^FCHI": "CAC 40",
    "^STOXX50E": "Euro Stoxx 50",
    "^GDAXI": "DAX",
    "^FTSE": "FTSE 100",
    "^VIX": "VIX (volatilité)",
    "^TNX": "US 10Y",
    "^FVX": "US 5Y",
    "GC=F": "Or (once)",
    "CL=F": "Pétrole WTI",
    "BTC-USD": "Bitcoin",
    "EURUSD=X": "EUR/USD",
    "EURMAD=X": "EUR/MAD",
    "MAD=X": "USD/MAD",
}

# Indices de référence de la BVC
MAIN_INDEX = "MASI"
BLUE_CHIP_INDEX = "MSI20"
YTD_REFERENCE = "MASI"

# Perception du risque par secteur (1 = faible, 5 = élevé) — libellés officiels BVC
SECTOR_RISK = {
    "Banques": 3,
    "Assurances": 2,
    "Télécommunications": 2,
    "Agroalimentaire et Production": 2,
    "Boissons": 2,
    "Santé": 3,
    "Industrie Pharmaceutique": 3,
    "Mines": 5,
    "Bâtiment et Matériaux de Construction": 4,
    "Electricité": 3,
    "Pétrole et Gaz": 4,
    "Transport": 3,
    "Services de transport": 3,
    "Distributeurs": 3,
    "Chimie": 4,
    "Ingénieries et Biens d'Equipement Industriels": 4,
    "Matériels, Logiciels et Services Informatiques": 3,
    "Participation et promotion immobilières": 4,
    "Sociétés de placement immobilier": 2,
    "Sociétés de Portefeuilles / Holdings": 3,
    "Sociétés de financement et Autres Activités Financières": 4,
    "Loisirs et Hôtels": 4,
    "Industrie Agricole": 4,
    "Sylviculture et Papier": 4,
    "Autres": 3,
}


def sector_risk_level(sector: str, default: int = 3) -> int:
    """Niveau de risque sectoriel (1–5) avec correspondance approximative."""
    if not sector:
        return default
    if sector in SECTOR_RISK:
        return SECTOR_RISK[sector]
    low = sector.lower()
    for key, value in SECTOR_RISK.items():
        if key.lower() == low or key.lower() in low or low in key.lower():
            return value
    for token in ("banque", "assur", "télécom", "telecom", "mine", "pétrole", "petrole",
                  "immobil", "santé", "sante", "chimie", "agro", "transport", "bâtiment",
                  "batiment", "informat", "pharma", "boisson", "holding"):
        if token in low:
            for key, value in SECTOR_RISK.items():
                if token in key.lower():
                    return value
    return default

# ═══════════════════════════ Drapeaux fonctionnels ═══════════════════════════
ENABLE_LIVE_BVC = os.getenv("ECOINVEST_DISABLE_LIVE", "0") != "1"
ENABLE_LIVE_YAHOO = os.getenv("ECOINVEST_DISABLE_YAHOO", "0") != "1"
DISCLAIMER = (
    "⚠️ **Avertissement** : MARKET MIND est un outil d'aide à la décision à visée "
    "pédagogique et analytique. Il ne constitue ni un conseil en investissement, ni une "
    "recommandation d'achat ou de vente. Les performances passées ne préjugent pas des "
    "performances futures. Vérifiez toujours les données auprès de la Bourse de Casablanca "
    "avant toute décision. Investir comporte un risque de perte en capital."
)
