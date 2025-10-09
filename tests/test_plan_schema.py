from __future__ import annotations

# [pipeline-v3 begin]
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from modules.pre_session_plan import build_pre_session_plan


def test_build_pre_session_plan_schema():
    raw_context = {
        'mail_brut': 'Bonjour, je suis épuisée par les contraintes de travail et la garde alternée.',
        'etat_depuis_derniere': 'Fatigue persistante et pression salariale.',
        'notes_therapeutiques': 'Travailler la coordination avec les soutiens collectifs et les droits sociaux.',
    }

    plan = build_pre_session_plan(raw_context, previous_plan=None)

    expected_keys = {
        'orientation',
        'objectif_prioritaire',
        'cadre_de_travail',
        'synthese',
        'cloture_attendue',
        'diff_avec_plan_precedent',
    }
    assert expected_keys.issubset(plan.keys())
    for key in ('orientation', 'objectif_prioritaire', 'cadre_de_travail'):
        assert plan[key], f"Le champ {key} ne doit pas être vide"
        assert '?' not in plan[key]
        assert 'vigilance' not in plan[key].lower()

    synthese = plan['synthese']
    for key in ('situation_actuelle', 'tensions_principales', 'axes_de_travail'):
        assert synthese[key], f"La synthèse {key} ne doit pas être vide"
        assert '?' not in synthese[key]

    diff = plan['diff_avec_plan_precedent']
    assert {'orientation_modifiee', 'elements_ajoutes', 'elements_retires'} <= diff.keys()

    # Vérifie l'idempotence : relancer avec le plan précédent doit respecter le schéma.
    second_plan = build_pre_session_plan(raw_context, previous_plan=plan)
    assert second_plan['diff_avec_plan_precedent']['elements_retires'] == []
# [pipeline-v3 end]
