from __future__ import annotations

import queue
import io
import shutil
import subprocess
import tempfile
import threading
import json
import re
import urllib.request
import wave
from pathlib import Path


MAX_TTS_RESPONSE_BYTES = 16 * 1024 * 1024


class Recorder:
    def __init__(self, config: dict):
        self.config = config

    @staticmethod
    def devices() -> list[dict]:
        import sounddevice as sd
        return [{"id": i, "name": d["name"], "inputs": d["max_input_channels"], "rate": d["default_samplerate"]} for i, d in enumerate(sd.query_devices())]

    def _device_id(self) -> int | None:
        needle = self.config.get("input_device_contains", "").casefold()
        if not needle:
            return None
        matches = [d for d in self.devices() if d["inputs"] > 0 and needle in d["name"].casefold()]
        if not matches:
            raise RuntimeError(f"Mikrofon mit Namen '{self.config['input_device_contains']}' nicht gefunden. Nutze: eve doctor")
        return int(matches[0]["id"])

    def record_until_enter(self, target: Path) -> None:
        import numpy as np
        import sounddevice as sd
        chunks: queue.Queue = queue.Queue()
        rate = int(self.config.get("sample_rate", 16000))
        channels = int(self.config.get("channels", 1))
        def callback(indata, frames, time_info, status):
            if status:
                print(f"[Audio] {status}")
            chunks.put(indata.copy())
        with sd.InputStream(samplerate=rate, channels=channels, dtype="int16", device=self._device_id(), callback=callback):
            input("Aufnahme läuft – Enter beendet … ")
        frames = []
        while not chunks.empty():
            frames.append(chunks.get())
        if not frames:
            raise RuntimeError("Keine Audiodaten aufgenommen")
        data = np.concatenate(frames, axis=0)
        with wave.open(str(target), "wb") as out:
            out.setnchannels(channels); out.setsampwidth(2); out.setframerate(rate); out.writeframes(data.tobytes())


class Transcriber:
    def __init__(self, config: dict):
        self.config = config
        self._model = None
        self._lock = threading.RLock()

    def transcribe(self, audio_path: Path) -> str:
        with self._lock:
            return self._transcribe_unlocked(audio_path)

    def _transcribe_unlocked(self, audio_path: Path) -> str:
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.config.get("model", "small"), device=self.config.get("device", "auto"), compute_type=self.config.get("compute_type", "auto"))
        segments, _ = self._model.transcribe(
            str(audio_path), language=self.config.get("language") or None, vad_filter=True,
            initial_prompt=self.config.get("initial_prompt") or None,
            hotwords=self.config.get("hotwords") or None,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


class Speaker:
    def __init__(self, config: dict, root: Path | None = None):
        self.config = config
        self.root = root or Path.cwd()
        self._piper_voice = None
        self._lock = threading.RLock()

    def speak(self, text: str) -> None:
        with self._lock:
            self._speak_unlocked(text)

    def _speak_unlocked(self, text: str) -> None:
        if not text or not text.strip():
            return
        engine = self.config.get("engine", "auto")
        if engine == "qwen3_tts":
            try:
                self._speak_http_tts(text, self.config.get("qwen3_tts_url", "http://127.0.0.1:8812"), "eve-qwen3-tts-")
                return
            except Exception as exc:
                print(f"[TTS] Qwen3-TTS nicht verfügbar ({exc}); Piper-Fallback")
                self._speak_piper(text)
                return
        if engine == "chatterbox":
            try:
                self._speak_chatterbox(text)
                return
            except Exception as exc:
                print(f"[TTS] Chatterbox nicht verfügbar ({exc}); Piper-Fallback")
                self._speak_piper(text)
                return
        if engine in ("auto", "piper"):
            try:
                self._speak_piper(text)
                return
            except Exception:
                if engine == "piper":
                    raise
        if engine in ("auto", "spd-say") and shutil.which("spd-say"):
            subprocess.run(["spd-say", "-w", "-l", self.config.get("voice", "de"), text], check=True)
            return
        if engine in ("auto", "espeak-ng") and shutil.which("espeak-ng"):
            subprocess.run(["espeak-ng", "-v", self.config.get("voice", "de"), text], check=True)
            return
        raise RuntimeError("Keine lokale TTS-Engine gefunden (spd-say oder espeak-ng)")

    def _speak_chatterbox(self, text: str) -> None:
        audio = self.synthesize_chatterbox(text)
        self._play_wav_bytes(audio, "eve-chatterbox-")

    def synthesize(self, text: str) -> bytes:
        with self._lock:
            return self._synthesize_unlocked(text)

    def _synthesize_unlocked(self, text: str) -> bytes:
        if self.config.get("engine") == "qwen3_tts":
            try:
                return self.synthesize_http_tts(
                    text, self.config.get("qwen3_tts_url", "http://127.0.0.1:8812"),
                    self.config.get("language"),
                )
            except Exception as exc:
                print(f"[TTS] Qwen3-TTS nicht verfügbar ({exc}); Piper-Fallback")
                return self.synthesize_piper(text)
        if self.config.get("engine") == "chatterbox":
            try:
                return self.synthesize_chatterbox(text)
            except Exception as exc:
                print(f"[TTS] Chatterbox nicht verfügbar ({exc}); Piper-Fallback")
                return self.synthesize_piper(text)
        return self.synthesize_piper(text)

    def _speak_http_tts(self, text: str, base_url: str, prefix: str) -> None:
        self._play_wav_bytes(
            self.synthesize_http_tts(text, base_url, self.config.get("language")), prefix,
        )

    @staticmethod
    def synthesize_http_tts(text: str, base_url: str, language: str | None = None) -> bytes:
        payload = {"text": text}
        if language:
            payload["language"] = language
        req = urllib.request.Request(
            base_url.rstrip("/") + "/synthesize",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as response:
            return Speaker._read_tts_response(response)

    def synthesize_chatterbox(self, text: str) -> bytes:
        payload = {"text": text}
        if self.config.get("language"):
            payload["language"] = self.config["language"]
        reference = self.config.get("reference_audio", "")
        if reference:
            ref_path = Path(reference).expanduser()
            if not ref_path.is_absolute():
                ref_path = self.root / ref_path
            payload["reference_audio"] = str(ref_path)
        req = urllib.request.Request(
            self.config.get("chatterbox_url", "http://127.0.0.1:8811") + "/synthesize",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            return self._read_tts_response(response)

    @staticmethod
    def _read_tts_response(response) -> bytes:
        try:
            declared_size = int(response.headers.get("Content-Length", "0"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("TTS-Dienst lieferte eine ungültige Content-Length") from exc
        if declared_size > MAX_TTS_RESPONSE_BYTES:
            raise RuntimeError("TTS-Antwort überschreitet das Größenlimit")
        content_type = response.headers.get("Content-Type", "")
        if content_type and not (
            content_type.casefold().startswith("audio/")
            or content_type.casefold().startswith("application/octet-stream")
        ):
            raise RuntimeError(f"TTS-Dienst lieferte kein Audio ({content_type})")
        audio = response.read(MAX_TTS_RESPONSE_BYTES + 1)
        if len(audio) > MAX_TTS_RESPONSE_BYTES:
            raise RuntimeError("TTS-Antwort überschreitet das Größenlimit")
        if not audio:
            raise RuntimeError("TTS-Dienst lieferte leeres Audio")
        return audio

    def _play_wav_bytes(self, audio: bytes, prefix: str = "eve-tts-") -> None:
        with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".wav", delete=False) as handle:
            handle.write(audio); output_path = Path(handle.name)
        try:
            player = shutil.which("pw-play") or shutil.which("aplay")
            if not player: raise RuntimeError("Kein lokaler WAV-Player gefunden")
            subprocess.run([player, str(output_path)], check=True)
        finally:
            output_path.unlink(missing_ok=True)

    def _speak_piper(self, text: str) -> None:
        self._play_wav_bytes(self.synthesize_piper(text), "eve-piper-")

    def synthesize_piper(self, text: str) -> bytes:
        from piper import PiperVoice, SynthesisConfig
        voice_name = self.config["voice"]
        data_dir = self.root / self.config.get("data_dir", "voices")
        model_path = data_dir / f"{voice_name}.onnx"
        if not model_path.exists():
            raise RuntimeError(f"Piper-Stimme fehlt: {model_path}")
        if self._piper_voice is None:
            self._piper_voice = PiperVoice.load(model_path)
        config = SynthesisConfig(
            length_scale=float(self.config.get("length_scale", 1.0)),
            noise_scale=float(self.config.get("noise_scale", 0.667)),
            noise_w_scale=float(self.config.get("noise_w_scale", 0.8)),
            volume=float(self.config.get("volume", 1.0)),
        )
        chunk_chars = max(200, min(int(self.config.get("piper_chunk_chars", 700)), 2_000))
        chunks = self.split_piper_text(text, chunk_chars)
        if not chunks:
            return b""

        pcm_parts = []
        wav_format = None
        for chunk in chunks:
            chunk_output = io.BytesIO()
            with wave.open(chunk_output, "wb") as wav_file:
                self._piper_voice.synthesize_wav(chunk, wav_file, syn_config=config)
            chunk_output.seek(0)
            with wave.open(chunk_output, "rb") as wav_file:
                params = wav_file.getparams()
                current_format = (params.nchannels, params.sampwidth, params.framerate, params.comptype)
                if wav_format is None:
                    wav_format = current_format
                elif current_format != wav_format:
                    raise RuntimeError("Piper lieferte uneinheitliche Audioformate für Text-Chunks")
                pcm_parts.append(wav_file.readframes(params.nframes))

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(wav_format[0])
            wav_file.setsampwidth(wav_format[1])
            wav_file.setframerate(wav_format[2])
            for pcm in pcm_parts:
                wav_file.writeframesraw(pcm)
        return output.getvalue()

    @staticmethod
    def split_piper_text(text: str, max_chars: int = 700) -> list[str]:
        """Split complete text at natural boundaries without dropping words."""
        remaining = text.strip()
        if not remaining:
            return []
        chunks = []
        while len(remaining) > max_chars:
            window = remaining[: max_chars + 1]
            candidates = []
            for match in re.finditer(r"(?:\n\s*\n|[.!?][\"'»”)]*\s+)", window):
                prefix = window[:match.start()].rstrip()
                token = prefix.rsplit(" ", 1)[-1] + window[match.start()]
                if re.fullmatch(r"(?:[^\W\d_]{1,3}\.){1,4}", token, re.UNICODE):
                    continue
                candidates.append(match.end())
            if not candidates:
                candidates = [match.end() for match in re.finditer(r"[,;:]\s+", window)]
            split_at = candidates[-1] if candidates else window.rfind(" ") + 1
            if split_at <= 0:
                split_at = max_chars
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].lstrip()
        if remaining:
            chunks.append(remaining)
        return chunks


def temporary_wav():
    return tempfile.NamedTemporaryFile(prefix="eve-", suffix=".wav", delete=False)
