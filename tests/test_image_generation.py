import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from jsonschema import ValidationError

from eve_agent.config import ConfigError, DEFAULTS, editable_config, load_config, update_editable_config
from eve_agent.image_generation import ImageGeneration


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=")


class ImageGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = deepcopy(DEFAULTS["image_generation"])
        self.provider = ImageGeneration(self.cfg, self.root)

    def run_image(self, response, **dimensions):
        seen = []
        class Opener:
            def open(self, request, timeout):
                seen.append((request, timeout))
                return io.BytesIO(json.dumps(response).encode())
        with patch("eve_agent.image_generation.urllib.request.build_opener", return_value=Opener()):
            job = self.provider.execute_operation("submit", {"prompt": "A mountain lake", **dimensions}, conversation_id="one")
            result = self.provider.execute_operation("status", {"job_id": job["job_id"], "wait_seconds": 20}, conversation_id="one")
        return job, result, seen[0]

    def test_sdapi_background_job_delivers_png_and_survives_reload(self):
        job, result, (request, timeout) = self.run_image({"images": [base64.b64encode(PNG).decode()]})
        self.assertEqual("completed", result["status"])
        self.assertEqual("http://127.0.0.1:1235/sdapi/v1/txt2img", request.full_url)
        body = json.loads(request.data)
        self.assertEqual((1024, 1024), (body["width"], body["height"]))
        self.assertEqual((1024, 1024), (job["width"], result["height"]))
        self.assertEqual((1, 1, 4), (body["batch_size"], body["n_iter"], body["steps"]))
        self.assertEqual(3600, timeout)
        self.assertEqual(PNG, base64.b64decode(result["resources"][0]["content"].split(",")[1]))
        restored = ImageGeneration(self.cfg, self.root)
        self.assertEqual("completed", restored.execute_operation("status", {"job_id": job["job_id"]}, conversation_id="one")["status"])
        with self.assertRaisesRegex(ValueError, "Unknown image job"):
            restored.execute_operation("status", {"job_id": job["job_id"]}, conversation_id="other")

    def test_openai_compatible_service_payload_and_auth(self):
        self.provider.config.update(api_format="openai", base_url="http://localhost:8000/v1", model="configured-model", api_key="private")
        _, result, (request, _) = self.run_image({"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
        self.assertEqual("completed", result["status"])
        self.assertEqual("http://localhost:8000/v1/images/generations", request.full_url)
        self.assertEqual("Bearer private", request.get_header("Authorization"))
        self.assertEqual("configured-model", json.loads(request.data)["model"])
        self.assertEqual("1024x1024", json.loads(request.data)["size"])
        self.assertNotIn("private", json.dumps(result))

    def test_per_job_dimensions_reach_both_apis_without_changing_defaults(self):
        for api_format in ("sdapi", "openai"):
            with self.subTest(api_format=api_format):
                self.provider.config["api_format"] = api_format
                response = {"images": [base64.b64encode(PNG).decode()]} if api_format == "sdapi" else {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
                job, result, (request, _) = self.run_image(response, width=1536, height=768)
                body = json.loads(request.data)
                self.assertEqual((1536, 768), (job["width"], job["height"]))
                self.assertEqual((1536, 768), (result["width"], result["height"]))
                if api_format == "sdapi":
                    self.assertEqual((1536, 768), (body["width"], body["height"]))
                else:
                    self.assertEqual("1536x768", body["size"])
                persisted = json.loads((self.provider.directory / (job["job_id"] + ".json")).read_text())
                self.assertEqual((1536, 768), (persisted["width"], persisted["height"]))
                self.assertEqual((1024, 1024), (self.provider.config["width"], self.provider.config["height"]))

    def test_one_dimension_can_override_configured_defaults(self):
        self.provider.config.update(width=768, height=1024)
        _, result, (request, _) = self.run_image({"images": [base64.b64encode(PNG).decode()]}, height=512)
        self.assertEqual((768, 512), (result["width"], result["height"]))
        self.assertEqual(512, json.loads(request.data)["height"])
        self.assertIn("768x1024", self.provider.minimal_contract()["operations"]["submit"]["description"])

    def test_invalid_dimensions_do_not_start_jobs(self):
        for dimensions in ({"width": 513}, {"height": 0}, {"width": 4160}, {"height": True}, {"width": "1024"}):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValidationError):
                self.provider.execute_operation("submit", {"prompt": "A lake", **dimensions}, conversation_id="one")
        self.assertIsNone(self.provider.active)
        self.assertEqual([], list(self.provider.directory.glob("*.json")))

    def test_bad_image_fails_without_retry(self):
        _, result, _ = self.run_image({"images": [base64.b64encode(b"not an image").decode()]})
        self.assertEqual("failed", result["status"])
        self.assertNotIn("resources", result)

    def test_only_one_generation_runs_and_submit_returns_before_completion(self):
        entered, release = threading.Event(), threading.Event()
        original = self.provider._generate
        def delayed(job):
            entered.set()
            release.wait(5)
            original(job)
        with patch.object(self.provider, "_generate", side_effect=delayed), patch("eve_agent.image_generation.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps({"images": [base64.b64encode(PNG).decode()]}).encode())
            job = self.provider.execute_operation("submit", {"prompt": "A lake"}, conversation_id="one")
            self.assertTrue(entered.wait(2))
            try:
                with self.assertRaisesRegex(RuntimeError, "busy"):
                    self.provider.execute_operation("submit", {"prompt": "Another lake"}, conversation_id="two")
                self.assertEqual("running", self.provider.execute_operation("status", {"job_id": job["job_id"]}, conversation_id="one")["status"])
            finally:
                release.set()
                self.provider.execute_operation("status", {"job_id": job["job_id"], "wait_seconds": 20}, conversation_id="one")

    def test_restart_does_not_resubmit_uncertain_job(self):
        identifier = "a" * 32
        self.provider._save({"job_id": identifier, "status": "running", "conversation_id": "one"})
        restored = ImageGeneration(self.cfg, self.root)
        result = restored.execute_operation("status", {"job_id": identifier}, conversation_id="one")
        self.assertEqual("failed", result["status"])
        self.assertIn("outcome unknown", result["error"])

    def test_public_channels_cannot_start_jobs_without_explicit_permission(self):
        from eve_agent.transport_access import transport_access
        with transport_access({"room_id": "public"}, public=True):
            with self.assertRaises(PermissionError):
                self.provider.execute_operation("submit", {"prompt": "A lake"}, conversation_id="one")
        self.assertIsNone(self.provider.active)

    def test_url_only_response_is_not_downloaded(self):
        self.provider.config["api_format"] = "openai"
        _, result, _ = self.run_image({"data": [{"url": "http://localhost/private"}]})
        self.assertEqual("failed", result["status"])

    def test_configuration_ui_validation_and_secret_roundtrip(self):
        path = self.root / "eve.json"
        path.write_text("{}")
        view = update_editable_config(path, {"values": {"image_generation.enabled": True,
            "image_generation.base_url": "http://localhost:1235", "image_generation.steps": 1,
            "image_generation.extra_parameters": {"seed": 123}}, "secrets": {"image_generation.api_key": "private"}}, environ={})
        _, cfg = load_config(path, environ={})
        self.assertTrue(cfg["image_generation"]["enabled"])
        self.assertEqual("private", cfg["image_generation"]["api_key"])
        self.assertNotIn("private", json.dumps(view))
        self.assertNotIn("private", path.read_text())
        self.assertIn("image_generation", {s["id"] for s in editable_config(path, environ={})["sections"]})
        for values in ({"image_generation.width": 513}, {"image_generation.extra_parameters": {"prompt": "override"}},
                       {"image_generation.base_url": "http://user:password@localhost:1235"}):
            with self.assertRaises(ConfigError):
                update_editable_config(path, {"values": values}, environ={})


if __name__ == "__main__":
    unittest.main()
