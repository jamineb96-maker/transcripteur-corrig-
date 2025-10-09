"""Gestion des sources pour la recherche pré-session v2."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

import yaml

CONFIG_PATH = Path("config/research_sources.yml")


@dataclass(frozen=True)
class SourceInfo:
    """Métadonnées décrivant une source connue."""

    domain: str
    type: str
    jurisdiction: str
    evidence_level: str


class SourceRegistry:
    """Registre des sources whitelist, greylist et domaines bloqués."""

    def __init__(
        self,
        whitelist: Dict[str, SourceInfo],
        greylist: Dict[str, SourceInfo],
        blocked: Iterable[str],
    ) -> None:
        self._whitelist = whitelist
        self._greylist = greylist
        self._blocked = list(blocked)

    # -------------------- propriétés --------------------
    @property
    def whitelist(self) -> Dict[str, SourceInfo]:
        return self._whitelist

    @property
    def greylist(self) -> Dict[str, SourceInfo]:
        return self._greylist

    @property
    def blocked(self) -> List[str]:
        return list(self._blocked)

    # -------------------- utilitaires --------------------
    @staticmethod
    def _normalise_domain(domain: str) -> str:
        return domain.lower().lstrip("*")

    @staticmethod
    def extract_domain(url: str) -> str:
        parsed = urlparse(url if "//" in url else f"https://{url}")
        return parsed.netloc.lower().strip()

    def _match_in_registry(self, domain: str, registry: Dict[str, SourceInfo]) -> Optional[SourceInfo]:
        for key, info in registry.items():
            if fnmatch(domain, key):
                return info
        return None

    def lookup(self, url: str) -> Optional[SourceInfo]:
        domain = self.extract_domain(url)
        return self._match_in_registry(domain, self._whitelist) or self._match_in_registry(domain, self._greylist)

    def is_blocked(self, url: str) -> bool:
        domain = self.extract_domain(url)
        return any(fnmatch(domain, pattern) for pattern in self._blocked)

    def is_whitelisted(self, url: str) -> bool:
        domain = self.extract_domain(url)
        return any(fnmatch(domain, pattern) for pattern in self._whitelist)

    def is_greylisted(self, url: str) -> bool:
        domain = self.extract_domain(url)
        return any(fnmatch(domain, pattern) for pattern in self._greylist)


def load_registry(config_path: Path = CONFIG_PATH) -> SourceRegistry:
    """Charge le registre de sources depuis un fichier YAML."""

    if not config_path.exists():
        raise FileNotFoundError(f"Fichier de configuration manquant: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    def _build_map(key: str) -> Dict[str, SourceInfo]:
        items = {}
        for entry in raw.get(key, []) or []:
            domain = SourceRegistry._normalise_domain(entry.get("domain", "").strip())
            if not domain:
                continue
            items[domain] = SourceInfo(
                domain=domain,
                type=entry.get("type", "unknown"),
                jurisdiction=entry.get("jurisdiction", "INT"),
                evidence_level=entry.get("evidence_level", "unknown"),
            )
        return items

    whitelist = _build_map("whitelist")
    greylist = _build_map("greylist")
    blocked = [
        SourceRegistry._normalise_domain(item.get("domain", item) if isinstance(item, dict) else str(item))
        for item in raw.get("blocked", []) or []
    ]

    return SourceRegistry(whitelist=whitelist, greylist=greylist, blocked=blocked)


__all__ = ["SourceInfo", "SourceRegistry", "load_registry"]
