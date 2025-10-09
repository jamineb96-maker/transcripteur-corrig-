"""Unit tests for the audio chunker.

These tests ensure that the chunker produces the expected number
of files and respects the ordering.  External dependencies on
``ffprobe`` and ``ffmpeg`` are monkeypatched to avoid requiring
those binaries during testing.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from server.services import audio_chunker


class TestAudioChunker(unittest.TestCase):
    def test_chunk_audio_with_mocked_ffmpeg(self):
        # Create a temporary directory and dummy input file
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_file = tmp_path / "input.mp3"
            input_file.write_bytes(b"dummy audio")

            # Mock duration to simulate a 1‑hour recording
            with patch(
                "server.services.audio_chunker.ffprobe_duration_seconds",
                lambda p: 3600.0,
            ):
                created_paths = []

                def fake_run(cmd, check=True):  # pragma: no cover
                    out_path = Path(cmd[-1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"chunk")
                    created_paths.append(out_path)
                    return None

                with patch("server.services.audio_chunker.subprocess.run", fake_run):
                    out_dir = tmp_path / "chunks"
                    parts = audio_chunker.chunk_audio(input_file, out_dir, chunk_seconds=1800)
                    # Expect two chunks
                    self.assertEqual(len(parts), 2)
                    names = [p.name for p in parts]
                    self.assertEqual(names, ["part_000.wav", "part_001.wav"])
                    for p in parts:
                        self.assertTrue(p.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()