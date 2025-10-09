from datetime import datetime, timedelta

from modules.research_v2.collector import CandidateDocument
from modules.research_v2.filter_dedupe import deduplicate_candidates, filter_candidates
from modules.research_v2.policy import load_policy
from modules.research_v2.sources import SourceRegistry, load_registry


REGISTRY = load_registry()
POLICY = load_policy()
NOW = datetime.utcnow()


def build_doc(url: str, content: str, days_old: int = 10):
    return CandidateDocument(
        url=url,
        title="Titre",
        snippet=content,
        content=content,
        published_at=NOW - timedelta(days=days_old),
        domain=SourceRegistry.extract_domain(url),
        source_type="guideline",
        evidence_level="guideline",
        jurisdiction="FR",
        raw={},
    )


def test_filter_removes_stale_content():
    stale_doc = build_doc("https://has-sante.fr/doc", "Contenu", days_old=4000)
    fresh_doc = build_doc("https://has-sante.fr/doc2", "Contenu récent", days_old=10)
    kept, decisions = filter_candidates([stale_doc, fresh_doc], REGISTRY, POLICY, NOW)
    assert fresh_doc in kept
    assert stale_doc not in kept
    assert any(d.reason == "stale" for d in decisions)


def test_deduplicate_blocks_same_domain_and_similar_text():
    doc1 = build_doc("https://has-sante.fr/doc", "Texte détaillé sur la prise en charge")
    doc2 = build_doc("https://has-sante.fr/doc-2", "Texte détaillé sur la prise en charge")
    kept, decisions = deduplicate_candidates([doc1, doc2])
    assert doc1 in kept
    assert doc2 not in kept
    assert any(d.reason == "duplicate_domain" for d in decisions)
