"""v1.0 – Analyse pharmacologique automatique post‑séance.

Le module propose ``analyze_pharmacology`` qui :
    * détecte les mentions de médicaments dans le transcript ;
    * normalise vers la DCI via la table ``pharma_map.json`` ;
    * récupère les informations synthétiques du lexique clinique ;
    * assemble un mémo pratique orienté réduction des risques.

Les résultats sont pensés pour être idempotents et directement intégrables
au méga-prompt via le bloc ``[PHARMA_MEMO]``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from server.research import resource_path
from server.research.utils import ensure_text, tokenize
from server.utils.fr_text import normalize_punctuation

_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "post_session.log"


@dataclass
class MoleculeEntry:
    dci: str
    classe: str
    mecanisme: str
    demi_vie: str
    effets_frequents: List[str]
    effets_severes: List[str]
    rdr: List[str]
    refs: List[str]


_LOGGER: Optional[logging.Logger] = None


def _get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger("assist.post_session.pharma")
    if not logger.handlers:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    _LOGGER = logger
    return logger


def _load_json(name: str) -> Dict[str, object]:
    path = resource_path(name)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


_MAPPING: Optional[Dict[str, str]] = None
_LEXICON: Optional[Dict[str, Dict[str, object]]] = None


def _mapping() -> Dict[str, str]:
    global _MAPPING
    if _MAPPING is not None:
        return _MAPPING
    raw = _load_json("pharma_map.json")
    mapping: Dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            mapping[ensure_text(key).casefold()] = ensure_text(value).casefold()
    _MAPPING = mapping
    return mapping


def _lexicon() -> Dict[str, Dict[str, object]]:
    global _LEXICON
    if _LEXICON is not None:
        return _LEXICON
    raw = _load_json("pharma_lexicon.json")
    lexicon: Dict[str, Dict[str, object]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            lexicon[ensure_text(key).casefold()] = value
    _LEXICON = lexicon
    return lexicon


def _detect_molecules(payload: Sequence[str]) -> List[str]:
    text = " ".join(ensure_text(part) for part in payload if part)
    tokens = tokenize(text)
    mapping = _mapping()
    found: List[str] = []
    seen: set[str] = set()
    for span in range(3, 0, -1):
        if span > len(tokens):
            continue
        for idx in range(len(tokens) - span + 1):
            chunk = " ".join(tokens[idx : idx + span])
            canonical = mapping.get(chunk)
            if canonical and canonical not in seen:
                seen.add(canonical)
                found.append(canonical)
    return found


def _to_entry(name: str, data: Dict[str, object]) -> MoleculeEntry:
    return MoleculeEntry(
        dci=name,
        classe=ensure_text(data.get("class")),
        mecanisme=ensure_text(data.get("mechanism")),
        demi_vie=ensure_text(data.get("half_life")),
        effets_frequents=[ensure_text(item) for item in data.get("common", []) if item],
        effets_severes=[ensure_text(item) for item in data.get("serious", []) if item],
        rdr=[ensure_text(item) for item in data.get("rdr", []) if item],
        refs=[ensure_text(item) for item in data.get("refs", []) if item],
    )


def _format_entry(entry: MoleculeEntry) -> Dict[str, object]:
    return {
        "dci": entry.dci,
        "classe": entry.classe,
        "mecanisme": entry.mecanisme,
        "demi_vie": entry.demi_vie,
        "effets_frequents": entry.effets_frequents,
        "effets_severes": entry.effets_severes,
        "rdr": entry.rdr,
        "refs": entry.refs,
    }


def _build_memo(entries: Sequence[MoleculeEntry]) -> str:
    if not entries:
        return "Analyse pharmacologique non contributive : aucune molécule identifiable."
    lines: List[str] = []
    for entry in entries:
        frequent = ", ".join(entry.effets_frequents[:3]) or "tolérance variable"
        rdr = ", ".join(entry.rdr[:3]) or "rappels RDR non documentés"
        line = (
            f"{entry.dci.capitalize()} : {entry.classe}; demi-vie {entry.demi_vie or 'n.c.'}. "
            f"Impacts quotidiens : {frequent}. RDR : {rdr}."
        )
        lines.append(normalize_punctuation(line))
        lines.append(
            normalize_punctuation(
                f"Titration/sevrage : prévoir paliers progressifs et surveillance des effets corporels."
            )
        )
        lines.append(
            normalize_punctuation(
                "Ce que l’on ignore : données limitées sur la réponse individuelle, suivre les priorités de la personne."
            )
        )
    memo = "\n".join(lines)
    memo = normalize_punctuation(memo)
    return memo


def analyze_pharmacology(transcript: str, plan_text: Optional[str] = None) -> Dict[str, object]:
    transcript = ensure_text(transcript)
    plan_text = ensure_text(plan_text)
    logger = _get_logger()
    logger.info("pharma_analysis_start len_transcript=%d", len(transcript))
    tokens_source = [transcript, plan_text]
    molecules = _detect_molecules(tokens_source)
    lexicon = _lexicon()
    entries: List[MoleculeEntry] = []
    for name in molecules:
        data = lexicon.get(name)
        if not data:
            continue
        entries.append(_to_entry(name, data))
    memo = _build_memo(entries)
    export_block = "[PHARMA_MEMO]\n" + memo if memo else "[PHARMA_MEMO]\n— néant explicite —"
    logger.info("pharma_analysis_done molecules=%d", len(entries))
    return {
        "molecules": [_format_entry(entry) for entry in entries],
        "memo": memo,
        "export_block": export_block,
    }


__all__ = ["analyze_pharmacology"]
