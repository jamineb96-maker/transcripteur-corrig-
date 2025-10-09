"""
Audio transcription utilities.

This module provides a :class:`Transcriber` class capable of splitting long
audio files into deterministic chunks, transcribing each chunk and
recombining the results into a single transcript.  The implementation
leverages `ffprobe` and `ffmpeg` to detect the duration of an input file
and extract segments without re‑encoding the entire file.  If the OpenAI
client library is available and a valid API key is configured, the
transcriber will use Whisper via the OpenAI API.  Otherwise, it falls back
to a simple mock that annotates the time range of each chunk.

The default chunk length is 120 seconds with a 4‑second overlap.  Chunks
are processed sequentially to limit resource usage.  Overlaps are left
intact in the concatenated transcript: some duplicated text may appear but
no content is lost.

Example
-------

>>> from server.transcriber import Transcriber
>>> tr = Transcriber()
>>> data = tr.transcribe_audio(Path('sample.mp3'))
>>> print(data['text'])
"Segment [0.0–120.0] ...\nSegment [116.0–236.0] ..."
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    # The openai package is optional; if unavailable we will fall back to a stub.
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # type: ignore


@dataclass
class Segment:
    """Represents a single transcribed segment.

    Attributes
    ----------
    start : float
        Start time in seconds.
    end : float
        End time in seconds.
    text : str
        Transcribed text for this time range.
    """

    start: float
    end: float
    text: str


class Transcriber:
    """Facade class to handle audio transcription.

    Parameters
    ----------
    model : str, optional
        Whisper model name to use with OpenAI (e.g. ``whisper-1``).  Ignored
        if the OpenAI client is not available or no API key is configured.
    fallback_model : str, optional
        Fallback Whisper model to use if the primary model fails.  Ignored
        when no OpenAI client is available.
    api_key : str, optional
        Explicit OpenAI API key.  When omitted the library will look for
        ``OPENAI_API_KEY`` in the environment.
    """

    def __init__(self, model: str = "whisper-1", fallback_model: str = "whisper-1", api_key: Optional[str] = None) -> None:
        self.model = model
        self.fallback_model = fallback_model
        # If OpenAI is available and a key is present, instantiate a client
        if OpenAI is not None and (api_key or os.getenv("OPENAI_API_KEY")):
            try:
                self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
            except Exception:
                self.client = None
        else:
            self.client = None

    # Public API
    def transcribe_audio(self, path: Path, chunk_seconds: int = 120, overlap_seconds: int = 4) -> Dict[str, object]:
        """Transcribe an audio file into text and segments.

        The audio is cut into overlapping chunks.  Each chunk is passed to
        :meth:`_transcribe_bytes`.  A list of :class:`Segment` objects is
        returned alongside the concatenated transcript and the total duration.

        Parameters
        ----------
        path : Path
            Path to the audio file.
        chunk_seconds : int, optional
            Length of each chunk in seconds.  Defaults to 120.
        overlap_seconds : int, optional
            Overlap between consecutive chunks in seconds.  Defaults to 4.

        Returns
        -------
        Dict[str, object]
            A dict with keys ``text`` (str), ``segments`` (List[Segment]) and
            ``duration`` (float).
        """
        if not path.exists():
            raise FileNotFoundError(str(path))
        duration = self._probe_duration(path)
        if duration is None:
            # If duration cannot be determined, treat as a single chunk
            duration = chunk_seconds
        segments: List[Segment] = []
        # Step through the file; ensure last chunk covers to end
        step = max(1.0, chunk_seconds - overlap_seconds)
        current = 0.0
        while current < duration:
            start = current
            end = min(duration, current + chunk_seconds)
            try:
                audio_bytes = self._extract_chunk(path, start, end)
                text = self._transcribe_bytes(audio_bytes)
            except Exception as exc:
                # In case of failure, include placeholder text but continue
                text = f"[Transcription échouée de {start:.1f} à {end:.1f} s: {exc}]"
            segments.append(Segment(start=start, end=end, text=text))
            current += step
        full_text = "\n".join(seg.text.strip() for seg in segments if seg.text.strip())
        return {"text": full_text.strip(), "segments": segments, "duration": duration}

    # Internal helpers
    def _probe_duration(self, path: Path) -> Optional[float]:
        """Return the duration of the audio in seconds using ffprobe.

        If ffprobe is unavailable or an error occurs, ``None`` is returned.
        """
        import shutil
        if shutil.which('ffprobe'):
            try:
                cmd = [
                    'ffprobe',
                    '-v',
                    'error',
                    '-show_entries',
                    'format=duration',
                    '-of',
                    'default=noprint_wrappers=1:nokey=1',
                    str(path),
                ]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
                value = result.stdout.strip()
                return float(value) if value else None
            except Exception:
                pass
        # Fallback: cannot determine duration
        return None

    def _extract_chunk(self, path: Path, start: float, end: float) -> bytes:
        """Extract a chunk of audio as bytes using ffmpeg.

        The chunk is converted to WAV with a single mono channel and a sample
        rate of 16 kHz.  ffmpeg is invoked via subprocess; the output is
        captured from stdout.

        Parameters
        ----------
        path : Path
            Input audio file.
        start : float
            Start time in seconds.
        end : float
            End time in seconds.

        Returns
        -------
        bytes
            Raw WAV data for the chunk.
        """
        import shutil
        # Try to use ffmpeg if available
        if shutil.which('ffmpeg'):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tempname = tmp.name
            duration = max(0.0, end - start)
            cmd = [
                'ffmpeg',
                '-loglevel',
                'quiet',
                '-ss',
                f'{start}',
                '-t',
                f'{duration}',
                '-i',
                str(path),
                '-ac',
                '1',
                '-ar',
                '16000',
                '-f',
                'wav',
                tempname,
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            data = Path(tempname).read_bytes()
            try:
                os.unlink(tempname)
            except Exception:
                pass
            return data
        # Fallback: read full file bytes without cutting
        return Path(path).read_bytes()

    def _transcribe_bytes(self, audio_bytes: bytes) -> str:
        """Transcribe a single audio chunk.

        If an OpenAI client is configured, the function attempts to send the
        bytes to the Whisper API.  Any exceptions fall back to a mock
        transcription that simply reports the length of the audio.

        Parameters
        ----------
        audio_bytes : bytes
            Encoded audio as WAV data.

        Returns
        -------
        str
            The recognised speech.
        """
        if self.client is not None:
            # Use OpenAI Whisper via the audio API
            try:
                import io
                buf = io.BytesIO(audio_bytes)
                response = self.client.audio.transcriptions.create(  # type: ignore[attr-defined]
                    model=self.model,
                    file=("chunk.wav", buf, "audio/wav"),
                    response_format="text",
                    language="fr",
                )
                # The response is either a dict or an object depending on SDK
                if isinstance(response, dict):
                    return response.get("text", "")
                return getattr(response, "text", "")
            except Exception:
                # Try fallback model once
                try:
                    import io
                    buf = io.BytesIO(audio_bytes)
                    response = self.client.audio.transcriptions.create(  # type: ignore[attr-defined]
                        model=self.fallback_model,
                        file=("chunk.wav", buf, "audio/wav"),
                        response_format="text",
                        language="fr",
                    )
                    if isinstance(response, dict):
                        return response.get("text", "")
                    return getattr(response, "text", "")
                except Exception:
                    pass
        # Mock transcription when OpenAI is unavailable or fails
        # Use the length of the audio to build a placeholder string
        import wave
        import io

        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate) if rate else 0.0
        except Exception:
            duration = 0.0
        return f"[audio {duration:.1f}s]"
