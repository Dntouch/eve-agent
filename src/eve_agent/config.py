from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """Raised when EVE's technical configuration is invalid."""


REMOVED_ARTIFICIAL_LIMITS: dict[str, frozenset[str]] = {
    "memory": frozenset({
        "retrieval_limit",
        "compiler_planner_budget",
        "compiler_answer_budget",
        "compiler_candidate_limit",
        "compiler_native_budget",
        "compiler_audit_budget",
        "compiler_relation_limit",
    }),
    "conversation": frozenset({"inactivity_timeout_minutes"}),
    "web": frozenset({"results", "read_pages", "page_chars"}),
}


DEFAULTS: dict[str, Any] = {
    "llm": {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model", "api_key": "local", "timeout_seconds": 180, "use_server_limits": True, "max_tokens": 500, "output_language": "auto"},
    "speech_to_text": {"model": "small", "language": "de", "device": "auto", "compute_type": "auto", "initial_prompt": "", "hotwords": ""},
    "audio": {"input_device_contains": "", "sample_rate": 16000, "channels": 1},
    "text_to_speech": {"engine": "piper", "language": "", "voice": "de_DE-eve-medium", "data_dir": "voices", "reference_audio": "", "qwen3_tts_url": "http://127.0.0.1:8812", "chatterbox_url": "http://127.0.0.1:8811", "piper_chunk_chars": 700, "length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8, "volume": 1.0, "llm_rewrite": False},
    "visual": {"host": "127.0.0.1", "port": 8790, "open_browser": True, "public_host": "", "allowed_hosts": [], "tls_cert": "", "tls_key": "", "max_connections": 32, "max_concurrent_requests": 8},
    "memory": {},
    "memory_search": {"backend": "local_onnx", "model": "", "model_dir": "data/models/multilingual-e5-small", "threads": 2, "timeout_seconds": 60, "query_prefix": "query: ", "document_prefix": "passage: "},
    "conversation_learning": {
        "enabled": True,
        "idle_delay_seconds": 120,
        "batch_size": 2,
    },
    "working_memory": {
        "cleanup_enabled": True,
        "completed_retention_hours": 1.0,
        "failed_retention_hours": 24.0,
        "temporary_learning_retention_hours": 0.25,
        "cleanup_interval_minutes": 15,
    },
    "memory_runtime_telemetry": {
        "enabled": False,
        "lifecycle_audit": "required",
        "contract_version": "memory-runtime-events-v1",
        "retention_days": 30,
        "max_detail_bytes": 4096,
    },
    "semantic_similarity": {"enabled": True, "mode": "active", "threshold": 0.85},
    "semantic_composition": {
        "enabled": True, "mode": "active", "min_support_roots": 2,
        "max_tokens": 64, "max_fields": 32, "max_lookup_candidates": 512,
        "max_shapes": 8, "max_support_scan": 20000, "max_update_pairs": 200000,
    },
    "conversation": {},
    "assist_api": {"enabled": False, "token": ""},
    "chatto": {
        "enabled": False, "server_url": "https://chat.example.org", "api_key": "",
        "node_executable": "node", "owner_user_id": "", "owner_dm_enabled": True,
        "member_dm_enabled": False, "show_member_dms_in_web": False,
        "show_owner_dms_in_web": True, "show_channels_in_web": True,
        "channel_ids": [], "reply_mode": "chat", "channel_mentions_only": True,
        "presence_enabled": True, "thread_status_enabled": True, "channel_learning_ids": [],
        "channel_capabilities": ["memory", "semantic_learning", "working_memory", "web", "clock", "calculator"],
    },
    "nova_maintenance": {"enabled": False, "command": "codex", "transport": "isolated", "shared_chat_socket": "", "shared_chat_timeout_seconds": 900, "bwrap_command": "bwrap", "timeout_seconds": 180, "verification_timeout_seconds": 180, "pending_ttl_seconds": 600, "require_process_isolation": True, "max_context_records": 20, "max_jobs": 20},
    "web": {"enabled": False, "searxng_url": "http://127.0.0.1:8888", "image_results": 4, "timeout_seconds": 12, "max_page_bytes": 5_000_000, "max_pdf_bytes": 50 * 1024 * 1024},
    "image_generation": {"enabled": False, "api_format": "sdapi", "base_url": "http://127.0.0.1:1235", "api_key": "", "model": "", "width": 1024, "height": 1024, "steps": 4, "guidance_scale": 1.0, "timeout_seconds": 3600, "extra_parameters": {}},
    "home_assistant": {"enabled": False, "url": "", "token": "", "language": "de", "timeout_seconds": 12},
    "network_tools": {"enabled": False, "subnet": "192.168.0.0/16", "image": "docker.io/instrumentisto/nmap:latest", "timeout_seconds": 35},
    "storage": {"data_path": "data/assets", "cache_path": "runtime/cache"},
    "local_files": {"roots": []},
    "shell": {"enabled": False, "executable": "/bin/bash", "forbidden_commands": ["rm -rf"]},
    "mcp": {"servers": {}, "max_sessions": 8},
    "wayland_computer": {"enabled": False, "env": {}},
    "paths": {"database": "data/eve.db", "runtime": "runtime", "web": "web"},
}


ENVIRONMENT_FIELDS: dict[str, tuple[str, str]] = {
    "EVE_IMAGE_API_KEY": ("image_generation", "api_key"),
    "EVE_CHATTO_BOT_KEY": ("chatto", "api_key"),
    "EVE_ASSIST_TOKEN": ("assist_api", "token"),
    "EVE_LLM_BASE_URL": ("llm", "base_url"), "EVE_LLM_MODEL": ("llm", "model"),
    "EVE_LLM_API_KEY": ("llm", "api_key"), "EVE_HOME_ASSISTANT_URL": ("home_assistant", "url"),
    "EVE_HOME_ASSISTANT_TOKEN": ("home_assistant", "token"), "EVE_WEB_SEARXNG_URL": ("web", "searxng_url"),
    "EVE_STT_MODEL": ("speech_to_text", "model"), "EVE_PIPER_VOICE": ("text_to_speech", "voice"),
    "EVE_PIPER_DATA_DIR": ("text_to_speech", "data_dir"), "EVE_STORAGE_DATA_PATH": ("storage", "data_path"),
    "EVE_STORAGE_CACHE_PATH": ("storage", "cache_path"),
}

UI_SECTIONS = (
    ("image_generation", "Bildgenerierung"),
    ("chatto", "Chatto"),
    ("assist_api", "Home Assistant Assist"),
    ("conversation_learning", "Lernen aus Gesprächen"),
    ("working_memory", "Kurzzeitgedächtnis"),
    ("semantic_similarity", "Dynamische Semantik"),
    ("semantic_composition", "Differenzielle Komposition"),
    ("home_assistant", "Home Assistant"), ("llm", "LLM"),
    ("speech_to_text", "STT"), ("text_to_speech", "TTS / Piper"),
    ("web", "Web"), ("nova_maintenance", "Nova"), ("conversation", "Unterhaltungen"),
    ("local_files", "Lokaler Dateizugriff"),
    ("mcp", "Integrationen"),
    ("wayland_computer", "Wayland Desktop"), ("shell", "Shellzugriff"),
)

# This is both the API allowlist and the rendering description. The browser
# never needs to duplicate defaults, validation rules, or config paths.
UI_FIELDS: dict[str, dict[str, Any]] = {
    "image_generation.enabled": {"label": "Bildgenerierung aktiviert", "type": "boolean", "description": "Separaten Bildserver anbinden. Änderungen nach EVE-Neustart wirksam."},
    "image_generation.api_format": {"label": "API-Format", "type": "select", "options": ["sdapi", "openai"], "description": "sdapi: /sdapi/v1/txt2img; openai: /images/generations relativ zur Basis-URL."},
    "image_generation.base_url": {"label": "Bildserver", "type": "text", "description": "Zum Beispiel http://127.0.0.1:1235 für sdapi; bei OpenAI-kompatiblen Servern gegebenenfalls /v1 anhängen. CPU/GPU wird am Bildserver eingestellt."},
    "image_generation.model": {"label": "Modell", "type": "text", "description": "Modellname für OpenAI-kompatible APIs. sdapi verwendet das am Server geladene Modell."},
    "image_generation.width": {"label": "Bildbreite", "type": "integer", "min": 64, "max": 4096, "description": "Standard in Pixeln; Vielfaches von 64. Größenangaben im Chat gelten nur für den jeweiligen Auftrag."},
    "image_generation.height": {"label": "Bildhöhe", "type": "integer", "min": 64, "max": 4096, "description": "Standard in Pixeln; Vielfaches von 64. Größenangaben im Chat gelten nur für den jeweiligen Auftrag."},
    "image_generation.steps": {"label": "Schritte", "type": "integer", "min": 1, "max": 150, "description": "Sampling-Schritte für sdapi."},
    "image_generation.guidance_scale": {"label": "Guidance", "type": "number", "min": 0, "max": 30, "step": 0.1, "description": "CFG-Skala für sdapi; modellabhängig."},
    "image_generation.timeout_seconds": {"label": "Zeitlimit (Sekunden)", "type": "integer", "min": 10, "max": 86400, "description": "Auch lange CPU-Aufträge laufen im Hintergrund. Status und fertiges Bild im Gespräch abrufen; keine automatische Fertigmeldung."},
    "image_generation.extra_parameters": {"label": "Zusätzliche Serverparameter", "type": "json", "description": "JSON-Objekt, etwa sampler_name oder seed. Nur Parameter verwenden, die der Bildserver unterstützt. Änderungen nach EVE-Neustart."},
    "mcp.max_sessions": {"label": "Maximale Sitzungen", "type": "integer", "min": 1, "max": 64, "description": "Maximal gleichzeitig gestartete externe MCP-Prozesse. Kein automatisches Verwerfen ungespeicherter Sitzungen; nach Neustart wirksam."},
    "mcp.servers": {"label": "MCP-Server", "type": "json", "description": "Server als JSON: command, args, env, cwd, scope (conversation/shared), timeout_seconds, description, attachment_roots. Platzhalter: {root}, {workspace}. Änderungen nach Neustart. Zugangsdaten über die Prozessumgebung setzen. Siehe docs/MCP.md."},
    "chatto.enabled": {"label": "Chatto aktiviert", "type": "boolean", "description": "Bot zusammen mit EVE starten und stoppen. Änderungen werden beim Speichern übernommen; EVE läuft weiter."},
    "chatto.server_url": {"label": "Chatto-Server", "type": "text", "description": "HTTPS-Adresse des Chatto-Servers."},
    "chatto.node_executable": {"label": "Node-Programm", "type": "text", "description": "Node 22.13 oder neuer; Programmname oder absoluter Pfad."},
    "chatto.owner_user_id": {"label": "Eigentümer-Konto-ID", "type": "text", "description": "Feste Chatto-ID für persönliche DMs. Anzeigenamen dürfen sich ändern."},
    "chatto.owner_dm_enabled": {"label": "Persönliche DMs aktiviert", "type": "boolean", "description": "Nur Zweier-DMs mit dem konfigurierten Bot-Eigentümer; bestehende persönliche Werkzeugrechte."},
    "chatto.thread_status_enabled": {"label": "Arbeitsstatus in Threads anzeigen", "type": "boolean", "description": "Während der Bearbeitung eine sichtbare Statusnachricht im Thread anzeigen und bei Abschluss oder Fehler aktualisieren."},
    "chatto.presence_enabled": {"label": "Online-Status anzeigen", "type": "boolean", "description": "Online melden, solange der Bot verbunden ist. Beim Stoppen offline; bei Verbindungsabbruch verfällt der Status automatisch nach etwa 60 Sekunden."},
    "chatto.channel_ids": {"label": "Freigegebene Channels", "type": "string_list", "description": "Nur ausgewählte Channels verarbeiten. Neue Räume werden alle 30 Sekunden eingelesen; Auswahl durch erneutes Öffnen der Konfiguration aktualisieren. Änderungen gelten ab der nächsten Nachricht."},
    "chatto.channel_mentions_only": {"label": "Im Channel nur auf Erwähnungen antworten", "type": "boolean", "description": "Deaktiviert: alle neuen Textnachrichten in freigegebenen Channels verarbeiten. Bot-Nachrichten werden ignoriert."},
    "chatto.channel_learning_ids": {"label": "Mitlernkanäle", "type": "string_list", "description": "In diesen ebenfalls freigegebenen Channels auch ohne @EVE still aus neuen Textnachrichten mitlernen. Keine Antworten oder Werkzeugaktionen. Leere Auswahl: kein stilles Mitlernen."},
    "chatto.member_dm_enabled": {"label": "Private Chats für andere Mitglieder", "type": "boolean", "description": "Andere menschliche Mitglieder dürfen EVE im Zweierchat anschreiben. Getrennte Gesprächsverläufe; nur Gedächtnis, Bedeutungslernen, Arbeitsgedächtnis, Web, Uhrzeit und Rechner. Deine persönliche DM behält ihre bisherigen Rechte."},
    "chatto.show_member_dms_in_web": {"label": "Private Mitglieder-Chats im Webfrontend anzeigen", "type": "boolean", "description": "Private Chatto-Unterhaltungen anderer Mitglieder in der Gesprächsliste anzeigen. Standardmäßig ausgeblendet. Verläufe und Lernen bleiben erhalten. Gilt beim nächsten Laden der Liste ohne Neustart."},
    "chatto.show_owner_dms_in_web": {"label": "Eigene Chatto-DMs im Webfrontend anzeigen", "type": "boolean", "description": "Persönliche Eigentümer-DMs in der Gesprächsliste anzeigen. Gilt beim nächsten Laden der Liste ohne Neustart; Speicherung und Lernen bleiben erhalten."},
    "chatto.show_channels_in_web": {"label": "Chatto-Channels im Webfrontend anzeigen", "type": "boolean", "description": "Channel-Unterhaltungen in der Gesprächsliste anzeigen. Gilt beim nächsten Laden der Liste ohne Neustart; Speicherung und Lernen bleiben erhalten."},
    "chatto.reply_mode": {"label": "Antwortmodus", "type": "select", "options": ["chat", "thread"], "description": "chat: direkt im Chat; thread: als Thread-Antwort."},
    "chatto.channel_capabilities": {"label": "Erlaubte Channel-Werkzeuge", "type": "string_list", "description": "Technische Freigabeliste. Standard: memory, semantic_learning, working_memory, web, clock, calculator. Haus-, Datei-, Shell-, Desktop-, Netzwerk- und Auftragszugriff sind damit gesperrt. Persönliche DMs bleiben unverändert."},
    "assist_api.enabled": {"label": "Assist-API aktiviert", "type": "boolean", "description": "Conversation, STT und TTS für Home Assistant; nach Neustart wirksam."},

    "shell.enabled": {
        "label": "Aktiviert", "type": "boolean",
        "description": "Shellbefehle mit den Linux-Rechten des EVE-Prozesses ausführen; sofort wirksam.",
    },
    "shell.executable": {
        "label": "Shellprogramm", "type": "text",
        "description": "Programm für neue Shellprozesse, beispielsweise /bin/bash. Aufruf mit -c.",
    },
    "shell.forbidden_commands": {
        "label": "Verbotene Befehle", "type": "string_list", "placeholder": "rm -rf",
        "description": "Eine gesperrte Wortfolge pro Zeile. Leerzeichen, Anführungszeichen und kurze Optionsgruppen werden normalisiert: rm -rf sperrt auch rm -fr und rm -r -f. Leere Liste erlaubt alle Befehle. Prüft übergebenen Text, nicht indirekte Skriptwirkungen; keine Isolation.",
    },
    "wayland_computer.enabled": {
        "label": "Aktiviert", "type": "boolean",
        "description": "Eigene Wayland-MCP-Capability mit den regulären Desktop-Portal-Freigaben; nach Neustart wirksam.",
    },
    "conversation_learning.enabled": {
        "label": "Gesprächslernen aktiviert", "type": "boolean",
        "description": "Sammelt abgeschlossene Turns als Evidenz und lässt Qwen sie gebündelt während einer Leerlaufphase für Memory auswerten.",
    },
    "conversation_learning.idle_delay_seconds": {
        "label": "Leerlauf vor Lernbeginn", "type": "integer", "min": 5, "max": 86400,
        "description": "Sekunden ohne neue Benutzeraktivität, bevor EVE offene Gesprächsevidenz gebündelt auswertet. Neue Eingaben pausieren einen laufenden Lernvorgang.",
    },
    "conversation_learning.batch_size": {
        "label": "Turns pro Lernpaket", "type": "integer", "min": 1, "max": 32,
        "description": "Anzahl offener Turns pro Lernpaket. Jeder Turn wird einzeln bewertet und sofort abgeschlossen, bevor der nächste beginnt.",
    },
    "working_memory.cleanup_enabled": {
        "label": "Automatisch bereinigen", "type": "boolean",
        "description": "Entfernt abgelaufene, nicht angeheftete Arbeitsstände aus der Datenbank. Laufende Vorgänge und Werkzeugaufrufe mit unklarem Ausgang bleiben geschützt.",
    },
    "working_memory.completed_retention_hours": {
        "label": "Erfolgreiche Arbeitsstände", "type": "number", "min": 0.01, "max": 8760, "step": "any",
        "description": "Stunden, die erfolgreich abgeschlossene, nicht angeheftete Arbeitsstände nach der letzten Nutzung erhalten bleiben.",
    },
    "working_memory.failed_retention_hours": {
        "label": "Fehlgeschlagene Arbeitsstände", "type": "number", "min": 0.01, "max": 8760, "step": "any",
        "description": "Stunden, die abgebrochene oder fehlgeschlagene Arbeitsstände für Diagnose und Wiederaufnahme erhalten bleiben.",
    },
    "working_memory.temporary_learning_retention_hours": {
        "label": "Temporäre Lernmaterialien", "type": "number", "min": 0.01, "max": 8760, "step": "any",
        "description": "Stunden, die große ausgelagerte Lernmaterialien nach einem erfolgreichen Lernlauf erhalten bleiben.",
    },
    "working_memory.cleanup_interval_minutes": {
        "label": "Bereinigungsintervall", "type": "integer", "min": 1, "max": 1440,
        "description": "Minuten zwischen automatischen Prüfungen. Zusätzlich prüft EVE beim Start.",
    },
    "semantic_similarity.enabled": {
        "label": "Ähnlichkeitswiederverwendung aktiviert", "type": "boolean",
        "description": "Pflegt formal ähnliche, bestätigte Formulierungen als Beziehungen ausschließlich in der Memory-Datenbank.",
    },
    "semantic_similarity.mode": {
        "label": "Modus", "type": "select", "options": ["active", "shadow"],
        "description": "Active pflegt bestätigte Beziehungen im Memory; Shadow beobachtet und protokolliert Kandidaten nur.",
    },
    "semantic_similarity.threshold": {
        "label": "Formale Ähnlichkeitsschwelle", "type": "number",
        "min": 0.5, "max": 1.0, "step": 0.01,
        "description": "Zeichenbasierte Freigabegrenze, keine semantische Wahrscheinlichkeit.",
    },
    "semantic_composition.enabled": {
        "label": "Differenzielle Komposition aktiviert", "type": "boolean",
        "description": "Pflegt aus bestätigten Memory-Belegen abgeleitete Beziehungen ausschließlich in der Memory-Datenbank.",
    },
    "semantic_composition.mode": {
        "label": "Modus", "type": "select", "options": ["active", "shadow"],
        "description": "Active pflegt belegte Beziehungen im Memory; Shadow wertet Kandidaten nur aus.",
    },
    "home_assistant.enabled": {
        "label": "Aktiviert", "type": "boolean",
        "description": "Verbindet EVE nach dem Neustart mit Home Assistant.",
    },
    "home_assistant.url": {
        "label": "URL", "type": "url",
        "description": "Vom EVE-Rechner erreichbare Basisadresse der Home-Assistant-Instanz.",
    },
    "home_assistant.language": {
        "label": "Sprache der Entitäten", "type": "text", "suggestions": ["de", "en"],
        "description": "Sprachcode für Namen, Aliasbildung und das gelernte HA-Inventar.",
    },
    "home_assistant.timeout_seconds": {
        "label": "Timeout (Sekunden)", "type": "integer", "min": 1, "max": 300,
        "description": "Maximale Wartezeit je Home-Assistant-Netzwerkanfrage.",
    },
    "llm.base_url": {
        "label": "API-URL", "type": "url",
        "description": "Basisadresse des tatsächlich verwendeten OpenAI-kompatiblen Modellservers.",
    },
    "llm.model": {
        "label": "Modell", "type": "text",
        "description": "Modellkennung, die EVE bei jedem LLM-Aufruf an den Server sendet.",
    },
    "llm.timeout_seconds": {
        "label": "Timeout (Sekunden)", "type": "integer", "min": 1, "max": 900,
        "description": "Maximale Wartezeit eines einzelnen LLM-Netzwerkaufrufs.",
    },
    "llm.use_server_limits": {
        "label": "Modellgrenzen vom Server übernehmen", "type": "boolean",
        "description": "Verwendet die tatsächlich geladene LM-Studio-Kontextgröße und überlässt das Ausgabelimit dem Modellserver. Das manuelle Tokenbudget dient nur als Fallback, wenn diese Option deaktiviert ist.",
    },
    "llm.max_tokens": {
        "label": "Manuelles Ausgabe-Fallback", "type": "integer", "min": 1, "max": 100000,
        "description": "Maximale Ausgabetokens nur bei deaktivierter automatischer Servergrenze.",
    },
    "speech_to_text.model": {
        "label": "Whisper-Modell", "type": "text",
        "suggestions": [
            "tiny", "tiny.en", "base", "base.en", "small", "small.en",
            "medium", "medium.en", "large-v1", "large-v2", "large-v3",
            "large", "large-v3-turbo", "turbo", "distil-small.en",
            "distil-medium.en", "distil-large-v2", "distil-large-v3",
            "distil-large-v3.5",
        ],
        "description": "Faster-Whisper-Modellgröße, lokaler Modellpfad oder Hugging-Face-Modell-ID.",
    },
    "speech_to_text.language": {
        "label": "Gesprochene Sprache", "type": "text", "suggestions": ["de", "en", "fr", "es", "it", "nl"],
        "description": "Whisper-Sprachcode der erwarteten Sprache, zum Beispiel de oder en.",
    },
    "speech_to_text.device": {
        "label": "Rechengerät", "type": "select", "options": ["auto", "cpu", "cuda"],
        "description": "Hardware, auf der Faster Whisper das Modell ausführt.",
    },
    "speech_to_text.compute_type": {
        "label": "Rechentyp", "type": "select",
        "options": ["auto", "default", "int8", "int8_float32", "int8_float16", "int8_bfloat16", "int16", "float16", "float32", "bfloat16"],
        "description": "Numerisches Format für Geschwindigkeit, Speicherbedarf und Hardwarekompatibilität.",
    },
    "speech_to_text.initial_prompt": {
        "label": "Erkennungskontext", "type": "text",
        "description": "Kurzer Startkontext für Schreibweisen, Domäne und erwartete Begriffe.",
    },
    "speech_to_text.hotwords": {
        "label": "Bevorzugte Begriffe", "type": "text",
        "description": "Zusätzliche seltene Wörter; gelernte Geräte-Aliase ergänzt EVE zur Laufzeit automatisch.",
    },
    "text_to_speech.engine": {
        "label": "Engine", "type": "select", "options": ["piper", "auto", "qwen3_tts", "chatterbox", "spd-say", "espeak-ng"],
        "description": "System, das Eves Antworten nach dem Neustart in Audio umwandelt.",
    },
    "text_to_speech.voice": {
        "label": "Stimme", "type": "text",
        "description": "Piper-Modellname; bei System-Engines wird der Wert als Sprach-/Stimmenkennung genutzt.",
    },
    "text_to_speech.data_dir": {
        "label": "Piper-Stimmenverzeichnis", "type": "path",
        "description": "Ordner mit der gewählten .onnx-Stimme und ihrer .onnx.json-Datei.",
    },
    "text_to_speech.piper_chunk_chars": {
        "label": "Piper-Chunk-Größe", "type": "integer", "min": 200, "max": 2000,
        "description": "Ungefähre Textlänge je Piper-Syntheseabschnitt bei längeren Antworten.",
    },
    "text_to_speech.language": {
        "label": "TTS-Sprachcode", "type": "text",
        "description": "Optionaler Sprachcode für TTS-Dienste; leer lässt den Dienst selbst entscheiden.",
    },
    "web.enabled": {
        "label": "Aktiviert", "type": "boolean",
        "description": "Stellt Qwen nach dem Neustart die echte Webrecherche als natives Werkzeug bereit.",
    },
    "web.searxng_url": {
        "label": "SearXNG-URL", "type": "url",
        "description": "Basisadresse der von EVE tatsächlich abgefragten SearXNG-Instanz.",
    },
    "web.image_results": {
        "label": "Bilder pro Suche", "type": "integer", "min": 1, "max": 8,
        "description": "Maximale Zahl gültiger Bilder aus einer Bildsuche.",
    },
    "web.timeout_seconds": {
        "label": "Timeout (Sekunden)", "type": "integer", "min": 1, "max": 300,
        "description": "Maximale Wartezeit je Suche, Seitenabruf oder Bildabruf.",
    },
    "web.max_page_bytes": {
        "label": "Maximale Seitengröße (Bytes)", "type": "integer", "min": 750_000, "max": 20_000_000,
        "description": "Abruflimit für HTML- und Textseiten vor der Textextraktion. Für PDFs gilt die eigene PDF-Größengrenze.",
    },
    "web.max_pdf_bytes": {
        "label": "Maximale PDF-Größe (Bytes)", "type": "integer", "min": 750_000, "max": 200 * 1024 * 1024,
        "description": "Abruflimit für PDF-Dokumente vor der Textextraktion; standardmäßig 50 MiB (52.428.800 Bytes).",
    },
    "nova_maintenance.enabled": {
        "label": "Aktiviert", "type": "boolean",
        "description": "Schaltet den isolierten lokalen Wartungsweg über Nova nach dem Neustart frei.",
    },
    "nova_maintenance.command": {
        "label": "Befehl", "type": "text",
        "description": "Ausführbare Datei, mit der Nova lokale Wartungsaufträge startet.",
    },
    "nova_maintenance.transport": {
        "label": "Auftragsweg", "type": "text",
        "description": "shared_chat: sichtbarer Codex-Projektchat; isolated: bisheriger Hintergrundauftrag. Nach Neustart wirksam.",
    },
    "nova_maintenance.shared_chat_socket": {
        "label": "Gemeinsamer Codex-Socket", "type": "text",
        "description": "Leer verwendet den lokalen Codex-Standardsocket. Keine Netzwerkadresse.",
    },
    "nova_maintenance.timeout_seconds": {
        "label": "Timeout (Sekunden)", "type": "integer", "min": 15, "max": 900,
        "description": "Maximale Laufzeit eines Nova-Wartungsauftrags.",
    },
    "local_files.roots": {
        "label": "Freigegebene Root-Verzeichnisse", "type": "path_list",
        "description": "Ein absoluter, sofort wirksamer Lesebereich pro Zeile; Unterordner sind eingeschlossen.",
    },
}

UI_SECRETS = {
    "image_generation.api_key": {"label": "Bildserver-Schlüssel", "environment": "EVE_IMAGE_API_KEY", "description": "Optional. Privat in .env gespeichert; für lokale Server meist leer."},
    "chatto.api_key": {"label": "Bot-Schlüssel", "environment": "EVE_CHATTO_BOT_KEY", "description": "Hier setzen oder ersetzen. Speicherung privat in .env; der hinterlegte Wert wird nicht angezeigt."},
    "assist_api.token": {"label": "Assist-Token", "environment": "EVE_ASSIST_TOKEN", "description": "Separater Zugriffstoken für Home Assistant."},

    "home_assistant.token": {
        "label": "Access Token", "environment": "EVE_HOME_ASSISTANT_TOKEN",
        "description": "Geheimer langlebiger Zugriffsschlüssel für die konfigurierte Home-Assistant-Instanz.",
    },
    "llm.api_key": {
        "label": "API-Key", "environment": "EVE_LLM_API_KEY",
        "description": "Authentifizierungsschlüssel des Modellservers; lokale Server benötigen oft nur einen Platzhalter.",
    },
}


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"Ungültige .env-Zeile {number}")
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or not name.replace("_", "A").isalnum():
            raise ConfigError(f"Ungültiger .env-Name in Zeile {number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _url(value: Any, label: str, *, required: bool = True) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text and not required:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{label} muss eine vollständige HTTP(S)-URL sein")
    return text


def _integer(section: dict, key: str, low: int, high: int, label: str) -> None:
    value = section.get(key)
    if isinstance(value, bool):
        raise ConfigError(f"{label} muss eine Zahl zwischen {low} und {high} sein")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} muss eine Zahl zwischen {low} und {high} sein") from exc
    if not low <= number <= high:
        raise ConfigError(f"{label} muss zwischen {low} und {high} liegen")
    section[key] = number


def _resolve_path(root: Path, value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text:
        raise ConfigError(f"{label} ist kein verwendbarer Pfad")
    path = Path(text).expanduser()
    return str((path if path.is_absolute() else root / path).resolve(strict=False))


def _validate(root: Path, config: dict[str, Any]) -> None:
    image = config["image_generation"]
    if not isinstance(image, dict) or not isinstance(image.get("enabled"), bool):
        raise ConfigError("image_generation.enabled muss boolesch sein")
    if not isinstance(image.get("api_format"), str) or image["api_format"] not in {"sdapi", "openai"}:
        raise ConfigError("image_generation.api_format muss sdapi oder openai sein")
    image["base_url"] = _url(image.get("base_url"), "image_generation.base_url")
    parsed_image = urlparse(image["base_url"])
    if parsed_image.username or parsed_image.password or parsed_image.query or parsed_image.fragment:
        raise ConfigError("image_generation.base_url darf keine Zugangsdaten, Query oder Fragment enthalten")
    for key in ("model", "api_key"):
        if not isinstance(image.get(key), str) or any(c in image[key] for c in "\x00\r\n"):
            raise ConfigError("image_generation." + key + " ist ungültig")
    for key, low, high in (("width", 64, 4096), ("height", 64, 4096), ("steps", 1, 150), ("timeout_seconds", 10, 86400)):
        _integer(image, key, low, high, "image_generation." + key)
    if image["width"] % 64 or image["height"] % 64:
        raise ConfigError("Bildmaße müssen Vielfache von 64 sein")
    guidance = image.get("guidance_scale")
    if isinstance(guidance, bool) or not isinstance(guidance, (float, int)) or not 0 <= guidance <= 30:
        raise ConfigError("image_generation.guidance_scale muss zwischen 0 und 30 liegen")
    if not isinstance(image.get("extra_parameters"), dict):
        raise ConfigError("image_generation.extra_parameters muss ein JSON-Objekt sein")
    if set(image["extra_parameters"]) & {"prompt", "n", "n_iter", "batch_size", "response_format", "width", "height", "size", "model", "steps", "cfg_scale"}:
        raise ConfigError("Zusätzliche Bildparameter dürfen die Standardfelder nicht überschreiben")
    chatto = config["chatto"]
    if not isinstance(chatto, dict):
        raise ConfigError("chatto muss ein Objekt sein")
    for key in ("enabled", "owner_dm_enabled", "member_dm_enabled", "show_member_dms_in_web", "show_owner_dms_in_web", "show_channels_in_web", "channel_mentions_only", "presence_enabled", "thread_status_enabled"):
        if not isinstance(chatto.get(key), bool):
            raise ConfigError("chatto." + key + " muss boolesch sein")
    chatto["server_url"] = _url(chatto.get("server_url"), "chatto.server_url")
    parsed_chatto = urlparse(chatto["server_url"])
    if parsed_chatto.scheme != "https" or parsed_chatto.path not in {"", "/"} or parsed_chatto.query or parsed_chatto.fragment or parsed_chatto.username:
        raise ConfigError("chatto.server_url muss eine HTTPS-Origin ohne Zugangsdaten sein")
    for key in ("node_executable", "owner_user_id", "api_key"):
        if not isinstance(chatto.get(key), str) or "\x00" in chatto[key] or "\n" in chatto[key] or "\r" in chatto[key]:
            raise ConfigError("chatto." + key + " ist ungültig")
    if not chatto["node_executable"].strip():
        raise ConfigError("chatto.node_executable fehlt")
    if chatto["reply_mode"] not in {"chat", "thread"}:
        raise ConfigError("chatto.reply_mode muss chat oder thread sein")
    for key in ("channel_ids", "channel_capabilities", "channel_learning_ids"):
        if not isinstance(chatto.get(key), list) or any(not isinstance(v, str) or not v.strip() or len(v) > 128 for v in chatto[key]):
            raise ConfigError("chatto." + key + " muss eine Liste nichtleerer Zeichenketten sein")
    known_capabilities = {"memory", "semantic_learning", "working_memory", "web", "image_generation", "clock", "calculator", "home_assistant", "home_assistant_inventory", "local_search", "local_files", "shell", "nova", "wayland_computer", "network", "scheduled_tasks", "work_tasks", "assist_events", "presentation"}
    from .external_mcp import validate_servers
    if not isinstance(config.get("mcp"), dict):
        raise ConfigError("mcp muss ein JSON-Objekt sein")
    try:
        validate_servers(config["mcp"]["servers"])
        _integer(config["mcp"], "max_sessions", 1, 64, "mcp.max_sessions")
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    known_capabilities.update("mcp_" + name for name in config["mcp"]["servers"])
    if set(chatto["channel_capabilities"]) - known_capabilities:
        raise ConfigError("chatto.channel_capabilities enthält unbekannte Werkzeuge")
    if chatto["enabled"] and (not chatto["api_key"].strip() or not chatto["owner_user_id"].strip()):
        raise ConfigError("Chatto benötigt Bot-Schlüssel und Eigentümer-Konto-ID")
    assist = config["assist_api"]
    if not isinstance(assist, Mapping) or not isinstance(assist.get("enabled"), bool):
        raise ConfigError("assist_api.enabled muss boolesch sein")
    if assist["enabled"] and not str(assist.get("token", "")).strip():
        raise ConfigError("Assist-API benötigt EVE_ASSIST_TOKEN")
    llm = config["llm"]
    llm["base_url"] = _url(llm.get("base_url"), "llm.base_url")
    if not str(llm.get("model", "")).strip():
        raise ConfigError("llm.model darf nicht leer sein")
    _integer(llm, "timeout_seconds", 1, 900, "llm.timeout_seconds")
    temperature = llm.get("temperature")
    if temperature is not None and (
        isinstance(temperature, bool) or not isinstance(temperature, (int, float))
        or not 0 <= temperature <= 2
    ):
        raise ConfigError("llm.temperature muss eine Zahl zwischen 0 und 2 sein")
    embedding = config["memory_search"]
    if not isinstance(embedding, Mapping):
        raise ConfigError("memory_search muss ein Objekt sein")
    _integer(embedding, "timeout_seconds", 1, 900, "memory_search.timeout_seconds")
    if embedding.get("backend") not in {"local_onnx", "http"}:
        raise ConfigError("memory_search.backend muss local_onnx oder http sein")
    _integer(embedding, "threads", 1, 32, "memory_search.threads")
    if not isinstance(embedding.get("model_dir"), str) or not embedding["model_dir"].strip():
        raise ConfigError("memory_search.model_dir fehlt")
    if embedding.get("backend") == "http" and embedding.get("model"):
        embedding["base_url"] = _url(embedding.get("base_url"), "memory_search.base_url")

    for key in ("model", "query_prefix", "document_prefix"):
        if not isinstance(embedding.get(key), str):
            raise ConfigError(f"memory_search.{key} muss eine Zeichenkette sein")
    if "base_url" in embedding and not isinstance(embedding["base_url"], str):
        raise ConfigError("memory_search.base_url muss eine Zeichenkette sein")

    if type(llm.get("use_server_limits")) is not bool:
        raise ConfigError("llm.use_server_limits muss boolesch sein")
    _integer(llm, "max_tokens", 1, 100_000, "llm.max_tokens")

    stt = config["speech_to_text"]
    if not str(stt.get("model", "")).strip():
        raise ConfigError("speech_to_text.model darf nicht leer sein")
    if stt.get("device") not in {"auto", "cpu", "cuda"}:
        raise ConfigError("speech_to_text.device muss auto, cpu oder cuda sein")
    if stt.get("compute_type") not in {
        "auto", "default", "int8", "int8_float32", "int8_float16",
        "int8_bfloat16", "int16", "float16", "float32", "bfloat16",
    }:
        raise ConfigError("speech_to_text.compute_type wird von CTranslate2 nicht unterstützt")
    language = str(stt.get("language", "")).strip().casefold()
    if not language or len(language) > 8 or not language.replace("-", "").isalpha():
        raise ConfigError("speech_to_text.language muss ein Whisper-Sprachcode wie de oder en sein")
    stt["model"] = str(stt["model"]).strip()
    stt["language"] = language

    similarity = config["semantic_similarity"]
    if type(similarity.get("enabled")) is not bool:
        raise ConfigError("semantic_similarity.enabled muss boolesch sein")
    if similarity.get("mode") not in {"active", "shadow"}:
        raise ConfigError("semantic_similarity.mode muss active oder shadow sein")
    threshold = similarity.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.5 <= float(threshold) <= 1:
        raise ConfigError("semantic_similarity.threshold muss zwischen 0.5 und 1.0 liegen")
    similarity["threshold"] = float(threshold)

    conversation_learning = config["conversation_learning"]
    if type(conversation_learning.get("enabled")) is not bool:
        raise ConfigError("conversation_learning.enabled muss boolesch sein")
    _integer(
        conversation_learning, "idle_delay_seconds", 5, 86400,
        "conversation_learning.idle_delay_seconds",
    )
    _integer(
        conversation_learning, "batch_size", 1, 32,
        "conversation_learning.batch_size",
    )

    working_memory = config["working_memory"]
    if type(working_memory.get("cleanup_enabled")) is not bool:
        raise ConfigError("working_memory.cleanup_enabled muss boolesch sein")
    for key in (
        "completed_retention_hours", "failed_retention_hours",
        "temporary_learning_retention_hours",
    ):
        value = working_memory.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.01 <= float(value) <= 8760:
            raise ConfigError(f"working_memory.{key} muss zwischen 0.01 und 8760 Stunden liegen")
        working_memory[key] = float(value)
    _integer(
        working_memory, "cleanup_interval_minutes", 1, 1440,
        "working_memory.cleanup_interval_minutes",
    )

    composition = config["semantic_composition"]
    if type(composition.get("enabled")) is not bool:
        raise ConfigError("semantic_composition.enabled muss boolesch sein")
    if composition.get("mode") not in {"active", "shadow"}:
        raise ConfigError("semantic_composition.mode muss active oder shadow sein")
    for key, low, high in (
        ("min_support_roots", 2, 20), ("max_tokens", 1, 256), ("max_fields", 1, 256),
        ("max_lookup_candidates", 1, 5000), ("max_shapes", 1, 64),
        ("max_support_scan", 10, 100000), ("max_update_pairs", 100, 2000000),
    ):
        _integer(composition, key, low, high, f"semantic_composition.{key}")

    ha = config["home_assistant"]
    ha["url"] = _url(ha.get("url"), "home_assistant.url", required=bool(ha.get("enabled")))
    _integer(ha, "timeout_seconds", 1, 300, "home_assistant.timeout_seconds")
    if ha.get("enabled") and not str(ha.get("token", "")).strip():
        raise ConfigError("Home Assistant ist aktiviert, aber EVE_HOME_ASSISTANT_TOKEN fehlt")

    web = config["web"]
    web["searxng_url"] = _url(web.get("searxng_url"), "web.searxng_url")
    for key, low, high in (("image_results", 1, 8), ("timeout_seconds", 1, 300),
                           ("max_page_bytes", 750_000, 20_000_000),
                           ("max_pdf_bytes", 750_000, 200 * 1024 * 1024)):
        _integer(web, key, low, high, f"web.{key}")

    shell = config["shell"]
    if type(shell.get("enabled")) is not bool:
        raise ConfigError("shell.enabled muss boolesch sein")
    if not isinstance(shell.get("executable"), str) or not shell["executable"].strip() or "\x00" in shell["executable"]:
        raise ConfigError("shell.executable muss ein Shellprogramm sein")
    forbidden = shell.get("forbidden_commands")
    if not isinstance(forbidden, list) or any(not isinstance(item, str) or not item.strip() or "\x00" in item for item in forbidden):
        raise ConfigError("shell.forbidden_commands muss eine Liste nichtleerer Befehle sein")
    from .shell import command_tokens
    if any(not command_tokens(item) for item in forbidden):
        raise ConfigError("shell.forbidden_commands enthält einen Befehl ohne Wörter")

    wayland = config["wayland_computer"]
    if type(wayland.get("enabled")) is not bool:
        raise ConfigError("wayland_computer.enabled muss boolesch sein")
    if not isinstance(wayland.get("env"), dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k,v in wayland.get("env", {}).items()
    ):
        raise ConfigError("wayland_computer.env muss Zeichenketten auf Zeichenketten abbilden")
    if "python" in wayland and not isinstance(wayland["python"], str):
        raise ConfigError("wayland_computer.python muss eine Zeichenkette sein")

    audio, visual, tts = config["audio"], config["visual"], config["text_to_speech"]
    _integer(audio, "sample_rate", 8_000, 192_000, "audio.sample_rate")
    _integer(audio, "channels", 1, 32, "audio.channels")
    _integer(visual, "port", 1, 65_535, "visual.port")
    _integer(visual, "max_connections", 1, 10_000, "visual.max_connections")
    _integer(visual, "max_concurrent_requests", 1, 1_000, "visual.max_concurrent_requests")
    _integer(tts, "piper_chunk_chars", 200, 2_000, "text_to_speech.piper_chunk_chars")
    if tts.get("engine") not in {"auto", "piper", "qwen3_tts", "chatterbox", "spd-say", "espeak-ng"}:
        raise ConfigError("text_to_speech.engine ist nicht unterstützt")
    nova = config["nova_maintenance"]
    if nova.get("transport", "shared_chat") not in {"shared_chat", "isolated"}:
        raise ConfigError("nova_maintenance.transport muss shared_chat oder isolated sein")
    _integer(nova, "shared_chat_timeout_seconds", 15, 3600, "nova_maintenance.shared_chat_timeout_seconds")
    _integer(nova, "timeout_seconds", 15, 900, "nova_maintenance.timeout_seconds")
    if not str(nova.get("command", "")).strip():
        raise ConfigError("nova_maintenance.command darf nicht leer sein")
    memory = config["memory"]
    if "backend" in memory:
        raise ConfigError("memory.backend wurde entfernt; EVE verwendet ausschließlich Memory")

    runtime_telemetry = config["memory_runtime_telemetry"]
    if type(runtime_telemetry.get("enabled")) is not bool:
        raise ConfigError("memory_runtime_telemetry.enabled muss boolesch sein")
    if runtime_telemetry.get("lifecycle_audit") != "required":
        raise ConfigError(
            "memory_runtime_telemetry.lifecycle_audit muss required sein"
        )
    if runtime_telemetry.get("contract_version") != "memory-runtime-events-v1":
        raise ConfigError(
            "memory_runtime_telemetry.contract_version muss memory-runtime-events-v1 sein"
        )
    _integer(
        runtime_telemetry, "retention_days", 1, 3650,
        "memory_runtime_telemetry.retention_days",
    )
    _integer(
        runtime_telemetry, "max_detail_bytes", 512, 16384,
        "memory_runtime_telemetry.max_detail_bytes",
    )

    for section, key, label in (
        (config["storage"], "data_path", "storage.data_path"), (config["storage"], "cache_path", "storage.cache_path"),
        (config["paths"], "database", "paths.database"),
        (config["paths"], "runtime", "paths.runtime"), (config["paths"], "web", "paths.web"),
        (tts, "data_dir", "text_to_speech.data_dir"),
    ):
        section[key] = _resolve_path(root, section[key], label)
    if tts.get("reference_audio"):
        tts["reference_audio"] = _resolve_path(root, tts["reference_audio"], "text_to_speech.reference_audio")
    for key in ("tls_cert", "tls_key"):
        if visual.get(key):
            visual[key] = _resolve_path(root, visual[key], f"visual.{key}")
    roots = config["local_files"].get("roots", [])
    if not isinstance(roots, list) or any(not isinstance(item, str) for item in roots):
        raise ConfigError("local_files.roots muss eine Liste von Verzeichnispfaden sein")
    resolved_roots = []
    for index, value in enumerate(roots):
        path = Path(_resolve_path(root, value, f"local_files.roots[{index}]")).resolve(strict=False)
        if path == Path(path.anchor):
            raise ConfigError("Das Dateisystem-Wurzelverzeichnis darf nicht freigegeben werden")
        if path in resolved_roots:
            continue
        resolved_roots.append(path)
    config["local_files"]["roots"] = [str(path) for path in resolved_roots]


def default_config_path(root: Path | None = None) -> Path:
    directory = root or ROOT
    local = directory / "eve.local.json"
    return local if local.is_file() else directory / "eve.json"


def load_config(path: Path | None = None, *, environ: Mapping[str, str] | None = None) -> tuple[Path, dict[str, Any]]:
    """Load validated config with: process environment > .env > JSON > defaults."""
    config_path = (path or default_config_path()).resolve()
    root = config_path.parent
    try:
        local = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"EVE-Konfiguration fehlt: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"EVE-Konfiguration ist kein gültiges JSON: {exc}") from exc
    if not isinstance(local, dict):
        raise ConfigError("EVE-Konfiguration muss ein JSON-Objekt sein")
    for section, removed_keys in REMOVED_ARTIFICIAL_LIMITS.items():
        configured = local.get(section, {})
        if not isinstance(configured, Mapping):
            continue
        obsolete = sorted(set(configured) & removed_keys)
        if obsolete:
            names = ", ".join(f"{section}.{key}" for key in obsolete)
            raise ConfigError(
                f"Entfernte künstliche Begrenzung noch konfiguriert: {names}"
            )
    if local.get("home_assistant", {}).get("token"):
        raise ConfigError("home_assistant.token gehört in EVE_HOME_ASSISTANT_TOKEN oder .env")
    if local.get("llm", {}).get("api_key"):
        raise ConfigError("llm.api_key gehört in EVE_LLM_API_KEY oder .env")
    if local.get("image_generation", {}).get("api_key"):
        raise ConfigError("image_generation.api_key gehört in EVE_IMAGE_API_KEY oder .env")
    if local.get("assist_api", {}).get("token"):
        raise ConfigError("assist_api.token gehört in EVE_ASSIST_TOKEN oder .env")
    if local.get("chatto", {}).get("api_key"):
        raise ConfigError("chatto.api_key gehört in EVE_CHATTO_BOT_KEY oder .env")
    config = _merge(copy.deepcopy(DEFAULTS), local)
    effective_environment = {**_read_dotenv(root / ".env"), **dict(os.environ if environ is None else environ)}
    for variable, (section, key) in ENVIRONMENT_FIELDS.items():
        if variable in effective_environment:
            config[section][key] = effective_environment[variable]

    # Compatibility migration for the existing installation. Only the central
    # loader reads this legacy file; components receive the resolved secret.
    if not str(config["home_assistant"].get("token", "")).strip():
        token_file = local.get("home_assistant", {}).get("token_file", "secrets/home-assistant.token")
        token_path = Path(str(token_file)).expanduser()
        token_path = token_path if token_path.is_absolute() else root / token_path
        if token_path.is_file():
            config["home_assistant"]["token"] = token_path.read_text(encoding="utf-8").strip()
    config["home_assistant"].pop("token_file", None)
    _validate(root, config)
    for key in ("data_path", "cache_path"):
        storage_path = Path(config["storage"][key])
        if storage_path == Path(storage_path.anchor):
            raise ConfigError(f"storage.{key} darf nicht das Dateisystem-Wurzelverzeichnis sein")
    return root, config


def _atomic_text(path: Path, text: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _source_map(config_path: Path, environ: Mapping[str, str] | None) -> dict[str, str]:
    local = json.loads(config_path.read_text(encoding="utf-8"))
    dotenv = _read_dotenv(config_path.parent / ".env")
    process = dict(os.environ if environ is None else environ)
    sources: dict[str, str] = {}
    for field in (*UI_FIELDS, *UI_SECRETS):
        section, key = field.split(".", 1)
        sources[field] = "eve.json" if key in local.get(section, {}) else "default"
    for variable, (section, key) in ENVIRONMENT_FIELDS.items():
        field = f"{section}.{key}"
        if field in sources and variable in dotenv:
            sources[field] = ".env"
        if field in sources and variable in process:
            sources[field] = "environment"
    token_file = local.get("home_assistant", {}).get("token_file", "secrets/home-assistant.token")
    token_path = Path(str(token_file)).expanduser()
    token_path = token_path if token_path.is_absolute() else config_path.parent / token_path
    if sources["home_assistant.token"] == "default" and token_path.is_file():
        sources["home_assistant.token"] = "legacy secret file"
    return sources



# Transport settings only; domain contracts continue to come from the MCP server.
MCP_SERVER_FIELDS = {
    "chatto_reply_mode": {"label": "Antworten in Chatto", "type": "select", "options": ["inherit", "thread"], "default": "inherit", "description": "inherit: allgemeinen Chatto-Antwortmodus beibehalten. thread: bei Verwendung dieser Integration im eigenen Thread antworten."},
    "title": {"label": "Name der Kategorie", "type": "text", "default": ""},
    "enabled": {"label": "Aktiviert", "type": "boolean", "default": True},
    "command": {"label": "Programm / CLI-Pfad", "type": "text", "default": "", "description": "Ausführbares CLI-Programm oder Programmname auf PATH. {root} bezeichnet den EVE-Ordner."},
    "args": {"label": "Programmargumente", "type": "string_list", "default": [], "description": "Ein Argument pro Zeile; keine Shell-Anführungszeichen. {workspace} bezeichnet den Sitzungsordner."},
    "scope": {"label": "Sitzungsumfang", "type": "select", "options": ["conversation", "shared"], "default": "conversation", "description": "conversation: eigene Sitzung pro Gespräch. shared: gemeinsam verwendete Sitzung."},
    "cwd": {"label": "Arbeitsverzeichnis", "type": "text", "default": "{workspace}"},
    "timeout_seconds": {"label": "Zeitlimit pro Aufruf (Sekunden)", "type": "integer", "min": 1, "max": 3600, "default": 330},
    "description": {"label": "Beschreibung für EVE", "type": "text", "default": ""},
    "attachment_roots": {"label": "Zusätzliche Ordner für Antwortdateien", "type": "path_list", "default": []},
    "env": {"label": "Prozessumgebung", "type": "key_value", "default": {}, "description": "Zusätzliche Umgebungsvariablen; Zugangsdaten über die Umgebung des EVE-Prozesses setzen."},
    "protocol_version": {"label": "MCP-Protokollversion", "type": "text", "default": "2025-06-18", "advanced": True},
    "startup": {"label": "Beim Sitzungsstart", "type": "mcp_calls", "default": [], "advanced": True},
    "after_write": {"label": "Nach Schreibaufrufen", "type": "mcp_calls", "default": [], "advanced": True},
}


def _mcp_server_section(name, server):
    fields = []
    for key, spec in MCP_SERVER_FIELDS.items():
        fields.append({**copy.deepcopy(spec), "id": f"mcp.server.{name}.{key}",
                       "value": copy.deepcopy(server.get(key, spec["default"])),
                       "source": "Konfiguration" if key in server else "default",
                       "restart_required": True, "locked": False})
    return {"id": "mcp_" + name, "title": server.get("title") or name,
            "fields": fields, "secrets": [], "mcp_server": name}


def editable_config(config_path: Path, *, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return the safe, server-described configuration model for the web UI."""
    resolved = config_path.resolve()
    _, effective = load_config(resolved, environ=environ)
    sources = _source_map(resolved, environ)
    sections = []
    for section, title in UI_SECTIONS:
        fields = []
        for field, meta in UI_FIELDS.items():
            field_section, key = field.split(".", 1)
            if field_section != section or field == "mcp.servers":
                continue
            fields.append({"id": field, "value": effective[section][key],
                           "default": copy.deepcopy(DEFAULTS[section][key]),
                           "source": sources[field],
                           "overridden": sources[field] in {"environment", ".env"},
                           "locked": sources[field] in {"environment", ".env"},
                           "restart_required": not (
                               field == "local_files.roots" or field.startswith("semantic_similarity.")
                               or field.startswith("semantic_composition.")
                               or field.startswith("conversation_learning.")
                               or field.startswith("working_memory.")
                               or field.startswith("shell.")
                               or field.startswith("chatto.")
                           ), **meta})
        secrets = []
        for field, meta in UI_SECRETS.items():
            field_section, key = field.split(".", 1)
            if field_section == section:
                secrets.append({"id": field, "configured": bool(str(effective[section][key]).strip()),
                                "source": sources[field], "restart_required": section != "chatto",
                                "locked": sources[field] == "environment",
                                "label": meta["label"], "type": "secret",
                                "description": meta["description"]})
        if fields or secrets:
            sections.append({"id": section, "title": title, "fields": fields, "secrets": secrets})
    sections.extend(_mcp_server_section(name, server)
                    for name, server in effective["mcp"]["servers"].items())
    sections.sort(key=lambda section: section["title"].casefold())
    return {"sections": sections, "runtime_effect": "mixed",
            "mcp_server_template": _mcp_server_section("{name}", {})}


def update_editable_config(config_path: Path, payload: Mapping[str, Any], *, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Validate and atomically persist allowlisted settings and non-empty secrets."""
    if set(payload) - {"values", "secrets"}:
        raise ConfigError("Unbekannte Eigenschaften in der Konfigurationsanfrage")
    values, secrets = payload.get("values", {}), payload.get("secrets", {})
    if not isinstance(values, Mapping) or not isinstance(secrets, Mapping):
        raise ConfigError("values und secrets müssen JSON-Objekte sein")
    dynamic = {}
    for field in values:
        match = re.fullmatch(r"mcp\.server\.([a-z][a-z0-9_]{0,39})\.([a-z_]+)", field)
        if match and match[2] in MCP_SERVER_FIELDS:
            dynamic[field] = (match[1], match[2])
    if "mcp.servers" in values and dynamic:
        raise ConfigError("Serverliste und einzelne Serverfelder können nicht gleichzeitig geändert werden")
    unknown = (set(values) - set(UI_FIELDS) - set(dynamic)) | (set(secrets) - set(UI_SECRETS))
    if unknown:
        raise ConfigError(f"Unbekanntes Konfigurationsfeld: {sorted(unknown)[0]}")
    resolved = config_path.resolve()
    local = json.loads(resolved.read_text(encoding="utf-8"))
    candidate = copy.deepcopy(local)
    for field, value in values.items():
        if field in dynamic:
            name, key = dynamic[field]
            candidate.setdefault("mcp", {}).setdefault("servers", {}).setdefault(name, {})[key] = value
            continue
        section, key = field.split(".", 1)
        field_type = UI_FIELDS[field]["type"]
        if field_type == "boolean" and not isinstance(value, bool):
            raise ConfigError(f"{field} muss boolesch sein")
        if field_type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ConfigError(f"{field} muss eine Ganzzahl sein")
        if field_type == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ConfigError(f"{field} muss eine Zahl sein")
        if field_type in {"path_list", "string_list"} and (
            not isinstance(value, list) or any(not isinstance(item, str) for item in value)
        ):
            raise ConfigError(f"{field} muss eine Liste von Zeichenketten sein")
        candidate.setdefault(section, {})[key] = value
    secret_updates = {UI_SECRETS[field]["environment"]: str(value) for field, value in secrets.items() if str(value).strip()}
    if any("\n" in value or "\r" in value for value in secret_updates.values()):
        raise ConfigError("Geheimnisse dürfen keine Zeilenumbrüche enthalten")
    # Validate the JSON values themselves, without allowing a higher-priority
    # environment override to hide an invalid persisted value.
    validation = _merge(copy.deepcopy(DEFAULTS), candidate)
    _, current = load_config(resolved, environ=environ)
    validation["home_assistant"]["token"] = secret_updates.get("EVE_HOME_ASSISTANT_TOKEN", current["home_assistant"]["token"])
    validation["llm"]["api_key"] = secret_updates.get("EVE_LLM_API_KEY", current["llm"]["api_key"])
    validation["image_generation"]["api_key"] = secret_updates.get("EVE_IMAGE_API_KEY", current["image_generation"]["api_key"])
    validation["assist_api"]["token"] = secret_updates.get("EVE_ASSIST_TOKEN", current["assist_api"]["token"])
    validation["chatto"]["api_key"] = secret_updates.get("EVE_CHATTO_BOT_KEY", current["chatto"]["api_key"])
    validation["home_assistant"].pop("token_file", None)
    _validate(resolved.parent, validation)
    env_path = resolved.parent / ".env"
    original_config = resolved.read_text(encoding="utf-8")
    original_env = env_path.read_text(encoding="utf-8") if env_path.exists() else None
    try:
        if values:
            _atomic_text(resolved, json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
        if secret_updates:
            env_values = _read_dotenv(env_path)
            env_values.update(secret_updates)
            _atomic_text(env_path, "".join(f"{key}={value}\n" for key, value in env_values.items()), mode=0o600)
    except Exception:
        if values:
            _atomic_text(resolved, original_config)
        if secret_updates:
            if original_env is None:
                env_path.unlink(missing_ok=True)
            else:
                _atomic_text(env_path, original_env, mode=0o600)
        raise
    return editable_config(resolved, environ=environ)


def config_status(config: Mapping[str, Any]) -> list[str]:
    """Return useful startup diagnostics without exposing secret values."""
    tts = config.get("text_to_speech", {})
    voice_path = Path(str(tts.get("data_dir", ""))) / f"{tts.get('voice', '')}.onnx"
    return [
        "Memory: v2",
        "Memory-Embeddings: " + (
            f"{config.get('memory_search', {}).get('backend', 'local_onnx')} · "
            f"{config.get('memory_search', {}).get('model')}"
            if config.get('memory_search', {}).get('model') else "deaktiviert"
        ),
        "Gesprächslernen: " + (
            f"aktiv · {config.get('conversation_learning', {}).get('batch_size', 2)} Turns nach "
            f"{config.get('conversation_learning', {}).get('idle_delay_seconds', 120)} s Leerlauf"
            if config.get("conversation_learning", {}).get("enabled", True) else "deaktiviert"
        ),
        "Kurzzeitgedächtnis-Bereinigung: " + (
            f"{config.get('working_memory', {}).get('completed_retention_hours', 1)} h erfolgreich · "
            f"{config.get('working_memory', {}).get('failed_retention_hours', 24)} h fehlgeschlagen · "
            f"{config.get('working_memory', {}).get('temporary_learning_retention_hours', .25)} h Lernmaterial"
            if config.get('working_memory', {}).get('cleanup_enabled', True) else "deaktiviert"
        ),
        f"Memory-Lifecycle-Audit: {config.get('memory_runtime_telemetry', {}).get('lifecycle_audit', 'required')}",
        "Memory-Runtime-Diagnose: " + (
            "aktiv" if config.get("memory_runtime_telemetry", {}).get("enabled") else "deaktiviert"
        ),
        f"Dynamische Semantik: {config.get('semantic_similarity', {}).get('mode', 'active')} "
        f"bei {float(config.get('semantic_similarity', {}).get('threshold', .85)):.0%}",
        f"Differenzielle Komposition: {config.get('semantic_composition', {}).get('mode', 'active')}",
        f"Home Assistant: {'konfiguriert' if config.get('home_assistant', {}).get('enabled') else 'deaktiviert'}",
        f"Bildgenerierung: {'aktiv' if config.get('image_generation', {}).get('enabled') else 'deaktiviert'}",
        "LLM-Endpunkt: gesetzt",
        f"Piper-Stimme: {'gefunden' if voice_path.is_file() else 'nicht gefunden'}",
        f"Storage data_path: {config.get('storage', {}).get('data_path', '')}",
        f"Storage cache_path: {config.get('storage', {}).get('cache_path', '')}",
    ]
