"""Core data models for the clinical library v2.

Each dataclass is documented with the JSON Schema used for
serialization/deserialization so that the API remains explicit and
traceable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping


@dataclass
class ChunkMeta:
    """JSON schema::
    {
        "type": "object",
        "required": [
            "chunk_id",
            "doc_id",
            "title",
            "authors",
            "year",
            "domains",
            "keywords",
            "evidence_level",
            "page_start",
            "page_end"
        ],
        "properties": {
            "chunk_id": {"type": "string"},
            "doc_id": {"type": "string"},
            "title": {"type": "string"},
            "authors": {"type": "string"},
            "year": {"type": "integer"},
            "domains": {"type": "array", "items": {"type": "string"}},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "evidence_level": {
                "type": "string",
                "enum": ["élevé", "modéré", "faible", "inconnu"]
            },
            "page_start": {"type": "integer", "minimum": 0},
            "page_end": {"type": "integer", "minimum": 0},
            "pseudonymized": {"type": "boolean", "default": false}
        }
    }
    """

    chunk_id: str
    doc_id: str
    title: str
    authors: str
    year: int
    domains: List[str]
    keywords: List[str]
    evidence_level: str  # "élevé" | "modéré" | "faible" | "inconnu"
    page_start: int
    page_end: int
    pseudonymized: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "domains": list(self.domains),
            "keywords": list(self.keywords),
            "evidence_level": self.evidence_level,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "pseudonymized": self.pseudonymized,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChunkMeta":
        return cls(
            chunk_id=str(data.get("chunk_id", "")),
            doc_id=str(data.get("doc_id", "")),
            title=str(data.get("title", "")),
            authors=str(data.get("authors", "")),
            year=int(data.get("year", 0)),
            domains=list(data.get("domains", []) or []),
            keywords=list(data.get("keywords", []) or []),
            evidence_level=str(data.get("evidence_level", "inconnu")),
            page_start=int(data.get("page_start", 0)),
            page_end=int(data.get("page_end", 0)),
            pseudonymized=bool(data.get("pseudonymized", False)),
        )


@dataclass
class Chunk:
    """JSON schema::
    {
        "type": "object",
        "required": ["meta", "text"],
        "properties": {
            "meta": {"$ref": "#/definitions/ChunkMeta"},
            "text": {"type": "string"},
            "embedding": {
                "type": "array",
                "items": {"type": "number"}
            }
        },
        "definitions": {"ChunkMeta": ChunkMeta.__doc__}
    }
    """

    meta: ChunkMeta
    text: str
    embedding: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "meta": self.meta.to_dict(),
            "text": self.text,
            "embedding": list(self.embedding),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Chunk":
        meta_data = data.get("meta", {})
        if not isinstance(meta_data, Mapping):
            raise TypeError("chunk meta must be a mapping")
        return cls(
            meta=ChunkMeta.from_dict(meta_data),
            text=str(data.get("text", "")),
            embedding=list(data.get("embedding", []) or []),
        )


@dataclass
class NotionSource:
    """JSON schema::
    {
        "type": "object",
        "required": ["doc_id", "chunk_ids", "citation"],
        "properties": {
            "doc_id": {"type": "string"},
            "chunk_ids": {"type": "array", "items": {"type": "string"}},
            "citation": {"type": "string"}
        }
    }
    """

    doc_id: str
    chunk_ids: List[str]
    citation: str  # "p. 12–17" ou "pp. 12–17"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "chunk_ids": list(self.chunk_ids),
            "citation": self.citation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotionSource":
        return cls(
            doc_id=str(data.get("doc_id", "")),
            chunk_ids=list(data.get("chunk_ids", []) or []),
            citation=str(data.get("citation", "")),
        )


@dataclass
class Notion:
    """JSON schema::
    {
        "type": "object",
        "required": [
            "id",
            "label",
            "definition",
            "synonyms",
            "domains",
            "evidence_level",
            "sources"
        ],
        "properties": {
            "id": {"type": "string"},
            "label": {"type": "string"},
            "definition": {"type": "string"},
            "synonyms": {"type": "array", "items": {"type": "string"}},
            "domains": {"type": "array", "items": {"type": "string"}},
            "evidence_level": {
                "type": "string",
                "enum": ["élevé", "modéré", "faible", "inconnu"]
            },
            "sources": {
                "type": "array",
                "items": {"$ref": "#/definitions/NotionSource"}
            }
        },
        "definitions": {"NotionSource": NotionSource.__doc__}
    }
    """

    id: str  # slug unique, kebab-case
    label: str  # étiquette canonique
    definition: str  # 1–3 phrases testables (pas de généralités vagues)
    synonyms: List[str]
    domains: List[str]
    evidence_level: str
    sources: List[NotionSource]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "definition": self.definition,
            "synonyms": list(self.synonyms),
            "domains": list(self.domains),
            "evidence_level": self.evidence_level,
            "sources": [src.to_dict() for src in self.sources],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Notion":
        raw_sources: Iterable[Mapping[str, Any]] = data.get("sources", []) or []
        sources = [
            NotionSource.from_dict(source) if isinstance(source, Mapping) else NotionSource.from_dict({})
            for source in raw_sources
        ]
        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            definition=str(data.get("definition", "")),
            synonyms=list(data.get("synonyms", []) or []),
            domains=list(data.get("domains", []) or []),
            evidence_level=str(data.get("evidence_level", "inconnu")),
            sources=sources,
        )

