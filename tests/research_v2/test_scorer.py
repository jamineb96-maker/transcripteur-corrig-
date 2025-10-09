from datetime import datetime, timedelta

from modules.research_v2.collector import CandidateDocument
from modules.research_v2.scorer import compute_scores, passes_gating
from modules.research_v2.policy import load_policy
from modules.research_v2.sources import SourceRegistry, load_registry


POLICY = load_policy()
REGISTRY = load_registry()
NOW = datetime.utcnow()


def make_doc(url: str, jurisdiction: str = "FR", days_old: int = 30):
    return CandidateDocument(
        url=url,
        title="Titre",
        snippet="Résumé",
        content="Résumé détaillé",
        published_at=NOW - timedelta(days=days_old),
        domain=SourceRegistry.extract_domain(url),
        source_type="guideline",
        evidence_level="guideline",
        jurisdiction=jurisdiction,
        raw={},
    )


def test_scores_above_threshold_pass_gating():
    docs = [
        make_doc("https://has-sante.fr/doc1"),
        make_doc("https://inserm.fr/doc2", jurisdiction="FR"),
    ]
    scores = compute_scores(docs, REGISTRY, POLICY, NOW)
    assert passes_gating(scores, POLICY)


def test_scores_fail_without_fr_or_eu():
    docs = [make_doc("https://ncbi.nlm.nih.gov/doc1", jurisdiction="INT", days_old=10)]
    scores = compute_scores(docs, REGISTRY, POLICY, NOW)
    assert not passes_gating(scores, POLICY) or scores.fr_or_eu_count == 0
