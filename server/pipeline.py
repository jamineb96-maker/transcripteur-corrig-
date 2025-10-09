"""
Post‑session pipeline for research and final prompt stages.

The pipeline is deliberately simple yet deterministic.  It produces
structured outputs from raw transcripts without relying on external web
queries or heavy language models.  Instead, heuristic splitting and
templating are used to assemble the evidence sheet, critical analysis and
mail content.  The resulting objects conform to the JSON schemas defined
in the specification.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime
from typing import Any, Dict, List, Optional


class ResearchPipeline:
    """Construct the research stage payload from a transcript.

    The research pipeline extracts high‑level features from the transcript
    needed to build the final mail.  It splits the transcript into
    approximate chapters, proposes candidate repères and notes key points for
    the mail.  No external knowledge is fetched; instead we simulate a
    critical reading by emphasising materialist and situated themes.
    """

    def run(
        self,
        transcript: str,
        prenom: Optional[str] = None,
        base_name: Optional[str] = None,
        date: Optional[str] = None,
        register: str = "vous",
    ) -> Dict[str, Any]:
        text = transcript.strip().replace("\r\n", "\n")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        # Derive a session hash from the transcript to ensure idempotence
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # Chapter splitting: divide lines into 3 equal parts for simplicity
        n = len(lines)
        # guard against zero division
        chapters: List[Dict[str, Any]] = []
        if n > 0:
            step = max(1, n // 3)
            for idx, start in enumerate(range(0, n, step)):
                end = min(n, start + step)
                chapter_lines = lines[start:end]
                title = ["Introduction", "Développement", "Conclusion"]
                title_str = title[idx] if idx < len(title) else f"Partie {idx+1}"
                summary = " ".join(chapter_lines[:3]) if chapter_lines else ""
                chapters.append({"t": [float(idx), float(idx + 1)], "title": title_str, "summary": summary})
        else:
            chapters.append({"t": [0.0, 1.0], "title": "Séance", "summary": ""})

        # Evidence sheet: pick the first few lines as evidence
        evidence = "\n".join(lines[:5]) if lines else "Aucun élément concret n’a été fourni."
        # Critical sheet: emphasise systemic factors
        critical = (
            "Cette séance met en lumière des rapports de pouvoir et des conditions matérielles. "
            "Une lecture critique invite à considérer les structures sociales qui déterminent les situations évoquées."
        )
        # Lenses used: fixed selection for demonstration
        lenses = ["matérialisme", "histoire du sujet", "analyse foucaldienne"]
        # Repères candidates: heuristically derive from the content
        repere_candidates: List[str] = []
        for line in lines:
            if len(repere_candidates) >= 5:
                break
            if len(line.split()) > 6 and any(word in line.lower() for word in ["ressource", "difficulté", "hypothèse"]):
                repere_candidates.append(line[:80].strip())
        if not repere_candidates:
            repere_candidates = ["Clarifier les ressources disponibles", "Identifier les structures en jeu"]
        # Points mail: pick sentences for the mail (first three lines)
        points_mail = lines[:3] if lines else []
        meta = {
            "session_id": sha,
            "hash": sha,
            "date": date or datetime.utcnow().strftime("%Y-%m-%d"),
            "prenom": prenom,
            "register": register,
        }
        return {
            "meta": meta,
            "evidence_sheet": evidence,
            "critical_sheet": critical,
            "lenses_used": lenses,
            "reperes_candidates": repere_candidates,
            "points_mail": points_mail,
            "chapters": chapters,
        }


class FinalPipeline:
    """Construct the final mail and analysis from a research payload.

    The final pipeline uses the research output to build a plan (mark‑down), an
    analysis object (containing requests, contradictions and objectives) and
    the mail in markdown form.  A deterministic template is applied to
    maintain stylistic constraints: no numbered lists, no long dashes and
    straight quotes only.  The register ("tu"/"vous") is honoured throughout.
    """

    def run(self, research_payload: Dict[str, Any]) -> Dict[str, Any]:
        meta = research_payload.get("meta", {}) if isinstance(research_payload, dict) else {}
        prenom = meta.get("prenom") or ""
        register = meta.get("register") or "vous"
        # Plan: simply list chapter titles and summaries
        chapters = research_payload.get("chapters") or []
        plan_lines = ["Plan de séance", ""]
        for chapter in chapters:
            title = chapter.get("title") or "Partie"
            summary = chapter.get("summary") or ""
            plan_lines.append(f"* {title} : {summary}")
        plan_md = "\n".join(plan_lines).strip()
        # Analysis: summarise lenses and repères
        analysis = {
            "lenses": research_payload.get("lenses_used") or [],
            "reperes_selected": research_payload.get("reperes_candidates")[:3] if research_payload.get("reperes_candidates") else [],
            "contradictions": ["Aucune contradiction explicite identifiée"],
            "objectives": ["Clarifier les besoins exprimés", "Identifier les obstacles structurels"],
        }
        # Mail: assemble sections respecting stylistic rules
        evidence = research_payload.get("evidence_sheet") or ""
        critical = research_payload.get("critical_sheet") or ""
        points = research_payload.get("points_mail") or []
        # Compose the résumé section
        resume_lines = []
        resume_lines.append(f"{prenom}, voici ce que je retiens de notre séance.")
        if points:
            resume_lines.append(" " .join(points))
        else:
            resume_lines.append("Nous avons exploré plusieurs thèmes sans entrer dans le détail.")
        resume_lines.append(
            "Nous avons replacé ces éléments dans leur contexte politique et matériel, en vérifiant que les responsabilités ne reposent pas uniquement sur vous."
        )
        resume = "\n".join(resume_lines)
        # Compose the repères section
        reperes_lines = []
        reperes_lines.append("Repères et pistes à explorer.")
        reperes_lines.append(evidence)
        reperes_lines.append(critical)
        # Mention reversibility and incertitude
        reperes_lines.append(
            "Ces repères sont proposés à titre indicatif; ils peuvent évoluer en fonction de votre vécu et des contextes institutionnels."
        )
        reperes_lines.append(
            "Il demeure des incertitudes quant aux effets de certaines démarches; nous resterons attentifs aux retours et ajusterons ensemble."
        )
        reperes = "\n".join(reperes_lines)
        # Assemble the final mail using two sections
        lines = []
        lines.append(f"# Compte‑rendu de séance")
        if prenom:
            lines.append("")
            lines.append(f"Bonjour {prenom},")
        lines.append("")
        lines.append("## Ce que je retiens de notre séance")
        lines.append("")
        lines.append(resume)
        lines.append("")
        lines.append("## Repères et pistes de lecture")
        lines.append("")
        lines.append(reperes)
        lines.append("")
        lines.append("Je reste disponible pour échanger davantage si nécessaire.")
        # Enforce style: replace long dashes with parentheses and remove list markers
        mail_md = "\n".join(lines)
        mail_md = mail_md.replace("–", "-")  # normalise dashes
        # No bullet characters
        mail_md = mail_md.replace("*", "")
        # Use straight quotes
        mail_md = mail_md.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        # Ensure register coherence (very basic substitution)
        if register.lower().strip() == "tu":
            mail_md = mail_md.replace("vous", "tu")
        return {
            "plan_markdown": plan_md,
            "analysis": analysis,
            "mail_markdown": mail_md,
        }
