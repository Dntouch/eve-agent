"""Run the dependency-free JavaScript PNG/pagination regression checks."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed for browser-module unit tests')
class ChatExportTest(unittest.TestCase):
    def test_png_encoding_and_complete_history_pagination(self):
        result = subprocess.run(
            [shutil.which('node'), str(Path(__file__).parent / 'js/chat-export.test.cjs')],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
