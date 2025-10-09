import importlib.util
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / 'server' / 'tabs' / 'pre_session' / 'logic.py'

spec = importlib.util.spec_from_file_location('pre_session_logic', MODULE_PATH)
logic = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(logic)

generate_brief = logic.generate_brief


def test_generate_brief_materialist_prompt():
    prompt = {
        'mailBody': "Le thérapeute décrit des difficultés liées au travail précaire et au manque de soutien social.",
        'patientReply': "La patiente insiste sur le fait que ses horaires instables aggravent son anxiété.",
        'promptInstructions': "Prévoir un plan de séance collectif avec une attention aux conditions matérielles."
    }

    result = generate_brief(prompt, params={'forceReturn': True})

    assert "analyse matérialiste et critique" in result
    assert "travail précaire" in result
    assert "horaires instables" in result
    assert "consignes particulières" in result
    assert "Commence par adresser un court message de retour" in result
    assert "outils de mesure chiffrée" in result


def test_generate_brief_filters_forbidden_terms_and_braces():
    prompt = {
        'mailBody': "Introduire une échelle de sévérité {score}",
        'patientReply': "Le patient préfère la TCC et un format JSON.",
        'promptInstructions': "Faire un plan en JSON avec une TCC graduée."
    }

    result = generate_brief(prompt)

    forbidden_terms = ['échelle', 'echelle', 'TCC', 'tcc', 'JSON', 'json', '{', '}']

    for term in forbidden_terms:
        assert term not in result

    # The synthesis should remain informative despite the sanitisation.
    assert "Introduire" in result or "sévérité" in result
    assert "Le patient" in result
