import importlib.util
import sys
from pathlib import Path


def _load_service_module(name: str):
    root = Path(__file__).resolve().parents[2]
    target = root / "server" / "services" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"server.services.{name}", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


research_queries = _load_service_module("research_queries")
build_queries_fr = research_queries.build_queries_fr


def test_build_queries_bans_patient_name_and_stopwords(monkeypatch):
    research_queries.IDF_CACHE = {"alliance": 2.0, "therapeutique": 2.0, "rupture": 1.5, "assertivite": 2.5, "limite": 2.0, "relationnel": 1.8, "trauma": 2.2, "complexe": 2.1, "fatigue": 2.3, "decisionnel": 2.4}
    text = (
        "Garance note une rupture de l'alliance thérapeutique avec beaucoup de tensions. "
        "Nous travaillons l'assertivité et les limites relationnelles pour restaurer la confiance. "
        "Fatigue décisionnelle marquée liée au trauma complexe et aux conditions matérielles."
    )
    queries = build_queries_fr(text, patient_names=["Garance"], places=["Paris"], top_n=6)

    assert queries, "La génération devrait retourner des requêtes pertinentes."
    assert all("garance" not in q for q in queries)
    assert all("relations" not in q for q in queries)
    assert any("alliance" in q and "therapeutique" in q for q in queries)
    assert any("assertivite" in q and "limite" in q for q in queries)
