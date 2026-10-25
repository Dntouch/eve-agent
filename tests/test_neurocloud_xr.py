"""WebXR math, controller picking and session lifecycle without a physical headset."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed for WebXR module checks')
class NeuroCloudXRTest(unittest.TestCase):
    def test_webxr_controller_and_session_contracts(self):
        result = subprocess.run(
            [shutil.which('node'), str(Path(__file__).parent / 'js/neurocloud-xr.test.cjs')],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
