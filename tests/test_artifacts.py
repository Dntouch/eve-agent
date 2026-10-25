import base64
import unittest

from eve_agent.artifacts import extract_artifacts


class ArtifactTest(unittest.TestCase):
    def test_plain_text_fence_is_spoken_instead_of_silently_removed(self):
        answer = "Bitte hör zu:\n\n```text\nHeute ist ein wunderbarer Abend!\n```"
        spoken, files = extract_artifacts(answer, "Lies mir einen Text vor")
        self.assertEqual(spoken, "Bitte hör zu:\n\nHeute ist ein wunderbarer Abend!")
        self.assertEqual(files, [])

    def test_code_is_download_and_not_spoken(self):
        answer = "Hier ist dein Script.\n\n```python filename=hello.py\nprint('Hallo')\n```"
        spoken, files = extract_artifacts(answer, "Schreib hello.py")
        self.assertEqual(spoken, "Hier ist dein Script.")
        self.assertEqual(files[0]["filename"], "hello.py")
        self.assertEqual(base64.b64decode(files[0]["base64"]).decode(), "print('Hallo')\n")
        self.assertNotIn("print", spoken)

    def test_requested_filename_is_used(self):
        spoken, files = extract_artifacts("```bash\necho ok\n```", "Erstelle start.sh")
        self.assertEqual(files[0]["filename"], "start.sh")
        self.assertIn("Download", spoken)


if __name__ == "__main__": unittest.main()
