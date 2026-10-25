import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import urllib.request
import urllib.error
import wave

from eve_agent.assist_api import AssistAPI
from eve_agent.visual import VisualServer


def wav_bytes(pcm=b"\x00\x00" * 100):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    return output.getvalue()


class AssistAPITest(unittest.TestCase):
    def setUp(self):
        self.transcriber = Mock(config={"language": "de"})
        self.speaker = Mock(config={"language": "de"})
        self.speaker.synthesize.return_value = wav_bytes()
        self.conversations = Mock()
        self.conversations.create.return_value = {"id": "eve-id"}
        self.message = Mock(return_value={"answer": "  Antwort\n", "conversation_id": "eve-id", "turn_id": "turn"})
        self.api = AssistAPI(self.transcriber, self.speaker, self.conversations, self.message)

    def test_conversation_preserves_text_and_never_synthesizes(self):
        result = self.api.conversation({"text": "  Bitte\n", "images": [], "conversation_id": "eve-id"})
        self.message.assert_called_once_with("  Bitte\n", [], "eve-id")
        self.assertEqual(result["answer"], "  Antwort\n")
        self.transcriber.transcribe.assert_not_called()
        self.speaker.synthesize.assert_not_called()

    def test_stt_wraps_pcm_and_removes_temporary_audio(self):
        paths = []
        def transcribe(path):
            paths.append(path)
            with wave.open(str(path)) as audio:
                self.assertEqual((audio.getframerate(), audio.getsampwidth(), audio.getnchannels()), (16000, 2, 1))
                self.assertEqual(audio.readframes(2), b"\x01\x00\x02\x00")
            return "Transkript"
        self.transcriber.transcribe.side_effect = transcribe
        self.assertEqual(self.api.transcribe(b"\x01\x00\x02\x00", "de"), {"text": "Transkript"})
        self.assertFalse(paths[0].exists())
        self.message.assert_not_called()
        self.speaker.synthesize.assert_not_called()

    def test_tts_returns_audio_without_local_playback_or_conversation(self):
        result = self.api.synthesize({"text": "  Hallo\n", "language": "de"})
        self.assertEqual(result, wav_bytes())
        self.speaker.synthesize.assert_called_once_with("  Hallo\n")
        self.speaker.speak.assert_not_called()
        self.message.assert_not_called()

    def test_invalid_audio_and_language_are_rejected_before_transcription(self):
        for audio, language in [(b"\x00", "de"), (b"", "de"), (b"\x00\x00", "xx")]:
            with self.assertRaises(ValueError):
                self.api.transcribe(audio, language)
        self.transcriber.transcribe.assert_not_called()

    def test_http_auth_and_independent_routes(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        server = VisualServer(Path(directory.name), Mock(), "127.0.0.1", 0,
                              assist_handler=self.api, assist_token="test-token")
        self.addCleanup(server.stop)
        server.start()
        base = f"http://127.0.0.1:{server.port}/api/assist/"

        def request(path, data=None, content_type="application/json", authorized=True):
            headers = {"Content-Type": content_type}
            if authorized:
                headers["Authorization"] = "Bearer test-token"
            return urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers), timeout=3)

        with self.assertRaises(urllib.error.HTTPError) as error:
            request("info", authorized=False)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        with request("info") as response:
            self.assertEqual(json.load(response)["api_version"], 1)
        with request("conversations", b"{}") as response:
            self.assertEqual(json.load(response)["conversation_id"], "eve-id")
        self.transcriber.transcribe.return_value = "Hallo"
        with request("stt?language=de", b"\x00\x00", "application/octet-stream") as response:
            self.assertEqual(json.load(response)["text"], "Hallo")
        with request("tts", json.dumps({"text": "Hallo", "language": "de"}).encode()) as response:
            self.assertEqual(response.headers.get_content_type(), "audio/wav")
            self.assertEqual(response.read(), wav_bytes())
        self.message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
