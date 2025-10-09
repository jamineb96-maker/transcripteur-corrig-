# [pipeline-v3 begin]
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from modules.prompt_builder import build_final_prompt


def test_build_final_prompt_constraints():
    plan = {
        'orientation': 'Ancrer la séance sur les contraintes professionnelles.',
        'objectif_prioritaire': 'Co-construire une action concrète contre la surcharge.',
        'cadre_de_travail': 'Cadre matérialiste et collectif.\nAnalyse evidence-based.\nRefus de la pathologisation.',
        'synthese': {
            'situation_actuelle': 'La personne décrit une fatigue intense liée au travail.',
            'tensions_principales': 'Charge mentale et isolement professionnel.',
            'axes_de_travail': 'Soutenir la négociation collective. Mobiliser les droits sociaux.',
        },
        'cloture_attendue': 'Identifier une continuité concrète avec un soutien collectif.',
        'diff_avec_plan_precedent': {
            'orientation_modifiee': False,
            'elements_ajoutes': [],
            'elements_retires': [],
        },
    }
    research = {
        'local_library': [
            {
                'source': 'travail/fiche1.md',
                'extrait': 'Analyse sur le temps de travail et ses déterminants sociaux.',
                'contexte': 'Met en avant les coopérations syndicales.',
            }
        ],
        'internet': [],
        'notes_integration': 'Relier la documentation au plan.',
    }
    prompt = build_final_prompt(plan, research, 'Mail brut exemple', 'Alex')
    assert 'http' not in prompt
    assert 'TCC' not in prompt
    assert prompt.lower().count('vigilance') <= 2
    assert "Questions d'ouverture nombreuses" in prompt
    assert 'Approche narrative et située' in prompt
# [pipeline-v3 end]
