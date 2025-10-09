"""Moteur de calcul pour le budget cognitif et somatique.

Ce module implémente les formules décrites dans le cahier des charges :
stock de cuillères, coût des activités, gains de récupération, dette et
synthèse éditoriale.  Les coefficients proviennent du fichier
``data/budget_presets.json`` afin de rester auditable.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_PRESETS_CACHE: Tuple[float, Dict[str, Any]] | None = None


class BudgetComputationError(ValueError):
    """Erreur levée lorsque la requête transmise est incomplète."""


@dataclass
class PatientContext:
    """Représente les méta-données minimales sur le patient."""

    id: str
    name: str
    gender: str
    language: str
    period: str
    budget_profile: str

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> "PatientContext":
        required = ['id', 'name', 'gender', 'language', 'period', 'budget_profile']
        missing = [key for key in required if key not in data]
        if missing:
            raise BudgetComputationError(f"missing_patient_fields:{','.join(missing)}")
        gender = data.get('gender')
        if gender not in {'neutral', 'feminine', 'masculine'}:
            raise BudgetComputationError('invalid_gender')
        language = data.get('language')
        if language not in {'tu', 'vous'}:
            raise BudgetComputationError('invalid_language')
        period = data.get('period')
        if period not in {'day', 'week'}:
            raise BudgetComputationError('invalid_period')
        profile = data.get('budget_profile')
        if profile not in {'low', 'mid', 'high'}:
            raise BudgetComputationError('invalid_profile')
        return cls(
            id=str(data['id']),
            name=str(data['name']),
            gender=gender,
            language=language,
            period=period,
            budget_profile=profile,
        )


@dataclass
class ActivityResult:
    """Résultat détaillé pour une activité."""

    id: str
    label: str
    category: str
    value: float
    intensity: float
    aggravants: List[str]
    attenuants: List[str]
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'category': self.category,
            'value': round(self.value, 2),
            'intensity': self.intensity,
            'aggravants': self.aggravants,
            'attenuants': self.attenuants,
            'notes': self.notes or '',
        }


@dataclass
class RecoveryResult(ActivityResult):
    """Spécialisation pour les récupérations (mêmes champs)."""


@dataclass
class AssessmentResult:
    """Structure renvoyée au client après calcul."""

    spoons_stock: float
    spoons_consumption: List[ActivityResult]
    spoons_recovery: List[RecoveryResult]
    net_spoons_day: float
    debt_projection: List[Dict[str, float]]
    hotspots: List[str]
    best_recoveries: List[str]
    narrative_summary: str
    alerts: List[Dict[str, str]]
    postsession_notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'spoons_stock': round(self.spoons_stock, 2),
            'spoons_consumption': [item.to_dict() for item in self.spoons_consumption],
            'spoons_recovery': [item.to_dict() for item in self.spoons_recovery],
            'net_spoons_day': round(self.net_spoons_day, 2),
            'debt_projection': self.debt_projection,
            'hotspots': self.hotspots,
            'best_recoveries': self.best_recoveries,
            'narrative_summary': self.narrative_summary,
            'alerts': self.alerts,
            'postsession_notes': self.postsession_notes,
        }


def _presets_path() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / 'data' / 'budget_presets.json'


def load_presets() -> Dict[str, Any]:
    """Charge le fichier de presets en mettant en cache le contenu."""

    global _PRESETS_CACHE
    path = _presets_path()
    if not path.exists():
        raise FileNotFoundError('Missing budget presets file.')
    mtime = path.stat().st_mtime
    if _PRESETS_CACHE and _PRESETS_CACHE[0] == mtime:
        return deepcopy(_PRESETS_CACHE[1])
    with path.open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    _PRESETS_CACHE = (mtime, data)
    return deepcopy(data)


def list_presets() -> Dict[str, Any]:
    """Renvoie une copie profonde des presets pour l'API publique."""

    return load_presets()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _activity_lookup(presets: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for category, payload in presets.get('activities', {}).items():
        for activity in payload.get('activities', []):
            mapping[activity['id']] = {
                'category': category,
                'label': activity['label'],
                'base_low': float(activity['base_low']),
                'base_high': float(activity['base_high']),
            }
    return mapping


def _category_biases(profile: Optional[Dict[str, Any]]) -> Dict[str, float]:
    if not profile:
        return {}
    biases = profile.get('profile_bias', {})
    output: Dict[str, float] = {}
    for key, value in biases.items():
        try:
            output[key] = float(value)
        except (TypeError, ValueError):
            continue
    return output


def _language_pack(language: str, gender: str) -> Dict[str, str]:
    if language == 'vous':
        pronoun = 'vous'
        poss = 'votre'
        reflexive = 'vous'
    else:
        pronoun = 'tu'
        poss = 'ton'
        reflexive = 'te'
    # Accord très simple, on reste en écriture inclusive pour éviter les erreurs
    if gender == 'feminine':
        fatigued = 'fatiguée'
    elif gender == 'masculine':
        fatigued = 'fatigué'
    else:
        fatigued = 'fatigué·e'
    return {
        'pronoun': pronoun,
        'possessive': poss,
        'reflexive': reflexive,
        'fatigued': fatigued,
    }


def _apply_postsession_adjustments(
    postsession: Dict[str, Any],
    presets: Dict[str, Any],
) -> Tuple[Dict[str, float], List[str], List[str]]:
    """Calcule des modulateurs issus de la pipeline Post-séance."""

    adjustments: Dict[str, float] = {
        'personal_care': 0.0,
        'transport': 0.0,
        'social': 0.0,
        'executive': 0.0,
        'sensory': 0.0,
        'recovery': 0.0,
    }
    notes: List[str] = []
    alerts: List[str] = []
    if not postsession:
        return adjustments, notes, alerts

    indices_cognitifs = ' '.join(postsession.get('indices_cognitifs', [])).lower()
    indices_somatiques = ' '.join(postsession.get('indices_somatiques', [])).lower()
    lenses = [str(item).lower() for item in postsession.get('lenses_used', [])]
    contradictions = postsession.get('contradiction_spans', []) or []

    if any(word in indices_cognitifs for word in ['surcharge', 'distract', 'brouillard']):
        adjustments['executive'] += 0.12
        adjustments['social'] += 0.08
        notes.append(
            "La séance précédente signale une surcharge cognitive ou une distractibilité élevée ; le coût des tâches exécutives est majoré et des micro-pauses avec externalisation de la mémoire sont suggérées."
        )
    if any(word in indices_somatiques for word in ['douleur', 'fatigue', 'inflammation']):
        adjustments['personal_care'] += 0.1
        adjustments['transport'] += 0.15
        adjustments['social'] += 0.08
        notes.append(
            "Les indices somatiques mentionnent douleur ou fatigue. Les activités physiques et sociales sont surpondérées et des repos sensoriels situés sont proposés."
        )
    if 'validisme' in lenses or 'patriarcat' in lenses:
        alerts.append(
            "Des contraintes normatives identifiées (validisme/patriarcat) sont rappelées dans la synthèse pour contextualiser l'effort imposé par l'environnement."
        )
    if contradictions:
        notes.append(
            "La pipeline post-séance repère des contradictions entre l'effort fourni et un sentiment de culpabilité : un plan non minuté avec jours tampons est recommandé."
        )
        adjustments['executive'] += 0.05
    return adjustments, notes, alerts


def _apply_bias(value: float, bias: float, presets: Dict[str, Any]) -> float:
    max_bias = float(presets.get('calibration', {}).get('max_bias', 0.2))
    return value * (1.0 + _clamp(bias, -max_bias, max_bias))


def _compute_stock(
    context: PatientContext,
    modulators: Iterable[Dict[str, Any]],
    presets: Dict[str, Any],
) -> float:
    stock_presets = presets.get('stock', {})
    base_stock = float(stock_presets.get(context.period, {}).get(context.budget_profile, 12))
    minimum_daily = float(stock_presets.get('minimum_daily', 4))
    delta_min = -abs(float(stock_presets.get('global_modulators', {}).get('max_negative', 4)))
    delta_max = abs(float(stock_presets.get('global_modulators', {}).get('max_positive', 4)))
    total_delta = 0.0
    for item in modulators:
        if not isinstance(item, dict):
            continue
        try:
            raw = float(item.get('delta', 0.0))
        except (TypeError, ValueError):
            raw = 0.0
        total_delta += _clamp(raw, delta_min, delta_max)
    stock = base_stock + total_delta
    if context.period == 'day':
        return max(stock, minimum_daily)
    # Pour la semaine on garantit un minimum journalier multiplié par 7
    return max(stock, minimum_daily * 7)


def _compute_activity_value(
    entry: Dict[str, Any],
    definition: Dict[str, Any],
    category_multiplier: float,
    bias: float,
    presets: Dict[str, Any],
) -> ActivityResult:
    intensity = _clamp(float(entry.get('intensity', 0.0)), 0.0, 10.0)
    span = max(definition['base_high'] - definition['base_low'], 0.0)
    base_value = definition['base_low'] + span * (intensity / 10.0)
    base_value = _apply_bias(base_value, bias, presets)
    base_value *= 1.0 + max(category_multiplier, -0.4)

    aggravants = [str(code) for code in entry.get('aggravants', []) if isinstance(code, str)]
    attenuants = [str(code) for code in entry.get('attenuants', []) if isinstance(code, str)]
    modulators = presets.get('modulators', {})
    aggr_conf = modulators.get('aggravants', {})
    attn_conf = modulators.get('attenuants', {})
    modifier = 1.0
    for code in aggravants:
        weight = float(aggr_conf.get(code, aggr_conf.get('default', 0.15)))
        modifier += max(weight, 0)
    for code in attenuants:
        weight = float(attn_conf.get(code, attn_conf.get('default', 0.12)))
        modifier -= max(weight, 0)
    modifier = max(modifier, 0.2)
    value = base_value * modifier
    notes = entry.get('notes')
    return ActivityResult(
        id=str(entry.get('id') or definition['category']),
        label=str(entry.get('label') or definition['label']),
        category=definition['category'],
        value=value,
        intensity=round(intensity, 2),
        aggravants=aggravants,
        attenuants=attenuants,
        notes=str(notes).strip() if notes else None,
    )


def _compute_recovery_value(
    entry: Dict[str, Any],
    definition: Dict[str, Any],
    category_multiplier: float,
    bias: float,
    presets: Dict[str, Any],
) -> RecoveryResult:
    result = _compute_activity_value(entry, definition, category_multiplier, bias, presets)
    return RecoveryResult(**result.__dict__)


def _aggregate_totals(items: Iterable[ActivityResult]) -> float:
    return sum(max(item.value, 0.0) for item in items)


def _build_debt_projection(
    period: str,
    net_value: float,
    presets: Dict[str, Any],
) -> List[Dict[str, float]]:
    alpha = float(presets.get('debt', {}).get('alpha', 0.6))
    projection_days = int(presets.get('debt', {}).get('projection_days', 7))
    if period == 'day':
        horizon = min(3, projection_days)
    else:
        horizon = min(7, projection_days)
    values: List[Dict[str, float]] = []
    debt_cumsum = 0.0
    current = net_value
    for day in range(horizon):
        if current < 0:
            debt = abs(current)
            penalty = math.ceil(debt * alpha)
            debt_cumsum += penalty
            next_net = net_value + debt_cumsum * -1
        else:
            penalty = 0.0
            next_net = net_value - debt_cumsum * 0.5
            if next_net > current:
                next_net = current
        values.append(
            {
                'day': day,
                'net': round(current, 2),
                'debt_cumsum': round(debt_cumsum, 2),
                'penalty': round(penalty, 2),
            }
        )
        current = next_net
    return values


def _detect_alerts(
    consumption: List[ActivityResult],
    recovery: List[RecoveryResult],
    fatigue_flag: bool,
    presets: Dict[str, Any],
) -> List[Dict[str, str]]:
    alerts: List[Dict[str, str]] = []
    total_cost = _aggregate_totals(consumption)
    total_recovery = _aggregate_totals(recovery)
    if total_cost and total_recovery > total_cost:
        if fatigue_flag:
            alerts.append(
                {
                    'code': 'incoherence',
                    'message': "La récupération estimée dépasse le coût tout en signalant une fatigue intense ; l'équipe est invitée à revisiter les hypothèses pour éviter de minimiser l'épuisement ressenti.",
                }
            )
    threshold = int(presets.get('alerts', {}).get('productivisme_threshold', 8))
    if len([item for item in consumption if item.value > 0.4]) > threshold and total_recovery < total_cost * 0.5:
        alerts.append(
            {
                'code': 'productivisme',
                'message': "Plus de huit activités coûteuses sont empilées sans repos suffisant ; proposer un plan non minuté avec blocs tampons et respiration critique vis-à-vis du productivisme.",
            }
        )
    return alerts


def _narrative_summary(
    context: PatientContext,
    stock: float,
    total_cost: float,
    total_recovery: float,
    net: float,
    hotspots: List[str],
    best_recoveries: List[str],
    projection: List[Dict[str, float]],
    postsession_notes: List[str],
    alerts: List[Dict[str, str]],
    fatigue_flag: bool,
) -> str:
    pack = _language_pack(context.language, context.gender)
    pronoun = pack['pronoun']
    poss = pack['possessive']
    fatigued = pack['fatigued']

    day_label = 'journée' if context.period == 'day' else 'semaine'
    intro = (
        f"{context.name} dispose d'un stock estimé à {round(stock, 1)} cuillères pour cette {day_label}. "
        f"Les activités déclarées mobilisent environ {round(total_cost, 1)} cuillères tandis que les ressources identifiées permettent d'en récupérer {round(total_recovery, 1)}."
    )

    debt_sentence = ""
    if net < 0:
        future = projection[1]['net'] if len(projection) > 1 else net - abs(net) * 0.6
        debt_sentence = (
            f" Le solde ressort à {round(net, 1)} cuillères, ce qui crée une dette qui pèsera dès J+1 (projection autour de {round(future, 1)}). "
            "Cette dette n'est pas un manque de volonté mais un signal physiologique qui rend {pronoun} plus {fatigued} et plus vulnérable aux imprévus."
        )
    else:
        debt_sentence = (
            f" Le solde reste positif ({round(net, 1)} cuillères). Pour autant, maintenir cette marge suppose de protéger {poss} repos et de résister aux injonctions productivistes."
        )

    hotspot_sentence = ""
    if hotspots:
        hotspot_sentence = (
            f" Les postes les plus coûteux sont {', '.join(hotspots)} ; il est proposé de les fractionner, d'inscrire des temps tampons et d'externaliser une partie de la charge."
        )

    recovery_sentence = ""
    if best_recoveries:
        recovery_sentence = (
            f" Les récupérations les plus efficaces identifiées sont {', '.join(best_recoveries)}. Elles sont à installer sans minutage strict, comme des rituels protecteurs."
        )

    adaptation = (
        " L'objectif n'est pas de renoncer à vivre mais de configurer un quotidien neuro-écologique : prioriser sans culpabilité, accepter l'ennui réparateur et négocier des environnements plus respirables."
    )

    postsession_sentence = ""
    if postsession_notes:
        postsession_sentence = " " + " ".join(postsession_notes)

    alert_sentence = ""
    if alerts:
        alert_sentence = " " + " ".join(alert['message'] for alert in alerts)

    if fatigue_flag and net >= 0:
        alert_sentence += (
            " Malgré un solde positif, la fatigue intense rapportée signale que ce budget reste théorique ; il doit être ajusté avec les feedbacks vécus."
        )

    debt_explanation = (
        " Une dette de cuillères n'est jamais un échec individuel : elle traduit l'addition des charges sensorielles, motrices et attentionnelles. Lorsqu'elle s'accumule, elle peut se traduire par des douleurs, une hypersensibilité ou des troubles de l'initiation à J+1 et J+2."
    )

    return (
        intro
        + debt_sentence
        + hotspot_sentence
        + recovery_sentence
        + postsession_sentence
        + alert_sentence
        + adaptation
        + debt_explanation
    )


def compute_assessment(
    payload: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
) -> AssessmentResult:
    """Calcule le budget cognitif à partir du payload reçu."""

    presets = load_presets()
    patient = PatientContext.from_payload(payload.get('patient', {}))
    factors = payload.get('factors') or {}
    if not isinstance(factors, dict) or not factors:
        raise BudgetComputationError('missing_factors')

    modulators = payload.get('modulators') or []
    postsession = payload.get('postsession') or {}
    fatigue_flag = bool(payload.get('fatigue_extreme'))

    adjustments, postsession_notes, postsession_alerts = _apply_postsession_adjustments(postsession, presets)

    biases = _category_biases(profile)
    lookup = _activity_lookup(presets)

    consumption_results: List[ActivityResult] = []
    recovery_results: List[RecoveryResult] = []

    for category, entries in factors.items():
        if category == 'recovery':
            target_list = recovery_results
        else:
            target_list = consumption_results
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            activity_id = entry.get('id')
            definition = lookup.get(activity_id)
            if not definition:
                continue
            bias = biases.get(definition['category'], 0.0)
            if definition['category'] == 'recovery':
                result = _compute_recovery_value(
                    entry,
                    definition,
                    adjustments.get(definition['category'], 0.0),
                    bias,
                    presets,
                )
            else:
                result = _compute_activity_value(
                    entry,
                    definition,
                    adjustments.get(definition['category'], 0.0),
                    bias,
                    presets,
                )
            target_list.append(result)

    if not consumption_results and not recovery_results:
        raise BudgetComputationError('empty_assessment')

    stock = _compute_stock(patient, modulators, presets)
    total_cost = _aggregate_totals(consumption_results)
    total_recovery = _aggregate_totals(recovery_results)
    net = stock - total_cost + total_recovery
    projection = _build_debt_projection(patient.period, net, presets)

    hotspots = [item.label for item in sorted(consumption_results, key=lambda x: x.value, reverse=True)[:3]]
    best_recoveries = [item.label for item in sorted(recovery_results, key=lambda x: x.value, reverse=True)[:3]]

    alerts = _detect_alerts(consumption_results, recovery_results, fatigue_flag, presets)
    for message in postsession_alerts:
        alerts.append({'code': 'context', 'message': message})

    summary = _narrative_summary(
        patient,
        stock,
        total_cost,
        total_recovery,
        net,
        hotspots,
        best_recoveries,
        projection,
        postsession_notes,
        alerts,
        fatigue_flag,
    )

    return AssessmentResult(
        spoons_stock=stock,
        spoons_consumption=consumption_results,
        spoons_recovery=recovery_results,
        net_spoons_day=net,
        debt_projection=projection,
        hotspots=hotspots,
        best_recoveries=best_recoveries,
        narrative_summary=summary,
        alerts=alerts,
        postsession_notes=postsession_notes,
    )


def update_profile_bias(
    profile: Dict[str, Any],
    category: str,
    observed_delta: float,
) -> Dict[str, Any]:
    """Met à jour la calibration patient."""

    presets = load_presets()
    biases = profile.setdefault('profile_bias', {})
    learning_rate = float(presets.get('calibration', {}).get('learning_rate', 0.5))
    current = float(biases.get(category, 0.0))
    new_value = current + observed_delta * learning_rate
    max_bias = float(presets.get('calibration', {}).get('max_bias', 0.2))
    biases[category] = _clamp(new_value, -max_bias, max_bias)
    return profile


def summarize_for_history(result: AssessmentResult) -> Dict[str, Any]:
    """Prépare un résumé compact pour l'historique stocké côté serveur."""

    return {
        'spoons_stock': round(result.spoons_stock, 2),
        'net': round(result.net_spoons_day, 2),
        'hotspots': result.hotspots,
        'best_recoveries': result.best_recoveries,
        'alerts': result.alerts,
    }


def export_basename(patient: PatientContext) -> str:
    period = 'jour' if patient.period == 'day' else 'semaine'
    return f"budget_{patient.id}_{period}"


def result_from_dict(data: Dict[str, Any]) -> AssessmentResult:
    """Reconstruit une :class:`AssessmentResult` depuis un dictionnaire JSON."""

    consumption: List[ActivityResult] = []
    for entry in data.get('spoons_consumption', []):
        if not isinstance(entry, dict):
            continue
        consumption.append(
            ActivityResult(
                id=str(entry.get('id', 'activity')),
                label=str(entry.get('label', 'Activité')),
                category=str(entry.get('category', 'unknown')),
                value=float(entry.get('value', 0.0)),
                intensity=float(entry.get('intensity', 0.0)),
                aggravants=[str(item) for item in entry.get('aggravants', []) if isinstance(item, str)],
                attenuants=[str(item) for item in entry.get('attenuants', []) if isinstance(item, str)],
                notes=str(entry.get('notes') or '').strip() or None,
            )
        )

    recoveries: List[RecoveryResult] = []
    for entry in data.get('spoons_recovery', []):
        if not isinstance(entry, dict):
            continue
        recoveries.append(
            RecoveryResult(
                id=str(entry.get('id', 'recovery')),
                label=str(entry.get('label', 'Récupération')),
                category=str(entry.get('category', 'recovery')),
                value=float(entry.get('value', 0.0)),
                intensity=float(entry.get('intensity', 0.0)),
                aggravants=[str(item) for item in entry.get('aggravants', []) if isinstance(item, str)],
                attenuants=[str(item) for item in entry.get('attenuants', []) if isinstance(item, str)],
                notes=str(entry.get('notes') or '').strip() or None,
            )
        )

    projection = []
    for item in data.get('debt_projection', []):
        if not isinstance(item, dict):
            continue
        projection.append(
            {
                'day': int(item.get('day', 0)),
                'net': float(item.get('net', 0.0)),
                'debt_cumsum': float(item.get('debt_cumsum', 0.0)),
                'penalty': float(item.get('penalty', 0.0)),
            }
        )

    return AssessmentResult(
        spoons_stock=float(data.get('spoons_stock', 0.0)),
        spoons_consumption=consumption,
        spoons_recovery=recoveries,
        net_spoons_day=float(data.get('net_spoons_day', 0.0)),
        debt_projection=projection,
        hotspots=[str(item) for item in data.get('hotspots', [])],
        best_recoveries=[str(item) for item in data.get('best_recoveries', [])],
        narrative_summary=str(data.get('narrative_summary', '')),
        alerts=[
            {
                'code': str(alert.get('code', 'info')),
                'message': str(alert.get('message', '')),
            }
            for alert in data.get('alerts', [])
            if isinstance(alert, dict)
        ],
        postsession_notes=[str(item) for item in data.get('postsession_notes', [])],
    )
