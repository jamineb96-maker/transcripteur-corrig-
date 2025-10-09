"""Gestion de la bibliothèque documentaire utilisée par les documents d'aide."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

_BASE_DIR = Path(__file__).resolve().parents[3]
_LIBRARY_INDEX = _BASE_DIR / 'library' / 'tools_index.json'


@dataclass
class Tool:
    """Représentation structurée d'un module documentaire."""

    id: str
    title: str
    description: str
    file: Path
    tags: List[str] = field(default_factory=list)
    level: str = 'base'
    contraindications: List[str] = field(default_factory=list)

    def to_metadata(self) -> Dict[str, object]:
        """Expose les métadonnées prêtes à être sérialisées."""

        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'file': str(self.file.relative_to(_BASE_DIR)),
            'tags': self.tags,
            'level': self.level,
            'contraindications': self.contraindications,
        }


_cache: Dict[str, object] = {'mtime': None, 'tools': []}


def _load_index() -> List[Tool]:
    path = _LIBRARY_INDEX
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    if _cache['mtime'] == mtime:
        return _cache['tools']  # type: ignore[return-value]
    data = json.loads(path.read_text(encoding='utf-8'))
    tools: List[Tool] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        identifier = str(entry.get('id') or '').strip()
        if not identifier:
            continue
        file_path = Path(entry.get('file') or '')
        if not file_path.is_absolute():
            file_path = (_BASE_DIR / file_path).resolve()
        try:
            file_path.relative_to(_BASE_DIR)
        except ValueError:
            # Hors du projet : on ignore par sécurité
            continue
        tool = Tool(
            id=identifier,
            title=str(entry.get('title') or identifier),
            description=str(entry.get('description') or ''),
            file=file_path,
            tags=[str(tag) for tag in (entry.get('tags') or []) if isinstance(tag, str)],
            level=str(entry.get('level') or 'base'),
            contraindications=[
                str(tag)
                for tag in (entry.get('contraindications') or [])
                if isinstance(tag, str)
            ],
        )
        tools.append(tool)
    _cache['mtime'] = mtime
    _cache['tools'] = tools
    return tools


def list_tools() -> List[Tool]:
    """Retourne la liste des modules disponibles."""

    return list(_load_index())


def get_tool(tool_id: str) -> Optional[Tool]:
    """Récupère un module par identifiant."""

    tool_id = str(tool_id or '').strip()
    if not tool_id:
        return None
    for tool in _load_index():
        if tool.id == tool_id:
            return tool
    return None


def read_tool_content(tool: Tool) -> str:
    """Lit le contenu Markdown du module demandé."""

    if not tool.file.exists():
        raise FileNotFoundError(f"Module introuvable: {tool.file}")
    content = tool.file.read_text(encoding='utf-8')
    return content


def list_metadata() -> List[Dict[str, object]]:
    """Expose les métadonnées publiques des modules."""

    return [tool.to_metadata() for tool in list_tools()]


def iter_tools_from_ids(ids: Iterable[str]) -> Iterable[Tool]:
    """Génère les modules correspondant aux identifiants fournis."""

    index = {tool.id: tool for tool in list_tools()}
    for identifier in ids:
        tool = index.get(identifier)
        if tool:
            yield tool
