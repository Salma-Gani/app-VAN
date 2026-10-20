"""Normalisation d'états financiers : du texte brut (PDF/web) à un tableau structuré.

Ce module se situe **entre la récupération** (PDF AMMC, CSV, Excel, API) **et
l'affichage**. Il ne remplace aucune source et n'invente jamais un montant.

Chaîne de traitement :

1. **Extraction** — ``extract_pdf_pages`` lit le texte page par page (mode
   ``layout`` quand ``pypdf`` le permet, sinon texte simple) ;
2. **Analyse** — ``parse_number`` / ``extract_amounts`` séparent les montants
   (espaces insécables, virgules/décimales, parenthèses négatives) des colonnes
   d'exercice ;
3. **Normalisation** — ``normalize_label`` associe chaque libellé d'origine à
   une rubrique canonique, avec un niveau de confiance. Deux libellés distincts
   ne sont **jamais** fusionnés silencieusement : un doute produit le statut
   « à vérifier » ;
4. **Structuration** — ``ExtractionResult`` puis ``to_editor_frame`` donnent un
   DataFrame *une ligne par rubrique, une colonne par exercice* ;
5. **Contrôles** — ``coherence_issues`` signale actif ≠ passif, doublons,
   colonnes multiples, unités ou devise non détectées, sans rien corriger.

Le libellé d'origine, la page, l'unité, la devise et la source sont conservés
pour la traçabilité.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from .statements import (
    ASSET_KEYS,
    LIABILITY_KEYS,
    LINE_DEFS,
    StatementError,
    detect_unit,
)

# ─────────────────────────────── Colonnes du tableau ───────────────────────
META_COLUMNS = ["Bloc", "Clé", "Rubrique", "Libellé d'origine", "Unité", "Devise",
                "Page", "Confiance", "Statut"]

BLOCK_LABELS = {
    "income": "CPC",
    "balance_assets": "Bilan actif",
    "balance_liabilities": "Bilan passif",
    "cashflow": "Trésorerie",
}

CURRENCY_PATTERNS = {
    "MAD": r"\b(mad|dh|dhs|dirhams?|marocains?)\b",
    "EUR": r"\b(eur|euros?)\b",
    "USD": r"\b(usd|dollars?)\b",
}


# ═══════════════════════════ 1. Analyse des nombres ═══════════════════════════

_SPACE_CHARS = ("\u00a0", "\u202f", "\u2009", "\u2007", "\u2060", "\ufeff")


def normalize_spaces(text: str) -> str:
    """Uniformise les espaces (insécables, fines) pour faciliter l'analyse."""
    out = str(text or "")
    for char in _SPACE_CHARS:
        out = out.replace(char, " ")
    return out.replace("\t", "    ")


def split_columns(line: str) -> List[str]:
    """Découpe une ligne en colonnes sur **2 espaces ou plus**.

    C'est la distinction essentielle : une espace simple sépare les milliers
    (``35 731``), deux espaces ou plus séparent les colonnes (``35 731   36 786``).
    """
    return [part.strip() for part in re.split(r"\s{2,}", normalize_spaces(line)) if part.strip()]


def parse_number_ex(token: Any) -> Tuple[Optional[float], bool]:
    """Convertit un jeton en nombre, avec drapeau d'ambiguïté.

    Gère : espaces de milliers, virgule ou point décimal, les deux mélangés,
    parenthèses négatives, signes Unicode, suffixes ``%`` et unités texte.
    ``(1 234,50)`` → ``(-1234.5, False)``.
    """
    if token is None:
        return None, False
    text = normalize_spaces(str(token)).strip()
    if not text:
        return None, False
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-").strip()
    if text.startswith("-"):
        negative = not negative
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()
    if text in {"", "-", "--", "/", "n/a", "na", "nd", "ns"}:
        return None, False
    text = re.sub(r"(?i)\b(mad|mmad|kmad|mdh|dh|dhs|dirhams?|eur|usd)\b", " ", text).strip()
    text = text.rstrip("%").strip()
    text = text.replace(" ", "")
    if not text or not re.search(r"\d", text):
        return None, False

    ambiguous = False
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        if tail.isdigit() and len(tail) in (1, 2) and "," not in head:
            text = head + "." + tail
        elif len(tail) == 3 and "," not in head and head:
            # Deux interprétations possibles : 1,234 = 1.234 ou 1 234.
            ambiguous = True
            text = head + tail
        else:
            text = text.replace(",", "")
    elif "." in text:
        head, _, tail = text.rpartition(".")
        parts = text.split(".")
        if len(parts) == 2 and tail.isdigit() and len(tail) == 3 and head.isdigit():
            ambiguous = True  # 1.234 → 1 234 (milliers) ou 1,234 (décimale)
            text = head + tail
        elif len(parts) > 2 and all(len(part) == 3 for part in parts[1:]):
            text = "".join(parts)
        else:
            text = "".join(parts[:-1]) + "." + parts[-1]

    text = re.sub(r"[^0-9.]", "", text)
    if text.count(".") > 1:
        head = text.split(".")[0]
        text = head
        ambiguous = True
    try:
        value = float(text)
    except ValueError:
        return None, False
    return (-value if negative else value), ambiguous


def parse_number(token: Any) -> Optional[float]:
    """Version sans drapeau : ``parse_number_ex`` en ne gardant que la valeur."""
    return parse_number_ex(token)[0]


def _split_runs(tokens: Sequence[str]) -> List[float]:
    """Regroupe une suite de jetons numériques en nombres (milliers par 3).

    ``["35", "731", "36", "786"]`` → ``[35731, 36786]``. Heuristique utilisée
    uniquement quand la mise en page n'offre pas de séparateur net : le
    résultat est toujours signalé « à vérifier ».
    """
    values: List[float] = []
    current = ""
    for token in tokens:
        if not re.fullmatch(r"\d{1,3}", token):
            if current:
                values.append(float(current))
                current = ""
            continue
        if not current:
            current = token
        elif len(token) == 3 and len(current) <= 4:
            current += token
        else:
            values.append(float(current))
            current = token
    if current:
        values.append(float(current))
    return values


def _single_number(tokens: Sequence[str]) -> Optional[int]:
    """Un jeton unique, ou un nombre à séparateurs de milliers corrects.

    ``["35", "731"]`` → ``35731`` ; ``["35", "731", "36", "786"]`` → ``None``
    (plusieurs nombres). Les espaces ne sont acceptés comme séparateurs de
    milliers que si les groupes font exactement 3 chiffres.
    """
    if not tokens:
        return None
    if not all(re.fullmatch(r"\d{1,3}", token) for token in tokens):
        return None
    if len(tokens) == 1:
        return int(tokens[0])
    if len(tokens[0]) > 3 or not tokens[0]:
        return None
    if all(len(token) == 3 for token in tokens[1:]):
        return int("".join(tokens))
    return None


def extract_amounts(segment: str) -> Tuple[List[float], bool]:
    """Extrait les montants d'un segment de droite de ligne.

    Retourne ``(montants, ambigu)``. L'ambiguïté vaut ``True`` dès que les
    colonnes n'étaient pas séparées par 2 espaces (regroupement par milliers
    inféré) ou qu'un jeton mélange plusieurs nombres.
    """
    if not segment or not str(segment).strip():
        return [], False
    columns = split_columns(segment)
    if len(columns) <= 1:
        tokens = [tok for tok in re.split(r"\s+", normalize_spaces(segment).strip()) if tok]
        if len(tokens) <= 1:
            value, ambiguous = parse_number_ex(tokens[0] if tokens else "")
            return ([value] if value is not None else []), ambiguous
        single = _single_number(tokens)
        if single is not None:
            return [float(single)], False
        return _split_runs(tokens), True

    values: List[float] = []
    ambiguous = False
    for column in columns:
        tokens = [tok for tok in re.split(r"\s+", column) if tok]
        single = _single_number(tokens)
        if single is not None:
            values.append(float(single))
        elif len(tokens) <= 1:
            value, flag = parse_number_ex(column)
            if value is not None:
                values.append(value)
            ambiguous = ambiguous or flag
        else:
            chunk = _split_runs(tokens)
            ambiguous = True
            values.extend(chunk)
    return values, ambiguous


# ═══════════════════════════ 2. Normalisation des libellés ═══════════════════════

# Chaque entrée : rubrique canonique, motifs « forts » (libellé comptable
# standard) et motifs « faibles » (abréviations ou libellés proches mais
# pouvant désigner autre chose → validation humaine obligatoire).
_RUBRIC_DEFS: List[Dict[str, Any]] = [
    {"block": "income", "key": "revenue", "label": "Chiffre d'affaires",
     "strong": [r"^chiffres?\s+d['’]?\s*affaires?\b", r"^chiffre\s+d['’]?\s*affaires?\s+net"],
     "weak": [r"^ca\b", r"ventes\s+de\s+marchandises"]},
    {"block": "income", "key": "gross_profit", "label": "Marge brute",
     "strong": [], "weak": [r"^marge\s+brute\b"]},
    {"block": "income", "key": "operating_income", "label": "Résultat d'exploitation",
     "strong": [r"r[ée]sultat\s+d['’]?\s*exploitation", r"r[ée]sultat\s+op[ée]rationnel"],
     "weak": [r"^r[ée]sultat\s+courant\b"]},
    {"block": "income", "key": "ebitda", "label": "EBITDA / EBE",
     "strong": [r"ex[cé]dent\s+brut\s+d['’]?\s*exploitation", r"^ebe\b"],
     "weak": []},
    {"block": "income", "key": "depreciation", "label": "Dotations aux amortissements",
     "strong": [r"dotations?\s+aux\s+amortissements?", r"amortissements?\s+et\s+provisions"],
     "weak": []},
    {"block": "income", "key": "interest_expense", "label": "Charges d'intérêts",
     "strong": [r"charges?\s+d['’]?\s*int[ée]r[êe]ts", r"int[ée]r[êe]ts\s+et\s+charges"],
     "weak": []},
    {"block": "income", "key": "taxes", "label": "Impôts sur les résultats",
     "strong": [r"imp[oô]ts?\s+sur\s+les\s+r[ée]sultats?"],
     "weak": [r"imp[oô]t\s+sur\s+les\s+soci[ée]t[ée]s"]},
    {"block": "income", "key": "net_income", "label": "Résultat net",
     "strong": [r"r[ée]sultat\s+net(\s+de\s+l['’]?\s*exercice)?(?!\s+(?:ajust|part|par|corrig))",
                r"^b[ée]n[ée]fice\s+net(?!\s+(?:ajust|part|par))"],
     "weak": [r"^r[ée]sultat\s+net\s+part\s+du\s+groupe", r"r[ée]sultat\s+net\s+ajust",
              r"^rn\b"]},
    {"block": "income", "key": "eps", "label": "Résultat par action",
     "strong": [r"r[ée]sultat\s+par\s+action", r"b[ée]n[ée]fice\s+par\s+action"],
     "weak": []},

    {"block": "balance", "key": "non_current_assets", "label": "Actif immobilisé",
     "strong": [r"^actif\s+immobilis[ée]", r"^immobilisations?\b"], "weak": []},
    {"block": "balance", "key": "current_assets", "label": "Actif circulant",
     "strong": [r"^actif\s+circulant\b", r"^total\s+actif\s+circulant"], "weak": []},
    {"block": "balance", "key": "inventory", "label": "Stocks",
     "strong": [r"^stocks?\b"], "weak": []},
    {"block": "balance", "key": "receivables", "label": "Créances clients",
     "strong": [r"cr[ée]ances?\s+(clients?|sur\s+clients?)", r"^clients?\b"], "weak": []},
    {"block": "balance", "key": "cash", "label": "Trésorerie & équivalents",
     "strong": [r"^tr[ée]sorerie[-\s]?actif\b", r"tr[ée]sorerie\s+et\s+[ée]quivalents?",
                r"^banques?,?\s*t\.?\s*g", r"^caisse\b"],
     "weak": [r"^tr[ée]sorerie\b"]},
    {"block": "balance", "key": "total_assets", "label": "Total du bilan",
     "strong": [r"total\s+du\s+bilan", r"total\s+g[ée]n[ée]ral", r"^total\s+actif\b"],
     "weak": [r"^total\s+i\b"]},
    {"block": "balance", "key": "equity", "label": "Capitaux propres",
     "strong": [r"capitaux\s+propres", r"total\s+des\s+capitaux\s+propres"], "weak": []},
    {"block": "balance", "key": "total_debt", "label": "Dettes de financement",
     "strong": [r"dettes?\s+de\s+financements?"], "weak": [r"dettes?\s+[àa]\s+(moyen|long)\s+terme"]},
    {"block": "balance", "key": "current_liabilities", "label": "Passif circulant",
     "strong": [r"^passif\s+circulant\b"], "weak": []},
    {"block": "balance", "key": "total_liabilities", "label": "Total du passif",
     "strong": [r"total\s+du\s+passif", r"^total\s+passif\b"], "weak": [r"^total\s+iii\b"]},
    {"block": "balance", "key": "net_debt", "label": "Dette nette",
     "strong": [r"dette\s+nette"], "weak": []},
    {"block": "balance", "key": "shares", "label": "Nombre de titres",
     "strong": [r"nombre\s+(d['’]?\s*actions|de\s+titres)"], "weak": []},

    {"block": "cashflow", "key": "operating_cf", "label": "Capacité d'autofinancement",
     "strong": [r"capacit[ée]\s+d['’]?\s*autofinancement",
                r"flux\s+(?:net[s]?\s+)?de\s+tr[ée]sorerie\s+(?:provenant\s+)?des?\s+activit[ée]s?\s+d['’]?\s*exploitation"],
     "weak": [r"^caf\b", r"tr[ée]sorerie\s+d['’]?\s*exploitation"]},
    {"block": "cashflow", "key": "capex", "label": "Investissements",
     "strong": [r"acquisitions?\s+et\s+augmentations?\s+d['’]?\s*immobilisations",
                r"flux\s+(?:net[s]?\s+)?de\s+tr[ée]sorerie\s+(?:provenant\s+)?des?\s+activit[ée]s?\s+d['’]?\s*investissement"],
     "weak": []},
    {"block": "cashflow", "key": "free_cash_flow", "label": "Free cash-flow",
     "strong": [r"free\s+cash[-\s]?flow", r"flux\s+de\s+tr[ée]sorerie\s+disponible"], "weak": []},
    {"block": "cashflow", "key": "dividends_paid", "label": "Distributions de bénéfices",
     "strong": [r"distributions?\s+de\s+b[ée]n[ée]fices", r"dividendes?\s+vers[ée]s"], "weak": []},
    {"block": "cashflow", "key": "net_cash_change", "label": "Variation de trésorerie",
     "strong": [r"variation\s+de\s+tr[ée]sorerie",
                r"flux\s+(?:net[s]?\s+)?de\s+tr[ée]sorerie\s+(?:provenant\s+)?des?\s+activit[ée]s?\s+d['’]?\s*financement"],
     "weak": []},
]

for _definition in _RUBRIC_DEFS:
    _definition["label"] = _definition.get("label") or _definition["key"]


@dataclass
class RubricMatch:
    block: str
    key: str
    label: str
    confidence: str  # "haute" | "moyenne"


def _compile(patterns: Sequence[str]) -> List[re.Pattern]:
    return [re.compile(pattern, re.I) for pattern in patterns]


_COMPILED: List[Tuple[Dict[str, Any], List[re.Pattern], List[re.Pattern]]] = [
    (definition, _compile(definition["strong"]), _compile(definition["weak"]))
    for definition in _RUBRIC_DEFS
]


def normalize_label(label: str) -> Tuple[List[RubricMatch], str]:
    """Associe un libellé d'origine à des rubriques canoniques.

    Retourne ``(correspondances, statut)`` avec ``statut`` ∈
    ``{"mappée", "à vérifier", "non reconnue"}``. Plusieurs correspondances ou
    une correspondance « faible » donnent « à vérifier » : la fusion n'est
    jamais décidée à la place de l'utilisateur.
    """
    text = normalize_spaces(str(label or "")).strip()
    if not text:
        return [], "non reconnue"
    strong_hits: List[RubricMatch] = []
    weak_hits: List[RubricMatch] = []
    for definition, strong_patterns, weak_patterns in _COMPILED:
        match = RubricMatch(definition["block"], definition["key"], definition["label"], "haute")
        if any(pattern.search(text) for pattern in strong_patterns):
            strong_hits.append(match)
        elif any(pattern.search(text) for pattern in weak_patterns):
            weak_hits.append(
                RubricMatch(definition["block"], definition["key"], definition["label"], "moyenne")
            )
    hits = strong_hits + weak_hits
    distinct = {(hit.block, hit.key) for hit in hits}
    if not hits:
        return [], "non reconnue"
    if len(distinct) > 1:
        return hits, "à vérifier"
    if strong_hits and not weak_hits:
        return strong_hits, "mappée"
    return hits, "à vérifier"


def canonical_key_options() -> List[str]:
    """Liste ``bloc.clé`` pour les listes déroulantes de validation."""
    options = []
    for definition in _RUBRIC_DEFS:
        options.append(f"{definition['block']}.{definition['key']}")
    return sorted(set(options))


def split_canonical(value: str) -> Optional[Tuple[str, str]]:
    """``"income.revenue"`` → ``("income", "revenue")`` ; ``None`` si vide."""
    text = str(value or "").strip()
    if not text or "." not in text:
        return None
    block, _, key = text.partition(".")
    block, key = block.strip(), key.strip()
    if block not in LINE_DEFS or key not in dict(LINE_DEFS[block]):
        return None
    return block, key


def display_block(block: str, key: str) -> str:
    if block == "income":
        return BLOCK_LABELS["income"]
    if block == "cashflow":
        return BLOCK_LABELS["cashflow"]
    if key in ASSET_KEYS:
        return BLOCK_LABELS["balance_assets"]
    return BLOCK_LABELS["balance_liabilities"]


def rubric_label(block: str, key: str) -> str:
    return dict(LINE_DEFS.get(block, [])).get(key, key)


# ═══════════════════════════ 3. Extraction PDF ═══════════════════════════

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def extract_pdf_pages(content: bytes) -> Tuple[List[str], List[str]]:
    """Texte par page d'un PDF, en privilégiant le mode ``layout``.

    Retourne ``(pages, problèmes)`` : une page illisible produit une chaîne vide
    **et** un message, jamais une exception silencieuse.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # dépendance optionnelle
        raise StatementError(
            "pypdf n'est pas installé : extraction PDF impossible. "
            "Installez-le avec « pip install pypdf »."
        ) from exc
    import io

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise StatementError(f"PDF illisible : {exc}") from exc

    pages: List[str] = []
    issues: List[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = ""
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except TypeError:
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                issues.append(f"Page {index} non extractible : {exc}")
        except Exception as exc:
            issues.append(f"Page {index} : extraction en mode layout impossible ({exc})")
            try:
                text = page.extract_text() or ""
            except Exception as inner:
                issues.append(f"Page {index} non extractible : {inner}")
        if not text.strip():
            issues.append(f"Page {index} : aucun texte extractible (document scanné ?).")
        pages.append(text)
    return pages, issues


def detect_exercise_labels(text: str, limit: int = 3) -> List[str]:
    """Repère les exercices d'une page (années, dans l'ordre d'apparition)."""
    found: List[str] = []
    for line in normalize_spaces(text).splitlines()[:60]:
        for year in _YEAR_RE.findall(line):
            if year not in found:
                found.append(year)
        if len(found) >= limit:
            break
    return found[:limit]


def detect_currency(text: str) -> str:
    sample = normalize_spaces(text)[:200000]
    for code, pattern in CURRENCY_PATTERNS.items():
        if re.search(pattern, sample, re.I):
            return code
    return ""


# ═══════════════════════════ 4. Structuration ═══════════════════════════

@dataclass
class ExtractedRow:
    """Une rubrique, ses libellés et les montants par exercice."""

    block: Optional[str]
    key: Optional[str]
    label: str
    values: List[Optional[float]]
    unit: str
    currency: str
    page: Optional[int]
    status: str
    confidence: str
    note: str = ""


@dataclass
class ExtractionResult:
    rows: List[ExtractedRow] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    unit: str = ""
    currency: str = ""
    value_columns: List[str] = field(default_factory=lambda: ["Exercice", "Exercice précédent"])
    source: str = ""
    pages: int = 0


# Pas d'expression régulière « label + montants » : sur des lignes longues,
# un motif gourmand peut provoquer un backtracking catastrophique. On découpe
# donc manuellement, de façon linéaire, au premier chiffre rencontré.
_HEADER_HINT_RE = re.compile(r"(exercice|au\s+31|ann[ée]e|[ée]tats?\s+financ)", re.I)


def _first_digit_index(text: str) -> int:
    for index, char in enumerate(text):
        if char.isdigit():
            return index
    return -1


def _split_label_amounts(line: str) -> Optional[Tuple[str, str]]:
    """Sépare un libellé de ses montants au **premier chiffre** de la ligne.

    ``"Chiffre d'affaires 1 000 900"`` → ``("Chiffre d'affaires", "1 000 900")``.
    Retourne ``None`` si la ligne ne contient pas de couple libellé/montant.
    """
    text = normalize_spaces(line).strip()
    index = _first_digit_index(text)
    if index <= 0:
        return None
    label = text[:index].strip(" .:\t")
    amounts = text[index:].strip()
    if not label or not amounts:
        return None
    return label, amounts


def _row_from_line(line: str, page: int, unit: str, currency: str,
                   columns: Sequence[str]) -> Optional[ExtractedRow]:
    """Transforme une ligne de tableau en ``ExtractedRow`` (ou ``None``)."""
    columns_list = split_columns(line)
    ambiguous = False
    if len(columns_list) >= 2:
        label = columns_list[0]
        amounts, ambiguous = extract_amounts("   ".join(columns_list[1:]))
    else:
        split = _split_label_amounts(line)
        if split is None:
            return None
        label, amounts_segment = split
        amounts, ambiguous = extract_amounts(amounts_segment)
        ambiguous = True  # pas de séparateur de colonnes net : découpage inféré
    if not amounts or not label or len(label) > 160:
        return None
    if len(amounts) > len(columns):
        amounts = amounts[: len(columns)]
        ambiguous = True

    matches, status = normalize_label(label)
    note = ""
    if len(matches) > 1:
        note = "plusieurs rubriques candidates : " + ", ".join(
            f"{hit.block}.{hit.key}" for hit in matches
        )
        status = "à vérifier"
    if status == "non reconnue":
        note = "libellé non reconnu automatiquement"
    if ambiguous:
        note = (note + " · " if note else "") + "séparateurs de colonnes incertains"
        if status == "mappée":
            status = "à vérifier"

    best = matches[0] if matches else None
    block = best.block if best else None
    key = best.key if best else None
    confidence = "haute" if status == "mappée" else ("moyenne" if matches else "faible")

    values: List[Optional[float]] = []
    for index in range(len(columns)):
        values.append(amounts[index] if index < len(amounts) else None)
    return ExtractedRow(block=block, key=key, label=label, values=values, unit=unit,
                        currency=currency, page=page, status=status,
                        confidence=confidence, note=note)


def structure_text(text: str, source: str = "", page: Optional[int] = None) -> ExtractionResult:
    """Structure un texte d'état financier (une page ou un document entier)."""
    unit = detect_unit(text)
    currency = detect_currency(text)
    years = detect_exercise_labels(text)
    if len(years) >= 2:
        columns = years[:2]
    elif len(years) == 1:
        columns = [years[0], "Exercice précédent"]
    else:
        columns = ["Exercice", "Exercice précédent"]

    result = ExtractionResult(unit=unit, currency=currency, source=source,
                              value_columns=columns, pages=1 if page else 0)
    for raw_line in normalize_spaces(text).splitlines():
        line = raw_line.strip()
        if not line or len(line) > 240:
            continue
        columns_list = split_columns(line)
        # Ligne d'en-tête : des années/sous-titres, peu ou pas de montants.
        if (_HEADER_HINT_RE.search(line) and len(columns_list) < 2
                and _split_label_amounts(line) is None):
            continue
        row = _row_from_line(line, page or 1, unit, currency, columns)
        if row is not None:
            result.rows.append(row)
    result.pages = 1 if page else 0
    result.issues.extend(coherence_issues(result.rows))
    return result


def structure_pdf(content: bytes, source: str = "") -> ExtractionResult:
    """Structure un PDF complet, page par page, avec traçabilité."""
    pages, extraction_issues = extract_pdf_pages(content)
    combined = "\n".join(pages)
    result = ExtractionResult(source=source, pages=len(pages))
    result.unit = detect_unit(combined)
    result.currency = detect_currency(combined)
    years = detect_exercise_labels(combined)
    if len(years) >= 2:
        result.value_columns = years[:2]
    elif len(years) == 1:
        result.value_columns = [years[0], "Exercice précédent"]
    for number, page_text in enumerate(pages, start=1):
        if not page_text.strip():
            continue
        page_result = structure_text(page_text, source=source, page=number)
        result.rows.extend(page_result.rows)
    result.issues.extend(extraction_issues)
    result.issues.extend(coherence_issues(result.rows))
    return result


# ═══════════════════════════ 5. Contrôles de cohérence ═══════════════════════

def coherence_issues(rows: Sequence[ExtractedRow]) -> List[str]:
    """Anomalies détectées, sans jamais modifier les montants sources."""
    issues: List[str] = []
    seen: Dict[Tuple[Optional[str], Optional[str]], float] = {}
    for row in rows:
        if not row.key or row.block is None or not row.values:
            continue
        key = (row.block, row.key)
        current = row.values[0]
        if current is None:
            continue
        if key in seen and abs(seen[key] - current) > 1.0:
            issues.append(
                f"Doublon « {rubric_label(row.block, row.key)} » avec deux valeurs différentes "
                f"({seen[key]:,.0f} et {current:,.0f}) : à vérifier."
            )
        else:
            seen[key] = current

    assets = seen.get(("balance", "total_assets"))
    liabilities = seen.get(("balance", "total_liabilities"))
    if assets is not None and liabilities is not None:
        tolerance = max(1.0, abs(assets) * 0.005)
        if abs(assets - liabilities) > tolerance:
            issues.append(
                "Total actif ≠ total passif "
                f"({assets:,.0f} vs {liabilities:,.0f}) : périmètre ou extraction à vérifier."
            )
    if not seen:
        issues.append("Aucune rubrique canonique reconnue : validation humaine nécessaire.")
    return issues


# ═══════════════════════════ 6. Tableaux et enregistrement ═══════════════════════

def to_editor_frame(result: ExtractionResult) -> pd.DataFrame:
    """DataFrame éditable : une ligne par rubrique, une colonne par exercice."""
    value_columns = result.value_columns or ["Exercice", "Exercice précédent"]
    records: List[Dict[str, Any]] = []
    for row in result.rows:
        entry: Dict[str, Any] = {
            "Bloc": display_block(row.block, row.key) if row.block else "—",
            "Clé": f"{row.block}.{row.key}" if row.block and row.key else "",
            "Rubrique": rubric_label(row.block, row.key) if row.block and row.key else row.label,
            "Libellé d'origine": row.label,
            "Unité": row.unit or result.unit,
            "Devise": row.currency or result.currency,
            "Page": row.page,
            "Confiance": row.confidence,
            "Statut": row.status + (f" — {row.note}" if row.note and row.note not in row.status else ""),
        }
        for index, column in enumerate(value_columns):
            entry[column] = row.values[index] if index < len(row.values) else None
        records.append(entry)
    columns = META_COLUMNS[:7] + list(value_columns) + META_COLUMNS[7:]
    frame = pd.DataFrame(records, columns=columns)
    return frame


def block_tables(result: ExtractionResult) -> Dict[str, pd.DataFrame]:
    """Un DataFrame par bloc, en lignes = rubriques et colonnes = exercices."""
    frame = to_editor_frame(result)
    tables: Dict[str, pd.DataFrame] = {}
    if frame.empty:
        return tables
    for label in ("Bilan actif", "Bilan passif", "CPC", "Trésorerie"):
        subset = frame[frame["Bloc"] == label]
        if subset.empty:
            continue
        tables[label] = subset
    return tables


def frame_to_record(frame: pd.DataFrame, symbol: str, *, issuer: Optional[str] = None,
                    consolidated: bool = False, source: str = "", source_url: str = "",
                    fiscal_year: Optional[int] = None,
                    period: str = "FY") -> Tuple[Dict[str, Any], List[str]]:
    """Construit un enregistrement canonique à partir d'un tableau **validé**.

    Les lignes sans clé canonique sont ignorées (jamais devinées) et listées en
    retour. Aucune valeur absente n'est remplacée par zéro.
    """
    if frame is None or frame.empty:
        raise StatementError("Aucune ligne à enregistrer : lancez d'abord une extraction.")
    value_columns = [column for column in frame.columns if column not in META_COLUMNS]
    if not value_columns:
        raise StatementError("Aucune colonne d'exercice identifiable dans le tableau.")

    record: Dict[str, Any] = {
        "symbol": symbol.strip().upper(),
        "issuer": issuer,
        "period": period,
        "fiscal_year": fiscal_year,
        "period_end": "",
        "currency": "",
        "unit": "",
        "consolidated": bool(consolidated),
        "source": source or "extraction PDF validée",
        "source_url": source_url,
        "status": "manual",
        "provider": "extraction PDF",
        "income": {}, "balance": {}, "cashflow": {},
        "lines": {"income": [], "balance_assets": [], "balance_liabilities": [], "cashflow": []},
    }
    skipped: List[str] = []
    for _, row in frame.iterrows():
        mapping = split_canonical(row.get("Clé"))
        if mapping is None:
            skipped.append(str(row.get("Libellé d'origine") or row.get("Rubrique") or "—"))
            continue
        block, key = mapping
        value = row.get(value_columns[0]) if value_columns else None
        previous = row.get(value_columns[1]) if len(value_columns) > 1 else None
        value = parse_number(value) if value is not None and not isinstance(value, (int, float)) else value
        previous = (parse_number(previous) if previous is not None and not isinstance(previous, (int, float))
                    else previous)
        if value is not None and value == value:
            record[block][key] = float(value)
        if not record["unit"] and row.get("Unité"):
            record["unit"] = str(row["Unité"])
        if not record["currency"] and row.get("Devise"):
            record["currency"] = str(row["Devise"])
        line_block = block if block != "balance" else (
            "balance_assets" if key in ASSET_KEYS else "balance_liabilities"
        )
        record["lines"][line_block].append({
            "label": str(row.get("Libellé d'origine") or rubric_label(block, key)),
            "value": float(value) if value is not None and value == value else None,
            "prior": float(previous) if previous is not None and previous == previous else None,
            "page": row.get("Page"),
        })
    record["currency"] = record["currency"] or "MAD"
    record["unit"] = record["unit"] or "MAD"
    if fiscal_year is None and value_columns:
        year = _YEAR_RE.search(str(value_columns[0]))
        if year:
            record["fiscal_year"] = int(year.group(0))
    if not any(record[block] for block in ("income", "balance", "cashflow")):
        raise StatementError(
            "Aucune rubrique canonique valide : assignez une « Clé » aux lignes à enregistrer."
        )
    for block in record["lines"]:
        record["lines"][block] = [item for item in record["lines"][block] if item["value"] is not None
                                  or item["prior"] is not None]
    # Une ligne de bilan sans valeur dans la colonne principale est conservée
    # uniquement si l'exercice précédent est renseigné.
    return record, skipped


__all__ = [
    "ExtractedRow", "ExtractionResult", "RubricMatch",
    "block_tables", "canonical_key_options", "coherence_issues",
    "detect_currency", "detect_exercise_labels", "extract_amounts", "extract_pdf_pages",
    "frame_to_record", "normalize_label", "normalize_spaces", "parse_number",
    "parse_number_ex", "split_canonical", "split_columns", "structure_pdf",
    "structure_text", "to_editor_frame",
]
