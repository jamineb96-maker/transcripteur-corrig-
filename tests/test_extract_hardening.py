import pytest

from server.post_v2.extract_session import extract_session_facts


@pytest.mark.parametrize(
    "transcript",
    [
        "Nous avons discuté de sommeil et de stress sans évoquer de traitement médicamenteux.",
        "Le patient parle de ses habitudes alimentaires et de sa fatigue chronique sans citer de molécule.",
    ],
)
def test_no_meds_detected_when_not_in_lexicon(transcript):
    facts = extract_session_facts(transcript, "Alice", "2024-02-01")
    assert facts.meds == []


def test_asks_include_full_question():
    transcript = (
        "Je n'arrive plus à suivre les cours correctement depuis deux semaines. "
        "J'aimerais savoir si on peut adapter mon horaire de travail pour que je récupère un peu ? "
        "Je prends des notes pour ne rien oublier."
    )
    facts = extract_session_facts(transcript, "Alice", "2024-02-01")
    assert facts.asks, "La liste des questions devrait contenir au moins un élément."
    first = facts.asks[0]
    assert first.endswith("?"), first
    assert 30 <= len(first) <= 140


def test_quotes_exclude_therapist_sentences():
    transcript = (
        "Je me sens perdue depuis plusieurs semaines et je n'arrive plus à structurer mes journées, tout mon travail en pâtit et je m'inquiète de perdre mon poste. "
        "Je passe mes nuits à ruminer et je me réveille très fatiguée, je ne sais pas comment tenir au travail sans soutien. "
        "J'aimerais savoir si on peut adapter mon horaire de travail pour que je récupère un peu ? "
        "Le thérapeute dit : je te propose de respirer profondément avant chaque réunion. "
        "Je voudrais expliquer à mon employeur que ma charge de travail actuelle n'est pas soutenable et que je risque de craquer si rien ne change. "
        "En dehors du foyer, mon frère me demande encore de l'argent et je suis perdue."
    )
    facts = extract_session_facts(transcript, "Alice", "2024-02-01")
    assert len(facts.quotes) >= 3
    joined = " ".join(facts.quotes).lower()
    assert "je te propose" not in joined


def test_context_sentence_is_clean():
    transcript = (
        "Je me sens perdue depuis plusieurs semaines et je n'arrive plus à structurer mes journées, tout mon travail en pâtit et je m'inquiète de perdre mon poste. "
        "Je passe mes nuits à ruminer et je me réveille très fatiguée, je ne sais pas comment tenir au travail sans soutien. "
        "J'aimerais savoir si on peut adapter mon horaire de travail pour que je récupère un peu ? "
        "Je voudrais expliquer à mon employeur que ma charge de travail actuelle n'est pas soutenable et que je risque de craquer si rien ne change."
    )
    facts = extract_session_facts(transcript, "Alice", "2024-02-01")
    travail_context = facts.context.get("travail")
    assert travail_context is not None
    assert travail_context.endswith(('.', '!', '?'))
    assert "charge de travail actuelle" in travail_context
