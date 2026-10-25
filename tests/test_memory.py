import tempfile
import unittest
from pathlib import Path

from eve_agent.memory import cosine_similarity, lexical_tokens, lexical_vector, redact_sensitive
from eve_agent.storage import EveDatabase


class MemoryBoundaryTest(unittest.TestCase):
    def test_database_initialization_creates_no_file_backed_memory_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            EveDatabase(root / "data" / "eve.db")

            self.assertFalse((root / "memory").exists())
            self.assertFalse((root / "facts.md").exists())
            self.assertFalse((root / "aliases.md").exists())
            self.assertFalse((root / "index.json").exists())

    def test_lexical_fingerprint_has_no_bundled_semantic_equivalence(self):
        first = lexical_vector("alpha beta")
        repeated = lexical_vector("alpha beta")
        unrelated = lexical_vector("gamma delta")

        self.assertEqual(first, repeated)
        self.assertLess(cosine_similarity(first, unrelated), 0.8)
        self.assertEqual({"alpha", "beta"}, lexical_tokens("Alpha, beta!"))

    def test_redaction_is_idempotent(self):
        once = redact_sensitive('local_key: "secret_value_123456789"')
        self.assertEqual(once, redact_sensitive(once))

    def test_credentials_are_redacted(self):
        secret = "test_secret_value_123456789"
        for wording in (
            f"password={secret}",
            f"api-key: {secret}",
            f"Authorization: Bearer {secret}",
        ):
            with self.subTest(wording=wording):
                cleaned = redact_sensitive(wording)
                self.assertNotIn(secret, cleaned)
                self.assertIn("[REDACTED]", cleaned)


if __name__ == "__main__":
    unittest.main()
