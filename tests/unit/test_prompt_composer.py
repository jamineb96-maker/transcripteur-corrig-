import importlib.machinery
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_namespace(name: str, path: Path) -> None:
    module = sys.modules.get(name)
    if module is not None:
        return
    namespace = types.ModuleType(name)
    namespace.__path__ = [str(path)]  # type: ignore[attr-defined]
    namespace.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    sys.modules[name] = namespace


_ensure_namespace('server', ROOT / 'server')
_ensure_namespace('server.services', ROOT / 'server' / 'services')

from server.services.clinical_repo import ClinicalRepo
from server.services.prompt_composer import PromptComposer, estimate_tokens


def _setup_composer(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    composer = PromptComposer(repo=repo)
    return repo, composer


def test_compose_prompt_basic_sections(tmp_path):
    repo, composer = _setup_composer(tmp_path)
    repo.write_patient_meta('caroline', {'display_name': 'Caroline'})
    repo.write_patient_file(
        'caroline',
        'quotes.json',
        {
            'quotes': [
                {
                    'text': "J’ai été traumatisée par X",
                    'date': '2025-09-30',
                    'speaker': 'patient',
                    'kind': 'quote',
                }
            ]
        },
    )
    repo.write_patient_file(
        'caroline',
        'milestones.json',
        {
            'milestones': [
                {
                    'note': 'Session charnière sur la régulation émotionnelle',
                    'date': '2025-09-15',
                    'speaker': 'clinician',
                }
            ]
        },
    )
    repo.write_patient_file(
        'caroline',
        'contradictions.json',
        {
            'contradictions': [
                {
                    'label': 'Envie vs retrait',
                    'details': ['Souhaite être vue mais se retire dès que le conflit apparaît.'],
                    'speaker': 'clinician',
                    'kind': 'hypothesis',
                }
            ]
        },
    )
    repo.write_patient_file(
        'caroline',
        'contexts.json',
        {
            'typical_situations': ['Lors des réunions d’équipe.'],
            'transformations': ['S’autorise à déléguer ponctuellement.'],
        },
    )
    repo.write_patient_file(
        'caroline',
        'somatic.json',
        {'resources': ['Respiration cohérente'], 'tensions': ['Mâchoire crispée']},
    )
    repo.write_patient_file(
        'caroline',
        'trauma_profile.json',
        {
            'core_patterns': [
                {
                    'pattern': 'Hypervigilance relationnelle',
                    'triggers': ['hausse du ton'],
                    'protections': ['contrôle'],
                    'signals': ['épaules raidies'],
                    'feasibility_windows': ['matinée'],
                }
            ]
        },
    )

    repo.write_session_files(
        'caroline',
        '2025-09-30_1',
        {
            'segments.json': {
                'segments': [
                    {
                        'topic': 'fatigue cognitive',
                        'text': 'Je suis exténuée après chaque réunion stratégique.',
                        'speaker': 'patient',
                        'kind': 'paraphrase',
                        'date': '2025-09-30',
                    }
                ]
            },
            'plan.txt': '- [ ] Revisiter la routine de récupération\n- [x] Partager le plan avec l’équipe',
        },
    )

    repo.write_session_files(
        'caroline',
        '2025-09-15_1',
        {
            'segments.json': {
                'segments': [
                    {
                        'topic': 'culpabilité',
                        'text': 'Je culpabilise quand je mets une limite nette.',
                        'speaker': 'patient',
                        'kind': 'quote',
                        'date': '2025-09-15',
                    }
                ]
            }
        },
    )

    result = composer.compose('caroline', max_tokens=500)

    assert 'CONTRAT D’ATTRIBUTION' in result['prompt']
    assert 'Ce que la personne a dit' in result['prompt']
    assert 'Observations / hypothèses du praticien' in result['prompt']
    assert 'Objectifs non résolus' in result['prompt']
    assert 'Vous avez dit' in result['prompt']
    assert estimate_tokens(result['prompt']) <= 500
    assert result['trace']
    speakers = {entry.get('speaker') for entry in result['trace']}
    assert 'patient' in speakers and 'clinician' in speakers


def test_compose_prompt_handles_missing_data(tmp_path):
    repo, composer = _setup_composer(tmp_path)
    repo.write_patient_meta('alice', {'display_name': 'Alice'})

    result = composer.compose('alice')

    assert 'CONTRAT D’ATTRIBUTION' in result['prompt']
    assert '- (aucune donnée patient disponible)' in result['prompt']
    assert result['usage']['segments'] == 0


def test_compose_prompt_respects_token_cap(tmp_path):
    repo, composer = _setup_composer(tmp_path)
    repo.write_patient_meta('bruno', {'display_name': 'Bruno'})
    long_text = 'Très long récit ' * 80
    repo.write_session_files(
        'bruno',
        '2025-09-01_1',
        {
            'segments.json': {
                'segments': [
                    {
                        'topic': 'répétitif',
                        'text': long_text,
                        'speaker': 'patient',
                        'kind': 'paraphrase',
                        'date': '2025-09-01',
                    },
                    {
                        'topic': 'répétitif',
                        'text': long_text,
                        'speaker': 'patient',
                        'kind': 'paraphrase',
                        'date': '2025-09-01',
                    },
                ]
            }
        },
    )

    result = composer.compose('bruno', max_tokens=80)

    assert estimate_tokens(result['prompt']) <= 80
    occurrences = [entry for entry in result['trace'] if entry.get('topic') == 'répétitif']
    assert len(occurrences) == 1
