import io
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from eve_agent.audio import Speaker, Transcriber


class SpeechToTextConfigurationTest(unittest.TestCase):
    def test_installed_audio_decoder_accepts_whisper_input_without_model_download(self):
        from faster_whisper.audio import decode_audio
        sample = io.BytesIO()
        with wave.open(sample, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 1600)
        sample.seek(0)
        decoded = decode_audio(sample, sampling_rate=16000)
        self.assertEqual(1600, len(decoded))


    def test_every_editable_stt_value_reaches_faster_whisper(self):
        observed = {}

        class FakeWhisperModel:
            def __init__(self, model, **kwargs):
                observed["model"] = model
                observed["load"] = kwargs

            def transcribe(self, path, **kwargs):
                observed["path"] = path
                observed["transcribe"] = kwargs
                return [types.SimpleNamespace(text=" Hallo ")], None

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        config = {
            "model": "medium", "language": "de", "device": "cpu",
            "compute_type": "int8", "initial_prompt": "Hausautomation",
            "hotwords": "EVE Rolllade",
        }
        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            result = Transcriber(config).transcribe(Path("aufnahme.wav"))

        self.assertEqual("Hallo", result)
        self.assertEqual("medium", observed["model"])
        self.assertEqual({"device": "cpu", "compute_type": "int8"}, observed["load"])
        self.assertEqual("aufnahme.wav", observed["path"])
        self.assertEqual("de", observed["transcribe"]["language"])
        self.assertEqual("Hausautomation", observed["transcribe"]["initial_prompt"])
        self.assertEqual("EVE Rolllade", observed["transcribe"]["hotwords"])
        self.assertTrue(observed["transcribe"]["vad_filter"])


class BrowserTTSFallbackTest(unittest.TestCase):
    def test_qwen_http_failure_returns_piper_audio_for_browser(self):
        speaker = Speaker({"engine": "qwen3_tts", "qwen3_tts_url": "http://127.0.0.1:1"})
        with patch.object(speaker, "synthesize_http_tts", side_effect=RuntimeError("busy")), patch.object(
            speaker, "synthesize_piper", return_value=b"RIFFfallback"
        ) as fallback:
            self.assertEqual(b"RIFFfallback", speaker.synthesize("Hallo"))
            fallback.assert_called_once_with("Hallo")

    def test_piper_split_keeps_short_and_normal_answers_complete(self):
        for text in ("Kurz.", "Das ist ein normaler Satz. Er bleibt vollständig erhalten."):
            self.assertEqual([text], Speaker.split_piper_text(text, 200))

    def test_piper_split_preserves_long_multi_paragraph_text_in_order(self):
        text = (
            "Der erste Absatz erklärt den Anfang ausführlich. " * 6
            + "\n\nDr. Weber nennt z.B. mehrere wichtige Details. " * 5
            + "Zum Schluss bleibt auch der letzte Satz vollständig erhalten."
        )
        chunks = Speaker.split_piper_text(text, 220)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 220 for chunk in chunks))
        self.assertEqual(" ".join(text.split()), " ".join(" ".join(chunks).split()))
        self.assertTrue(chunks[-1].endswith("erhalten."))

    def test_piper_synthesizes_every_chunk_into_one_ordered_wav(self):
        spoken_chunks = []

        class FakeVoice:
            def synthesize_wav(self, text, wav_file, syn_config=None):
                spoken_chunks.append(text)
                wav_file.setnchannels(1)
                wav_file.setsampwidth(1)
                wav_file.setframerate(8_000)
                wav_file.writeframes(bytes([len(spoken_chunks)]) * len(text))

        fake_piper = types.SimpleNamespace(
            PiperVoice=types.SimpleNamespace(load=lambda path: FakeVoice()),
            SynthesisConfig=lambda **kwargs: kwargs,
        )
        text = "Erster vollständiger Satz. " * 20 + "Letzter vollständiger Satz."
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "voice.onnx").touch()
            speaker = Speaker(
                {"engine": "piper", "voice": "voice", "data_dir": ".", "piper_chunk_chars": 200},
                Path(tmp),
            )
            with patch.dict(sys.modules, {"piper": fake_piper}):
                audio = speaker.synthesize_piper(text)

        self.assertGreater(len(spoken_chunks), 1)
        self.assertEqual(" ".join(text.split()), " ".join(" ".join(spoken_chunks).split()))
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
        expected = b"".join(bytes([index]) * len(chunk) for index, chunk in enumerate(spoken_chunks, 1))
        self.assertEqual(expected, frames)

    def test_piper_chunk_failure_is_reported_instead_of_returning_partial_audio(self):
        class FailingVoice:
            calls = 0

            def synthesize_wav(self, text, wav_file, syn_config=None):
                self.calls += 1
                wav_file.setnchannels(1)
                wav_file.setsampwidth(1)
                wav_file.setframerate(8_000)
                if self.calls == 2:
                    raise RuntimeError("chunk failed")
                wav_file.writeframes(b"ok")

        fake_piper = types.SimpleNamespace(
            PiperVoice=types.SimpleNamespace(load=lambda path: FailingVoice()),
            SynthesisConfig=lambda **kwargs: kwargs,
        )
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "voice.onnx").touch()
            speaker = Speaker(
                {"engine": "piper", "voice": "voice", "data_dir": ".", "piper_chunk_chars": 200},
                Path(tmp),
            )
            with patch.dict(sys.modules, {"piper": fake_piper}), self.assertRaisesRegex(RuntimeError, "chunk failed"):
                speaker.synthesize_piper("Ein vollständiger Satz. " * 30)

    def test_http_tts_rejects_declared_oversized_response_without_reading_it(self):
        response = Mock()
        response.headers = {"Content-Length": "5", "Content-Type": "audio/wav"}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("eve_agent.audio.MAX_TTS_RESPONSE_BYTES", 4), patch(
            "eve_agent.audio.urllib.request.urlopen", return_value=response
        ):
            with self.assertRaisesRegex(RuntimeError, "Größenlimit"):
                Speaker.synthesize_http_tts("Hallo", "http://127.0.0.1:8812")
        response.read.assert_not_called()

    def test_http_tts_rejects_chunk_larger_than_response_limit(self):
        response = Mock()
        response.headers = {"Content-Type": "audio/wav"}
        response.read.return_value = b"12345"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("eve_agent.audio.MAX_TTS_RESPONSE_BYTES", 4), patch(
            "eve_agent.audio.urllib.request.urlopen", return_value=response
        ):
            with self.assertRaisesRegex(RuntimeError, "Größenlimit"):
                Speaker.synthesize_http_tts("Hallo", "http://127.0.0.1:8812")
        response.read.assert_called_once_with(5)

    def test_http_tts_rejects_non_audio_success_response(self):
        response = Mock()
        response.headers = {"Content-Length": "2", "Content-Type": "application/json"}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("eve_agent.audio.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "kein Audio"):
                Speaker.synthesize_http_tts("Hallo", "http://127.0.0.1:8812")

    def test_http_tts_rejects_empty_audio(self):
        response = Mock()
        response.headers = {"Content-Length": "0", "Content-Type": "audio/wav"}
        response.read.return_value = b""
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("eve_agent.audio.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "leeres Audio"):
                Speaker.synthesize_http_tts("Hallo", "http://127.0.0.1:8812")

    def test_chatterbox_failure_returns_piper_audio_for_browser(self):
        speaker = Speaker({"engine": "chatterbox"})
        with patch.object(speaker, "synthesize_chatterbox", side_effect=RuntimeError("offline")), patch.object(
            speaker, "synthesize_piper", return_value=b"RIFFfallback"
        ):
            self.assertEqual(b"RIFFfallback", speaker.synthesize("Hallo"))


if __name__ == "__main__":
    unittest.main()
