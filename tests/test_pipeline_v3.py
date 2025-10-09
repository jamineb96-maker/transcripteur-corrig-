# [pipeline-v3 begin]
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from modules.pre_session_plan import build_pre_session_plan
from modules.research_engine import run_research
from modules.prompt_builder import build_final_prompt

ANTI = [
    "échelle de 0 à 10",
    "TCC",
    "restructuration cognitive",
    "exposition graduée",
    "SMART",
    "homework",
    "devoirs à domicile",
]


def test_plan_minimal_no_extras():
    plan = build_pre_session_plan(
        {"mail_brut": "x", "etat_depuis_derniere": "y", "notes_therapeutiques": "z"},
        None,
    )
    txt = str(plan).lower()
    assert "vigilance" not in txt and "00:" not in txt


def test_research_outputs_have_no_urls():
    res = run_research(
        {
            "orientation": "fatigue cognitive",
            "objectif_prioritaire": "clarifier",
            "synthese": {"tensions_principales": "camouflage social"},
        },
        {"mail_brut": "x"},
        allow_internet=False,
    )
    assert "http" not in str(res).lower()


def test_prompt_builder_anti_tcc():
    plan = {
        "orientation": "O",
        "objectif_prioritaire": "P",
        "cadre_de_travail": "C",
        "synthese": {
            "situation_actuelle": "S",
            "tensions_principales": "T",
            "axes_de_travail": "A",
        },
        "cloture_attendue": "K",
    }
    research = {
        "local_library": [{"source": "a", "extrait": "b", "contexte": "c"}],
        "internet": [
            {
                "title": "Synthèse",
                "url": "https://example.org",
                "snippet": "Contenu.",
            }
        ],
    }
    out = build_final_prompt(plan, research, "MAIL", "Prénom")
    lo = out.lower()
    for token in ANTI:
        assert token.lower() not in lo
    lowered = out.lower()
    assert "questions d'ouverture" in lowered or "questions d’ouverture" in lowered
# [pipeline-v3 end]
