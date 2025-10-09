# [pipeline-v3 begin]
"""Construction du prompt final (anti-TCC, matérialiste, narrative, située)."""

from __future__ import annotations

from typing import Any, Dict

ANTI_TCC_BANNED = [
    "TCC",
    "thérapie cognitivo-comportementale",
    "restructuration cognitive",
    "exposition graduée",
    "défi des pensées automatiques",
    "ABC de Ellis",
    "devoirs à domicile",
    "homework",
    "échelle de 0 à 10",
    "SMART",
]


def build_final_prompt(
    plan: Dict[str, Any],
    research: Dict[str, Any],
    mail_brut: str,
    prenom: str,
) -> str:
    """Assemble le prompt final prêt à être copié dans ChatGPT web."""

    def bloc_local() -> str:
        items = research.get("local_library", [])[:3]
        return "\n".join([f"- {it.get('extrait', '')}" for it in items]) if items else ""

    def bloc_web() -> str:
        items = research.get("internet", [])[:3]
        if not items:
            return ""

        def _clean(value: str) -> str:
            return value.replace("http://", "").replace("https://", "").strip()

        def to_line(it: Dict[str, Any]) -> str:
            snippet = _clean(str(it.get("snippet") or it.get("resume") or ""))
            title = _clean(str(it.get("title") or it.get("titre") or ""))
            url = _clean(str(it.get("url") or it.get("site") or ""))
            note = _clean(str(it.get("source_note") or ""))
            meta_parts = [part for part in (title, note, url) if part]
            if meta_parts:
                meta = " — ".join(dict.fromkeys(meta_parts))
                return "\n".join([part for part in (snippet, f"Source : {meta}") if part])
            return snippet

        return "\n\n".join(filter(None, (to_line(it) for it in items)))

    prompt = f"""
Tu es un·e praticien·ne matérialiste, féministe et evidence based.
Prépare un déroulé de séance thérapeutique pour {prenom}.

Contraintes éditoriales :
1. Pas de psychanalyse ni d'interprétations symboliques.
2. Pas d'échelles chiffrées et pas de coaching individualisant.
3. Pas de points de vigilance et pas de chronos.
4. Proposer des pistes d'action concrètes, solidaires et collectivisantes.
5. Valider explicitement l'expérience de la personne.
6. Langue inclusive et accessible.
7. Surveillance anti comportementaliste : interdire tout travail imposé hors séance, tout palier d'exposition forcé, toute mise à l'épreuve dirigée des pensées, toute échelle chiffrée et les objectifs comportementalistes ou autres dérivés prescriptifs.
8. Approche narrative et située : relier les phénomènes aux conditions matérielles, sociales et institutionnelles; privilégier co-construction, consentement, formulation des besoins, continuité thérapeutique sur moyen terme.

Contexte brut à intégrer tel quel :
{mail_brut}

Plan préparatoire :
Orientation : {plan.get('orientation', '')}
Objectif prioritaire : {plan.get('objectif_prioritaire', '')}
Cadre de travail : {plan.get('cadre_de_travail', '')}
Situation actuelle : {plan.get('synthese', {}).get('situation_actuelle', '')}
Tensions principales : {plan.get('synthese', {}).get('tensions_principales', '')}
Axes de travail : {plan.get('synthese', {}).get('axes_de_travail', '')}
Clôture attendue : {plan.get('cloture_attendue', '')}

Connaissances situées issues de la librairie locale :
{bloc_local()}

Synthèses internet si nécessaire :
{bloc_web()}

Attendus de sortie :
1. Introduction courte qui ancre immédiatement la séance dans l'orientation et l'objectif prioritaire, en nommant la co-construction et l'accord sur la direction de travail.
2. Trois modules au minimum. Pour chaque module :
   a) Questions d'ouverture nombreuses, non-répétitives, qui ouvrent des pistes d'exploration, vérifient le consentement et l'accord, articulent vécu et contexte matériel/institutionnel, et anticipent une continuité thérapeutique de moyen terme (prochaines 2-6 semaines).
   b) Un paragraphe de psychoéducation développée, matérialiste, evidence based et située, lisible à voix haute en séance; relier explicitement les phénomènes aux mécanismes neurocognitifs et aux déterminants sociaux (travail, droits, logement, accès aux soins), sans culpabilisation.
3. Clôture : quelques questions de projection concrète (en termes de cap, pas de métriques), formulation d'une continuité, et vérification d'alignement avec les objectifs de la personne.

Interdictions :
1. Aucune 'vigilance'.
2. Aucun chronométrage.
3. Aucune liste de liens ou URL.
4. Aucune pathologisation individualisante. Aucun registre prescriptif comportementaliste.
"""

    for token in ANTI_TCC_BANNED:
        assert token.lower() not in prompt.lower()

    return prompt.strip()
# [pipeline-v3 end]
