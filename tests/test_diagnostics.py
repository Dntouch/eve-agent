import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from eve_agent.diagnostics import DiagnosticJournal


class DiagnosticJournalTest(unittest.TestCase):
    def test_records_private_redacted_jsonl(self):
        secret = "dummy_secret_value_123456789"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            journal = DiagnosticJournal(
                root,
                clock=lambda: datetime(2026, 9, 26, 10, 30, tzinfo=timezone.utc),
            )
            journal.record(
                "home_assistant",
                "get_state",
                "error",
                f"Authorization: Bearer {secret}",
                exception=RuntimeError(f"client_secret={secret}"),
                route=f"cookie={secret}",
                correlation="turn-7",
            )

            raw = journal.path.read_text(encoding="utf-8")
            self.assertNotIn(secret, raw)
            self.assertIn("[REDACTED]", raw)
            parsed = json.loads(raw)
            self.assertEqual("RuntimeError", parsed["exception"]["type"])
            self.assertEqual("2026-09-26T10:30:00Z", parsed["timestamp"])
            self.assertEqual(0o700, os.stat(root).st_mode & 0o777)
            self.assertEqual(0o600, os.stat(journal.path).st_mode & 0o777)

    def test_rotation_and_component_filter_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "journal"
            journal = DiagnosticJournal(root, max_records=3)
            for index in range(5):
                journal.record("web" if index % 2 else "audio", "test", "ok", f"event {index}")

            restarted = DiagnosticJournal(root, max_records=3)
            self.assertEqual(["event 2", "event 3", "event 4"], [item["message"] for item in restarted.recent(99)])
            self.assertEqual(["event 3"], [item["message"] for item in restarted.recent(2, component="WEB")])
            self.assertEqual([], restarted.recent(0))

    def test_concurrent_writers_leave_only_complete_bounded_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = DiagnosticJournal(Path(tmp) / "journal", max_records=40)
            threads = []
            for worker in range(6):
                thread = threading.Thread(
                    target=lambda number=worker: [
                        journal.record("runtime", "thread", "ok", f"worker {number} item {item}")
                        for item in range(20)
                    ]
                )
                threads.append(thread)
                thread.start()
            for thread in threads:
                thread.join()

            records = journal.recent(100)
            self.assertEqual(40, len(records))
            self.assertEqual(40, len(journal.path.read_text(encoding="utf-8").splitlines()))
            self.assertTrue(all(record["status"] == "ok" for record in records))

    def test_invalid_legacy_lines_are_discarded_and_valid_content_scrubbed(self):
        secret = "dummy_credential_1234567890"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "journal"
            root.mkdir()
            path = root / "diagnostics.jsonl"
            path.write_text(
                "not-json\n"
                + json.dumps({"component": "web", "message": f"api_key={secret}"})
                + "\n",
                encoding="utf-8",
            )

            journal = DiagnosticJournal(root)
            raw = journal.path.read_text(encoding="utf-8")
            self.assertNotIn("not-json", raw)
            self.assertNotIn(secret, raw)
            self.assertEqual(1, len(journal.recent()))

    def test_rejects_symlink_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "journal"
            root.mkdir()
            target = Path(tmp) / "outside"
            target.write_text("do not touch", encoding="utf-8")
            (root / "diagnostics.jsonl").symlink_to(target)
            with self.assertRaises(ValueError):
                DiagnosticJournal(root)
            self.assertEqual("do not touch", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
