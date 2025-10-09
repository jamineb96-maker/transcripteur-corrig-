"""Indexeur simple pour la librairie de ressources.

Ce module parcourt le contenu du répertoire `store` pour extraire des
métadonnées (identifiant, titre, étiquettes, résumé) et construit un
index en mémoire permettant la recherche par mots clés et par tags.
L'index est volontairement simple : il tokenise les textes en enlevant
les accents et la ponctuation, filtre quelques mots courants et
associe chaque token aux documents qui le contiennent.  Le contenu
complet des documents n'est pas conservé en mémoire afin de limiter
l'utilisation de ressources, il est relu à la demande dans `get_item`.

Le module expose les fonctions suivantes :

* `build_index(base_path)` : construit l'index en parcourant les
  fichiers contenus dans `base_path`.
* `status()` : renvoie un dictionnaire contenant le nombre de documents
  indexés et la date d'indexation.
* `search(query, tags=None, limit=10)` : effectue une recherche sur
  l'index et renvoie les meilleurs résultats.
* `get_item(doc_id)` : renvoie le contenu complet d'un document.

Les variables globales `_DOCS`, `_INDEX`, `_TAGS` et `_INDEXED_AT`
contiennent respectivement la liste des documents, l'index inversé,
l'ensemble des étiquettes et la date d'indexation.

Ce module n'utilise pas d'annotations de type pour éviter des problèmes
de compatibilité avec l'outil de patch.
"""

import os
import re
import json
import unicodedata
import time
import math

# Répertoire dans lequel se trouvent les fichiers à indexer
STORE_DIR = os.path.join(os.path.dirname(__file__), 'store')

# Mots vides simples à exclure des index (français et anglais)
_STOPWORDS = {
    'et', 'le', 'la', 'les', 'des', 'un', 'une', 'de', 'du', 'en',
    'a', 'an', 'the', 'and', 'or', 'to', 'of', 'for', 'with', 'on', 'in',
    'au', 'aux', 'ce', 'ces', 'dans', 'que', 'qui', 'quoi', 'ou', 'où'
}

# Structures d'indexation globales
_DOCS = []  # liste de documents avec métadonnées
_INDEX = {}  # index inversé : token -> set(ids)
_TAGS = set()  # ensemble de toutes les étiquettes connues
_INDEXED_AT = None  # horodatage de dernière indexation


def _strip_accents(text):
    """Retire les accents d'une chaîne en utilisant Unicode NFD."""
    normalized = unicodedata.normalize('NFD', text)
    return ''.join(ch for ch in normalized if unicodedata.category(ch) != 'Mn')


def _tokenize(text):
    """Tokenise un texte brut en supprimant la ponctuation et les stopwords."""
    if not text:
        return []
    # Passage en minuscules et retrait des accents
    text_norm = _strip_accents(text.lower())
    # Découpage sur les caractères non alphanumériques
    tokens = re.split(r'[^a-z0-9]+', text_norm)
    # Filtre les mots vides et les chaînes courtes
    return [t for t in tokens if t and t not in _STOPWORDS]


def _parse_front_matter(lines):
    """Extrait un front-matter YAML minimal en début de fichier Markdown.

    Si le fichier commence par une ligne '---', lit jusqu'à la prochaine
    ligne '---' et extrait les clés simples `title` et `tags`.
    Retourne un dictionnaire de métadonnées et l'index où le contenu
    principal commence.
    """
    meta = {}
    start = 0
    if lines and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            line = lines[i].strip()
            if line == '---':
                # Fin du front‑matter
                start = i + 1
                break
            # Extraction clé: valeur
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip().strip('"\'')
                if key == 'title':
                    meta['title'] = value
                elif key == 'tags':
                    # Sépare les tags par virgule
                    meta['tags'] = [t.strip() for t in value.split(',') if t.strip()]
        else:
            # Aucune fermeture du front matter trouvée
            start = 0
    return meta, start


def _read_text_file(path):
    """Lit un fichier texte (UTF‑8) et renvoie le contenu.

    Les fichiers sont lus en ignorant les erreurs d'encodage.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ''


def _read_json_file(path):
    """Lit un fichier JSON et le convertit en chaîne lisible.

    Si la conversion échoue, renvoie une chaîne vide.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            data = json.load(f)
        # Transforme les structures en texte lisible
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return ''


def _extract_metadata(file_path, rel_path):
    """Extrait les métadonnées et le contenu d'un fichier.

    Cette fonction supporte les fichiers `.md`, `.txt` et `.json`.  Elle
    renvoie un dictionnaire avec les clés `id`, `title`, `tags`,
    `summary` et `content`.
    """
    name, ext = os.path.splitext(rel_path)
    ext = ext.lower()
    title = os.path.basename(name)
    tags = []
    content = ''
    summary = ''
    if ext in {'.md', '.markdown'}:
        text = _read_text_file(file_path)
        lines = text.split('\n')
        meta, start = _parse_front_matter(lines)
        if 'title' in meta:
            title = meta['title']
        if 'tags' in meta:
            tags = meta['tags']
        content = '\n'.join(lines[start:]).strip()
        summary = content[:300]
    elif ext in {'.txt'}:
        content = _read_text_file(file_path)
        summary = content[:300]
    elif ext in {'.json'}:
        content = _read_json_file(file_path)
        summary = content[:300]
    else:
        # Fichiers non pris en charge
        return None
    return {
        'id': rel_path.replace(os.sep, '/'),
        'title': title,
        'tags': tags[:],
        'summary': summary,
        'content': content,
    }


def build_index(base_path=None):
    """Construit l'index à partir du contenu du répertoire `base_path`.

    Si aucun chemin n'est fourni, utilise `STORE_DIR`.  Met à jour
    les structures globales `_DOCS`, `_INDEX`, `_TAGS` et `_INDEXED_AT`.
    """
    global _DOCS, _INDEX, _TAGS, _INDEXED_AT
    _DOCS = []
    _INDEX = {}
    _TAGS = set()
    base = base_path or STORE_DIR
    for root, _, files in os.walk(base):
        for fname in files:
            # Ignore les fichiers cachés ou temporaires
            if fname.startswith('.'):
                continue
            rel_dir = os.path.relpath(root, base)
            rel_path = os.path.join(rel_dir, fname) if rel_dir != '.' else fname
            full_path = os.path.join(root, fname)
            doc = _extract_metadata(full_path, rel_path)
            if not doc:
                continue
            doc_id = doc['id']
            _DOCS.append(doc)
            # Met à jour l'ensemble des tags
            for tag in doc['tags']:
                _TAGS.add(tag)
            # Indexation simple par tokens dans le titre et le contenu
            tokens = _tokenize(doc['title'] + ' ' + doc['content'])
            for token in tokens:
                current = _INDEX.get(token)
                if current is None:
                    current = set()
                    _INDEX[token] = current
                current.add(doc_id)
    _INDEXED_AT = int(time.time())


def status():
    """Renvoie l'état courant de l'index."""
    count = len(_DOCS)
    return {
        'count': count,
        'indexedAt': _INDEXED_AT,
        'tags': sorted(_TAGS),
    }


def search(query, tags=None, limit=10):
    """Recherche les documents correspondant à la requête et aux tags.

    La requête est tokenisée, les tokens présents dans le titre ou le
    contenu augmentent le score.  Les tags fournis filtrent les
    documents.  Le résultat est une liste de documents (sans le contenu
    complet) triés par score décroissant.
    """
    if not query:
        return []
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    # Ensemble candidat d'IDs (intersection des tokens)
    candidate_ids = None
    for token in q_tokens:
        ids = _INDEX.get(token)
        if not ids:
            continue
        ids = set(ids)
        candidate_ids = ids if candidate_ids is None else candidate_ids & ids
    if not candidate_ids:
        return []
    results = []
    # Filtrage par tags si spécifiés
    tags_set = set()
    if tags:
        tags_set = set([t.strip() for t in tags if t.strip()])
    for doc in _DOCS:
        if doc['id'] not in candidate_ids:
            continue
        if tags_set and not tags_set.issubset(set(doc['tags'])):
            continue
        # Score basique : nombre de tokens de la requête présents dans le titre
        score = 0
        title_tokens = set(_tokenize(doc['title']))
        content_tokens = set(_tokenize(doc['content']))
        for tok in q_tokens:
            if tok in title_tokens:
                score += 5  # poids fort sur le titre
            if tok in doc['tags']:
                score += 3
            if tok in content_tokens:
                score += 1
        results.append((score, doc))
    # Tri décroissant par score
    results.sort(key=lambda x: x[0], reverse=True)
    # Construction de la réponse en tronquant au nombre demandé
    output = []
    for score, doc in results[:limit]:
        output.append({
            'id': doc['id'],
            'title': doc['title'],
            'tags': doc['tags'],
            'summary': doc['summary'],
            'path': doc['id'],
        })
    return output


def get_item(doc_id):
    """Renvoie le contenu complet d'un document par son identifiant."""
    # Recherche du document dans la liste
    for doc in _DOCS:
        if doc['id'] == doc_id:
            return {
                'id': doc['id'],
                'title': doc['title'],
                'tags': doc['tags'],
                'content': doc['content'],
            }
    return None


# Construis l'index dès l'importation du module.  En cas d'erreur,
# aucune exception n'est propagée pour ne pas interrompre l'application.
try:
    build_index()
except Exception:
    # Laisse les structures vides en cas de problème
    _DOCS = []
    _INDEX = {}
    _TAGS = set()
    _INDEXED_AT = int(time.time())
# ---------------------------------------------------------------------------
# Extensions v2 : découpage PDF en chunks + embeddings
# ---------------------------------------------------------------------------

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .embeddings_backend import EmbeddingsBackend
from .journal import log_event
from .models import Chunk, ChunkMeta
from .vector_db import VectorDB

LOGGER = logging.getLogger(__name__)

DEFAULT_CHUNK_WORDS = 1100
DEFAULT_OVERLAP_WORDS = 180
EMBED_BATCH_SIZE = 64


try:  # pragma: no cover - dépendance optionnelle
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover - import défensif
    PdfReader = None  # type: ignore


def _read_pdf_pages(path: str) -> List[Tuple[int, str]]:
    """Extract text page by page from a PDF file."""

    pages: List[Tuple[int, str]] = []
    if PdfReader is not None:
        try:
            reader = PdfReader(path)  # type: ignore[operator]
            for index, page in enumerate(getattr(reader, "pages", []) or []):
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                pages.append((index + 1, text))
        except Exception as exc:  # pragma: no cover - dépendance externe
            LOGGER.warning("pdf_reader_failed", extra={"doc_path": path, "error": str(exc)})
    if not pages:
        try:
            with open(path, "rb") as handle:
                raw = handle.read().decode("utf-8", errors="ignore")
        except Exception:
            raw = ""
        pages = [(1, raw)]
    return pages


def _normalize_text(text: str) -> str:
    cleaned = text.replace("\n", " ")
    cleaned = re.sub(r"[\u2013\u2014]", "-", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    sentences = re.split(r"(?<=[\.!?])\s+(?=[A-ZÉÈÊÎÏÔÙÛÜÀÂÇ0-9])", text)
    if len(sentences) <= 1:
        sentences = re.split(r"(?<=[\.!?])\s+", text)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _words_count(text: str) -> int:
    return len(text.split())


def _normalize_evidence_level(value: Any) -> str:
    mapping = {
        "élevé": "élevé",
        "eleve": "élevé",
        "haut": "élevé",
        "modéré": "modéré",
        "modere": "modéré",
        "moyen": "modéré",
        "faible": "faible",
        "bas": "faible",
        "inconnu": "inconnu",
    }
    normalized = str(value or "inconnu").strip().lower()
    return mapping.get(normalized, "inconnu")


def _build_chunk_id(doc_id: str, page_start: int, page_end: int, text: str) -> str:
    text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
    payload = f"{doc_id}|{page_start}|{page_end}|{text_hash}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:16]


def _pseudonymize_text(text: str) -> str:
    email_re = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    phone_re = re.compile(r"\+?\d[\d\s().-]{5,}\d")
    masked = email_re.sub("[EMAIL]", text)
    masked = phone_re.sub("[PHONE]", masked)
    return masked


def _coerce_list(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [part.strip() for part in values.split(",") if part.strip()]
    return [str(item) for item in values if str(item).strip()]


def _doc_id_from_meta(meta: Mapping[str, Any], doc_path: str) -> str:
    candidate = meta.get("doc_id") or meta.get("id")
    if candidate:
        return str(candidate)
    return Path(doc_path).stem


def _chunk_pdf_from_meta(
    doc_path: str,
    meta: Mapping[str, Any],
    *,
    chunk_words: int,
    overlap_words: int,
) -> List[Chunk]:
    pages = _read_pdf_pages(doc_path)
    doc_id = _doc_id_from_meta(meta, doc_path)
    title = str(meta.get("title") or doc_id)
    authors = str(meta.get("authors") or meta.get("author") or "")
    try:
        year = int(meta.get("year") or meta.get("publication_year") or 0)
    except Exception:
        year = 0
    domains = _coerce_list(meta.get("domains"))
    keywords = _coerce_list(meta.get("keywords"))
    evidence_level = _normalize_evidence_level(meta.get("evidence_level") or meta.get("evidence"))
    pseudonymize_flag = bool(meta.get("pseudonymize"))

    sentences: List[Tuple[int, str]] = []
    for page, raw_text in pages:
        normalized = _normalize_text(raw_text)
        for sentence in _split_sentences(normalized):
            sentences.append((page, sentence))

    if not sentences:
        return []

    chunks: List[Chunk] = []
    buffer: List[Tuple[int, str]] = []
    current_words = 0

    def flush(sequence: List[Tuple[int, str]]) -> Optional[Chunk]:
        if not sequence:
            return None
        joined = " ".join(sentence for _, sentence in sequence).strip()
        if not joined:
            return None
        processed_text = _pseudonymize_text(joined) if pseudonymize_flag else joined
        pages_numbers = [page for page, _ in sequence]
        page_start = min(pages_numbers)
        page_end = max(pages_numbers)
        chunk_meta = ChunkMeta(
            chunk_id=_build_chunk_id(doc_id, page_start, page_end, processed_text),
            doc_id=doc_id,
            title=title,
            authors=authors,
            year=year,
            domains=domains,
            keywords=keywords,
            evidence_level=evidence_level,
            page_start=page_start,
            page_end=page_end,
            pseudonymized=pseudonymize_flag,
        )
        return Chunk(meta=chunk_meta, text=processed_text)

    for page, sentence in sentences:
        buffer.append((page, sentence))
        current_words += _words_count(sentence)
        if current_words >= chunk_words:
            chunk = flush(buffer)
            if chunk is not None:
                chunks.append(chunk)
            overlap: List[Tuple[int, str]] = []
            overlap_words_used = 0
            for page_num, sent in reversed(buffer):
                overlap.insert(0, (page_num, sent))
                overlap_words_used += _words_count(sent)
                if overlap_words_used >= overlap_words:
                    break
            buffer = overlap
            current_words = sum(_words_count(sent) for _, sent in buffer)

    tail_chunk = flush(buffer)
    if tail_chunk is not None:
        chunks.append(tail_chunk)

    return chunks


def chunk_pdf(
    doc_path: str,
    meta: Optional[Mapping[str, Any]] = None,
    *,
    doc_id: Optional[str] = None,
    base_meta: Optional[Mapping[str, Any]] = None,
    chunk_words: int = DEFAULT_CHUNK_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
    pseudonymize: Optional[bool] = None,
) -> List[Chunk]:
    """Chunk a PDF according to the metadata provided."""

    payload: Dict[str, Any] = {}
    if base_meta:
        payload.update(dict(base_meta))
    if meta:
        payload.update(dict(meta))
    if doc_id:
        payload["doc_id"] = doc_id
    if pseudonymize is not None:
        payload["pseudonymize"] = bool(pseudonymize)
    return _chunk_pdf_from_meta(doc_path, payload, chunk_words=chunk_words, overlap_words=overlap_words)


def embed_chunks(
    chunks: List[Chunk],
    *,
    backend: Optional[EmbeddingsBackend] = None,
    batch_size: int = EMBED_BATCH_SIZE,
) -> None:
    """Fill the embedding field for each chunk."""

    if not chunks:
        return
    engine = backend or EmbeddingsBackend()
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = engine.embed_texts([chunk.text for chunk in batch])
        if len(vectors) != len(batch):
            raise RuntimeError("embedding_mismatch")
        for chunk, vector in zip(batch, vectors):
            chunk.embedding = list(vector)


def _upsert_document(
    doc_path: str,
    meta: Mapping[str, Any],
    *,
    backend: Optional[EmbeddingsBackend] = None,
    vector_db: Optional[VectorDB] = None,
) -> Dict[str, Any]:
    start = time.perf_counter()
    payload = dict(meta)
    doc_id = _doc_id_from_meta(payload, doc_path)
    engine = backend or EmbeddingsBackend()
    store = vector_db or VectorDB()
    chunks = chunk_pdf(doc_path, payload)
    if not chunks:
        duration = int((time.perf_counter() - start) * 1000)
        stats = store.stats(doc_id)
        log_event(
            "index_chunks",
            {
                "doc_id": doc_id,
                "inserted": 0,
                "upserted": 0,
                "total": stats.get("chunks_indexed", 0),
                "ms": duration,
                "backend": engine.name,
                "pseudonymized": bool(payload.get("pseudonymize")),
                "empty": True,
            },
        )
        return {"doc_id": doc_id, "inserted": 0, "total": stats.get("chunks_indexed", 0), "ms": duration}

    embed_chunks(chunks, backend=engine)
    inserted = store.upsert(chunks)
    stats = store.stats(doc_id)
    duration = int((time.perf_counter() - start) * 1000)
    log_event(
        "index_chunks",
        {
            "doc_id": doc_id,
            "inserted": inserted,
            "upserted": len(chunks),
            "total": stats.get("chunks_indexed", 0),
            "ms": duration,
            "backend": engine.name,
            "pseudonymized": bool(payload.get("pseudonymize")),
        },
    )
    return {"doc_id": doc_id, "inserted": inserted, "total": stats.get("chunks_indexed", 0), "ms": duration}


def upsert_chunks(
    doc_path_or_chunks: Union[str, List[Chunk]],
    meta_or_db: Union[Mapping[str, Any], VectorDB],
    *,
    backend: Optional[EmbeddingsBackend] = None,
    vector_db: Optional[VectorDB] = None,
    duration_ms: Optional[int] = None,
) -> Union[int, Dict[str, Any]]:
    """Dual API for legacy callers and the new orchestrator."""

    if isinstance(doc_path_or_chunks, list):
        if not isinstance(meta_or_db, VectorDB):
            raise TypeError("legacy upsert requires a VectorDB instance")
        inserted = meta_or_db.upsert(doc_path_or_chunks)
        log_event(
            "index_chunks",
            {
                "doc_id": doc_path_or_chunks[0].meta.doc_id if doc_path_or_chunks else None,
                "n_chunks": len(doc_path_or_chunks),
                "inserted": inserted,
                "ms": duration_ms,
                "legacy": True,
            },
        )
        return inserted
    if not isinstance(meta_or_db, Mapping):
        raise TypeError("meta must be a mapping for the new upsert API")
    return _upsert_document(str(doc_path_or_chunks), meta_or_db, backend=backend, vector_db=vector_db)


__all__ = ["chunk_pdf", "embed_chunks", "upsert_chunks", "EmbeddingsBackend"]
