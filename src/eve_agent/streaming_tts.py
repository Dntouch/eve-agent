from __future__ import annotations

import queue
import re
import threading
import time


class SpeechSegmenter:
    """Incrementally emit complete sentences with a bounded long-phrase fallback."""

    def __init__(self, *, max_chars: int = 220, min_fallback_chars: int = 90):
        self.max_chars = max_chars
        self.min_fallback_chars = min_fallback_chars
        self.buffer = ""

    def feed(self, text: str) -> list[str]:
        self.buffer += text
        return self._drain(final=False)

    def finish(self) -> list[str]:
        parts = self._drain(final=True)
        return parts

    def _drain(self, *, final: bool) -> list[str]:
        parts = []
        while self.buffer:
            sentence = re.search(r"[.!?…]+(?:[\"')\]]*)\s+", self.buffer)
            if sentence:
                end = sentence.end()
                parts.append(self.buffer[:end])
                self.buffer = self.buffer[end:]
                continue
            if len(self.buffer) >= self.max_chars:
                split = self.buffer.rfind(" ", self.min_fallback_chars, self.max_chars)
                if split < self.min_fallback_chars:
                    split = self.max_chars
                else:
                    split += 1
                parts.append(self.buffer[:split])
                self.buffer = self.buffer[split:]
                continue
            break
        if final and self.buffer:
            parts.append(self.buffer)
            self.buffer = ""
        return parts


class StreamingTTSPipeline:
    """One-turn ordered speech queue; synthesis never blocks the LLM producer."""

    def __init__(
        self, synthesize, publish, cancelled, *, prepare=lambda text: text,
        on_segment=lambda _text, _index: None,
    ):
        self.segmenter = SpeechSegmenter()
        self.synthesize = synthesize
        self.publish = publish
        self.cancelled = cancelled
        self.prepare = prepare
        self.on_segment = on_segment
        self.queue: queue.Queue[str | None] = queue.Queue()
        self.done = threading.Event()
        self.cancelled_locally = threading.Event()
        self.queued_segments = 0
        self.result = {
            "status": "pending", "segments": 0, "first_audio_at": None,
            "queued_chars": 0, "spoken_chars": 0,
        }

    def _enqueue(self, segment: str) -> None:
        self.on_segment(segment, self.queued_segments)
        self.queued_segments += 1
        self.result["queued_chars"] += len(segment)
        self.queue.put(segment)

    def feed(self, chunk: str) -> None:
        if self.cancelled_locally.is_set() or self.cancelled():
            return
        for segment in self.segmenter.feed(chunk):
            self._enqueue(segment)

    def close(self) -> None:
        for segment in self.segmenter.finish():
            self._enqueue(segment)
        self.queue.put(None)

    def cancel(self) -> None:
        self.cancelled_locally.set()
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.queue.put(None)

    def run(self) -> dict:
        try:
            while True:
                segment = self.queue.get()
                if segment is None:
                    break
                if self.cancelled_locally.is_set() or self.cancelled():
                    break
                spoken = self.prepare(segment)
                if not spoken:
                    continue
                audio = self.synthesize(spoken)
                if self.cancelled_locally.is_set() or self.cancelled():
                    break
                self.publish(spoken, audio)
                self.result["segments"] += 1
                self.result["spoken_chars"] += len(segment)
                self.result["first_audio_at"] = self.result["first_audio_at"] or time.time()
            self.result["status"] = (
                "cancelled" if self.cancelled_locally.is_set() or self.cancelled() else "success"
            )
        except Exception as exc:
            self.result.update(status="error", error=type(exc).__name__)
        finally:
            self.done.set()
        return dict(self.result)
