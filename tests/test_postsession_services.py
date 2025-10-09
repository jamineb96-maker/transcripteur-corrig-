from __future__ import annotations

from typing import Any, Dict

import sys
import types

sys.modules.setdefault("yaml", types.ModuleType("yaml"))

import pytest

from server.services import pharma_analyzer, plan_post_session, research_unified


@pytest.fixture(autouse=True)
def _no_openai(monkeypatch: pytest.MonkeyPatch):
    """Désactive les appels OpenAI par défaut pour ces tests."""

    monkeypatch.setattr(plan_post_session, "get_openai_client", lambda: None)
    monkeypatch.setattr(research_unified, "get_openai_client", lambda: None)


def test_generate_structured_plan_fallback():
    transcript = "Au début la personne décrit son travail pénible. Ensuite, milieu agit. Enfin on parle de repos."  # noqa: E501
    plan = plan_post_session.generate_structured_plan(transcript)
    assert isinstance(plan, dict)
    modules = plan.get("modules")
    assert isinstance(modules, list) and len(modules) == 6
    assert all(module.get("anchors") for module in modules)


def test_analyze_pharmacology_basic():
    analysis = pharma_analyzer.analyze_pharmacology("La personne prend de la sertraline chaque matin.")
    molecules = analysis.get("molecules")
    assert isinstance(molecules, list) and molecules
    assert molecules[0]["dci"] == "sertraline"
    assert analysis.get("export_block", "").startswith("[PHARMA_MEMO]")


def test_run_unified_research_minimal(monkeypatch: pytest.MonkeyPatch):
    class DummyEngine:
        def search(self, queries, top_k=6):
            return [
                {
                    "doc_id": "doc-1",
                    "page": 1,
                    "title": "Guide CNAM",
                    "year": 2020,
                    "type": "guide",
                    "level": "A",
                    "domain": [],
                    "text": "Guide CNAM sur les droits sociaux.",
                    "snippet": "Approche matérielle.",
                    "score": 1.0,
                }
            ]

    def fake_engine():
        return DummyEngine()

    def fake_llm(context: str, config: Any) -> Dict[str, Any]:
        return {
            "cards": [
                {
                    "these": "Les droits sociaux soutiennent la stabilisation.",
                    "implications": [
                        "Informer sur les dispositifs d'aide au logement.",
                        "Prévoir un point sur les revenus de remplacement.",
                    ],
                    "citation_courte": "« revue HAS »",
                    "source": {
                        "type": "guide",
                        "auteurs": "HAS",
                        "annee": 2021,
                        "ref": "HAS – Accès aux droits",
                        "url": "https://has.fr/guide",
                    },
                    "limite": "Synthèse nationale, pas de données locales.",
                }
            ]
        }

    monkeypatch.setattr(research_unified, "_engine", fake_engine)
    monkeypatch.setattr(research_unified, "_call_llm", fake_llm)
    monkeypatch.setattr(research_unified, "search_web_openai", lambda *args, **kwargs: [])

    result = research_unified.run_unified_research("Transcript : difficultés de logement et fatigue chronique.")
    assert result["cards"], "Au moins une carte est attendue"
    assert result["biblio"], "Les références courtes doivent être présentes"
