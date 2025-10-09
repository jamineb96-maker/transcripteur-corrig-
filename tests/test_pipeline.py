import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))  # noqa: E402
from pipeline import ResearchPipeline, FinalPipeline


def test_research_and_final():
    transcript = (
        "Aujourd'hui nous avons parlé des contraintes matérielles au travail. "
        "Cette situation est difficile car les responsabilités sont distribuées. "
        "Nous avons aussi évoqué les ressources disponibles et les hypothèses pour la suite."
    )
    research = ResearchPipeline().run(transcript, prenom='Alice', register='vous')
    assert research['meta']['prenom'] == 'Alice'
    assert research['chapters']
    assert research['evidence_sheet']
    assert 'matérialisme' in research['lenses_used']
    final = FinalPipeline().run(research)
    assert 'Compte‑rendu' in final['mail_markdown']
    # Ensure no bullet list markers remain
    assert '*' not in final['mail_markdown']
    # Register substitution: 'vous' should remain since input register is 'vous'
    assert 'tu' not in final['mail_markdown']