import base64
import io
import math
import struct
import wave

import pytest

from server import create_app


def generate_wav_bytes(duration: float = 1.0, freq: float = 440.0) -> bytes:
    """Generate a mono sine wave of the given duration and frequency as WAV bytes."""
    framerate = 16000
    amplitude = 32767
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        num_frames = int(duration * framerate)
        for i in range(num_frames):
            t = i / float(framerate)
            sample = int(amplitude * math.sin(2 * math.pi * freq * t))
            wf.writeframesraw(struct.pack("<h", sample))
    return buffer.getvalue()


def test_transcribe_idempotency(tmp_path):
    """The same audio should yield the same session_id and be cached on repeat."""
    app = create_app()
    client = app.test_client()
    wav_bytes = generate_wav_bytes(duration=2.0)
    data_url = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode()
    payload = {"audio": data_url, "options": {"chunk_seconds": 2, "overlap_seconds": 1}}
    resp1 = client.post("/transcribe", json=payload)
    assert resp1.status_code == 200
    resp2 = client.post("/transcribe", json=payload)
    assert resp2.status_code == 200
    d1 = resp1.get_json()
    d2 = resp2.get_json()
    assert d1["session_id"] == d2["session_id"]
    # Second response should indicate cached
    assert d2.get("cached") is True


def test_post_session_idempotency(tmp_path):
    """Calling /post_session twice with the same audio should reuse persisted artefacts."""
    app = create_app()
    client = app.test_client()
    wav_bytes = generate_wav_bytes(duration=2.0)
    data_url = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode()
    payload = {
        "audio": data_url,
        "options": {"chunk_seconds": 2, "overlap_seconds": 1},
        "prenom": "Test",
    }
    resp1 = client.post("/post_session", json=payload)
    assert resp1.status_code == 200
    d1 = resp1.get_json()
    resp2 = client.post("/post_session", json=payload)
    assert resp2.status_code == 200
    d2 = resp2.get_json()
    assert d1["meta"]["session_id"] == d2["meta"]["session_id"]
    assert d2["meta"].get("cached") is True