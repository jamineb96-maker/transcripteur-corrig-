"""Outils de personnalisation linguistique et morphologique."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Mapping

_LANG_PATTERN = re.compile(r"\{\{TUT\|VOUS\}\}")
_GEN_PATTERN = re.compile(r"\{\{GEN:([^{}]+)\}\}")
_VAR_PATTERN = re.compile(r"\{\{([A-Z_À-ÖØ-öø-ÿ]+)\}\}")

_PRONOUNS = {
    'feminine': {
        'PRONOM_SUJET': 'elle',
        'PRONOM_OBJET': 'la',
        'PRONOM_POSSESSIF': 'la sienne',
        'DETERMINANT_POSSESSIF': 'sa',
        'ADJ_POSSESSIF': 'sa',
    },
    'masculine': {
        'PRONOM_SUJET': 'il',
        'PRONOM_OBJET': 'le',
        'PRONOM_POSSESSIF': 'le sien',
        'DETERMINANT_POSSESSIF': 'son',
        'ADJ_POSSESSIF': 'son',
    },
    'neutral': {
        'PRONOM_SUJET': 'iel',
        'PRONOM_OBJET': 'iel',
        'PRONOM_POSSESSIF': 'le leur',
        'DETERMINANT_POSSESSIF': 'son',
        'ADJ_POSSESSIF': 'son',
    },
}


@dataclass
class PersonalizationContext:
    """Représente les paramètres de personnalisation applicables."""

    langage: str
    gender: str
    patient_name: str
    patient_first_name: str
    cabinet: str = 'Cabinet'

    def to_mapping(self) -> Dict[str, str]:
        pronouns = _PRONOUNS.get(self.gender, _PRONOUNS['neutral']).copy()
        mapping = {
            'LANGAGE': self.langage,
            'PATIENT_NOM_COMPLET': self.patient_name,
            'PATIENT_PRENOM': self.patient_first_name,
            'PATIENT_PRÉNOM': self.patient_first_name,
            'CABINET_NOM': self.cabinet,
        }
        mapping.update(pronouns)
        # Alias pour compatibilité large
        mapping['PRONOM_SUJET'] = pronouns['PRONOM_SUJET']
        mapping['PRONOM_OBJET'] = pronouns['PRONOM_OBJET']
        mapping['PRONOM_POSSESSIF'] = pronouns['PRONOM_POSSESSIF']
        mapping['DETERMINANT_POSSESSIF'] = pronouns['DETERMINANT_POSSESSIF']
        mapping['ADJECTIF_POSSESSIF'] = pronouns['ADJ_POSSESSIF']
        return mapping


def build_context(patient: Mapping[str, object], langage: str, gender: str) -> PersonalizationContext:
    """Construit un contexte de personnalisation à partir des données patient."""

    langage = 'tu' if (langage or '').lower() == 'tu' else 'vous'
    gender = (gender or '').lower()
    if gender not in ('feminine', 'masculine', 'neutral'):
        gender = 'neutral'
    name = str(patient.get('name') or patient.get('displayName') or '').strip()
    if not name:
        name = str(patient.get('id') or 'patient·e')
    first_name = name.split()[0]
    cabinet = str(patient.get('cabinet') or 'Cabinet')
    return PersonalizationContext(langage=langage, gender=gender, patient_name=name, patient_first_name=first_name, cabinet=cabinet)


def apply_personalization(text: str, context: PersonalizationContext) -> str:
    """Applique les tokens de personnalisation sur le texte fourni."""

    if not text:
        return ''
    mapping = context.to_mapping()

    def replace_lang(match: re.Match) -> str:
        return 'tu' if context.langage == 'tu' else 'vous'

    def replace_gen(match: re.Match) -> str:
        options = [opt.strip() for opt in match.group(1).split('|')]
        options = [opt for opt in options if opt]
        if not options:
            return ''
        idx = {'feminine': 0, 'masculine': 1, 'neutral': 2}[context.gender]
        if idx >= len(options):
            idx = len(options) - 1
        return options[idx]

    def replace_var(match: re.Match) -> str:
        key = match.group(1)
        # Normalise les clés sans accents
        normalized = key.replace('É', 'E').replace('È', 'E').replace('Ê', 'E')
        normalized = normalized.replace('À', 'A').replace('Ù', 'U').replace('Î', 'I')
        normalized = normalized.replace('Ô', 'O').replace('Â', 'A')
        if key in mapping:
            return mapping[key]
        if normalized in mapping:
            return mapping[normalized]
        return mapping.get(key.replace('É', 'E').replace('À', 'A'), '')

    text = _LANG_PATTERN.sub(replace_lang, text)
    text = _GEN_PATTERN.sub(replace_gen, text)
    text = _VAR_PATTERN.sub(replace_var, text)
    return text
