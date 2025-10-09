import pytest

from modules.research_v2.faceting import DEFAULT_FACETS, extract_facets


def test_extract_facets_returns_all_defaults():
    context = {
        "orientation": "Douleur chronique et migraines", 
        "notes": "Exploration du TDAH et de la charge allostatique"
    }
    facets = extract_facets(context)
    names = {facet.name for facet in facets}
    expected = {facet.name for facet in DEFAULT_FACETS}
    assert expected.issubset(names)
    assert any(facet.required for facet in facets)


@pytest.mark.parametrize("keyword", ["douleur", "migraine", "droits"])
def test_keywords_flag_required(keyword):
    context = {"notes": f"{keyword} présent"}
    facets = extract_facets(context)
    matched = [facet for facet in facets if keyword in " ".join(facet.expected_topics).lower()]
    assert matched
    assert all(f.required for f in matched)
