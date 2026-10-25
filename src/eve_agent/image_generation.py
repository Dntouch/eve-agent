"""Configurable image service client. Inference belongs to the configured server."""
from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
import threading
import urllib.request
import uuid

from jsonschema import Draft202012Validator


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 28 * 1024 * 1024


class ImageGeneration:
    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription("image_generation.generate", "image_generation",
            "Ich kann über den konfigurierten Bildserver Bilder erzeugen und fertige Aufträge als Datei ausgeben.",
            "ImageGeneration", "submit,status")]

    def __init__(self, config, root):
        self.config = deepcopy(config)
        self.directory = Path(root) / "data" / "generated-images"
        self.lock = threading.RLock()
        self.active = None
        self.events = {}
        self.directory.mkdir(parents=True, exist_ok=True)
        # HTTP requests interrupted by an EVE restart must never be retried.
        for path in self.directory.glob("*.json"):
            job = json.loads(path.read_text())
            if job.get("status") == "running":
                job.update(status="failed", error="EVE restarted; server outcome unknown. No automatic retry.")
                self._save(job)

    def minimal_contract(self):
        return {
            "description": "Generate images using the configured image server. submit returns a job ID immediately. "
                           "CPU generation can be slow. Use status with the same ID to retrieve the finished image; "
                           "never resubmit a running job. No automatic completion message is sent.",
            "operations": {
                "submit": {"description": "Start one image generation job. Use optional width and height for dimensions "
                    "requested in chat; omitted dimensions use configured defaults "
                    f'({self.config["width"]}x{self.config["height"]}). Per-job dimensions do not change the configuration.', "effect": "write",
                    "parameters_schema": {"type": "object", "additionalProperties": False,
                        "properties": {"prompt": {"type": "string", "minLength": 1, "maxLength": 8000},
                            "width": {"type": "integer", "minimum": 64, "maximum": 4096, "multipleOf": 64,
                                      "description": "Requested image width in pixels; omit to use configured default."},
                            "height": {"type": "integer", "minimum": 64, "maximum": 4096, "multipleOf": 64,
                                       "description": "Requested image height in pixels; omit to use configured default."}},
                        "required": ["prompt"]}},
                "status": {"description": "Read job status and attach the image when completed. Optionally wait up to 20 seconds.",
                    "effect": "read", "parameters_schema": {"type": "object", "additionalProperties": False,
                        "properties": {"job_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
                            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 20}},
                        "required": ["job_id"]}},
            },
        }

    def _save(self, job):
        target = self.directory / (job["job_id"] + ".json")
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)

    def execute_operation(self, operation, parameters, *, conversation_id):
        from .transport_access import require_capability
        require_capability("image_generation")
        contract = self.minimal_contract()["operations"]
        if operation not in contract:
            raise ValueError("Unknown image operation")
        Draft202012Validator(contract[operation]["parameters_schema"]).validate(parameters)
        if not conversation_id:
            raise ValueError("Image jobs require a conversation")
        if operation == "submit":
            if not parameters["prompt"].strip():
                raise ValueError("Image prompt must not be blank")
            with self.lock:
                if self.active:
                    raise RuntimeError("Image generation is busy. Wait for the running job; do not resubmit.")
                job = {"job_id": uuid.uuid4().hex, "status": "running", "conversation_id": conversation_id,
                       "prompt": parameters["prompt"],
                       "width": parameters.get("width", self.config["width"]),
                       "height": parameters.get("height", self.config["height"])}
                self._save(job)
                self.active = job["job_id"]
                self.events[self.active] = threading.Event()
                threading.Thread(target=self._generate, args=(job,), daemon=True, name="eve-image-generation").start()
                return {key: job[key] for key in ("job_id", "status", "width", "height")}
        identifier = parameters["job_id"]
        with self.lock:
            job = self._load(identifier, conversation_id)
            event = self.events.get(identifier)
        if event and job["status"] == "running":
            event.wait(parameters.get("wait_seconds", 0))
        with self.lock:
            job = self._load(identifier, conversation_id)
        result = {key: job[key] for key in ("job_id", "status", "width", "height", "error") if key in job}
        if job["status"] == "completed":
            data = (self.directory / (identifier + ".png")).read_bytes()
            result["resources"] = [{"type": "file", "source": "image_generation",
                "filename": "eve-image-" + identifier + ".png", "media_type": "image/png",
                "content": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}]
        return result

    def _load(self, identifier, conversation_id):
        path = self.directory / (identifier + ".json")
        if not path.is_file():
            raise ValueError("Unknown image job")
        job = json.loads(path.read_text())
        if job["conversation_id"] != conversation_id:
            raise ValueError("Unknown image job")
        return job

    def _generate(self, job):
        try:
            cfg = self.config
            if cfg["api_format"] == "sdapi":
                path = "/sdapi/v1/txt2img"
                body = {"width": job["width"], "height": job["height"], "steps": cfg["steps"],
                        "cfg_scale": cfg["guidance_scale"], **cfg["extra_parameters"],
                        "prompt": job["prompt"], "batch_size": 1, "n_iter": 1}
            else:
                path = "/images/generations"
                body = {"model": cfg["model"], "size": f'{job["width"]}x{job["height"]}',
                        **cfg["extra_parameters"], "prompt": job["prompt"], "n": 1,
                        "response_format": "b64_json"}
            headers = {"Content-Type": "application/json"}
            if cfg.get("api_key"):
                headers["Authorization"] = "Bearer " + cfg["api_key"]
            request = urllib.request.Request(cfg["base_url"].rstrip("/") + path,
                data=json.dumps(body).encode("utf-8"), headers=headers)
            # Do not forward credentials through redirects or implicitly use a proxy.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=cfg["timeout_seconds"]) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Image server response exceeds 28 MiB")
            response = json.loads(raw)
            encoded = response["images"][0] if cfg["api_format"] == "sdapi" else response["data"][0]["b64_json"]
            if encoded.startswith("data:image/png;base64,"):
                encoded = encoded.split(",", 1)[1]
            data = base64.b64decode(encoded, validate=True)
            if len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Image server must return a PNG no larger than 20 MiB")
            (self.directory / (job["job_id"] + ".png")).write_bytes(data)
            job["status"] = "completed"
        except Exception as exc:
            # Server responses and URLs can contain secrets; keep errors technical.
            job.update(status="failed", error=f"Image generation failed ({type(exc).__name__}). No automatic retry.")
        finally:
            with self.lock:
                try:
                    self._save(job)
                finally:
                    self.active = None
                    self.events.pop(job["job_id"]).set()
