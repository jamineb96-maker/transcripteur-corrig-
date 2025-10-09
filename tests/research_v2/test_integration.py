from datetime import datetime
from pathlib import Path

from modules.research_v2.collector import Collector, LocalCache
from modules.research_v2 import ResearchOptions, run_research_v2


NOW = datetime.utcnow()


def fake_fetcher(query, facet):
    return [
        {
            "url": "https://has-sante.fr/recommandation-endometriose",
            "title": "Recommandation HAS",
            "snippet": "Prise en charge actualisée",
            "content": "Prise en charge actualisée de l'endométriose",
            "published_at": NOW.isoformat(),
            "jurisdiction": "FR",
            "source_type": "guideline",
            "evidence_level": "guideline",
        },
        {
            "url": "https://cochranelibrary.com/review-endometriosis",
            "title": "Cochrane Review",
            "snippet": "Synthèse récente",
            "content": "Synthèse récente européenne",
            "published_at": NOW.isoformat(),
            "jurisdiction": "EU",
            "source_type": "meta_analysis",
            "evidence_level": "meta",
        },
        {
            "url": "https://example.com/blog",
            "title": "Blog commercial",
            "snippet": "SEO pauvre",
            "content": "SEO pauvre",
            "published_at": NOW.isoformat(),
            "jurisdiction": "INT",
            "source_type": "blog",
            "evidence_level": "low",
        },
    ]


def build_collector(tmp_path: Path):
    cache = LocalCache(tmp_path / "cache.json", ttl_seconds=1)
    return Collector(fetcher=fake_fetcher, cache=cache)


def test_run_research_v2_returns_facets(tmp_path):
    collector = build_collector(tmp_path)
    context = {"orientation": "Gestion douleur et droits", "objectif_prioritaire": "Soutien France"}
    payload = run_research_v2(
        plan={},
        raw_context=context,
        options=ResearchOptions(location="France", enable_v2=True),
        collector=collector,
        now=NOW,
    )
    assert "facets" in payload
    first_facet = payload["facets"][0]
    assert first_facet["status"] in {"ok", "insuffisant"}
    assert "progress" in first_facet
    assert "audit" in payload
    # Vérifie que la page SEO a été rejetée pour faible qualité
    assert any(decision["reason"] == "low_quality" for decision in payload["audit"]["decisions"])


def test_gating_marks_insufficient_when_no_fr_eu(tmp_path):
    def intl_fetcher(query, facet):
        return [
            {
                "url": "https://example.org/article",
                "title": "Article générique",
                "snippet": "Contenu international",
                "content": "Contenu international solide et long" * 10,
                "published_at": NOW.isoformat(),
                "jurisdiction": "INT",
                "source_type": "research",
                "evidence_level": "review",
            }
            for _ in range(4)
        ]

    cache = LocalCache(tmp_path / "cache-intl.json", ttl_seconds=1)
    collector = Collector(fetcher=intl_fetcher, cache=cache)
    payload = run_research_v2(
        plan={},
        raw_context={"orientation": "Nouvelle question"},
        options=ResearchOptions(location="France", enable_v2=True),
        collector=collector,
        now=NOW,
    )
    assert any(facet["status"] == "insuffisant" for facet in payload["facets"])
