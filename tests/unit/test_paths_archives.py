"""Unit tests for the patient archives path resolution."""

"""Unit tests for the patient archives path resolution."""

import unittest
from pathlib import Path
from unittest.mock import patch

from server.services.paths import ensure_patient_subdir


class TestPathsArchives(unittest.TestCase):
    def test_ensure_patient_subdir_creates_and_returns_expected_path(self):
        # Create a temporary directory
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Patch patients_repo.resolve_patient_archive to return a deterministic path
            with patch(
                "server.services.patients_repo.resolve_patient_archive",
                lambda slug: str(tmp_path / slug),
                create=True,
            ):
                sub = ensure_patient_subdir("Fourmi", "notes")
                # Path should exist
                self.assertTrue(sub.exists())
                # It should end with the expected slugified patient name and subdirectory
                tail = Path(str(sub).lower()).parts[-2:]
                self.assertEqual(tail, ("fourmi", "notes"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()