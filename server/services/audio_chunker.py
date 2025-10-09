"""Utility functions for splitting large audio files into chunks.

These helpers wrap `ffprobe` and `ffmpeg` commands via Python's
``subprocess`` module to determine the duration of an audio file and
to cut it into uniform segments.  They are designed to work on
both Windows and Linux without relying on a shell.  All paths are
handled using ``pathlib.Path`` for cross‑platform safety.

Example usage::

    from pathlib import Path
    from server.services.audio_chunker import chunk_audio

    input_path = Path("/path/to/long_audio.mp3")
    out_dir = Path("/tmp/chunks")
    chunks = chunk_audio(input_path, out_dir, chunk_seconds=1800)
    for part in chunks:
        print(part)

Note that these functions do not perform any transcription; they
only prepare files suitable for feeding into ASR engines.  If
``ffprobe`` or ``ffmpeg`` are unavailable, the duration will be
reported as zero and the chunker will simply return the original
file path as a single element list.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import List


def ffprobe_duration_seconds(path: Path) -> float:
    """Return the duration of the audio file in seconds using ffprobe.

    If ffprobe cannot be executed or does not return a valid
    duration, this function returns 0.0.  The ``path`` argument is
    coerced to string before invocation.  The subprocess is run
    without using the shell for security reasons.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = result.stdout.strip() if result.stdout else ""
        return float(output) if output else 0.0
    except Exception:  # pragma: no cover - depends on ffprobe availability
        return 0.0


def chunk_audio(input_path: Path, out_dir: Path, chunk_seconds: int = 1800) -> List[Path]:
    """Split a long audio file into smaller chunks of a given length.

    Parameters
    ----------
    input_path: Path
        The path to the original audio file.
    out_dir: Path
        The directory where the chunks will be written.  It will be
        created if it does not exist.
    chunk_seconds: int, optional
        The maximum duration of each chunk in seconds.  Defaults
        to 1800 (30 minutes).

    Returns
    -------
    List[Path]
        A list of ``Path`` objects pointing to the generated chunk
        files.  If the duration cannot be determined, a list
        containing only the original ``input_path`` is returned.

    This function requires ``ffmpeg`` and ``ffprobe`` to be
    installed on the system.  The audio is converted to mono
    (``-ac 1``) at 16 kHz (``-ar 16000``) to ensure compatibility
    with many ASR models.  Chunks are named ``part_000.wav``,
    ``part_001.wav``, etc.  The chunking is idempotent: repeated
    calls with the same parameters will overwrite existing chunk
    files.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total_duration = ffprobe_duration_seconds(input_path)
    # If the duration is invalid or less than a chunk, return the original file
    if total_duration <= 0:
        return [input_path]
    # Compute number of chunks
    n_chunks = max(1, int(math.ceil(total_duration / float(chunk_seconds))))
    parts: List[Path] = []
    for idx in range(n_chunks):
        start = idx * chunk_seconds
        # Output file name with zero‑padded index
        out_name = f"part_{idx:03d}.wav"
        out_path = out_dir / out_name
        # Build ffmpeg command
        cmd = [
            "ffmpeg",
            "-y",  # overwrite output files without asking
            "-i",
            str(input_path),
            "-ss",
            str(start),
            "-t",
            str(chunk_seconds),
            "-ac",
            "1",  # mono audio
            "-ar",
            "16000",  # 16 kHz sampling rate
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True)  # pragma: no cover - depends on ffmpeg
        except Exception:  # pragma: no cover
            # If ffmpeg fails, stop further chunking and return what we have
            break
        if out_path.exists():
            parts.append(out_path)
    return parts


__all__ = ["ffprobe_duration_seconds", "chunk_audio"]