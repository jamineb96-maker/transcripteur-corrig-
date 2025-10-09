"""Compositeur de prompt post‑séance.

Ce module rassemble la logique nécessaire pour agréger l'historique
clinique d'un·e patient·e, appliquer un scorING simple et produire un
prompt prêt à être envoyé à un modèle de langage tout en respectant le
contrat d'attribution entre patient et praticien.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional

from server.services.clinical_repo import ClinicalRepo


DEFAULT_MAX_TOKENS = 1400

DEFAULT_INCLUDE = {
    "segments": True,
    "milestones": True,
    "quotes": True,
    "contradictions": True,
    "contexts": True,
    "somatic": True,
    "trauma_profile": True,
    "unresolved_objectives": True,
}

SECTION_QUOTAS = {
    "segments": 600,
    "quotes": 150,
    "milestones": 150,
    "contradictions": 120,
    "contexts": 120,
    "somatic": 100,
    "trauma": 160,
    "meta": 40,
}

CONTRACT_BLOCK = """CONTRAT D’ATTRIBUTION — À RESPECTER STRICTEMENT
- N’écrivez jamais “vous avez dit …” pour des éléments issus d’observations/hypothèses du praticien.
- Réservez “vous avez dit …” uniquement aux citations directes du/de la patient·e, marquées comme telles.
- Les formulations du praticien doivent être introduites par “Je note… / J’observe… / Hypothèse prudente…”.
- Si l’attribution est incertaine, ne l’attribuez pas au/à la patient·e : classez-la comme observation du praticien.
- Avant d’émettre la version finale, effectuez un AUTOCHECK interne :
  * Pour chaque phrase contenant “vous avez”/“tu as”/“you said”, vérifiez qu’elle provient d’une citation patient.
  * Sinon, reformulez immédiatement en observation du praticien.
Ne listez pas ce contrôle dans la sortie au patient."""


class PromptComposerError(RuntimeError):
    """Erreur spécifique au compositeur."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class Candidate:
    """Représente un élément susceptible d'être inséré dans le prompt."""

    section: str
    content: str
    session: str | None = None
    topic: str | None = None
    speaker: str = "unknown"
    origin: str = "note"
    kind: str = "paraphrase"
    date: datetime | None = None
    meta: Dict[str, object] = field(default_factory=dict)
    score: float = 0.0

    def key_terms(self) -> set[str]:
        words = re.findall(r"[\wàâäéèêëîïôöùûüç]+", self.content.lower())
        return {word for word in words if len(word) > 2}


def estimate_tokens(text: str) -> int:
    """Estimation grossière du nombre de tokens."""

    if not text:
        return 0
    words = len(re.findall(r"\S+", text))
    return max(1, math.ceil(words * 1.2))


def redact_pii(text: str) -> str:
    """Masquage minimaliste des informations sensibles."""

    if not text:
        return ""
    masked = re.sub(r"\b([A-ZÉÈÎÏÂÄÔÖÙÛÜ][a-zéèàùâêîôûäëïöüç]{2,})\b", r"⟦\1⟧", text)
    masked = re.sub(r"\b\d{2,}[A-Z0-9]*\b", "⟦identifiant⟧", masked)
    masked = re.sub(r"\b\d{1,3} ?(?:rue|avenue|boulevard|impasse) [^,\n]+", "⟦adresse⟧", masked, flags=re.IGNORECASE)
    return masked


def _safe_list(payload: object, key: str) -> List[Mapping[str, object]]:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _parse_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d_%H%M", "%Y-%m-%d_%H", "%Y-%m-%d_%H-%M", "%Y-%m-%d_%f"):
        try:
            return datetime.strptime(value[: len(fmt)], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _session_date_from_path(path: str | None) -> Optional[datetime]:
    if not path:
        return None
    raw = path.split("/")[-1]
    return _parse_date(raw.split("_")[0])


def _exp_decay(reference: datetime, date: Optional[datetime]) -> float:
    if not date:
        return 0.1
    delta = max(0, (reference - date).days)
    return math.exp(-delta / 30.0)


def _jaccard(a: Candidate, b: Candidate) -> float:
    terms_a = a.key_terms()
    terms_b = b.key_terms()
    if not terms_a or not terms_b:
        return 0.0
    inter = len(terms_a & terms_b)
    union = len(terms_a | terms_b)
    return inter / union if union else 0.0


def _ensure_iterable(value: object) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    if isinstance(value, Mapping):
        return [str(item) for item in value.values() if item]
    if value:
        return [str(value)]
    return []


class PromptComposer:
    """Service de composition de prompt."""

    def __init__(self, repo: ClinicalRepo | None = None) -> None:
        self.repo = repo or ClinicalRepo()

    # ------------------------------------------------------------------
    def compose(
        self,
        slug: str,
        window: Mapping[str, object] | None = None,
        topics: Optional[Iterable[str]] = None,
        include: Optional[Mapping[str, object]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        strict_attribution: bool = True,
    ) -> Dict[str, object]:
        if not slug:
            raise PromptComposerError("missing_slug", "Le paramètre slug est requis.")

        self._patient_quote_lines: set[str] = set()

        include_flags = dict(DEFAULT_INCLUDE)
        if isinstance(include, Mapping):
            for key, value in include.items():
                if key in include_flags:
                    include_flags[key] = bool(value)

        topics = [t.strip().lower() for t in (topics or []) if t and str(t).strip()]

        sessions = self._resolve_window(slug, window)
        patient_meta = self.repo.read_patient_meta(slug)
        latest_plan = self._latest_plan(slug)

        source_payload = self._load_sources(slug, sessions)

        candidates = self._build_candidates(
            slug=slug,
            sessions=sessions,
            payload=source_payload,
            topics=topics,
            include=include_flags,
            latest_plan=latest_plan,
        )

        ranked = self._rank_candidates(candidates, sessions)
        deduped = self._deduplicate(ranked)

        sections = self._assemble_sections(deduped, include_flags)

        usage = self._measure_usage(sections)

        context_lines = self._build_context_section(patient_meta, sessions, latest_plan)

        prompt_lines = [CONTRACT_BLOCK, ""] + context_lines
        prompt_lines += self._build_patient_section(sections["patient"], sections)
        prompt_lines += self._build_clinician_section(sections["clinician"])
        prompt_lines += self._build_remaining_sections(sections, include_flags)
        prompt_lines += self._build_requests_section()

        prompt, warnings = self._lint_and_join(prompt_lines, strict_attribution)
        prompt_lines_after_lint = prompt.split("\n")

        total_tokens = estimate_tokens(prompt)
        if max_tokens and total_tokens > max_tokens:
            prompt = self._trim_prompt(prompt_lines_after_lint, max_tokens)
            total_tokens = estimate_tokens(prompt)

        usage["meta"] = total_tokens

        result = {
            "prompt": prompt,
            "usage": usage,
            "trace": self._build_trace(deduped),
        }
        if warnings:
            result["warnings"] = warnings
        return result

    # ------------------------------------------------------------------
    def _resolve_window(
        self, slug: str, window: Mapping[str, object] | None
    ) -> List[Dict[str, object]]:
        count = 6
        mode = "sessions"
        if isinstance(window, Mapping):
            mode = str(window.get("type") or "sessions")
            try:
                count = max(1, int(window.get("count", 6)))
            except Exception:
                count = 6

        sessions = self.repo.list_sessions(slug)
        enriched = []
        for handle in sessions:
            date = _session_date_from_path(handle.path)
            enriched.append({
                "handle": handle,
                "date": date or datetime.now(),
            })

        enriched.sort(key=lambda item: item["date"])
        if not enriched:
            return []

        if mode == "months":
            latest = enriched[-1]["date"]
            threshold = latest - timedelta(days=30 * count)
            return [item for item in enriched if item["date"] >= threshold]
        return enriched[-count:]

    def _load_sources(
        self, slug: str, sessions: List[Dict[str, object]]
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {}
        for name in (
            "index.json",
            "milestones.json",
            "quotes.json",
            "contradictions.json",
            "contexts.json",
            "somatic.json",
            "trauma_profile.json",
        ):
            try:
                payload[name] = self.repo.read_patient_file(slug, name)
            except Exception:
                payload[name] = None

        payload["sessions"] = []
        for item in sessions:
            handle = item.get("handle")
            if not handle:
                continue
            try:
                payload["sessions"].append(self.repo.read_session(slug, handle.path))
            except Exception:
                payload["sessions"].append({"path": handle.path, "files": {}})
        return payload

    def _build_candidates(
        self,
        slug: str,
        sessions: List[Dict[str, object]],
        payload: Mapping[str, object],
        topics: List[str],
        include: Mapping[str, bool],
        latest_plan: Optional[Dict[str, object]],
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        topic_counts: MutableMapping[str, int] = defaultdict(int)

        latest_date = sessions[-1]["date"] if sessions else None

        for entry, session_meta in zip(payload.get("sessions", []), sessions):
            files = entry.get("files", {}) if isinstance(entry, Mapping) else {}
            segments_payload = files.get("segments.json") if isinstance(files, Mapping) else None
            session_path = entry.get("path") if isinstance(entry, Mapping) else None
            session_date = session_meta.get("date") if isinstance(session_meta, Mapping) else None
            for segment in _safe_list(segments_payload, "segments"):
                topic = str(segment.get("topic") or "")
                if topics and topic.lower() not in topics:
                    continue
                text = redact_pii(str(segment.get("text") or ""))
                if not text:
                    continue
                speaker = str(segment.get("speaker") or "patient")
                kind = str(segment.get("kind") or "paraphrase")
                origin = str(segment.get("origin") or "transcript")
                candidate = Candidate(
                    section="segments",
                    content=text,
                    session=session_path,
                    topic=topic,
                    speaker=speaker or "unknown",
                    origin=origin,
                    kind=kind,
                    date=session_date,
                    meta={
                        "date": segment.get("date") or (session_date.strftime("%Y-%m-%d") if session_date else None),
                        "topic_key": topic.lower() if topic else None,
                    },
                )
                candidates.append(candidate)
                if topic:
                    topic_counts[topic.lower()] += 1

        quotes_payload = payload.get("quotes.json")
        if include.get("quotes"):
            for quote in _safe_list(quotes_payload, "quotes"):
                topic = str(quote.get("topic") or "")
                if topics and topic and topic.lower() not in topics:
                    continue
                text = redact_pii(str(quote.get("text") or ""))
                if not text:
                    continue
                date = _parse_date(str(quote.get("date") or ""))
                candidate = Candidate(
                    section="quotes",
                    content=text,
                    topic=topic,
                    date=date,
                    speaker=str(quote.get("speaker") or "patient"),
                    origin=str(quote.get("origin") or "note"),
                    kind=str(quote.get("kind") or "quote"),
                    meta={
                        "date": quote.get("date"),
                        "topic_key": topic.lower() if topic else None,
                        "reason": "patient-quote",
                    },
                )
                candidates.append(candidate)

        if include.get("milestones"):
            for milestone in _safe_list(payload.get("milestones.json"), "milestones"):
                text = redact_pii(str(milestone.get("note") or ""))
                if not text:
                    continue
                date = _parse_date(str(milestone.get("date") or ""))
                candidates.append(
                    Candidate(
                        section="milestones",
                        content=text,
                        date=date,
                        speaker=str(milestone.get("speaker") or "clinician"),
                        origin="note",
                        kind=str(milestone.get("kind") or "observation"),
                        meta={"reason": "recent-milestone"},
                    )
                )

        if include.get("contradictions"):
            for contradiction in _safe_list(payload.get("contradictions.json"), "contradictions"):
                label = contradiction.get("label") or contradiction.get("title") or "Contradiction"
                details = contradiction.get("details") or contradiction.get("examples") or []
                if isinstance(details, str):
                    text = details
                else:
                    text = "; ".join(str(item) for item in details if item)
                text = redact_pii(str(text))
                candidate = Candidate(
                    section="contradictions",
                    content=f"{label}: {text}".strip(),
                    topic=str(contradiction.get("topic") or ""),
                    speaker=str(contradiction.get("speaker") or "clinician"),
                    origin="note",
                    kind=str(contradiction.get("kind") or "hypothesis"),
                    meta={"reason": "contradiction"},
                )
                candidates.append(candidate)

        if include.get("contexts"):
            contexts_payload = payload.get("contexts.json")
            typical = contexts_payload.get("typical_situations") if isinstance(contexts_payload, Mapping) else []
            transformations = contexts_payload.get("transformations") if isinstance(contexts_payload, Mapping) else []
            for note in _ensure_iterable(typical):
                candidates.append(
                    Candidate(
                        section="contexts",
                        content=redact_pii(str(note)),
                        speaker="clinician",
                        origin="note",
                        meta={"reason": "context"},
                    )
                )
            for note in _ensure_iterable(transformations):
                candidates.append(
                    Candidate(
                        section="contexts",
                        content=redact_pii(str(note)),
                        speaker="clinician",
                        origin="note",
                        meta={"reason": "context"},
                    )
                )

        if include.get("somatic"):
            somatic_payload = payload.get("somatic.json") or {}
            for key in ("resources", "tensions", "patterns"):
                values = somatic_payload.get(key) if isinstance(somatic_payload, Mapping) else []
                for value in values or []:
                    text = redact_pii(str(value))
                    if text:
                        candidates.append(
                            Candidate(
                                section="somatic",
                                content=f"{key}: {text}",
                                speaker="clinician",
                                origin="note",
                                meta={"reason": "somatic"},
                            )
                        )

        if include.get("trauma_profile"):
            trauma_payload = payload.get("trauma_profile.json") or {}
            for summary in self._summarize_trauma_profile(trauma_payload):
                candidates.append(
                    Candidate(
                        section="trauma",
                        content=summary,
                        speaker="clinician",
                        origin="note",
                        kind="hypothesis",
                        meta={"reason": "trauma-pattern"},
                    )
                )

        if include.get("unresolved_objectives") and latest_plan:
            for line in latest_plan.get("undone", []):
                text = redact_pii(str(line))
                if text:
                    candidates.append(
                        Candidate(
                            section="unresolved_objectives",
                            content=text,
                            speaker="clinician",
                            origin="plan",
                            meta={"reason": "plan"},
                        )
                    )

        # Ajuster les scores en fonction des occurrences thématiques
        for candidate in candidates:
            topic_score = 0.0
            if candidate.topic:
                topic_key = candidate.topic.lower()
                topic_score = 0.2 * topic_counts.get(topic_key, 0)
                candidate.meta["topic_count"] = topic_counts.get(topic_key, 0)
                if candidate.section == "segments":
                    recent_flag = ""
                    if candidate.date and latest_date:
                        delta = (latest_date - candidate.date).days
                        if delta <= 45:
                            recent_flag = "recent"
                    recurrent_flag = "recurrent" if topic_counts.get(topic_key, 0) > 1 else ""
                    parts = [flag for flag in (recent_flag, recurrent_flag) if flag]
                    if parts:
                        candidate.meta["reason"] = "+".join(parts)
            candidate.score += topic_score

        return candidates

    def _summarize_trauma_profile(self, payload: Mapping[str, object]) -> List[str]:
        summaries: List[str] = []
        patterns = payload.get("core_patterns") if isinstance(payload, Mapping) else []
        if not isinstance(patterns, list):
            return summaries
        for item in patterns:
            if not isinstance(item, Mapping):
                continue
            label = str(item.get("pattern") or item.get("label") or "Pattern")
            triggers = ", ".join(item.get("triggers", []) or []) if isinstance(item.get("triggers"), list) else str(item.get("triggers") or "")
            protections = ", ".join(item.get("protections", []) or []) if isinstance(item.get("protections"), list) else str(item.get("protections") or "")
            signals = ", ".join(item.get("signals", []) or []) if isinstance(item.get("signals"), list) else str(item.get("signals") or "")
            windows = ", ".join(item.get("feasibility_windows", []) or []) if isinstance(item.get("feasibility_windows"), list) else str(item.get("feasibility_windows") or "")
            summary = (
                f"{label}: déclencheurs {triggers or 'n.d.'}, stratégies de protection {protections or 'n.d.'}, "
                f"signaux corporels {signals or 'n.d.'}, fenêtres de faisabilité {windows or 'n.d.'}."
                " Hypothèse clinique, à confirmer."
            )
            summaries.append(redact_pii(summary))
        return summaries

    def _rank_candidates(self, candidates: List[Candidate], sessions: List[Dict[str, object]]) -> List[Candidate]:
        if not candidates:
            return []
        reference = sessions[-1]["date"] if sessions else datetime.now()
        for candidate in candidates:
            candidate.score += _exp_decay(reference, candidate.date)
            if candidate.kind == "hypothesis":
                candidate.score += 0.1
            if candidate.section == "contradictions":
                candidate.score += 0.2
            if candidate.section == "milestones":
                candidate.score += 0.15
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _deduplicate(self, candidates: List[Candidate]) -> List[Candidate]:
        kept: List[Candidate] = []
        seen_topics: MutableMapping[str, int] = defaultdict(int)
        for candidate in candidates:
            if candidate.topic:
                seen_topics[candidate.topic.lower()] += 1
                if seen_topics[candidate.topic.lower()] > 3:
                    continue
            duplicate = False
            for existing in kept:
                if candidate.section != existing.section:
                    continue
                if _jaccard(candidate, existing) >= 0.75:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(candidate)
        return kept

    def _assemble_sections(
        self, candidates: List[Candidate], include: Mapping[str, bool]
    ) -> Dict[str, List[Candidate]]:
        sections: Dict[str, List[Candidate]] = {
            "segments": [],
            "quotes": [],
            "milestones": [],
            "contradictions": [],
            "contexts": [],
            "somatic": [],
            "trauma": [],
            "unresolved_objectives": [],
            "patient": [],
            "clinician": [],
        }

        for candidate in candidates:
            if not include.get(candidate.section, True) and candidate.section not in {"unresolved_objectives"}:
                continue
            sections.setdefault(candidate.section, []).append(candidate)
            bucket = "patient"
            speaker = (candidate.speaker or "").lower()
            kind = (candidate.kind or "").lower()
            if speaker not in {"patient"}:
                bucket = "clinician"
            if kind == "hypothesis":
                bucket = "clinician"
            if speaker == "unknown" and bucket == "patient":
                bucket = "clinician"
            sections[bucket].append(candidate)
        return sections

    def _measure_usage(self, sections: Mapping[str, List[Candidate]]) -> Dict[str, int]:
        usage: Dict[str, int] = {
            "segments": sum(estimate_tokens(item.content) for item in sections.get("segments", [])),
            "milestones": sum(estimate_tokens(item.content) for item in sections.get("milestones", [])),
            "quotes": sum(estimate_tokens(item.content) for item in sections.get("quotes", [])),
            "contradictions": sum(estimate_tokens(item.content) for item in sections.get("contradictions", [])),
            "contexts": sum(estimate_tokens(item.content) for item in sections.get("contexts", [])),
            "somatic": sum(estimate_tokens(item.content) for item in sections.get("somatic", [])),
            "trauma": sum(estimate_tokens(item.content) for item in sections.get("trauma", [])),
        }
        return usage

    def _build_context_section(
        self,
        meta: Mapping[str, object],
        sessions: List[Dict[str, object]],
        latest_plan: Optional[Dict[str, object]],
    ) -> List[str]:
        slug = meta.get("slug") or ""
        display = meta.get("display_name") or meta.get("displayName") or slug
        period = f"{len(sessions)} séances" if sessions else "aucune séance enregistrée"
        objectives = latest_plan.get("undone", []) if latest_plan else []
        cleaned_objectives = [str(item).strip("- []") for item in objectives]
        objective_line = ", ".join(filter(None, cleaned_objectives)) if cleaned_objectives else "n.d."
        return [
            "Contexte clinique minimal",
            f"Patient·e: {display or slug}, période: {period}, objectifs en cours: {objective_line or 'n.d.'}",
            "",
        ]

    def _build_patient_section(
        self, candidates: List[Candidate], sections: Mapping[str, List[Candidate]]
    ) -> List[str]:
        lines = ["Ce que la personne a dit"]
        quota = SECTION_QUOTAS.get("segments", 600)
        used = 0
        allowed_lines: set[str] = set()
        output: List[str] = []
        for candidate in candidates:
            tokens = estimate_tokens(candidate.content)
            if used + tokens > quota:
                truncated = candidate.content[:280].rstrip() + " …"
                entry = self._format_patient_line(candidate, truncated)
                output.append(entry)
                break
            entry = self._format_patient_line(candidate, candidate.content)
            output.append(entry)
            used += tokens
            if "Vous avez dit" in entry:
                allowed_lines.add(entry.strip())
        if not output:
            output.append("- (aucune donnée patient disponible)")
        lines.extend(output)
        lines.append("")
        self._patient_quote_lines = allowed_lines
        return lines

    def _format_patient_line(self, candidate: Candidate, text: str) -> str:
        date = ""
        if candidate.meta.get("date"):
            date = f" [{candidate.meta['date']}]"
        elif candidate.date:
            date = f" [{candidate.date.strftime('%d-%m')}]"
        badge = "[P-QUOTE]" if candidate.kind == "quote" else "[P-PARA]"
        if candidate.kind == "quote":
            return f"- {badge} Vous avez dit : « {text.strip()} »{date}".replace("  ", " ")
        if candidate.kind == "paraphrase":
            return f"- {badge} Reformulation: {text.strip()}{date}"
        return f"- {badge} {text.strip()}{date}"

    def _build_clinician_section(self, candidates: List[Candidate]) -> List[str]:
        lines = ["Observations / hypothèses du praticien"]
        if not candidates:
            lines.append("- [CL-HYP] Aucun élément praticien disponible")
            lines.append("")
            return lines
        quota = SECTION_QUOTAS.get("milestones", 150)
        used = 0
        for candidate in candidates:
            tokens = estimate_tokens(candidate.content)
            if used + tokens > quota:
                lines.append("- [CL-HYP] Je note… (contenu tronqué) …")
                break
            prefix = "Hypothèse prudente" if candidate.kind == "hypothesis" else "Je note"
            lines.append(f"- [CL-HYP] {prefix} : {candidate.content.strip()}")
            used += tokens
        lines.append("")
        return lines

    def _build_remaining_sections(
        self,
        sections: Mapping[str, List[Candidate]],
        include: Mapping[str, bool],
    ) -> List[str]:
        lines: List[str] = []
        mapping = [
            ("Éléments saillants récents (segments résumés)", "segments"),
            ("Contradictions actives", "contradictions"),
            ("Repères de transformation", "milestones"),
            ("Citations cliniques", "quotes"),
            ("Profil traumatique (synthèse prudente)", "trauma"),
            ("Mémoire somatique", "somatic"),
            ("Contextes cliniques", "contexts"),
        ]
        for title, key in mapping:
            if not include.get(key, True):
                continue
            items = sections.get(key, [])
            if not items:
                continue
            lines.append(title)
            quota = SECTION_QUOTAS.get(key, 120)
            used = 0
            for candidate in items:
                text = candidate.content.strip()
                if key == "segments":
                    topic = candidate.topic or "thème"
                    date = ""
                    if candidate.meta.get("date"):
                        try:
                            parsed = _parse_date(str(candidate.meta.get("date")))
                        except Exception:
                            parsed = None
                        if parsed:
                            date = f" [{parsed.strftime('%d-%m')}]"
                    text = f"{topic}: {text}{date}".strip()
                elif key == "quotes":
                    date = ""
                    if candidate.meta.get("date"):
                        date = f" [{candidate.meta['date']}]"
                    text = f"« {text} »{date}".strip()
                elif key == "milestones":
                    prefix = candidate.meta.get("date") or (
                        candidate.date.strftime("%d-%m") if candidate.date else "repère"
                    )
                    text = f"{prefix}: {text}".strip()
                tokens = estimate_tokens(text)
                if used + tokens > quota:
                    text = text[:280].rstrip() + " …"
                lines.append(f"- {text}")
                used += tokens
                if used >= quota:
                    break
            lines.append("")
        unresolved = sections.get("unresolved_objectives", [])
        if unresolved and include.get("unresolved_objectives", True):
            lines.append("Objectifs non résolus")
            for item in unresolved:
                cleaned = item.content.replace("- [ ]", "").strip()
                lines.append(f"- {cleaned}")
            lines.append("")
        return lines

    def _build_requests_section(self) -> List[str]:
        return [
            "Demandes pour la suite",
            "1. Aider à formuler un plan post-séance réaliste dans la fenêtre de faisabilité actuelle",
            "2. Proposer 2-3 pistes psychoéducatives alignées avec les thèmes récurrents",
            "Contraintes: pas de pathologisation, pas de injonctions performatives, formulations descriptives",
        ]

    def _lint_and_join(self, lines: List[str], strict: bool) -> tuple[str, List[str]]:
        text = "\n".join(lines).strip()
        warnings: List[str] = []
        if not strict:
            return text, warnings
        pattern = re.compile(r"\b(vous avez|tu as|you said)\b", re.IGNORECASE)
        parts = text.split("\n")
        contract_limit = 0
        for idx, line in enumerate(parts):
            if not line.strip():
                contract_limit = idx
                break
        for index, line in enumerate(parts):
            if index <= contract_limit:
                continue
            if not pattern.search(line):
                continue
            if line.strip() in getattr(self, "_patient_quote_lines", set()):
                continue
            corrected = pattern.sub("Je note que", line, count=1)
            if corrected != line:
                parts[index] = corrected
                warnings.append(
                    "Correction automatique d'une attribution sensible: remplacement par \"Je note que\"."
                )
        return "\n".join(parts).strip(), warnings

    def _trim_prompt(self, lines: List[str], max_tokens: int) -> str:
        parts = [line for line in lines if line is not None]
        while parts and estimate_tokens("\n".join(parts)) > max_tokens:
            parts.pop()
        return "\n".join(parts).strip()

    def _build_trace(self, candidates: List[Candidate]) -> List[Dict[str, object]]:
        trace = []
        for candidate in candidates:
            trace.append(
                {
                    "source": candidate.section,
                    "session": candidate.session,
                    "topic": candidate.topic,
                    "speaker": candidate.speaker,
                    "kind": candidate.kind,
                    "reason": candidate.meta.get("reason") or "scored",
                }
            )
        return trace

    def _latest_plan(self, slug: str) -> Optional[Dict[str, object]]:
        sessions = self.repo.list_sessions(slug)
        for handle in reversed(sessions):
            session = self.repo.read_session(slug, handle.path)
            plan = session.get("files", {}).get("plan.txt") if isinstance(session, Mapping) else None
            if not plan:
                continue
            undone = [
                line.strip()
                for line in str(plan).splitlines()
                if line.strip().startswith("- [ ]")
            ]
            return {"session": handle.path, "raw": plan, "undone": undone}
        return None

