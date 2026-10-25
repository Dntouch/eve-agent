#!/usr/bin/env python3
"""Loopback-only Qwen3-TTS voice-clone service for EVE."""
from __future__ import annotations

import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


HOST = "127.0.0.1"
PORT = int(os.environ.get("EVE_QWEN_TTS_PORT", "8812"))
ROOT = Path(__file__).resolve().parent
REFERENCE_AUDIO = Path(os.environ.get("EVE_QWEN_TTS_REFERENCE", ROOT / "voice-candidates/eve-02-klar-futuristisch.wav"))
REFERENCE_TEXT = (
    "Hallo Stefan. Ich bin EVE. Ich höre dir zu, denke kurz darüber nach und sage dir dann klar, "
    "was ich herausgefunden habe. Und keine Sorge: Für gute Ideen brauche ich keine Beleidigungen."
)
MODEL_ID = os.environ.get("EVE_QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
DTYPE = torch.bfloat16 if torch.cuda.is_available() else torch.float32
LOCK = threading.Lock()
MAX_TEXT_CHARS = int(os.environ.get("EVE_QWEN_TTS_MAX_CHARS", "480"))
MAX_NEW_TOKENS = int(os.environ.get("EVE_QWEN_TTS_MAX_NEW_TOKENS", "2048"))
MIN_FREE_VRAM_MB = int(os.environ.get("EVE_QWEN_TTS_MIN_FREE_VRAM_MB", "1200"))
MAX_REQUEST_BYTES = 32 * 1024

print(f"Qwen3-TTS: loading {MODEL_ID} on {DEVICE} …", flush=True)
MODEL = Qwen3TTSModel.from_pretrained(
    MODEL_ID,
    device_map=DEVICE,
    dtype=DTYPE,
    attn_implementation="sdpa",
    local_files_only=True,
)
VOICE_PROMPT = MODEL.create_voice_clone_prompt(
    ref_audio=str(REFERENCE_AUDIO),
    ref_text=REFERENCE_TEXT,
)
print(f"Qwen3-TTS: ready at http://{HOST}:{PORT}", flush=True)


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self._connection_slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(15)
        return request, address

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._connection_slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._send(200, json.dumps({"status": "ok", "device": DEVICE, "model": MODEL_ID}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/synthesize":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("invalid request size")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete request")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("invalid request")
            text = str(payload["text"]).strip()
            if not text:
                raise ValueError("empty text")
            if len(text) > MAX_TEXT_CHARS:
                raise ValueError("text too long for local TTS")
            if torch.cuda.is_available():
                free_bytes, _ = torch.cuda.mem_get_info()
                if free_bytes < MIN_FREE_VRAM_MB * 1024 * 1024:
                    self._send(503, json.dumps({"error": "insufficient GPU memory; use fallback TTS"}).encode(), "application/json")
                    return
            if not LOCK.acquire(blocking=False):
                self._send(429, json.dumps({"error": "TTS worker is busy"}).encode(), "application/json")
                return
            try:
                wavs, sample_rate = MODEL.generate_voice_clone(
                    text=text,
                    language="German",
                    voice_clone_prompt=VOICE_PROMPT,
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            finally:
                LOCK.release()
            out = io.BytesIO()
            sf.write(out, wavs[0], sample_rate, format="WAV", subtype="PCM_16")
            del wavs
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            self._send(200, out.getvalue(), "audio/wav")
        except torch.cuda.OutOfMemoryError:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            self._send(503, json.dumps({"error": "GPU memory exhausted; use fallback TTS"}).encode(), "application/json")
        except Exception as exc:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")

    def _send(self, status, body, content_type):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


BoundedThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
