from __future__ import annotations

# [pipeline-v3 begin]
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from modules.research_engine import search_local_library


def test_search_local_library_returns_clean_excerpts(tmp_path, monkeypatch):
    library_dir = tmp_path / 'library'
    library_dir.mkdir()
    (library_dir / 'fiche1.md').write_text(
        'Analyse des contraintes matérielles au travail. Solidarités syndicales décrites.',
        encoding='utf-8',
    )
    (library_dir / 'fiche2.txt').write_text(
        'Ressources locales pour accompagnement social, pas de lien http ici.',
        encoding='utf-8',
    )

    monkeypatch.setenv('LIBRARY_DIR', str(library_dir))

    results = search_local_library('contraintes travail solidarités', k=2)
    assert len(results) == 2
    for item in results:
        assert item['source']
        assert 'http' not in item['extrait'].lower()
        assert 'http' not in item['contexte'].lower()
# [pipeline-v3 end]
