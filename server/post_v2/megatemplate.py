"""Mega prompt assembly for post-session v2."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List

from .schemas import (
    EvidenceItemLocal,
    EvidenceItemWeb,
    KnowledgePack,
    MegaPromptBundle,
    SessionFacts,
    TokenEstimator,
)


def _log_event(event: str, payload: Dict[str, object]) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    record.update(payload)
    try:
        journal_path = Path(__file__).resolve().parents[1] / "library" / "store" / "journal.log"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover
        pass


def _serialize_facts(facts: SessionFacts) -> str:
    return json.dumps(facts.to_dict(), ensure_ascii=False, indent=2)


def _format_local_items(items: Iterable[EvidenceItemLocal]) -> str:
    lines: List[str] = []
    for item in items:
        lines.append(
            f"- {item.title} (doc_id={item.doc_id}, pages={item.pages}, niveau={item.evidence_level}, année={item.year})\n  Extrait: {item.extract}"
        )
    return "\n".join(lines) if lines else "(Aucune évidence locale sélectionnée)"


def _format_web_items(items: Iterable[EvidenceItemWeb]) -> str:
    lines: List[str] = []
    for item in items:
        lines.append(
            f"- {item.title} — {item.outlet} ({item.date})\n  Citation: {item.quote}\n  Claim: {item.claim}\n  URL: {item.url}\n  Fiabilité: {item.reliability_tag}"
        )
    return "\n".join(lines) if lines else "(Aucune évidence web retenue)"


def _format_knowledge_pack(pack: KnowledgePack) -> str:
    axes_lines = []
    for axis in pack.axes:
        citations = ", ".join(
            f"{ref.type}:{ref.ref}{' [' + ref.pages + ']' if ref.pages else ''}" if ref.url is None else f"{ref.type}:{ref.ref} ({ref.url})"
            for ref in axis.citations
        )
        phrases = "\n    - ".join(axis.phrases_appui)
        axes_lines.append(
            f"* {axis.label}\n  Rationale: {axis.rationale}\n    - {phrases}\n  Citations: {citations or 'aucune'}"
        )
    citations_lines = [
        f"- {c.short} ({c.source})" + (f" — {c.url}" if c.url else "") + (f" – p.{c.pages}" if c.pages else "")
        for c in pack.citations_candidates
    ]
    hypotheses = "\n- ".join(pack.hypotheses_situees)
    pistes = "\n- ".join(pack.pistes_regulation)
    return (
        "Axes:\n" + "\n".join(axes_lines)
        + "\n\nCitations candidates:\n" + ("\n".join(citations_lines) if citations_lines else "- aucune")
        + "\n\nHypothèses situées:\n- " + hypotheses
        + "\n\nPistes de régulation:\n- " + pistes
    )


def _build_system_block() -> str:
    return (
        "=== SYSTEM ===\n"
        "Tu es un rédacteur clinique matérialiste et critique. Refus explicite de la psychanalyse,"
        " pas d'injonctions comportementales, pas de moraline. Respect strict du style Za et de la ban-list."
    )


def _build_context_block(patient: str, date: str, facts: SessionFacts, transcript: str) -> str:
    return (
        "=== CONTEXT ===\n"
        f"Patient: {patient} — Date: {date}\n"
        f"SessionFacts: {_serialize_facts(facts)}\n"
        "Transcription intégrale (délimitée):\n"
        "<<<TRANSCRIPTION WHISPER COMPLÈTE>>>\n"
        f"{transcript}\n"
        "<<<FIN TRANSCRIPTION>>>"
    )


def _build_evidence_block(local_items: List[EvidenceItemLocal], web_items: List[EvidenceItemWeb], kp: KnowledgePack) -> str:
    return (
        "=== EVIDENCE ===\n"
        "[Local]\n"
        f"{_format_local_items(local_items)}\n\n"
        "[Web]\n"
        f"{_format_web_items(web_items)}\n\n"
        "[Knowledge Pack]\n"
        f"{_format_knowledge_pack(kp)}"
    )


def _build_task_block() -> str:
    return (
        "=== TASK ===\n"
        "Rédiger le mail récapitulatif final en quatre sections Za : ouverture déontique, écoute, pistes situées, suites concrètes."
        " Toujours expliciter le niveau de preuve, ne citer qu'une ou deux sources pertinentes maximum."
        " Mentionner l'incertitude lorsque nécessaire et refuser toute injonction comportementale."
    )


def _build_qa_block() -> str:
    return (
        "=== QA-CHECKS ===\n"
        "- Vérifier l'absence totale des termes bannis (observance, compliance, psychanalyse, etc.).\n"
        "- Refuser tout ton infantilisant et toute prescription comportementale.\n"
        "- Confirmer la cohérence du style Za (phrases longues mais lisibles, pas de listes scolaires).\n"
        "- Si les sources sont jugées insuffisantes, répondre explicitement 'INSUFFISANT'."
    )


def _build_fail_safes_block() -> str:
    return (
        "=== FAIL-SAFES ===\n"
        "- Si le rendu ressemble à une IA générique, régénérer avec un ancrage plus matérialiste.\n"
        "- Si le budget de tokens menace d'être dépassé, suggérer de placer la transcription en annexe mais ne jamais la tronquer ici.\n"
        "- Si des contradictions internes apparaissent, prioriser la transparence sur les incertitudes."
    )


def assemble_megaprompt(
    transcript_full: str,
    session_facts: SessionFacts,
    local_items: List[EvidenceItemLocal],
    web_items: List[EvidenceItemWeb],
    kp: KnowledgePack,
    style_profile_text: str,
    token_estimator: TokenEstimator,
) -> MegaPromptBundle:
    start = time.perf_counter()
    style_block = "=== STYLE_PROFILE ===\n" + style_profile_text
    system_block = _build_system_block()
    context_block = _build_context_block(session_facts.patient, session_facts.date, session_facts, transcript_full)
    evidence_block = _build_evidence_block(local_items, web_items, kp)
    task_block = _build_task_block()
    qa_block = _build_qa_block()
    fail_block = _build_fail_safes_block()
    blocks = [system_block, context_block, evidence_block, task_block, qa_block, fail_block, style_block]
    full_prompt = "\n\n".join(blocks)
    token_estimate = int(token_estimator(full_prompt)) if callable(token_estimator) else len(full_prompt)
    threshold = int(os.getenv("PROMPT_MAX_TOKENS_ESTIMATE", "180000") or 180000)
    token_warning = token_estimate > threshold
    if token_warning:
        warning = f"*** AVERTISSEMENT: estimation tokens {token_estimate} > seuil {threshold}.***\n"
        full_prompt = warning + full_prompt
    bundle = MegaPromptBundle(
        token_estimate=token_estimate,
        system_block=system_block,
        context_block=context_block,
        evidence_block=evidence_block,
        task_block=task_block,
        qa_checks_block=qa_block,
        fail_safes_block=fail_block,
        style_profile_block=style_block,
        full_prompt=full_prompt,
        token_warning=token_warning,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event(
        "post_v2_megaprompt",
        {
            "token_estimate": token_estimate,
            "size_local": len(local_items),
            "size_web": len(web_items),
            "ms": duration_ms,
            "token_warning": token_warning,
        },
    )
    return bundle


__all__ = ["assemble_megaprompt"]
