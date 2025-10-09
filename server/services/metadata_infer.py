"""Inférence de métadonnées locales pour les documents PDF."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import regex as re
import yaml
from langdetect import DetectorFactory
from langdetect import detect_langs
from langdetect.lang_detect_exception import LangDetectException
from pdfminer.high_level import extract_text
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfparser import PDFParser
from sklearn.feature_extraction.text import TfidfVectorizer

try:  # pragma: no cover - dépendance optionnelle
    import pikepdf
except Exception:  # pragma: no cover - fallback
    pikepdf = None  # type: ignore

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = BASE_DIR / "library_config"
DOMAINS_PATH = CONFIG_DIR / "domains.yml"
DEFAULTS_PATH = CONFIG_DIR / "defaults.yml"
STOPWORDS_DIR = CONFIG_DIR / "stopwords"

DetectorFactory.seed = 0

_ALNUM_RE = re.compile(r"[\p{L}\p{N}]")
_ABSTRACT_RE = re.compile(r"\b(abstract|résumé)\b[:\s-]*", re.IGNORECASE)
_SECTION_SPLIT_RE = re.compile(r"\n{2,}")
_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}")
_NAME_FORBIDDEN_RE = re.compile(r"(universit|department|centre|clinic|h[oô]pital|hospital|college)", re.IGNORECASE)
_WORD_SPLIT_RE = re.compile(r"[\s,;]+")


def _normalise_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", "ignore")
    return str(value)


def _normalise_xmp(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalise_xmp(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalise_xmp(item) for item in value]
    if hasattr(value, "as_pdf_object"):
        try:
            return _normalise_text(value)
        except Exception:  # pragma: no cover - robustesse
            return str(value)
    return _normalise_text(value)


def _read_pdf_info(path: Path) -> Dict[str, str] | None:
    try:
        with path.open("rb") as handle:
            parser = PDFParser(handle)
            document = PDFDocument(parser)
            entries = document.info or []
            if not entries:
                return None
            info = {}
            for key, value in entries[0].items():
                info[_normalise_text(key)] = _normalise_text(value)
            return info
    except Exception as exc:  # pragma: no cover - robustesse
        LOGGER.debug("pdf_info_failed", extra={"path": str(path), "error": str(exc)})
        return None


def _read_xmp(path: Path) -> Dict[str, Any] | None:
    if pikepdf is None:  # pragma: no cover - dépendance optionnelle
        return None
    try:
        with pikepdf.open(str(path)) as pdf:  # type: ignore[arg-type]
            metadata = pdf.open_metadata()
            payload: Dict[str, Any] = {}
            for key in list(metadata.keys()):
                try:
                    payload[str(key)] = _normalise_xmp(metadata[key])
                except KeyError:
                    continue
            return payload or None
    except Exception as exc:  # pragma: no cover - robustesse
        LOGGER.debug("xmp_read_failed", extra={"path": str(path), "error": str(exc)})
        return None


def _extract_text(path: Path, *, page_numbers: Sequence[int] | None = None) -> str:
    try:
        text = extract_text(str(path), page_numbers=page_numbers)
    except Exception as exc:  # pragma: no cover - robustesse
        LOGGER.warning("pdf_text_failed", extra={"path": str(path), "error": str(exc)})
        return ""
    if not text:
        return ""
    return text.replace("\u0000", " ").strip()


def _detect_language(sample: str) -> str:
    cleaned = _ALNUM_RE.findall(sample)
    if len(cleaned) < 20:
        return "und"
    snippet = sample[:5000]
    try:
        candidates = detect_langs(snippet)
    except LangDetectException:
        return "und"
    if not candidates:
        return "und"
    best = max(candidates, key=lambda item: item.prob)
    return best.lang


def extract_pdf_streams(path: Path | str) -> Dict[str, Any]:
    """Extrait les flux texte et métadonnées brutes d'un PDF."""

    pdf_path = Path(path)
    info = _read_pdf_info(pdf_path)
    xmp = _read_xmp(pdf_path)
    full_text = _extract_text(pdf_path)
    first_page_text = _extract_text(pdf_path, page_numbers=[0])
    language = _detect_language(" ".join(filter(None, [
        (info or {}).get("Title", ""),
        first_page_text,
        full_text[:4000],
    ])))

    return {
        "xmp": xmp,
        "info": info,
        "text": full_text,
        "first_page_text": first_page_text,
        "language": language,
    }


def _select_lang_alt(value: Any, language: str | None) -> str:
    if isinstance(value, dict):
        lang_key = (language or "").split("-")[0]
        for key in (lang_key, f"{lang_key}-xx", "x-default"):
            if key and key in value:
                result = _select_lang_alt(value.get(key), language)
                if result:
                    return result
        for candidate in value.values():
            result = _select_lang_alt(candidate, language)
            if result:
                return result
        return ""
    if isinstance(value, list):
        for candidate in value:
            result = _select_lang_alt(candidate, language)
            if result:
                return result
        return ""
    return _normalise_text(value).strip()


def _clean_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line and line.strip()]


def infer_title(meta: Mapping[str, Any]) -> Tuple[str, str]:
    language = meta.get("language") if isinstance(meta, Mapping) else None
    xmp = meta.get("xmp") if isinstance(meta, Mapping) else None
    if isinstance(xmp, Mapping):
        xmp_title = _select_lang_alt(xmp.get("dc:title"), language)
        if xmp_title:
            return xmp_title, "xmp"

    info = meta.get("info") if isinstance(meta, Mapping) else None
    if isinstance(info, Mapping):
        info_title = _normalise_text(info.get("Title") or info.get("title"))
        if info_title:
            return info_title, "info"

    first_page_text = meta.get("first_page_text", "") or ""
    candidates: List[str] = []
    for line in _clean_lines(first_page_text):
        if re.search(r"^(abstract|résumé)\b", line, re.IGNORECASE):
            break
        if len(line) < 4:
            continue
        if re.fullmatch(r"[0-9\-\s]+", line):
            continue
        candidates.append(line)
        if len(candidates) >= 3:
            break
    if candidates:
        best = max(candidates, key=len)
        return best, "heuristic"
    return "Document sans titre", "fallback"


def _split_authors(value: str) -> List[str]:
    authors: List[str] = []
    for chunk in _WORD_SPLIT_RE.split(value):
        candidate = chunk.strip()
        if not candidate or len(candidate) < 2:
            continue
        authors.append(candidate)
    if not authors:
        fragments = [frag.strip() for frag in re.split(r";|/", value) if frag.strip()]
        for frag in fragments:
            if frag not in authors:
                authors.append(frag)
    return authors


def _looks_like_name(value: str) -> bool:
    if not value:
        return False
    if _NAME_FORBIDDEN_RE.search(value):
        return False
    tokens = [token.strip(".-") for token in value.replace("'", " ").split() if token.strip(".-")]
    if len(tokens) < 2 or len(tokens) > 5:
        return False
    score = 0
    for token in tokens:
        if not re.fullmatch(r"[\p{L}]+", token):
            return False
        if token[0].isupper():
            score += 1
    return score >= max(2, len(tokens) - 1)


def infer_authors(meta: Mapping[str, Any]) -> Tuple[List[str], str]:
    language = meta.get("language") if isinstance(meta, Mapping) else None
    xmp = meta.get("xmp") if isinstance(meta, Mapping) else None
    if isinstance(xmp, Mapping):
        creators = xmp.get("dc:creator")
        if creators:
            if isinstance(creators, list):
                authors = [
                    _normalise_text(item).strip()
                    for item in creators
                    if _looks_like_name(_normalise_text(item))
                ]
            else:
                authors = [
                    name
                    for name in _split_authors(_normalise_text(creators))
                    if _looks_like_name(name)
                ]
            if authors:
                return list(dict.fromkeys(authors)), "xmp"

    info = meta.get("info") if isinstance(meta, Mapping) else None
    if isinstance(info, Mapping):
        raw = _normalise_text(info.get("Author") or info.get("author"))
        if raw:
            authors = [name for name in _split_authors(raw) if _looks_like_name(name)]
            if authors:
                return list(dict.fromkeys(authors)), "info"

    first_page_text = meta.get("first_page_text", "") or ""
    lines = _clean_lines(first_page_text)
    names: List[str] = []
    for line in lines[1:6]:
        fragments = [frag.strip() for frag in re.split(r",|;| et | and ", line) if frag.strip()]
        for fragment in fragments:
            if _looks_like_name(fragment):
                names.append(fragment)
    if names:
        return list(dict.fromkeys(names)), "heuristic"
    return [], "heuristic"


def _extract_year_candidates(*values: Any) -> List[int]:
    years: List[int] = []
    for value in values:
        text = _normalise_text(value)
        for match in _YEAR_RE.findall(text):
            try:
                year = int(match[0:4])
            except ValueError:
                continue
            years.append(year)
    return years


def infer_year(meta: Mapping[str, Any]) -> Tuple[int | None, str]:
    xmp = meta.get("xmp") if isinstance(meta, Mapping) else None
    info = meta.get("info") if isinstance(meta, Mapping) else None
    first_page_text = meta.get("first_page_text", "") or ""
    candidates: List[int] = []
    provenance = "heuristic"
    if isinstance(xmp, Mapping):
        date_field = xmp.get("dc:date") or xmp.get("xmp:CreateDate")
        if date_field:
            candidates = _extract_year_candidates(date_field)
            if candidates:
                provenance = "xmp"
    if not candidates and isinstance(info, Mapping):
        date_fields = [info.get("CreationDate"), info.get("ModDate"), info.get("Producer")]
        candidates = _extract_year_candidates(*date_fields)
        if candidates:
            provenance = "info"
    if not candidates:
        candidates = _extract_year_candidates(first_page_text)
    filtered = [year for year in candidates if 1900 <= year <= 2100]
    if not filtered:
        return None, provenance
    return max(filtered), provenance


TYPE_RULES: List[Tuple[str, List[re.Pattern[str]]]] = [
    (
        "Méta-analyse",
        [re.compile(pattern, re.IGNORECASE) for pattern in [r"méta[- ]analyse", r"meta-?analysis"]],
    ),
    (
        "Revue systématique",
        [
            re.compile(pattern, re.IGNORECASE)
            for pattern in [r"revue systématique", r"systematic review", r"evidence synthesis"]
        ],
    ),
    (
        "Essai randomisé",
        [
            re.compile(pattern, re.IGNORECASE)
            for pattern in [
                r"essai randomis",
                r"randomized controlled trial",
                r"randomised controlled trial",
            ]
        ],
    ),
    (
        "Observationnelle",
        [
            re.compile(pattern, re.IGNORECASE)
            for pattern in [r"cohort", r"étude observationnelle", r"observational study"]
        ],
    ),
    (
        "Cas clinique",
        [re.compile(pattern, re.IGNORECASE) for pattern in [r"case report", r"étude de cas", r"n=1"]],
    ),
    (
        "Qualitatif",
        [
            re.compile(pattern, re.IGNORECASE)
            for pattern in [r"qualitative", r"entretiens", r"focus group", r"analyse thématique"]
        ],
    ),
    (
        "Guide",
        [
            re.compile(pattern, re.IGNORECASE)
            for pattern in [r"guide", r"guideline", r"recommandation clinique", r"practice guideline"]
        ],
    ),
]


def infer_type(meta: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    text = " ".join(
        filter(
            None,
            [
                _normalise_text(meta.get("first_page_text")),
                _normalise_text(meta.get("text"))[:10000],
            ],
        )
    )
    signals: List[str] = []
    for type_label, patterns in TYPE_RULES:
        for pattern in patterns:
            if pattern.search(text):
                signals.append(pattern.pattern)
                return type_label, {"signals": signals, "provenance": "rule"}
    return "Article", {"signals": [], "provenance": "rule"}


@lru_cache(maxsize=1)
def _load_defaults() -> Dict[str, Any]:
    if not DEFAULTS_PATH.exists():
        return {}
    try:
        payload = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - robustesse
        LOGGER.warning("defaults_yaml_invalid", extra={"error": str(exc)})
        return {}
    return payload or {}


def infer_evidence_level(inferred_type: str, meta: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    defaults = _load_defaults()
    mapping = defaults.get("type_to_level", {}) or {}
    level = mapping.get(inferred_type)
    conflict = False
    if level is None:
        level = mapping.get("Article", "Théorique")
        conflict = True
    return level, {"provenance": "defaults", "conflict": conflict}


@lru_cache(maxsize=1)
def _load_domains() -> Dict[str, Any]:
    if not DOMAINS_PATH.exists():
        return {}
    try:
        payload = yaml.safe_load(DOMAINS_PATH.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - robustesse
        LOGGER.warning("domains_yaml_invalid", extra={"error": str(exc)})
        return {}
    domains: Dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if not isinstance(value, Mapping):
            continue
        synonyms_raw = value.get("synonyms", {})
        synonyms: Dict[str, List[str]] = {}
        if isinstance(synonyms_raw, Mapping):
            for lang, entries in synonyms_raw.items():
                synonyms[str(lang)] = [str(entry).lower() for entry in entries or []]
        elif isinstance(synonyms_raw, list):
            synonyms["any"] = [str(entry).lower() for entry in synonyms_raw]
        else:
            synonyms["any"] = []
        domains[key] = {
            "label": value.get("label") or key.replace("_", " ").title(),
            "synonyms": synonyms,
        }
    return domains


def infer_domains(meta: Mapping[str, Any], config_domains: Mapping[str, Any] | None = None) -> List[str]:
    domains = config_domains or _load_domains()
    if not domains:
        return []
    language = (meta.get("language") or "und").split("-")[0]
    haystack = " ".join(
        filter(
            None,
            [
                _normalise_text(meta.get("first_page_text")),
                _normalise_text(meta.get("text"))[:12000],
            ],
        )
    ).lower()
    matches: List[str] = []
    for key, entry in domains.items():
        synonyms = entry.get("synonyms", {})
        tokens: List[str] = []
        tokens.extend(synonyms.get("any", []))
        if language in synonyms:
            tokens.extend(synonyms.get(language, []))
        for token in tokens:
            if not token:
                continue
            pattern = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
            if pattern.search(haystack):
                matches.append(entry.get("label") or key)
                break
    return matches


@lru_cache(maxsize=32)
def _load_stopwords(language: str) -> List[str]:
    lang = language.split("-")[0]
    candidates = [STOPWORDS_DIR / f"{lang}.txt", STOPWORDS_DIR / "en.txt"]
    words: List[str] = []
    for path in candidates:
        if not path.exists():
            continue
        words.extend(
            [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        )
    return words


def _levenshtein_ratio(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    # Utilise la distance de Levenshtein via l'algorithme de Wagner-Fischer simplifié
    len_a, len_b = len(a), len(b)
    prev = list(range(len_b + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i] + [0] * len_b
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current[j] = min(
                current[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            )
        prev = current
    distance = prev[-1]
    return 1.0 - distance / max(len_a, len_b)


def infer_keywords(meta: Mapping[str, Any]) -> List[Dict[str, Any]]:
    language = (meta.get("language") or "en").split("-")[0]
    stopwords = _load_stopwords(language)
    defaults = _load_defaults().get("keyword", {})
    max_terms = int(defaults.get("max_terms", 10))
    min_len = int(defaults.get("min_len", 3))

    title_value, _ = infer_title(meta)
    first_page = _normalise_text(meta.get("first_page_text"))
    abstract = ""
    abstract_match = _ABSTRACT_RE.split(first_page, maxsplit=1)
    if len(abstract_match) > 1:
        abstract = abstract_match[-1].split("\n\n", 1)[0]
    body = _normalise_text(meta.get("text"))[:20000]

    regions: List[Tuple[str, str]] = []
    for name, text in (
        ("title", title_value),
        ("abstract", abstract),
        ("heading", first_page),
        ("body", body),
    ):
        if text and text.strip():
            regions.append((name, text))
    if not regions:
        return []

    documents = [text for _, text in regions]
    try:
        vectorizer = TfidfVectorizer(
            stop_words=stopwords,
            ngram_range=(1, 2),
            max_features=max_terms * 4,
            lowercase=True,
        )
        matrix = vectorizer.fit_transform(documents)
    except ValueError:
        return []

    features = vectorizer.get_feature_names_out()
    scores = matrix.toarray()
    candidates: List[Tuple[str, str, float, int]] = []
    for idx, token in enumerate(features):
        best_region_index = int(scores[:, idx].argmax())
        best_score = float(scores[best_region_index, idx])
        if best_score <= 0:
            continue
        region_name = regions[best_region_index][0]
        region_text = regions[best_region_index][1].lower()
        occurrences = len(re.findall(rf"\b{re.escape(token)}\b", region_text))
        candidates.append((token, region_name, best_score, occurrences))

    candidates.sort(key=lambda item: (-item[2], -item[3], item[0]))
    results: List[Dict[str, Any]] = []
    for token, region, score, occurrences in candidates:
        cleaned = token.strip()
        if len(cleaned) < min_len:
            continue
        if any(_levenshtein_ratio(cleaned, entry["text"]) > 0.85 for entry in results):
            continue
        results.append({"text": cleaned, "source": region, "freq": max(1, occurrences)})
        if len(results) >= max_terms:
            break
    return results


def propose_critical_notes(meta: Mapping[str, Any]) -> List[str]:
    text = "\n".join(
        filter(
            None,
            [
                _normalise_text(meta.get("first_page_text")),
                _normalise_text(meta.get("text"))[:8000],
            ],
        )
    )
    patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"limitation",
            r"limites",
            r"biais",
            r"bias",
            r"financement",
            r"funding",
            r"conflict of interest",
            r"prisma",
            r"grade",
            r"rob",
        ]
    ]
    notes: List[str] = []
    for block in _SECTION_SPLIT_RE.split(text):
        line = block.strip()
        if not line:
            continue
        if any(pattern.search(line) for pattern in patterns):
            notes.append(line)
    return notes[:8]


def default_toggles(
    inferred_type: str,
    inferred_level: str,
    meta: Mapping[str, Any],
    defaults: Mapping[str, Any] | None = None,
) -> Dict[str, bool]:
    rules = (defaults or {}).get("toggle_rules") or _load_defaults().get("toggle_rules", {})
    toggles = {"pre": False, "post": False}
    for key in toggles:
        rule = rules.get(key) if isinstance(rules, Mapping) else {}
        default_value = bool(rule.get("default", False)) if isinstance(rule, Mapping) else False
        allow = rule.get("allow", []) if isinstance(rule, Mapping) else []
        toggles[key] = inferred_type in allow or default_value
    return toggles


def should_pseudonymize(meta: Mapping[str, Any]) -> bool:
    defaults = _load_defaults()
    triggers = defaults.get("pseudonymize_triggers", [])
    haystack = " ".join(
        filter(
            None,
            [
                _normalise_text(meta.get("first_page_text")),
                _normalise_text(meta.get("text"))[:8000],
            ],
        )
    ).lower()
    for trigger in triggers:
        if trigger and trigger.lower() in haystack:
            return True
    return False


__all__ = [
    "default_toggles",
    "extract_pdf_streams",
    "infer_authors",
    "infer_domains",
    "infer_evidence_level",
    "infer_keywords",
    "infer_title",
    "infer_type",
    "infer_year",
    "propose_critical_notes",
    "should_pseudonymize",
]

