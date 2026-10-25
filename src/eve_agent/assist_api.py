"""Authenticated, independent transport operations for Home Assistant Assist."""
from __future__ import annotations

import io
from pathlib import Path
import tempfile
import wave

MAX_AUDIO_BYTES = 30 * 1024 * 1024


class AssistAPI:
    def __init__(self, transcriber, speaker, conversations, message_handler, event_inbox=None):
        self.event_inbox = event_inbox
        self.transcriber, self.speaker = transcriber, speaker
        self.conversations, self.message_handler = conversations, message_handler
        self.stt_language = transcriber.config.get("language") or "de"
        self.tts_language = speaker.config.get("language") or self.stt_language

    def info(self):
        return {"api_version": 1, "name": "EVE", "conversation": True,
                "events": self.event_inbox is not None,
                "stt": {"languages": [self.stt_language], "sample_rate": 16000,
                        "sample_bytes": 2, "channels": 1},
                "tts": {"languages": [self.tts_language], "format": "wav"}}

    def create_conversation(self):
        return {"conversation_id": self.conversations.create("Home Assistant")["id"]}

    def conversation(self, payload):
        text, identifier = payload.get("text"), payload.get("conversation_id")
        images = payload.get("images", [])
        if not isinstance(text, str) or len(text) > 32000 or (not text.strip() and not images):
            raise ValueError("Ungültiger Gesprächstext")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("conversation_id fehlt")
        self.conversations.get(identifier)
        result = self.message_handler(text, images, identifier)
        return {key: result[key] for key in ("answer", "conversation_id", "turn_id")}

    def transcribe(self, pcm, language):
        if language != self.stt_language:
            raise ValueError("Nicht unterstützte STT-Sprache")
        if not pcm or len(pcm) > MAX_AUDIO_BYTES or len(pcm) % 2:
            raise ValueError("Ungültiges PCM-Audio: erwartet 16 kHz, 16 Bit, mono, little endian")
        with tempfile.TemporaryDirectory(prefix="eve-assist-stt-") as directory:
            path = Path(directory) / "input.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(pcm)
            return {"text": self.transcriber.transcribe(path)}

    def synthesize(self, payload):
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 32000:
            raise ValueError("Ungültiger TTS-Text")
        if payload.get("language", self.tts_language) != self.tts_language:
            raise ValueError("Nicht unterstützte TTS-Sprache")
        audio = self.speaker.synthesize(text)
        # A malformed upstream response must not masquerade as playable WAV.
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getnframes() == 0:
                raise RuntimeError("TTS lieferte leeres Audio")
        return audio

    def receive_event(self, payload):
        if self.event_inbox is None:
            raise RuntimeError("Ereigniskanal nicht verfügbar")
        return self.event_inbox.receive(payload)

    def read_events(self, after=0, limit=100):
        if self.event_inbox is None:
            raise RuntimeError("Ereigniskanal nicht verfügbar")
        return self.event_inbox.read(after, limit)
