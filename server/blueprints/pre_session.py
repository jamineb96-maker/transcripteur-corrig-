"""Préparation de séance : analyse et génération de prompts structurés."""

from __future__ import annotations

import json
import logging
import os
import re
import textwrap
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import uuid4

from flask import Blueprint, Response, jsonify, request

from server.services.openai_client import DEFAULT_TEXT_MODEL, get_openai_client


LOGGER = logging.getLogger("assist.pre")

bp = Blueprint("pre_session", __name__, url_prefix="/api/pre")


@dataclass
class AnalyseResult:
    resume: str
    themes: List[str]
    priorites: List[str]
    leviers: List[str]
    vigilances: List[str]
    queries: List[str]
    brief: str


_TOPIC_MAP: Dict[str, Tuple[Tuple[str, ...], str, str]] = {
    "travail": (
        ("travail", "emploi", "boulot", "licenciement", "precarite", "bureaux", "harcelement"),
        "Explorer les déterminants matériels liés au travail et aux droits sociaux.",
        '"conditions de travail" droits sociaux clinique evidence',
    ),
    "logement": (
        ("logement", "appartement", "hébergement", "expulsion", "colocation", "demenagement"),
        "Cartographier les contraintes de logement et l'accès aux protections collectives.",
        '"mal-logement" accompagnement social evidence',
    ),
    "sante": (
        ("douleur", "sante", "medical", "somatique", "fatigue", "diagnostic"),
        "Faire le lien entre symptômes et conditions matérielles de santé.",
        '"santé communautaire" matérialiste clinique',
    ),
    "violence": (
        ("violence", "agression", "abus", "harcelement", "trauma", "danger"),
        "Sécuriser la séance face aux violences et activer les soutiens collectifs.",
        '"prise en charge" violences evidence based',
    ),
    "argent": (
        ("budget", "argent", "financier", "dette", "precarite", "rsa"),
        "Détailler la situation financière et les ressources mobilisables.",
        '"précarité" accompagnement materialiste',
    ),
    "isolement": (
        ("isolement", "solitude", "amis", "soutien", "collectif"),
        "Identifier les ressources collectives pour rompre l'isolement.",
        '"isolement social" pair-aidance evidence',
    ),
}

_BASE_MODULES: List[str] = [
    "Ouverture et sécurisation du cadre",
    "Exploration structurelle des déterminants",
    "Psychoéducation matérialiste et collectivisation",
]

_BASE_VIGILANCES: List[str] = [
    "Éviter toute culpabilisation individuelle ; partir des faits matériels.",
    "Pas de métaphores psychologisantes ; rester sur des propositions concrètes.",
]

_RISK_KEYWORDS = {
    "urgence": (
        ("suicide", "suicidaire", "mettre fin", "danger", "urgence", "crise"),
        "Vérifier immédiatement la sécurité et mobiliser les protocoles d'urgence collectifs.",
    ),
    "violence": (
        ("violence", "agression", "menace", "contrainte", "coercition"),
        "Prendre en charge les violences déclarées avec les réseaux spécialisés.",
    ),
    "logement": (
        ("expulsion", "sans abri", "hebergement", "squat"),
        "Anticiper les ruptures de logement et contacter les structures d'hébergement d'urgence.",
    ),
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _normalize(text: str) -> str:
    collapsed = " ".join(text.strip().split())
    return collapsed


def _truncate(text: str, limit: int) -> Tuple[str, bool]:
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit], True


def _split_sentences(text: str) -> List[str]:
    chunks = re.split(r"(?<=[.!?])\s+", text)
    sentences = [chunk.strip() for chunk in chunks if chunk.strip()]
    if not sentences:
        sentences = [text.strip()] if text.strip() else []
    return sentences


def _build_resume(text: str, max_sentences: int = 3) -> str:
    sentences = _split_sentences(text)
    selected = sentences[:max_sentences]
    return " ".join(selected).strip()


def _detect_topics(text: str) -> List[str]:
    lowered = re.sub(r"[^a-zà-ÿ0-9 ]", " ", text.lower())
    results: List[str] = []
    for key, (keywords, _, _) in _TOPIC_MAP.items():
        if any(keyword in lowered for keyword in keywords):
            results.append(key)
    return results


def _detect_risks(text: str) -> List[str]:
    lowered = re.sub(r"[^a-zà-ÿ0-9 ]", " ", text.lower())
    items: List[str] = []
    for key, (keywords, message) in _RISK_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            items.append(message)
    return items


def _suggest_queries(topics: Sequence[str]) -> List[str]:
    queries: List[str] = []
    for topic in topics:
        spec = _TOPIC_MAP.get(topic)
        if spec:
            queries.append(spec[2])
    if not queries:
        queries.append('"alliance thérapeutique" matérialisme clinique')
        queries.append('"embodiment" evidence based collectif')
    return queries[:6]


def _flatten_strings(payload: Any) -> Iterable[str]:
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from _flatten_strings(value)
    elif isinstance(payload, (list, tuple, set)):
        for item in payload:
            yield from _flatten_strings(item)


def _parse_analysis_payload(data: Dict[str, Any]) -> Optional[AnalyseResult]:
    if not isinstance(data, dict):
        return None
    resume = str(data.get("resume") or "").strip()
    themes = [str(item).strip() for item in data.get("themes", []) if str(item).strip()]
    priorites = [str(item).strip() for item in data.get("priorites", []) if str(item).strip()]
    leviers = [str(item).strip() for item in data.get("leviers", []) if str(item).strip()]
    vigilances = [str(item).strip() for item in data.get("vigilances", []) if str(item).strip()]
    queries = [str(item).strip() for item in data.get("queries", []) if str(item).strip()]
    brief = str(data.get("brief") or "").strip()
    if not resume and not themes:
        return None
    return AnalyseResult(
        resume=resume,
        themes=themes,
        priorites=priorites,
        leviers=leviers or [
            "Co-construire des pistes d'action concrètes avec les ressources collectives disponibles.",
            "Renforcer l'alliance en valorisant les stratégies déjà mobilisées par la personne.",
        ],
        vigilances=vigilances,
        queries=queries,
        brief=brief,
    )


def _extract_json_blob(payload: Any) -> Optional[Dict[str, Any]]:
    for candidate in _flatten_strings(payload):
        text = candidate.strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            continue
    return None


def _analyse_with_openai(client: Any, normalized: str) -> Optional[AnalyseResult]:  # pragma: no cover - externe
    chat_api = getattr(client, "chat", None)
    if chat_api is None or not hasattr(chat_api, "completions"):
        return None
    completions_api = getattr(chat_api, "completions", None)
    if completions_api is None or not hasattr(completions_api, "create"):
        return None
    model = os.getenv("PRE_ANALYSE_MODEL", DEFAULT_TEXT_MODEL)
    try:
        temperature = float(os.getenv("PRE_TEMPERATURE", "0.2"))
    except (TypeError, ValueError):
        temperature = 0.2
    schema = {
        "name": "PreSessionAnalysis",
        "schema": {
            "type": "object",
            "properties": {
                "resume": {"type": "string"},
                "themes": {"type": "array", "items": {"type": "string"}},
                "priorites": {"type": "array", "items": {"type": "string"}},
                "leviers": {"type": "array", "items": {"type": "string"}},
                "vigilances": {"type": "array", "items": {"type": "string"}},
                "queries": {"type": "array", "items": {"type": "string"}},
                "brief": {"type": "string"},
            },
            "required": ["resume", "themes", "priorites", "leviers", "vigilances", "queries", "brief"],
            "additionalProperties": False,
        },
        "strict": True,
    }
    instructions = textwrap.dedent(
        """
        Tu es un·e praticien·ne matérialiste, féministe et evidence-based.
        Analyse les mails bruts suivants pour préparer une séance préalable.
        Renvoie exclusivement un JSON respectant le schéma fourni.
        """
    ).strip()
    schema_text = json.dumps(schema["schema"], ensure_ascii=False)
    system_prompt = f"{instructions}\nSchéma JSON attendu : {schema_text}"
    try:
        response = completions_api.create(  # type: ignore[attr-defined]
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": normalized},
            ],
            temperature=temperature,
        )
    except Exception:
        raise

    message_content = None
    try:
        if response.choices:
            message_content = response.choices[0].message.content
    except Exception:
        message_content = None
    json_payload = _extract_json_blob(message_content)
    if not json_payload:
        return None
    parsed = _parse_analysis_payload(json_payload)
    return parsed


def _derive_agenda(topics: Sequence[str]) -> List[str]:
    agenda: List[str] = [
        "Commencer par une mise à niveau somatique (respiration, ancrage collectif).",
        "Valider explicitement les faits rapportés puis cartographier les contraintes matérielles.",
    ]
    if "travail" in topics:
        agenda.append("Temps spécifique : cartographier les pressions du travail et les droits activables.")
    if "violence" in topics:
        agenda.append("Prévoir un espace sécurisé pour qualifier les violences et activer les relais spécialisés.")
    if "logement" in topics:
        agenda.append("Identifier les options immédiates de logement et les soutiens collectifs.")
    if "sante" in topics:
        agenda.append("Mettre en lien symptômes et accès aux soins somatiques accessibles.")
    if "argent" in topics:
        agenda.append("Dresser l'état des ressources financières et des aides ouvertes.")
    if "isolement" in topics:
        agenda.append("Programmer un temps pour connecter avec les réseaux de pair-aidance.")
    return agenda[:6]


def _derive_modules(topics: Sequence[str]) -> List[str]:
    modules = list(_BASE_MODULES)
    for topic in topics:
        spec = _TOPIC_MAP.get(topic)
        if spec:
            modules.append(spec[1])
    seen: List[str] = []
    for item in modules:
        if item not in seen:
            seen.append(item)
    return seen[:6]


def _build_brief(resume: str, modules: Sequence[str], agenda: Sequence[str]) -> str:
    resume_part = resume or "Résumé à compléter en séance."
    modules_part = ", ".join(modules[:3]) if modules else "modules à co-construire"
    agenda_part = agenda[0] if agenda else "Prioriser un temps d'écoute active."
    brief = textwrap.dedent(
        f"""
        Synthèse rapide : {resume_part}
        Modules clés : {modules_part}.
        Priorité séance : {agenda_part}
        Cadre : matérialiste, evidence-based, sans échelles de 0 à 10 ni coaching individuel.
        """
    ).strip()
    return brief


def analyse_pre_session(mails_raw: str, client: Any | None = None) -> AnalyseResult:
    normalized = _normalize(mails_raw)
    resume = _build_resume(normalized)
    topics = _detect_topics(normalized)
    priorites: List[str] = []

    if client is not None:  # pragma: no cover - dépendance externe
        try:
            ai_result = _analyse_with_openai(client, normalized)
            if ai_result:
                return ai_result
        except Exception as exc:  # pragma: no cover - réseau
            LOGGER.warning("Analyse OpenAI indisponible: %s", exc, exc_info=True)
            raise

    if topics:
        for topic in topics:
            spec = _TOPIC_MAP.get(topic)
            if spec:
                priorites.append(spec[1])
    else:
        priorites.append("Identifier les déterminants matériels prioritaires avec la personne.")
    leviers = [
        "Co-construire des pistes d'action concrètes avec les ressources collectives disponibles.",
        "Renforcer l'alliance en valorisant les stratégies déjà mobilisées par la personne.",
    ]
    vigilances = list(_BASE_VIGILANCES)
    vigilances.extend(_detect_risks(normalized))
    queries = _suggest_queries(topics)
    brief = _build_brief(resume, priorites, leviers)
    return AnalyseResult(
        resume=resume,
        themes=list(dict.fromkeys(topics)),
        priorites=list(dict.fromkeys(priorites)),
        leviers=leviers,
        vigilances=list(dict.fromkeys(vigilances))[:6],
        queries=queries,
        brief=brief,
    )


def planifier_pre_session(analyse: AnalyseResult) -> Dict[str, Any]:
    modules = _derive_modules(analyse.themes)
    agenda = _derive_agenda(analyse.themes)
    vigilances = analyse.vigilances or list(_BASE_VIGILANCES)
    plan = {
        "resume": analyse.resume or "Résumé à compléter en séance.",
        "modules": modules,
        "agenda": agenda,
        "vigilances": vigilances,
    }
    return {
        "plan": plan,
        "queries": analyse.queries,
        "brief": analyse.brief,
    }


def _stub_prepare_payload() -> Dict[str, Any]:
    plan = {
        "resume": "(démo) résumé reconstruit",
        "modules": [
            "Ouverture et sécurisation du cadre",
            "Exploration structurelle",
            "Psychoéducation matérialiste",
        ],
        "agenda": [
            "Si surcharge → commencer par embodiment",
            "Temps fort : micro-levier concret",
            "Différer le reste sur une séance dédiée",
        ],
        "vigilances": [
            "Contraintes matérielles",
            "Accès au soin",
        ],
    }
    return {
        "ok": True,
        "plan": plan,
        "queries": [
            '"hypervigilance" contraintes matérielles clinique',
            '"interoception" alexithymie evidence based',
        ],
        "brief": "(démo) synthèse brève",
        "tokens": {"in": 0, "out": 0},
        "warnings": [],
    }


def _json_error(kind: str, message: str, status: int = 400) -> Tuple[Dict[str, Any], int]:
    return {"ok": False, "error": {"kind": kind, "message": message}}, status


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text.split()))


def _log_request(event: str, req_id: str, start: float, **extra: Any) -> None:
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    payload = {"event": event, "req_id": req_id, "elapsed_ms": elapsed_ms}
    payload.update({k: v for k, v in extra.items() if v is not None})
    LOGGER.info("pre_session.%s", event, extra=payload)


def _handle_openai_exception(exc: Exception) -> Tuple[Dict[str, Any], int]:
    status = getattr(exc, "status_code", None)
    if status is None and hasattr(exc, "status"):
        status = getattr(exc, "status")
    if status in (401, 403):
        return _json_error("auth", "Clé OpenAI invalide ou non autorisée.", 502)
    if status == 429:
        return _json_error("quota", "Quota OpenAI épuisé ou trop de requêtes.", 503)
    if status and 500 <= status < 600:
        return _json_error("upstream", "Service OpenAI indisponible.", 503)
    return _json_error("upstream", "Appel OpenAI impossible.", 502)


@bp.post("/prepare")
def prepare() -> Response:
    start = time.perf_counter()
    req_id = uuid4().hex[:12]
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        body, status = _json_error("invalid_request", "Requête JSON attendue.")
        response = jsonify(body)
        response.status_code = status
        return response

    mails_raw = str(payload.get("mails_raw") or "")
    patient = payload.get("patient")

    max_chars = _env_int("MAX_INPUT_CHARS", 24000)
    truncated_raw, truncated = _truncate(mails_raw, max_chars)

    if not truncated_raw.strip():
        body, status = _json_error("invalid_request", "Le champ mails_raw est requis.")
        response = jsonify(body)
        response.status_code = status
        return response

    warnings: List[str] = []
    if truncated:
        warnings.append(f"Le matériau a été tronqué à {max_chars} caractères.")

    tokens_in = _estimate_tokens(truncated_raw)

    openai_client = get_openai_client()
    use_stub = openai_client is None

    try:
        if openai_client is None:
            analyse = analyse_pre_session(truncated_raw)
            result = planifier_pre_session(analyse)
        else:
            analyse = analyse_pre_session(truncated_raw, client=openai_client)
            result = planifier_pre_session(analyse)
            use_stub = False
    except Exception as exc:  # pragma: no cover - robustesse
        if openai_client is not None:
            body, status = _handle_openai_exception(exc)
            response = jsonify(body)
            response.status_code = status
            _log_request(
                "prepare_error",
                req_id,
                start,
                chars_in=len(truncated_raw),
                patient=patient,
                truncated=truncated,
                error_kind=body["error"]["kind"],
            )
            return response
        LOGGER.exception("Analyse pré-séance impossible", extra={"req_id": req_id})
        body, status = _json_error("internal", "Impossible de préparer le plan.", 500)
        response = jsonify(body)
        response.status_code = status
        return response

    payload_out = {
        "ok": True,
        "plan": result["plan"],
        "queries": result.get("queries", []),
        "brief": result.get("brief", ""),
        "tokens": {"in": tokens_in, "out": 0},
        "warnings": warnings,
    }

    if use_stub:
        payload_out = _stub_prepare_payload()
        if warnings:
            payload_out["warnings"] = warnings
        payload_out["tokens"] = {"in": tokens_in, "out": 0}
        payload_out["plan"]["resume"] = payload_out["plan"].get("resume", "") or result["plan"].get("resume")
        if result.get("plan", {}).get("agenda"):
            payload_out["plan"]["agenda"] = result["plan"].get("agenda")
        if result.get("plan", {}).get("vigilances"):
            payload_out["plan"]["vigilances"] = result["plan"].get("vigilances")
        if result.get("plan", {}).get("modules"):
            payload_out["plan"]["modules"] = result["plan"].get("modules")
        if result.get("brief"):
            payload_out["brief"] = result["brief"]
        if result.get("queries"):
            payload_out["queries"] = result["queries"]

    response = jsonify(payload_out)
    _log_request(
        "prepare",
        req_id,
        start,
        chars_in=len(truncated_raw),
        patient=patient,
        truncated=truncated,
        use_stub=use_stub,
    )
    return response


def _format_plan_for_prompt(plan: Dict[str, Any]) -> str:
    lines: List[str] = []
    resume = plan.get("resume")
    if resume:
        lines.append(f"Résumé : {resume}")
    modules = [item for item in plan.get("modules", []) if item]
    if modules:
        lines.append("Modules prioritaires :")
        for module in modules:
            lines.append(f"- {module}")
    agenda = [item for item in plan.get("agenda", []) if item]
    if agenda:
        lines.append("")
        lines.append("Agenda prévisionnel :")
        for item in agenda:
            lines.append(f"- {item}")
    vigilances = [item for item in plan.get("vigilances", []) if item]
    if vigilances:
        lines.append("")
        lines.append("Vigilances :")
        for item in vigilances:
            lines.append(f"- {item}")
    return "\n".join(lines).strip()


def _clip_output(text: str) -> str:
    limit = _env_int("MAX_RETURN_CHARS", 24000)
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit]


def _build_prompt(plan: Dict[str, Any], mails_raw: str, brief: str, patient: Optional[str]) -> str:
    patient_label = patient or "la personne accompagnée"
    plan_text = _format_plan_for_prompt(plan)
    mails_excerpt = mails_raw.strip()
    prompt = textwrap.dedent(
        f"""
        Tu es un·e praticien·ne matérialiste, féministe et evidence-based.
        Prépare un déroulé de séance pré-thérapeutique pour {patient_label}.

        Contraintes éditoriales :
        - pas de psychanalyse ni d'interprétations symboliques ;
        - pas d'échelles chiffrées (0-10) ni de coaching individuel ;
        - proposer des pistes d'action concrètes, solidaires et collectivisantes ;
        - valider explicitement l'expérience de la personne ;
        - langue inclusive et accessible.

        Brief synthétique :
        {brief.strip() if brief else '(brief à compléter)'}

        Plan proposé :
        {plan_text or '(plan à construire avec l équipe)'}

        Contexte brut à garder en tête :
        {mails_excerpt or '(aucun mail fourni)'}

        Produit la réponse finale sous forme de déroulé prêt à l'emploi, structuré par sections.
        """
    ).strip()
    return _clip_output(prompt)


@bp.post("/generate")
def generate() -> Response:
    start = time.perf_counter()
    req_id = uuid4().hex[:12]
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        body, status = _json_error("invalid_request", "Requête JSON attendue.")
        response = jsonify(body)
        response.status_code = status
        return response

    mails_raw = str(payload.get("mails_raw") or "")
    plan = payload.get("plan") or {}
    patient = payload.get("patient") or None
    brief = payload.get("brief") or payload.get("summary") or ""

    if not isinstance(plan, dict):
        body, status = _json_error("invalid_request", "Plan invalide.")
        response = jsonify(body)
        response.status_code = status
        return response

    max_chars = _env_int("MAX_INPUT_CHARS", 24000)
    truncated_raw, truncated = _truncate(mails_raw, max_chars)

    prompt_text = _build_prompt(plan, truncated_raw, brief, patient)
    tokens_out = _estimate_tokens(prompt_text)

    payload_out = {
        "ok": True,
        "prompt": prompt_text,
        "tokens": {"in": _estimate_tokens(truncated_raw), "out": tokens_out},
        "warnings": [f"Le matériau a été tronqué à {max_chars} caractères."] if truncated else [],
    }

    response = jsonify(payload_out)
    _log_request(
        "generate",
        req_id,
        start,
        chars_in=len(truncated_raw),
        chars_out=len(prompt_text),
        truncated=truncated,
        patient=patient,
    )
    return response


__all__ = ["bp", "analyse_pre_session", "planifier_pre_session"]
