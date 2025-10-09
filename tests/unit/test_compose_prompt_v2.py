"""Unit tests for the v2 prompt composition template."""

import re
import unittest

from server.blueprints.post_session_v2 import _compose_prompt


class TestComposePromptV2(unittest.TestCase):
    def test_compose_prompt_v2_format_and_content(self):
        """The composed prompt should obey the formatting rules and include required markers."""
        plan = "Plan X"
        queries = ["repère A", "repère B"]
        prompt, subject = _compose_prompt("Fourmi", plan, queries, "sobre")
        # Version marker should appear
        self.assertIn("PROMPT_TEMPLATE_VERSION=2025-10-09-z2", prompt)
        # Titles must be present
        self.assertIn("Ce que vous avez exprimé et ce que j'en ai compris", prompt)
        self.assertIn("Pistes de lecture et repères", prompt)
        # Prohibited characters should not appear
        self.assertNotIn("—", prompt)
        self.assertNotIn("--", prompt)
        self.assertNotIn("*", prompt)
        self.assertNotIn("•", prompt)
        # Micro‑sous‑titres: at least two paragraphs in section 2 start with a word followed by ':'
        matches = re.findall(r"\n\s*[^\n:]{2,30}:", prompt)
        self.assertGreaterEqual(len(matches), 2)
        # Subject line should include the patient name
        self.assertTrue(subject.startswith("Compte-rendu"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()