import threading
import unittest

from eve_agent.streaming_tts import SpeechSegmenter, StreamingTTSPipeline
from eve_agent.llm import OpenAICompatibleLLM


class SpeechSegmenterTest(unittest.TestCase):
    def collect(self, chunks, **options):
        segmenter = SpeechSegmenter(**options)
        parts = []
        for chunk in chunks:
            parts.extend(segmenter.feed(chunk))
        parts.extend(segmenter.finish())
        return parts

    def test_short_answer_is_flushed_at_end(self):
        self.assertEqual(["Kurz und gut"], self.collect(["Kurz und gut"]))

    def test_multiple_sentences_are_emitted_in_order(self):
        source = "Erster Satz. Zweiter Satz! Dritter Satz?"
        parts = self.collect(["Erster Sa", "tz. Zweiter Satz! ", "Dritter Satz?"])
        self.assertEqual(source, "".join(parts))
        self.assertEqual(["Erster Satz. ", "Zweiter Satz! ", "Dritter Satz?"], parts)

    def test_long_sentence_uses_phrase_fallback_without_loss(self):
        source = "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"
        parts = self.collect([source], max_chars=24, min_fallback_chars=12)
        self.assertGreater(len(parts), 1)
        self.assertEqual(source, "".join(parts))
        self.assertTrue(all(len(part) <= 24 for part in parts[:-1]))

    def test_answer_without_final_punctuation_is_not_lost(self):
        source = "Eine Antwort ohne Punkt am Ende"
        self.assertEqual(source, "".join(self.collect([source])))


class StreamingTTSPipelineTest(unittest.TestCase):
    def test_synthesizes_and_publishes_sequentially(self):
        published = []
        recognized = []
        pipeline = StreamingTTSPipeline(
            lambda text: text.encode(),
            lambda text, audio: published.append((text, audio)),
            lambda: False,
            on_segment=lambda text, index: recognized.append((index, text)),
        )
        worker = threading.Thread(target=pipeline.run)
        worker.start()
        pipeline.feed("Eins. Zwei. ")
        pipeline.feed("Drei")
        pipeline.close()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual("Eins. Zwei. Drei", "".join(text for text, _ in published))
        self.assertEqual([text.encode() for text, _ in published], [audio for _, audio in published])
        self.assertEqual(
            [(0, "Eins. "), (1, "Zwei. "), (2, "Drei")], recognized,
        )
        self.assertEqual(len("Eins. Zwei. Drei"), pipeline.result["queued_chars"])
        self.assertEqual(len("Eins. Zwei. Drei"), pipeline.result["spoken_chars"])
        self.assertEqual("success", pipeline.result["status"])

    def test_first_sentence_reaches_tts_before_stream_end_without_duplicate_speech(self):
        first_published = threading.Event()
        published = []
        pipeline = StreamingTTSPipeline(
            lambda text: text.encode(),
            lambda text, audio: (published.append((text, audio)), first_published.set()),
            lambda: False,
        )
        worker = threading.Thread(target=pipeline.run)
        worker.start()
        pipeline.feed("Satz eins. Satz zwei")
        self.assertTrue(first_published.wait(1))
        self.assertEqual(["Satz eins. "], [text for text, _ in published])
        pipeline.feed(". Satz drei.")
        pipeline.close()
        worker.join(1)
        self.assertEqual(
            "Satz eins. Satz zwei. Satz drei.",
            "".join(text for text, _ in published),
        )

    def test_cancel_discards_queued_segments_and_suppresses_inflight_audio(self):
        synthesis_started = threading.Event()
        release = threading.Event()
        published = []

        def synthesize(text):
            synthesis_started.set()
            release.wait(1)
            return text.encode()

        pipeline = StreamingTTSPipeline(synthesize, lambda *item: published.append(item), lambda: False)
        worker = threading.Thread(target=pipeline.run)
        worker.start()
        pipeline.feed("Eins. Zwei. Drei. ")
        self.assertTrue(synthesis_started.wait(1))
        pipeline.cancel()
        release.set()
        worker.join(1)
        self.assertEqual([], published)
        self.assertEqual("cancelled", pipeline.result["status"])

    def test_tts_failure_is_contained(self):
        def fail(_text):
            raise RuntimeError("Piper kaputt")

        pipeline = StreamingTTSPipeline(fail, lambda *_: None, lambda: False)
        worker = threading.Thread(target=pipeline.run)
        worker.start()
        pipeline.feed("Text bleibt sichtbar. ")
        pipeline.close()
        worker.join(1)
        self.assertEqual("error", pipeline.result["status"])
        self.assertEqual("RuntimeError", pipeline.result["error"])

    def test_markdown_is_removed_from_spoken_segments(self):
        published = []
        pipeline = StreamingTTSPipeline(
            lambda text: text.encode(),
            lambda text, _audio: published.append(text),
            lambda: False,
            prepare=OpenAICompatibleLLM.sanitize_for_speech,
        )
        worker = threading.Thread(target=pipeline.run)
        worker.start()
        pipeline.feed("## **Status**\n\n- Temperatur: 21 °C")
        pipeline.close()
        worker.join(1)
        spoken = " ".join(published)
        self.assertNotIn("#", spoken)
        self.assertNotIn("*", spoken)
        self.assertNotIn("- Temperatur", spoken)
        self.assertIn("Status", spoken)
        self.assertIn("Temperatur", spoken)


if __name__ == "__main__":
    unittest.main()
