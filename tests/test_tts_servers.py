import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LocalTTSServerSafetyTest(unittest.TestCase):
    def test_standalone_tts_servers_are_syntax_valid_and_resource_bounded(self):
        for filename in ("qwen_tts_server.py", "chatterbox_server.py"):
            with self.subTest(filename=filename):
                source = (PROJECT_ROOT / filename).read_text(encoding="utf-8")
                compile(source, filename, "exec")
                self.assertIn("MAX_REQUEST_BYTES = 32 * 1024", source)
                self.assertIn("if len(body) != length", source)
                self.assertIn("class BoundedThreadingHTTPServer", source)
                self.assertIn("threading.BoundedSemaphore(16)", source)
                self.assertIn("request.settimeout(15)", source)

    def test_gpu_tts_servers_fail_fast_instead_of_overlapping_inference(self):
        for filename in ("qwen_tts_server.py", "chatterbox_server.py"):
            with self.subTest(filename=filename):
                source = (PROJECT_ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("LOCK.acquire(blocking=False)", source)
                self.assertIn('self._send(429', source)
                self.assertIn("MIN_FREE_VRAM_MB", source)
                self.assertIn("torch.cuda.empty_cache()", source)


if __name__ == "__main__":
    unittest.main()
