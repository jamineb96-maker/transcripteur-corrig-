"""Utility functions to build text for the Pre-session tab."""

import re


def _clean_text(value):
    if not value:
        return ''
    return str(value).strip()


def generate_brief(prompt, params=None):
    """Generate a ready-to-copy prompt for ChatGPT Web.

    The function accepts either the new structured ``prompt`` payload
    (dictionary with ``mailBody``, ``patientReply`` and
    ``promptInstructions`` keys) or the legacy list-based ``contexts``.
    Parameters may contain auxiliary flags such as ``forceReturn``.
    """

    params = params or {}

    mail_body = ''
    patient_reply = ''
    prompt_instructions = ''

    if isinstance(prompt, dict):
        mail_body = _clean_text(prompt.get('mailBody'))
        patient_reply = _clean_text(prompt.get('patientReply'))
        prompt_instructions = _clean_text(prompt.get('promptInstructions'))
    else:
        contexts = prompt or []
        if isinstance(contexts, (list, tuple)):
            mail_body = _clean_text(contexts[0] if len(contexts) > 0 else '')
            patient_reply = _clean_text(contexts[1] if len(contexts) > 1 else '')
            prompt_instructions = _clean_text(contexts[2] if len(contexts) > 2 else '')

    force_return = bool(params.get('forceReturn'))
    should_add_return = force_return or bool(patient_reply)

    forbidden_pattern = re.compile(r"\b(tcc|json|échelles?|echelles?)\b", flags=re.IGNORECASE)

    def sanitize(text):
        cleaned = _clean_text(text)
        cleaned = cleaned.replace('{', '').replace('}', '')
        cleaned = forbidden_pattern.sub('', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned.strip()

    sanitized_mail = sanitize(mail_body)
    sanitized_reply = sanitize(patient_reply)
    sanitized_instructions = sanitize(prompt_instructions)

    synthesis_segments = [
        (
            "Prépare une analyse matérialiste et critique de la situation clinique à partir des échanges qui suivent, "
            "en soulignant les rapports sociaux et matériels impliqués."
        )
    ]

    if sanitized_mail:
        synthesis_segments.append(
            f"Le courrier initial du ou de la thérapeute met en avant les éléments suivants : {sanitized_mail}."
        )
    else:
        synthesis_segments.append("Aucun courrier initial n'est disponible ; reconstitue le contexte avec prudence.")

    if sanitized_reply:
        synthesis_segments.append(
            f"La réponse du ou de la patient·e souligne : {sanitized_reply}."
        )
    else:
        synthesis_segments.append(
            "Le ou la patient·e n'a pas fourni de retour ; concentre-toi sur les données déjà connues."
        )

    if sanitized_instructions:
        synthesis_segments.append(
            f"Prends aussi en compte les consignes particulières suivantes : {sanitized_instructions}."
        )

    synthesis_segments.append(
        "Garde un ton engagé, matérialiste et critique : relie systématiquement les symptômes aux conditions sociales, "
        "matérielles et institutionnelles qui peuvent les produire ou les entretenir."
    )

    synthesis_segments.append(
        "Écarte toute proposition fondée sur des outils de mesure chiffrée, sur des protocoles cognitivo-comportementaux "
        "ou sur des formats de restitution sérialisés ; privilégie des recommandations ancrées dans la réalité matérielle."
    )

    if should_add_return and sanitized_reply:
        synthesis_segments.append(
            "Commence par adresser un court message de retour au ou à la patient·e en réutilisant explicitement ses propres "
            "mots, puis enchaîne avec l'analyse critique."
        )
    else:
        synthesis_segments.append(
            "Si aucun retour n'est attendu, passe directement à l'analyse tout en rappelant les limites des informations "
            "disponibles."
        )

    prompt_text = " ".join(segment for segment in synthesis_segments if segment).strip()
    return prompt_text
