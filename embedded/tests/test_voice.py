from __future__ import annotations

from app.voice.recognizer import VoiceRecognizer


def test_voice_stub():
    vr = VoiceRecognizer()
    out = vr.listen_and_recognize(0.1)
    assert out in (None, "iniciar rutina")