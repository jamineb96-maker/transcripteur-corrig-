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
from server.services.prompt_composer import PromptComposer


def _composer(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    repo.write_patient_meta('demo', {'display_name': 'Démo'})
    return PromptComposer(repo=repo), repo


def test_clinician_hypothesis_not_tagged_as_patient(tmp_path):
    composer, repo = _composer(tmp_path)
    repo.write_patient_file(
        'demo',
        'contradictions.json',
        {
            'contradictions': [
                {
                    'label': 'Hypothèse clinicien',
                    'details': ['elle a l’air d’avoir été traumatisée par X'],
                    'speaker': 'clinician',
                    'kind': 'hypothesis',
                }
            ]
        },
    )

    repo.write_session_files(
        'demo',
        '2025-09-01_1',
        {
            'segments.json': {'segments': []},
        },
    )

    result = composer.compose('demo', max_tokens=200)

    assert 'Vous avez dit : « elle a l’air d’avoir été traumatisée par X »' not in result['prompt']
    assert 'Hypothèse prudente' in result['prompt']


def test_patient_quote_preserves_vous_avez(tmp_path):
    composer, repo = _composer(tmp_path)
    repo.write_patient_file(
        'demo',
        'quotes.json',
        {
            'quotes': [
                {
                    'text': 'J’ai été traumatisée par X',
                    'date': '2025-09-10',
                    'speaker': 'patient',
                    'kind': 'quote',
                }
            ]
        },
    )
    repo.write_session_files(
        'demo',
        '2025-09-10_1',
        {
            'segments.json': {
                'segments': [
                    {
                        'topic': 'trauma',
                        'text': 'Je me souviens encore de X',
                        'speaker': 'patient',
                        'kind': 'quote',
                        'date': '2025-09-10',
                    }
                ]
            }
        },
    )

    result = composer.compose('demo', max_tokens=200)

    assert 'Vous avez dit : « J’ai été traumatisée par X »' in result['prompt']


def test_lint_converts_faulty_vous_avez(tmp_path):
    composer, repo = _composer(tmp_path)
    repo.write_patient_file(
        'demo',
        'milestones.json',
        {
            'milestones': [
                {
                    'note': 'vous avez oublié de respirer pendant l’exercice',
                    'speaker': 'clinician',
                    'date': '2025-09-05',
                    'kind': 'observation',
                }
            ]
        },
    )
    repo.write_session_files('demo', '2025-09-05_1', {'segments.json': {'segments': []}})

    result = composer.compose('demo', max_tokens=200)

    assert 'Je note : Je note que' in result['prompt']
    assert result.get('warnings')


def test_unknown_speaker_classified_as_clinician(tmp_path):
    composer, repo = _composer(tmp_path)
    repo.write_session_files(
        'demo',
        '2025-09-02_1',
        {
            'segments.json': {
                'segments': [
                    {
                        'topic': 'observation',
                        'text': 'Point délicat à surveiller',
                        'speaker': 'unknown',
                        'kind': 'paraphrase',
                        'date': '2025-09-02',
                    }
                ]
            }
        },
    )

    result = composer.compose('demo', max_tokens=200)

    assert 'délicat à surveiller' not in _extract_patient_section(result['prompt'])
    assert '⟦Point⟧ délicat à surveiller' in _extract_clinician_section(result['prompt'])


def _extract_patient_section(prompt: str) -> str:
    parts = prompt.split('Observations / hypothèses du praticien')
    return parts[0]


def _extract_clinician_section(prompt: str) -> str:
    parts = prompt.split('Observations / hypothèses du praticien')
    if len(parts) < 2:
        return ''
    return parts[1]
