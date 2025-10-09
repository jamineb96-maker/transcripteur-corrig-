import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))  # noqa: E402
from transcriber import Transcriber


@pytest.fixture(scope='module')
def sine_wave(tmp_path_factory):
    """Generate a temporary sine wave audio file using Python's wave module."""
    tmpdir = tmp_path_factory.mktemp('audio')
    path = tmpdir / 'tone.wav'
    # Generate 20 seconds of 440Hz tone sampled at 16000 Hz
    framerate = 16000
    duration = 20
    amplitude = 32767
    import math
    import wave
    import struct
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit samples
        wf.setframerate(framerate)
        num_frames = int(duration * framerate)
        frames = bytearray()
        for i in range(num_frames):
            t = float(i) / framerate
            sample = int(amplitude * math.sin(2 * math.pi * 440 * t))
            frames += struct.pack('<h', sample)
        wf.writeframes(frames)
    yield path
    try:
        os.unlink(path)
    except Exception:
        pass


def test_chunking_and_transcription(sine_wave):
    tr = Transcriber()
    data = tr.transcribe_audio(sine_wave, chunk_seconds=10, overlap_seconds=2)
    # At least two segments due to 20s duration and 10s chunk with 2s overlap
    assert len(data['segments']) >= 2
    # The concatenated text should include placeholder transcripts
    assert '[audio' in data['text']
    # Duration should be reported
    assert data['duration'] >= 19