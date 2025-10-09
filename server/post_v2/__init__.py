"""Post-session v2 package with lazy exports."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "extract_session_facts",
    "search_local_evidence",
    "search_web_evidence",
    "build_knowledge_pack",
    "assemble_megaprompt",
    "style_blocks",
    "SessionFacts",
    "EvidenceItemLocal",
    "EvidenceItemWeb",
    "KnowledgePack",
    "MegaPromptBundle",
]


def __getattr__(name: str) -> Any:
    if name == "extract_session_facts":
        return importlib.import_module(".extract_session", __name__).extract_session_facts
    if name == "search_local_evidence":
        return importlib.import_module(".rag_local", __name__).search_local_evidence
    if name == "search_web_evidence":
        return importlib.import_module(".rag_web", __name__).search_web_evidence
    if name == "build_knowledge_pack":
        return importlib.import_module(".consolidate", __name__).build_knowledge_pack
    if name == "assemble_megaprompt":
        return importlib.import_module(".megatemplate", __name__).assemble_megaprompt
    if name == "style_blocks":
        return importlib.import_module(".style_profile", __name__).style_blocks
    if name in {
        "SessionFacts",
        "EvidenceItemLocal",
        "EvidenceItemWeb",
        "KnowledgePack",
        "MegaPromptBundle",
    }:
        schemas = importlib.import_module(".schemas", __name__)
        return getattr(schemas, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
