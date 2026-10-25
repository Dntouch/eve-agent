import tempfile
import unittest
from pathlib import Path

from eve_agent.config import ConfigError, load_config
from eve_agent.search import PersistentSearch
from eve_agent.storage import EveDatabase


class MemoryPhase6Test(unittest.TestCase):
    def test_runtime_sources_have_no_backend_selection_or_cutover_command(self):
        root = Path(__file__).resolve().parents[1]
        cli = (root / "src/eve_agent/cli.py").read_text(encoding="utf-8")
        agent = (root / "src/eve_agent/agent.py").read_text(encoding="utf-8")
        search = (root / "src/eve_agent/search.py").read_text(encoding="utf-8")
        config = (root / "src/eve_agent/config.py").read_text(encoding="utf-8")
        self.assertNotIn("memory_backend", cli + agent + search)
        self.assertNotIn("memory-cutover", cli)
        self.assertNotIn('"backend": "legacy"', config)

    def test_removed_backend_option_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.json"
            path.write_text('{"memory":{"backend":"legacy"}}', encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "wurde entfernt"):
                load_config(path, environ={})

    def test_memory_error_has_no_legacy_search_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = EveDatabase(Path(tmp) / "eve.db")
            with database.connect() as connection:
                connection.execute(
                    """INSERT INTO memory_items
                       (id,category,content,status,confidence,metadata_json,created_at,updated_at)
                       VALUES ('old','fact','Legacy-Fallback-Marker','active',1,'{}','2026','2026')"""
                )
            with self.assertRaisesRegex(RuntimeError, "Memory-Runtime fehlt"):
                PersistentSearch(database).knowledge("Legacy-Fallback-Marker")


if __name__ == "__main__":
    unittest.main()
