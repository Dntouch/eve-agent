import os
import tempfile
import unittest
from pathlib import Path

from eve_agent.state import StateBus


class StateBusTest(unittest.TestCase):
    def test_state_file_is_private_and_atomically_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = StateBus(Path(tmp))
            bus.set("thinking", "Test")
            self.assertEqual({"state", "detail", "updated_at"}, set(bus.read()))
            self.assertEqual(0o700, os.stat(Path(tmp)).st_mode & 0o777)
            self.assertEqual(0o600, os.stat(Path(tmp) / "state.json").st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
