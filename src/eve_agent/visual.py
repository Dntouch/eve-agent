from __future__ import annotations

import errno
import base64
import binascii
import inspect
import hmac
import json
import ssl
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .memory import redact_sensitive


EXPECTED_CLIENT_ERRORS = (
    BrokenPipeError,
    ConnectionAbortedError,
    ConnectionResetError,
    TimeoutError,
    ssl.SSLError,
)

AUDIO_CONTENT_TYPES = {
    "application/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-wav": ".wav",
}

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_MESSAGE_TEXT_CHARS = 32_000
IMAGE_SIGNATURES = {
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


class EveHTTPServer(ThreadingHTTPServer):
    """Small bounded HTTP server suitable for browsers on the local network."""

    daemon_threads = True
    request_queue_size = 64

    def __init__(
        self,
        server_address,
        request_handler_class,
        *,
        max_connections: int = 32,
        max_concurrent_requests: int = 8,
    ):
        if max_connections < 1 or max_concurrent_requests < 1:
            raise ValueError("HTTP-Limits müssen mindestens eins sein")
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        self.request_slots = threading.BoundedSemaphore(max_concurrent_requests)
        super().__init__(server_address, request_handler_class)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(30)
        return request, address

    def process_request(self, request, client_address):
        # TLS may not have handshaken yet, so a saturated connection is closed
        # instead of blocking the accept loop while trying to write a response.
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._connection_slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()

    def handle_error(self, request, client_address):
        # Browsers commonly close speculative/stale TLS connections. Those are
        # transport events, not application failures, and should stay quiet.
        import sys

        error = sys.exc_info()[1]
        if isinstance(error, EXPECTED_CLIENT_ERRORS):
            return
        if isinstance(error, OSError) and error.errno in {
            errno.ECONNABORTED,
            errno.ECONNRESET,
            errno.EPIPE,
            errno.ETIMEDOUT,
        }:
            return
        super().handle_error(request, client_address)


class VisualServer:
    def __init__(
        self,
        web_dir: Path,
        bus,
        host: str,
        port: int,
        turn_handler=None,
        message_handler=None,
        tls_cert=None,
        tls_key=None,
        access_token="",
        notification_handler=None,
        readiness_handler=None,
        conversation_handler=None,
        task_handler=None,
        work_list_handler=None,
        work_item_handler=None,
        config_handler=None,
        home_assistant_inventory_handler=None,
        home_assistant_policy_handler=None,
        training_package_handler=None,
        telemetry_handler=None,
        brainwatch_handler=None,
        semantic_feedback_handler=None,
        turn_result_handler=None,
        presentation_handler=None,
        presentation_resource_handler=None,
        conversation_asset_handler=None,
        backend_message_start_handler=None,
        backend_message_snapshot_handler=None,
        backend_voice_start_handler=None,
        backend_turn_cancel_handler=None,
        max_connections: int = 32,
        max_concurrent_requests: int = 8,
        allowed_hosts: list[str] | None = None,
        assist_handler=None,
        assist_token: str = "",
        chatto_handler=None,
        chatto_token: str = "",
        chatto_status_handler=None,
    ):
        self.web_dir, self.bus, self.host = web_dir, bus, host
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        bus_ref = bus
        handle_turn = turn_handler
        handle_message = message_handler
        handle_notifications = notification_handler
        handle_readiness = readiness_handler
        handle_conversations = conversation_handler
        handle_tasks = task_handler
        handle_work_lists = work_list_handler
        handle_work_items = work_item_handler
        handle_config = config_handler
        handle_home_assistant_inventory = home_assistant_inventory_handler
        handle_home_assistant_policy = home_assistant_policy_handler
        handle_training_packages = training_package_handler
        handle_telemetry = telemetry_handler
        handle_brainwatch = brainwatch_handler
        handle_semantic_feedback = semantic_feedback_handler
        handle_turn_result = turn_result_handler
        handle_presentation = presentation_handler
        handle_presentation_resource = presentation_resource_handler
        handle_conversation_asset = conversation_asset_handler
        handle_backend_message_start = backend_message_start_handler
        handle_backend_message_snapshot = backend_message_snapshot_handler
        handle_backend_voice_start = backend_voice_start_handler
        handle_backend_turn_cancel = backend_turn_cancel_handler
        message_has_conversation = bool(
            handle_message and len(inspect.signature(handle_message).parameters) >= 3
        )
        turn_has_conversation = bool(
            handle_turn and len(inspect.signature(handle_turn).parameters) >= 2
        )
        required_token = access_token
        handle_assist = assist_handler
        handle_chatto = chatto_handler
        directory = str(web_dir)
        trusted_hosts = {"127.0.0.1", "localhost", "::1"}
        if host not in {"0.0.0.0", "::"}:
            trusted_hosts.add(host.casefold())
        trusted_hosts.update(
            str(item).casefold()
            for item in (allowed_hosts or [])
            if item is not None and str(item).strip()
        )

        class Handler(SimpleHTTPRequestHandler):
            server_version = "EVE"

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=directory, **kwargs)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/health/live":
                    self._json(200, {"status": "ok"})
                    return
                if path == "/health/ready":
                    status, payload = self._readiness()
                    self._json(status, payload)
                    return
                if path.startswith("/api/") and not self._trusted_browser_request():
                    self._json(403, {"error": "Cross-Origin-Anfragen sind nicht erlaubt"})
                    return
                if not self._acquire_request_slot():
                    return
                try:
                    if path == "/api/assist/events":
                        if self._assist_authorized():
                            query = parse_qs(urlsplit(self.path).query)
                            try:
                                result = handle_assist.read_events(
                                    int(query.get("after", ["0"])[0]),
                                    int(query.get("limit", ["100"])[0]))
                            except ValueError as exc:
                                self._json(400, {"error": str(exc)})
                            except Exception as exc:
                                self._json(503, {"error": redact_sensitive(str(exc))})
                            else:
                                self._json(200, result)
                        return
                    elif path == "/api/chatto/status":
                        if self._authorized():
                            self._json(200, chatto_status_handler() if chatto_status_handler else {"state": "disabled"})
                        return
                    elif path == "/api/assist/info":
                        if self._assist_authorized():
                            self._json(200, handle_assist.info())
                        return
                    stream_prefix = "/api/message/stream/"
                    turn_prefix = "/api/backend-turns/"
                    if path.startswith(stream_prefix) and handle_backend_message_snapshot is not None:
                        if not self._authorized():
                            return
                        turn_id = path.removeprefix(stream_prefix)
                        if not turn_id or "/" in turn_id:
                            self.send_error(404)
                            return
                        self._observe_backend_turn(turn_id)
                        return
                    if path.startswith(turn_prefix) and handle_backend_message_snapshot is not None:
                        if not self._authorized():
                            return
                        turn_id = path.removeprefix(turn_prefix)
                        if not turn_id or "/" in turn_id:
                            self.send_error(404)
                            return
                        try:
                            self._json(200, handle_backend_message_snapshot(turn_id))
                        except KeyError as exc:
                            self._json(404, {"error": str(exc.args[0])})
                        return
                    resource_prefix = "/api/presentation/resource/"
                    asset_prefix = "/api/conversation-assets/"
                    if path.startswith(asset_prefix) and handle_conversation_asset is not None:
                        if not self._authorized():
                            return
                        asset_id = path[len(asset_prefix):]
                        if not asset_id or "/" in asset_id:
                            self.send_error(404)
                            return
                        try:
                            mime, body = handle_conversation_asset(asset_id)
                        except (KeyError, OSError):
                            self.send_error(404)
                            return
                        self._binary(200, body, mime)
                    elif path.startswith(resource_prefix) and handle_presentation_resource is not None:
                        if not self._authorized():
                            return
                        parts = path[len(resource_prefix):].split("/", 1)
                        if len(parts) != 2 or not parts[0].isdigit():
                            self.send_error(404)
                            return
                        try:
                            mime, body = handle_presentation_resource(int(parts[0]), parts[1])
                        except KeyError:
                            self.send_error(404)
                            return
                        except ValueError:
                            self.send_error(400)
                            return
                        self._binary(200, body, mime)
                    elif path == "/api/state":
                        if not self._authorized():
                            return
                        self._json(200, bus_ref.read())
                    elif self._is_conversation_path(path) and handle_conversations is not None:
                        if not self._authorized():
                            return
                        self._conversation_request("GET")
                    elif self._is_task_path(path) and handle_tasks is not None:
                        if not self._authorized():
                            return
                        self._task_request("GET")
                    elif self._is_resource_path(path, "/api/work-lists") and handle_work_lists is not None:
                        if not self._authorized():
                            return
                        self._resource_request("GET", "/api/work-lists", handle_work_lists)
                    elif self._is_resource_path(path, "/api/work-items") and handle_work_items is not None:
                        if not self._authorized():
                            return
                        self._resource_request("GET", "/api/work-items", handle_work_items)
                    elif path == "/api/config" and handle_config is not None:
                        if not self._authorized():
                            return
                        self._config_request("GET")
                    elif path == "/api/home-assistant/policy" and handle_home_assistant_policy is not None:
                        if not self._authorized():
                            return
                        self._home_assistant_policy_request("GET")
                    elif path == "/api/training-packages" and handle_training_packages is not None:
                        if not self._authorized():
                            return
                        self._training_package_request("GET")
                    elif path == "/api/telemetry" and handle_telemetry is not None:
                        if not self._authorized():
                            return
                        try:
                            query = parse_qs(urlsplit(self.path).query)
                            self._json(200, handle_telemetry(query))
                        except Exception:
                            self._json(500, {"error": "Telemetrie konnte nicht gelesen werden"})
                    elif path.startswith("/api/brainwatch/") and handle_brainwatch is not None:
                        if not self._authorized():
                            return
                        self._brainwatch_request(path)
                    elif path.startswith("/api/turn-results/") and handle_turn_result is not None:
                        if not self._authorized():
                            return
                        turn_id = path.removeprefix("/api/turn-results/")
                        if not turn_id or "/" in turn_id:
                            self.send_error(404)
                            return
                        try:
                            self._json(200, handle_turn_result(turn_id))
                        except KeyError as exc:
                            self._json(404, {"error": str(exc.args[0])})
                    elif path == "/api/presentation" and handle_presentation is not None:
                        if not self._authorized():
                            return
                        self._presentation_request("GET")
                    elif path == "/api/notifications":
                        self._json(
                            405,
                            {"error": "Benachrichtigungen müssen per POST abgefragt werden"},
                            {"Allow": "POST"},
                        )
                    else:
                        super().do_GET()
                finally:
                    self.server.request_slots.release()

            def do_POST(self):
                if not self._trusted_browser_request():
                    self._json(403, {"error": "Cross-Origin-Anfragen sind nicht erlaubt"})
                    return
                if not self._acquire_request_slot():
                    return
                try:
                    self._do_POST()
                finally:
                    self.server.request_slots.release()

            def do_PATCH(self):
                self._api_mutation("PATCH")

            def do_DELETE(self):
                self._api_mutation("DELETE")

            def _api_mutation(self, method: str) -> None:
                if not self._trusted_browser_request():
                    self._json(403, {"error": "Cross-Origin-Anfragen sind nicht erlaubt"})
                    return
                if not self._acquire_request_slot():
                    return
                try:
                    if not self._authorized():
                        return
                    path = self.path.split("?", 1)[0]
                    if self._is_conversation_path(path) and handle_conversations is not None:
                        self._conversation_request(method)
                    elif self._is_task_path(path) and handle_tasks is not None:
                        self._task_request(method)
                    elif self._is_resource_path(path, "/api/work-lists") and handle_work_lists is not None:
                        self._resource_request(method, "/api/work-lists", handle_work_lists)
                    elif self._is_resource_path(path, "/api/work-items") and handle_work_items is not None:
                        self._resource_request(method, "/api/work-items", handle_work_items)
                    elif path == "/api/config" and method == "PATCH" and handle_config is not None:
                        self._config_request(method)
                    elif (path == "/api/home-assistant/policy" and method == "PATCH"
                          and handle_home_assistant_policy is not None):
                        self._home_assistant_policy_request(method)
                    elif path == "/api/presentation" and handle_presentation is not None:
                        self._presentation_request(method)
                    else:
                        self.send_error(404)
                finally:
                    self.server.request_slots.release()

            def _do_POST(self):
                if self.path.split("?", 1)[0].startswith("/api/chatto/"):
                    self._chatto_request()
                    return
                if self.path.split("?", 1)[0].startswith("/api/assist/"):
                    self._assist_request()
                    return
                path = self.path.split("?", 1)[0]
                if path == "/api/home-assistant/inventory" and handle_home_assistant_inventory is not None:
                    if not self._authorized():
                        return
                    try:
                        status, result = handle_home_assistant_inventory()
                    except (OSError, RuntimeError, ValueError) as exc:
                        self._json(503, {"error": str(exc) or "Home-Assistant-Inventur fehlgeschlagen"})
                        return
                    self._json(status, result)
                    return
                if path == "/api/training-packages" and handle_training_packages is not None:
                    if not self._authorized():
                        return
                    self._training_package_request("POST")
                    return
                feedback_parts = self._semantic_feedback_path(path)
                if feedback_parts is not None and handle_semantic_feedback is not None:
                    if not self._authorized():
                        return
                    try:
                        if self.headers.get_content_type() != "application/json":
                            self._json(415, {"error": "Feedback muss application/json verwenden"})
                            return
                        length = int(self.headers.get("Content-Length", "0"))
                        if length < 1 or length > 4096:
                            raise ValueError("Feedback ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Feedback muss ein JSON-Objekt sein")
                        result = handle_semantic_feedback(
                            *feedback_parts, payload.get("decision"), payload.get("explanation"),
                        )
                        self._json(200, {"feedback": result})
                    except KeyError:
                        self._json(404, {"error": "Antwort wurde nicht gefunden"})
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        self._json(409, {"error": str(exc) or "Feedback konnte nicht gespeichert werden"})
                    except Exception:
                        self._json(500, {"error": "Feedback konnte nicht gespeichert werden"})
                    return
                if path.startswith("/api/brainwatch/semantic-links/") and path.endswith("/reject") and handle_brainwatch is not None:
                    if not self._authorized():
                        return
                    claim_id = unquote(path.removeprefix("/api/brainwatch/semantic-links/").removesuffix("/reject"))
                    try:
                        if not claim_id or "/" in claim_id:
                            raise ValueError("Ungültige Claim-ID")
                        length = int(self.headers.get("Content-Length", "0"))
                        if length < 1 or length > 4096:
                            raise ValueError("Ungültige Bestätigung")
                        payload = json.loads(self._read_body(length))
                        self._json(200, handle_brainwatch("semantic_reject", claim_id, payload))
                    except KeyError:
                        self._json(404, {"error": "Claim wurde nicht gefunden"})
                    except (TypeError, ValueError):
                        self._json(400, {"error": "Ungültige Bestätigung"})
                    except Exception:
                        self._json(500, {"error": "Ablehnung konnte nicht gespeichert werden"})
                    return
                if path == "/api/brainwatch/conversation-learning" and handle_brainwatch is not None:
                    if not self._authorized():
                        return
                    try:
                        if self.headers.get_content_type() != "application/json":
                            self._json(415, {"error": "Learning-Steuerung muss application/json verwenden"})
                            return
                        length = int(self.headers.get("Content-Length", "0"))
                        if length < 1 or length > 1024:
                            raise ValueError("Learning-Steuerung ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Learning-Steuerung erwartet ein Objekt")
                        if payload.get("action") in {"review", "reopen_review"}:
                            if (set(payload) - {"action", "turn_id", "note"} or not isinstance(payload.get("turn_id"), str)
                                    or not payload["turn_id"].strip() or not isinstance(payload.get("note", ""), str)):
                                raise ValueError("Lernprüfung erwartet eine Turn-ID und optional eine Prüfnotiz")
                        elif set(payload) != {"action"}:
                            raise ValueError("Learning-Steuerung erwartet genau eine Aktion")
                        self._json(200, handle_brainwatch(
                            "conversation_learning_control", None, payload,
                        ))
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc) or "Learning-Steuerung ist ungültig"})
                    except Exception:
                        self._json(500, {"error": "Gesprächslernen konnte nicht gesteuert werden"})
                    return
                similarity_prefix = "/api/brainwatch/semantic-similarity/"
                if path.startswith(similarity_prefix) and handle_brainwatch is not None:
                    if not self._authorized():
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length < 1 or length > 8192 or self.headers.get_content_type() != "application/json":
                            raise ValueError("Ungültige Semantik-Korrektur")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Korrektur muss ein JSON-Objekt sein")
                        suffix = path.removeprefix(similarity_prefix)
                        if suffix == "relations":
                            result = handle_brainwatch("semantic_similarity_relation", None, payload)
                        elif suffix == "recognitions":
                            result = handle_brainwatch("semantic_similarity_recognition", None, payload)
                        elif suffix.startswith("relations/") and suffix.endswith("/undo"):
                            relation_id = unquote(suffix.removeprefix("relations/").removesuffix("/undo"))
                            if not relation_id or "/" in relation_id:
                                raise ValueError("Ungültige Relations-ID")
                            result = handle_brainwatch("semantic_similarity_undo", relation_id, payload)
                        else:
                            self.send_error(404); return
                        self._json(200, result)
                    except KeyError:
                        self._json(404, {"error": "Semantik-Relation wurde nicht gefunden"})
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        self._json(409, {"error": str(exc) or "Korrektur konnte nicht gespeichert werden"})
                    except Exception:
                        self._json(500, {"error": "Korrektur konnte nicht gespeichert werden"})
                    return
                cancel_prefix = "/api/backend-turns/"
                if path.startswith(cancel_prefix) and path.endswith("/cancel") and handle_backend_turn_cancel:
                    if not self._authorized():
                        return
                    turn_id = path[len(cancel_prefix):-len("/cancel")]
                    if not turn_id or "/" in turn_id:
                        self.send_error(404)
                        return
                    try:
                        self._json(200, handle_backend_turn_cancel(turn_id))
                    except KeyError as exc:
                        self._json(404, {"error": str(exc.args[0])})
                    return
                if path == "/api/presentation" and handle_presentation is not None:
                    if not self._authorized():
                        return
                    self._presentation_request("POST")
                    return
                if self._is_conversation_path(path) and handle_conversations is not None:
                    if not self._authorized():
                        return
                    self._conversation_request("POST")
                    return
                if self._is_task_path(path) and handle_tasks is not None:
                    if not self._authorized():
                        return
                    self._task_request("POST")
                    return
                if self._is_resource_path(path, "/api/work-lists") and handle_work_lists is not None:
                    if not self._authorized():
                        return
                    self._resource_request("POST", "/api/work-lists", handle_work_lists)
                    return
                if self._is_resource_path(path, "/api/work-items") and handle_work_items is not None:
                    if not self._authorized():
                        return
                    self._resource_request("POST", "/api/work-items", handle_work_items)
                    return
                if path == "/api/notifications" and handle_notifications is not None:
                    if not self._authorized():
                        return
                    self._json(200, handle_notifications())
                    return
                if path == "/api/message" and handle_message is not None:
                    if not self._authorized():
                        return
                    try:
                        if self.headers.get_content_type() != "application/json":
                            self._json(415, {"error": "Nachrichten müssen application/json verwenden"})
                            return
                        length = int(self.headers.get("Content-Length", "0"))
                        if length <= 0 or length > 25 * 1024 * 1024:
                            raise ValueError("Nachricht ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Nachricht muss ein JSON-Objekt sein")
                        text = str(payload.get("text", "")).strip()
                        images = payload.get("images", [])
                        conversation_id = payload.get("conversation_id")
                        if conversation_id is not None and not isinstance(conversation_id, str):
                            raise ValueError("conversation_id muss Text sein")
                        if len(text) > MAX_MESSAGE_TEXT_CHARS:
                            raise ValueError("Text ist zu lang")
                        self._validate_images(images)
                        if not text and not images:
                            raise ValueError("Bitte Text oder Screenshot übergeben")
                        result = (
                            handle_message(text, images, conversation_id)
                            if message_has_conversation else handle_message(text, images)
                        )
                        self._json(200, result)
                    except ValueError as exc:
                        self._json(400, {"error": str(exc)})
                    except KeyError as exc:
                        self._json(404, {"error": str(exc.args[0])})
                    except Exception as exc:
                        bus_ref.set("error", str(exc))
                        self._json(500, {"error": str(exc)})
                    return
                if path == "/api/message/stream" and handle_backend_message_start is not None:
                    if not self._authorized():
                        return
                    self._stream_message_request()
                    return
                if path == "/api/turn/stream" and handle_backend_voice_start is not None:
                    if not self._authorized():
                        return
                    self._stream_voice_request()
                    return
                if path != "/api/turn" or handle_turn is None:
                    self.send_error(404)
                    return
                if not self._authorized():
                    return
                try:
                    content_type = self.headers.get_content_type()
                    suffix = AUDIO_CONTENT_TYPES.get(content_type)
                    if suffix is None:
                        self._json(415, {"error": "Nicht unterstütztes Audioformat"})
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 30 * 1024 * 1024:
                        raise ValueError("Ungültige oder zu große Audioaufnahme")
                    with tempfile.NamedTemporaryFile(prefix="eve-browser-", suffix=suffix, delete=False) as audio:
                        audio.write(self._read_body(length))
                        audio_path = Path(audio.name)
                    try:
                        conversation_id = parse_qs(urlsplit(self.path).query).get("conversation_id", [None])[0]
                        result = (
                            handle_turn(audio_path, conversation_id)
                            if turn_has_conversation else handle_turn(audio_path)
                        )
                    finally:
                        audio_path.unlink(missing_ok=True)
                    self._json(200, result)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                except KeyError as exc:
                    self._json(404, {"error": str(exc.args[0])})
                except Exception as exc:
                    bus_ref.set("error", str(exc))
                    self._json(500, {"error": str(exc)})

            def _stream_message_request(self):
                """Send one NDJSON response: content deltas followed by one final result."""
                try:
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Nachrichten müssen application/json verwenden"})
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 25 * 1024 * 1024:
                        raise ValueError("Nachricht ist leer oder zu groß")
                    payload = json.loads(self._read_body(length))
                    if not isinstance(payload, dict):
                        raise ValueError("Nachricht muss ein JSON-Objekt sein")
                    text = str(payload.get("text", "")).strip()
                    images = payload.get("images", [])
                    conversation_id = payload.get("conversation_id")
                    if conversation_id is not None and not isinstance(conversation_id, str):
                        raise ValueError("conversation_id muss Text sein")
                    explicit_resume = payload.get("resume_conversation", False)
                    if not isinstance(explicit_resume, bool):
                        raise ValueError("resume_conversation muss boolesch sein")
                    if len(text) > MAX_MESSAGE_TEXT_CHARS:
                        raise ValueError("Text ist zu lang")
                    self._validate_images(images)
                    if not text and not images:
                        raise ValueError("Bitte Text oder Screenshot übergeben")
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json(400, {"error": str(exc)})
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                try:
                    retry_context = payload.get("retry_context")
                    if retry_context is None:
                        turn = handle_backend_message_start(text, images, conversation_id, explicit_resume)
                    else:
                        turn = handle_backend_message_start(text, images, conversation_id, explicit_resume,
                                                            retry_context=retry_context)
                    self._observe_backend_turn(turn["turn_id"], headers_sent=True)
                except Exception as exc:
                    bus_ref.set("error", str(exc))
                    try:
                        self._emit_ndjson({"type": "error", "error": str(exc)})
                    except EXPECTED_CLIENT_ERRORS:
                        pass

            def _stream_voice_request(self):
                audio_path = None
                try:
                    content_type = self.headers.get_content_type()
                    suffix = AUDIO_CONTENT_TYPES.get(content_type)
                    if suffix is None:
                        self._json(415, {"error": "Nicht unterstütztes Audioformat"})
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 30 * 1024 * 1024:
                        raise ValueError("Ungültige oder zu große Audioaufnahme")
                    with tempfile.NamedTemporaryFile(
                        prefix="eve-browser-backend-", suffix=suffix, delete=False,
                    ) as audio:
                        audio.write(self._read_body(length))
                        audio_path = Path(audio.name)
                    conversation_id = parse_qs(urlsplit(self.path).query).get("conversation_id", [None])[0]
                    explicit_resume = (
                        parse_qs(urlsplit(self.path).query).get("resume_conversation", ["false"])[0]
                        == "true"
                    )
                except ValueError as exc:
                    if audio_path:
                        audio_path.unlink(missing_ok=True)
                    self._json(400, {"error": str(exc)})
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                try:
                    turn = handle_backend_voice_start(audio_path, conversation_id, explicit_resume)
                    self._observe_backend_turn(turn["turn_id"], headers_sent=True)
                except Exception as exc:
                    if audio_path:
                        audio_path.unlink(missing_ok=True)
                    bus_ref.set("error", str(exc))
                    try:
                        self._emit_ndjson({"type": "error", "error": str(exc)})
                    except EXPECTED_CLIENT_ERRORS:
                        pass

            def _emit_ndjson(self, event):
                self.wfile.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
                self.wfile.flush()

            def _observe_backend_turn(self, turn_id: str, *, headers_sent: bool = False):
                if not headers_sent:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                sent_chars = 0
                sent_preview = ""
                sent_preview_generation = 0
                sent_reasoning_chars = 0
                version = 0
                accepted_sent = False
                transcript_sent = False
                input_sent = False
                sent_audio = 0
                audio_initialized = False
                try:
                    while True:
                        snapshot = handle_backend_message_snapshot(turn_id, version)
                        version = snapshot["version"]
                        if not accepted_sent:
                            self._emit_ndjson({
                                "type": "accepted", "turn_id": turn_id,
                                "conversation_id": snapshot.get("conversation_id"),
                                "status": snapshot["status"], "version": version,
                                "cancellable": snapshot.get("cancellable", False),
                            })
                            accepted_sent = True
                        answer = snapshot.get("answer") or ""
                        answer_preview = snapshot.get("answer_preview") or ""
                        answer_preview_generation = int(
                            snapshot.get("answer_preview_generation") or 0
                        )
                        reasoning = snapshot.get("reasoning") or ""
                        input_text = snapshot.get("input_text")
                        if input_text and not input_sent:
                            self._emit_ndjson({
                                "type": "input", "turn_id": turn_id,
                                "content": input_text,
                            })
                            input_sent = True
                        transcript = snapshot.get("transcript")
                        if transcript and not transcript_sent:
                            self._emit_ndjson({
                                "type": "transcript", "turn_id": turn_id,
                                "content": transcript,
                            })
                            transcript_sent = True
                        audio_segments = snapshot.get("audio_segments") or []
                        if not audio_initialized:
                            # A new POST observer receives live audio. A reconnect
                            # starts at the current tail so old speech is not replayed.
                            sent_audio = 0 if headers_sent else len(audio_segments)
                            audio_initialized = True
                        for segment in audio_segments[sent_audio:]:
                            self._emit_ndjson({
                                "type": "audio", "turn_id": turn_id, **segment,
                            })
                        sent_audio = len(audio_segments)
                        if len(reasoning) > sent_reasoning_chars:
                            self._emit_ndjson({
                                "type": "reasoning_delta",
                                "content": reasoning[sent_reasoning_chars:],
                            })
                            sent_reasoning_chars = len(reasoning)
                        if sent_chars == 0:
                            if answer_preview_generation != sent_preview_generation:
                                if sent_preview:
                                    self._emit_ndjson({"type": "preview_reset"})
                                sent_preview = ""
                                sent_preview_generation = answer_preview_generation
                            if answer_preview != sent_preview:
                                if answer_preview.startswith(sent_preview):
                                    self._emit_ndjson({
                                        "type": "preview_delta",
                                        "content": answer_preview[len(sent_preview):],
                                    })
                                else:
                                    self._emit_ndjson({"type": "preview_reset"})
                                    if answer_preview:
                                        self._emit_ndjson({
                                            "type": "preview_delta", "content": answer_preview,
                                        })
                                sent_preview = answer_preview
                        if len(answer) > sent_chars:
                            if sent_chars == 0 and sent_preview:
                                if answer.startswith(sent_preview):
                                    self._emit_ndjson({"type": "preview_commit"})
                                    sent_chars = len(sent_preview)
                                else:
                                    self._emit_ndjson({"type": "preview_reset"})
                                    sent_preview = ""
                            if len(answer) > sent_chars:
                                self._emit_ndjson({"type": "delta", "content": answer[sent_chars:]})
                            sent_chars = len(answer)
                        self._emit_ndjson({
                            "type": "status", "turn_id": turn_id,
                            "status": snapshot["status"], "version": version,
                            "cancellable": snapshot.get("cancellable", False),
                            "cancel_requested": snapshot.get("cancel_requested", False),
                        })
                        if snapshot["status"] == "completed":
                            self._emit_ndjson({
                                "type": "complete", "result": snapshot.get("response"),
                                "backend_turn": snapshot,
                            })
                            return
                        if snapshot["status"] == "cancelled":
                            self._emit_ndjson({
                                "type": "cancelled", "turn_id": turn_id,
                                "status": "cancelled", "backend_turn": snapshot,
                            })
                            return
                        if snapshot["status"] == "failed":
                            self._emit_ndjson({
                                "type": "error", "turn_id": turn_id,
                                "status": snapshot["status"],
                                "error": snapshot.get("error") or "Turn wurde abgebrochen",
                                "failure_report": snapshot.get("failure_report"),
                            })
                            return
                except EXPECTED_CLIENT_ERRORS:
                    # Only this observer is gone. The backend-owned worker continues.
                    return
                except KeyError as exc:
                    self._emit_ndjson({"type": "error", "error": str(exc.args[0])})

            def _presentation_request(self, method: str) -> None:
                payload = {}
                if method in {"POST", "PATCH"}:
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Präsentation muss application/json verwenden"})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length <= 0 or length > 2 * 1024 * 1024:
                            raise ValueError("Präsentationsanfrage ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Präsentationsanfrage muss ein Objekt sein")
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                try:
                    status, result = handle_presentation(method, payload)
                except KeyError as exc:
                    self._json(404, {"error": str(exc.args[0])})
                    return
                except (TypeError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(status, result)

            def _brainwatch_request(self, path: str) -> None:
                query = parse_qs(urlsplit(self.path).query)
                try:
                    memory_claims_path = "/api/brainwatch/memory/claims"
                    if path == "/api/brainwatch/assist-events":
                        result = handle_brainwatch("assist_events", None, query)
                    elif path == "/api/brainwatch/working-memory":
                        result = handle_brainwatch("working_memory", None, query)
                    elif path == "/api/brainwatch/memory/events":
                        result = handle_brainwatch("memory_events", None, query)
                    elif path == "/api/brainwatch/memory/runtime-events":
                        result = handle_brainwatch("memory_runtime_events", None, query)
                    elif path == "/api/brainwatch/memory/graph/working":
                        result = handle_brainwatch("working_memory_graph", None, query)
                    elif path == "/api/brainwatch/memory/graph/relations":
                        result = handle_brainwatch("memory_graph_relations", None, query)
                    elif path == "/api/brainwatch/memory/graph/revision":
                        result = handle_brainwatch("memory_graph_revision", None, query)
                    elif path == "/api/brainwatch/memory/graph":
                        result = handle_brainwatch("memory_graph", None, query)
                    elif path == "/api/brainwatch/statistics":
                        result = handle_brainwatch("statistics", None, query)
                    elif path == "/api/brainwatch/conversation-learning":
                        result = handle_brainwatch("conversation_learning_status", None, query)
                    elif path.startswith("/api/brainwatch/memory/runtime-events/"):
                        event_id = unquote(path.removeprefix("/api/brainwatch/memory/runtime-events/"))
                        if not event_id or "/" in event_id:
                            raise KeyError("Runtime-Ereignis wurde nicht gefunden")
                        result = handle_brainwatch("memory_runtime_event", event_id, query)
                    elif path == memory_claims_path:
                        result = handle_brainwatch("memory_claims", None, query)
                    elif path.startswith(memory_claims_path + "/"):
                        remainder = path.removeprefix(memory_claims_path + "/")
                        operation = "memory_claim"
                        for suffix, candidate in (
                            ("/evidence", "memory_evidence"),
                            ("/relations", "memory_relations"),
                            ("/turns", "memory_claim_turns"),
                            ("/runtime-events", "memory_claim_runtime"),
                        ):
                            if remainder.endswith(suffix):
                                remainder = remainder.removesuffix(suffix)
                                operation = candidate
                                break
                        claim_id = unquote(remainder)
                        if not claim_id or "/" in claim_id:
                            raise KeyError("Claim wurde nicht gefunden")
                        result = handle_brainwatch(operation, claim_id, query)
                    elif path.startswith("/api/brainwatch/turns/") and path.endswith("/memory"):
                        turn_id = unquote(path.removeprefix("/api/brainwatch/turns/").removesuffix("/memory"))
                        if not turn_id or "/" in turn_id:
                            raise KeyError("Turn wurde nicht gefunden")
                        result = handle_brainwatch("turn_memory", turn_id, query)
                    elif path.startswith("/api/brainwatch/turns/") and path.endswith("/runtime-events/live"):
                        turn_id = unquote(path.removeprefix("/api/brainwatch/turns/").removesuffix("/runtime-events/live"))
                        if not turn_id or "/" in turn_id:
                            raise KeyError("Turn wurde nicht gefunden")
                        result = handle_brainwatch("turn_runtime_live", turn_id, query)
                    elif path.startswith("/api/brainwatch/turns/") and path.endswith("/runtime-events"):
                        turn_id = unquote(path.removeprefix("/api/brainwatch/turns/").removesuffix("/runtime-events"))
                        if not turn_id or "/" in turn_id:
                            raise KeyError("Turn wurde nicht gefunden")
                        result = handle_brainwatch("turn_runtime", turn_id, query)
                    elif path == "/api/brainwatch/semantic-summary":
                        result = handle_brainwatch("semantic_summary", None, query)
                    elif path == "/api/brainwatch/semantic-composition":
                        result = handle_brainwatch("semantic_composition", None, query)
                    elif path == "/api/brainwatch/semantic-similarity":
                        result = handle_brainwatch("semantic_similarity", None, query)
                    elif path == "/api/brainwatch/semantic-actions":
                        result = handle_brainwatch("semantic_actions", None, query)
                    elif path.startswith("/api/brainwatch/semantic-actions/"):
                        representation_id = unquote(path.removeprefix("/api/brainwatch/semantic-actions/"))
                        if not representation_id or "/" in representation_id:
                            raise KeyError("Handlungsrepräsentation wurde nicht gefunden")
                        result = handle_brainwatch("semantic_action", representation_id, query)
                    elif path == "/api/brainwatch/semantic-links":
                        result = handle_brainwatch("semantic_list", None, query)
                    elif path.startswith("/api/brainwatch/semantic-links/"):
                        claim_id = unquote(path.removeprefix("/api/brainwatch/semantic-links/"))
                        if not claim_id or "/" in claim_id:
                            raise KeyError("Claim wurde nicht gefunden")
                        result = handle_brainwatch("semantic_detail", claim_id, query)
                    elif path == "/api/brainwatch/search":
                        result = handle_brainwatch("search", None, query)
                    elif path.startswith("/api/brainwatch/nodes/"):
                        remainder = path.removeprefix("/api/brainwatch/nodes/")
                        neighbors = remainder.endswith("/neighbors")
                        namespaced_id = unquote(remainder.removesuffix("/neighbors") if neighbors else remainder)
                        if not namespaced_id or "/" in namespaced_id:
                            raise KeyError("Knoten wurde nicht gefunden")
                        result = handle_brainwatch("neighbors" if neighbors else "node", namespaced_id, query)
                    else:
                        self.send_error(404)
                        return
                except KeyError as exc:
                    self._json(404, {"error": str(exc.args[0])})
                    return
                except (TypeError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                except Exception:
                    self._json(500, {"error": "Brainwatch konnte nicht gelesen werden"})
                    return
                self._json(200, result)

            @staticmethod
            def _is_conversation_path(path: str) -> bool:
                if path == "/api/conversations":
                    return True
                prefix = "/api/conversations/"
                return path.startswith(prefix) and bool(path[len(prefix):]) and "/" not in path[len(prefix):]

            @staticmethod
            def _semantic_feedback_path(path: str):
                prefix = "/api/conversations/"
                suffix = next((suffix for suffix in ("/semantic-feedback", "/feedback") if path.endswith(suffix)), None)
                if not path.startswith(prefix) or suffix is None:
                    return None
                middle = path[len(prefix):-len(suffix)]
                parts = middle.split("/messages/")
                if len(parts) != 2 or not all(parts) or any("/" in part for part in parts):
                    return None
                return tuple(unquote(part) for part in parts)

            def _conversation_request(self, method: str) -> None:
                path = self.path.split("?", 1)[0]
                prefix = "/api/conversations/"
                conversation_id = path[len(prefix):] if path.startswith(prefix) else None
                payload = {}
                if method in {"POST", "PATCH"}:
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Anfrage muss application/json verwenden"})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length <= 0 or length > 16 * 1024:
                            raise ValueError("Anfrage ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Anfrage muss ein JSON-Objekt sein")
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                query = parse_qs(urlsplit(self.path).query)
                try:
                    status, result = handle_conversations(method, conversation_id, payload, query)
                except Exception:
                    bus_ref.set("error", "Konversationsverwaltung fehlgeschlagen")
                    self._json(500, {"error": "Konversationsverwaltung fehlgeschlagen"})
                    return
                self._json(status, result)

            def _home_assistant_policy_request(self, method: str) -> None:
                payload = {}
                if method == "PATCH":
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Bereichsregeln müssen application/json verwenden"})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length < 1 or length > 16 * 1024:
                            raise ValueError("Bereichsregel ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Bereichsregel muss ein JSON-Objekt sein")
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                try:
                    status, result = handle_home_assistant_policy(method, payload)
                except (KeyError, TypeError, ValueError) as exc:
                    self._json(400, {"error": str(exc) or "Bereichsregel ist ungültig"})
                    return
                except Exception as exc:
                    cause = redact_sensitive(str(exc)).strip()[:300]
                    self._json(500, {"error": (
                        "Bereichsregel konnte nicht verarbeitet werden"
                        + (f": {type(exc).__name__}: {cause}" if cause else f": {type(exc).__name__}")
                    )})
                    return
                self._json(status, result)

            def _training_package_request(self, method: str) -> None:
                payload = {}
                if method == "POST":
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Trainingspakete müssen application/json verwenden"})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length < 1 or length > 2 * 1024 * 1024:
                            raise ValueError("Trainingspaket ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Trainingsanfrage muss ein JSON-Objekt sein")
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                try:
                    status, result = handle_training_packages(
                        method, payload, parse_qs(urlsplit(self.path).query),
                    )
                except Exception as exc:
                    cause = redact_sensitive(str(exc)).strip()[:300]
                    self._json(500, {"error": (
                        "Trainingspaket konnte nicht verarbeitet werden"
                        + (f": {type(exc).__name__}: {cause}" if cause else f": {type(exc).__name__}")
                    )})
                    return
                self._json(status, result)

            @staticmethod
            def _is_task_path(path: str) -> bool:
                if path == "/api/tasks":
                    return True
                prefix = "/api/tasks/"
                return path.startswith(prefix) and bool(path[len(prefix):]) and "/" not in path[len(prefix):]

            def _task_request(self, method: str) -> None:
                path = self.path.split("?", 1)[0]
                prefix = "/api/tasks/"
                task_id = path[len(prefix):] if path.startswith(prefix) else None
                payload = {}
                if method in {"POST", "PATCH"}:
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Anfrage muss application/json verwenden"})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length <= 0 or length > 16 * 1024:
                            raise ValueError("Anfrage ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Anfrage muss ein JSON-Objekt sein")
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                query = parse_qs(urlsplit(self.path).query)
                try:
                    status, result = handle_tasks(method, task_id, payload, query)
                except Exception:
                    bus_ref.set("error", "Aufgabenverwaltung fehlgeschlagen")
                    self._json(500, {"error": "Aufgabenverwaltung fehlgeschlagen"})
                    return
                self._json(status, result)

            @staticmethod
            def _is_resource_path(path: str, base: str) -> bool:
                return path == base or (
                    path.startswith(base + "/") and bool(path[len(base) + 1:])
                    and "/" not in path[len(base) + 1:]
                )

            def _resource_request(self, method: str, base: str, handler) -> None:
                path = self.path.split("?", 1)[0]
                identifier = path[len(base) + 1:] if path.startswith(base + "/") else None
                payload = {}
                if method in {"POST", "PATCH"}:
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Anfrage muss application/json verwenden"})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length <= 0 or length > 64 * 1024:
                            raise ValueError("Anfrage ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Anfrage muss ein JSON-Objekt sein")
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                try:
                    status, result = handler(
                        method, identifier, payload, parse_qs(urlsplit(self.path).query)
                    )
                except KeyError as exc:
                    self._json(404, {"error": str(exc.args[0])})
                    return
                except (TypeError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(status, result)

            def _config_request(self, method: str) -> None:
                payload = {}
                if method == "PATCH":
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "Anfrage muss application/json verwenden"})
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if length <= 0 or length > 64 * 1024:
                            raise ValueError("Anfrage ist leer oder zu groß")
                        payload = json.loads(self._read_body(length))
                        if not isinstance(payload, dict):
                            raise ValueError("Anfrage muss ein JSON-Objekt sein")
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                try:
                    status, result = handle_config(method, payload)
                except Exception:
                    bus_ref.set("error", "Konfigurationsverwaltung fehlgeschlagen")
                    self._json(500, {"error": "Konfigurationsverwaltung fehlgeschlagen"})
                    return
                self._json(status, result)

            def _readiness(self):
                if handle_readiness is None:
                    return 200, {"status": "ready"}
                try:
                    result = handle_readiness()
                except Exception:
                    return 503, {"status": "not_ready"}
                if isinstance(result, dict):
                    ready = bool(result.get("ready", result.get("status") in {"ok", "ready"}))
                    payload = dict(result)
                    payload.setdefault("status", "ready" if ready else "not_ready")
                    return (200 if ready else 503), payload
                ready = bool(result)
                return (200 if ready else 503), {"status": "ready" if ready else "not_ready"}

            def _read_body(self, length: int) -> bytes:
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Anfrage wurde unvollständig übertragen")
                return body

            def _validate_images(self, images) -> None:
                if not isinstance(images, list) or len(images) > 4:
                    raise ValueError("Ungültige Screenshots")
                max_encoded = ((MAX_IMAGE_BYTES + 2) // 3) * 4
                for item in images:
                    if not isinstance(item, str):
                        raise ValueError("Ungültiger Screenshot")
                    header, separator, encoded = item.partition(",")
                    if not separator or not header.startswith("data:") or not header.endswith(";base64"):
                        raise ValueError("Screenshot muss Base64 enthalten")
                    mime = header[5:-7].casefold()
                    signatures = IMAGE_SIGNATURES.get(mime)
                    if signatures is None:
                        raise ValueError("Nicht unterstütztes Screenshot-Format")
                    if len(encoded) > max_encoded:
                        raise ValueError("Screenshot ist größer als 5 MB")
                    try:
                        decoded = base64.b64decode(encoded, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError("Screenshot enthält ungültiges Base64") from exc
                    if len(decoded) > MAX_IMAGE_BYTES:
                        raise ValueError("Screenshot ist größer als 5 MB")
                    if mime == "image/webp":
                        signature_ok = decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP"
                    else:
                        signature_ok = any(decoded.startswith(signature) for signature in signatures)
                    if not signature_ok:
                        raise ValueError("Screenshot-Daten passen nicht zum Bildformat")

            def _url_matches_request_origin(self, value: str) -> bool:
                try:
                    parsed_origin = urlsplit(value)
                    parsed_host = urlsplit("//" + self.headers.get("Host", ""))
                    expected_scheme = "https" if isinstance(self.connection, ssl.SSLSocket) else "http"
                    default_port = 443 if expected_scheme == "https" else 80
                    return (
                        parsed_origin.scheme.casefold() == expected_scheme
                        and parsed_origin.username is None
                        and parsed_origin.password is None
                        and bool(parsed_origin.hostname)
                        and parsed_origin.hostname.casefold() == (parsed_host.hostname or "").casefold()
                        and (parsed_origin.port or default_port) == (parsed_host.port or default_port)
                    )
                except ValueError:
                    return False

            def _trusted_browser_request(self) -> bool:
                """Reject cross-site browsers while preserving native/curl clients."""
                try:
                    request_host = urlsplit("//" + self.headers.get("Host", "")).hostname
                except ValueError:
                    return False
                if not request_host or request_host.casefold() not in trusted_hosts:
                    return False
                if self.headers.get("Sec-Fetch-Site", "").casefold() == "cross-site":
                    return False
                origin = self.headers.get("Origin")
                if origin is not None and not self._url_matches_request_origin(origin):
                    return False
                referer = self.headers.get("Referer")
                if referer is not None and not self._url_matches_request_origin(referer):
                    return False
                return True

            def _acquire_request_slot(self) -> bool:
                if self.server.request_slots.acquire(blocking=False):
                    return True
                self._json(
                    429,
                    {"error": "EVE verarbeitet gerade zu viele Anfragen"},
                    {"Retry-After": "1"},
                )
                return False

            def _json(self, status, payload, extra_headers=None):
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                for name, value in (extra_headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _binary(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def end_headers(self):
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                super().end_headers()

            def _authorized(self):
                if not required_token or self.headers.get("X-EVE-Token", "") == required_token:
                    return True
                self._json(401, {"error": "Zugriffstoken fehlt oder ist ungültig"})
                return False

            def _chatto_request(self):
                if handle_chatto is None or not chatto_token:
                    self._json(404, {"error": "Chatto is disabled"})
                    return
                supplied = self.headers.get("Authorization", "")
                if not hmac.compare_digest(supplied.encode(), ("Bearer " + chatto_token).encode()):
                    self._json(401, {"error": "Chatto token required"})
                    return
                try:
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "application/json required"})
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 30 * 1024 * 1024:
                        raise ValueError("Invalid Chatto request size")
                    payload = json.loads(self._read_body(length))
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object required")
                    path = self.path.split("?", 1)[0]
                    if path == "/api/chatto/output-rooms":
                        self._json(200, handle_chatto.register_output_rooms(payload))
                    elif path == "/api/chatto/deliveries":
                        self._json(200, handle_chatto.deliveries(payload))
                    elif path == "/api/chatto/delivery-ack":
                        self._json(200, handle_chatto.delivery_ack(payload))
                    elif path == "/api/chatto/conversations":
                        self._json(201, handle_chatto.create_conversation(payload))
                    elif path == "/api/chatto/conversation":
                        self._validate_images(payload.get("images", []))
                        self._json(200, handle_chatto.conversation(payload))
                    elif path == "/api/chatto/activity":
                        self._json(200, handle_chatto.activity(payload))
                    elif path == "/api/chatto/observe":
                        self._json(200, handle_chatto.observe(payload))
                    else:
                        self._json(404, {"error": "Unknown Chatto operation"})
                except PermissionError as exc:
                    self._json(403, {"error": str(exc)})
                except (ValueError, TypeError):
                    self._json(400, {"error": "Invalid Chatto request"})
                except KeyError:
                    self._json(404, {"error": "Chatto conversation not found"})
                except Exception:
                    self._json(503, {"error": "Chatto turn failed"})

            def _assist_authorized(self):
                if handle_assist is None or not assist_token:
                    self._json(404, {"error": "Assist-API ist nicht aktiviert"})
                    return False
                supplied = self.headers.get("Authorization", "")
                if not hmac.compare_digest(supplied.encode(), ("Bearer " + assist_token).encode()):
                    self._json(401, {"error": "Assist-Token fehlt oder ist ungültig"})
                    return False
                return True

            def _assist_request(self):
                if not self._assist_authorized():
                    return
                path = self.path.split("?", 1)[0]
                try:
                    limit = 30 * 1024 * 1024 if path == "/api/assist/stt" else 25 * 1024 * 1024
                    if path == "/api/assist/events":
                        limit = 65536
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= limit:
                        raise ValueError("Ungültige Anfragegröße")
                    body = self._read_body(length)
                    if path == "/api/assist/stt":
                        if self.headers.get_content_type() != "application/octet-stream":
                            self._json(415, {"error": "STT erwartet PCM als application/octet-stream"})
                            return
                        language = parse_qs(urlsplit(self.path).query).get("language", [""])[0]
                        self._json(200, handle_assist.transcribe(body, language))
                        return
                    if self.headers.get_content_type() != "application/json":
                        self._json(415, {"error": "application/json erforderlich"})
                        return
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError("JSON-Objekt erforderlich")
                    if path == "/api/assist/conversations":
                        self._json(201, handle_assist.create_conversation())
                    elif path == "/api/assist/conversation":
                        self._validate_images(payload.get("images", []))
                        self._json(200, handle_assist.conversation(payload))
                    elif path == "/api/assist/events":
                        self._json(202, handle_assist.receive_event(payload))
                    elif path == "/api/assist/tts":
                        self._binary(200, handle_assist.synthesize(payload), "audio/wav")
                    else:
                        self._json(404, {"error": "Unbekannte Assist-Operation"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                except KeyError:
                    self._json(404, {"error": "EVE-Unterhaltung nicht gefunden"})
                except Exception as exc:
                    self._json(503, {"error": redact_sensitive(str(exc))})

            def log_message(self, *args):
                pass

        server_kwargs = {
            "max_connections": max_connections,
            "max_concurrent_requests": max_concurrent_requests,
        }
        self.scheme = "http"
        if tls_cert and tls_key:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(tls_cert), str(tls_key))

            class TLSEveHTTPServer(EveHTTPServer):
                def get_request(inner_self):
                    # Accept first and defer the TLS handshake to the request
                    # thread. A client that opens TCP without completing TLS can
                    # therefore no longer block the server's accept loop.
                    raw_socket, address = inner_self.socket.accept()
                    try:
                        tls_socket = context.wrap_socket(
                            raw_socket,
                            server_side=True,
                            do_handshake_on_connect=False,
                        )
                        tls_socket.settimeout(30)
                        return tls_socket, address
                    except Exception:
                        raw_socket.close()
                        raise

            self.server = TLSEveHTTPServer((host, port), Handler, **server_kwargs)
            self.scheme = "https"
        else:
            self.server = EveHTTPServer((host, port), Handler, **server_kwargs)
        self.port = int(self.server.server_address[1])

    @property
    def url(self) -> str:
        display_host = "127.0.0.1" if self.host == "0.0.0.0" else self.host
        return f"{self.scheme}://{display_host}:{self.port}/"

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("VisualServer wurde bereits geschlossen")
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self.server.serve_forever,
                kwargs={"poll_interval": .1},
                name="eve-visual-server",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            thread = self._thread
            if thread and thread.is_alive():
                self.server.shutdown()
            self.server.server_close()
            self._closed = True
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
