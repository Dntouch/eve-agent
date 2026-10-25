#!/usr/bin/env python3
"""Install EVE on Windows, Linux or macOS using Python 3.11+."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
import venv

ROOT = Path(__file__).resolve().parent


def configuration(base: dict, url: str, model: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Modelladresse muss eine HTTP(S)-Adresse ohne Zugangsdaten sein.")
    if parsed.query or parsed.fragment:
        raise ValueError("Modelladresse darf keine Query oder Fragment enthalten.")
    if not model.strip():
        raise ValueError("Modellname fehlt.")
    result = json.loads(json.dumps(base))
    result["llm"] = {"base_url": url.rstrip("/"), "model": model.strip()}
    return result


def verify_voice(root: Path) -> None:
    manifest = json.loads((root / "voices/eve-voice.json").read_text())
    for name, expected in manifest["sha256"].items():
        path = root / "voices" / name
        if not path.is_file():
            raise ValueError(f"EVE-Stimme fehlt: {path}. Vollständige Veröffentlichung herunterladen.")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"EVE-Stimme beschädigt oder unvollständig: {path}")


def write_starters(root: Path, speech: bool = False, port: int = 8790) -> None:
    audio_flag = "" if speech else " --no-tts"
    # Resolve the installation directory at launch time, including paths with spaces.
    if os.name == "nt":
        (root / "EVE-starten.cmd").write_text(
            '@echo off\ncd /d "%~dp0"\n'
            f'echo EVE: http://127.0.0.1:{port}\n'
            f'"%~dp0.venv\\Scripts\\eve.exe" serve{audio_flag} --config "%~dp0eve.local.json" %*\n'
            'if errorlevel 1 pause\n', encoding="utf-8",
        )
    else:
        starter = root / "eve-start"
        starter.write_text(
            '#!/usr/bin/env sh\nset -eu\n'
            'HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'cd "$HERE"\n'
            f'echo "EVE: http://127.0.0.1:{port}"\n'
            f'exec "$HERE/.venv/bin/eve" serve{audio_flag} --config "$HERE/eve.local.json" "$@"\n'
        )
        starter.chmod(0o755)


def main() -> int:
    if sys.version_info < (3, 11):
        print("EVE benötigt Python 3.11 oder neuer.", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-url", default=os.environ.get("EVE_LLM_BASE_URL"))
    parser.add_argument("--model", default=os.environ.get("EVE_LLM_MODEL"))
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--without-embeddings", action="store_true", help="Reduzierte Installation ohne semantische Gedächtnissuche")
    parser.add_argument("--with-speech", action="store_true", help="EVE-Piper-Stimme prüfen und Whisper small herunterladen")
    parser.add_argument("--with-web-search", action="store_true", help="Eigene SearXNG-Instanz über vorhandenes Docker/Podman einrichten")
    parser.add_argument("--search-port", type=int, default=8888)
    parser.add_argument("--searxng-url", help="Adresse eines vorhandenen SearXNG mit JSON-API")
    parser.add_argument("--port", type=int, help="Webport dieser Instanz, z. B. 8791 für eine zweite EVE")
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port muss zwischen 1 und 65535 liegen.")
    if args.with_web_search and args.searxng_url:
        parser.error("--with-web-search und --searxng-url schließen einander aus.")
    if args.with_web_search and args.search_port == (args.port or 8790):
        parser.error("EVE und SearXNG benötigen unterschiedliche Ports.")
    if not 1 <= args.search_port <= 65535:
        parser.error("--search-port muss zwischen 1 und 65535 liegen.")
    config_path = ROOT / "eve.local.json"
    pending = None
    speech = args.with_speech
    search_url = f"http://127.0.0.1:{args.search_port}" if args.with_web_search else args.searxng_url
    if not config_path.exists():
        url, model = args.llm_url, args.model
        if not args.non_interactive:
            url = url or input("Modellserver [http://127.0.0.1:1234/v1]: ").strip() or "http://127.0.0.1:1234/v1"
            model = model or input("Modellname beim Server: ").strip()
        if not args.non_interactive:
            speech = speech or input("EVE-Stimme einrichten und Whisper herunterladen? [J/n]: ").strip().lower() not in {"n", "nein", "no"}
            search_url = search_url or input("SearXNG-Adresse [Enter: keine Websuche]: ").strip()
        if not url or not model:
            parser.error("--llm-url und --model sind ohne Eingabe erforderlich.")
        try:
            pending = configuration(json.loads((ROOT / "eve.example.json").read_text()), url, model)
        except ValueError as error:
            parser.error(str(error))
    if pending is not None:
        if not args.without_embeddings:
            pending["memory_search"] = {"backend": "local_onnx", "model": "intfloat/multilingual-e5-small", "model_dir": "data/models/multilingual-e5-small"}
        if args.port is not None:
            pending.setdefault("visual", {})["port"] = args.port
        if speech:
            pending["text_to_speech"] = {"engine": "piper", "voice": "de_DE-eve-medium", "data_dir": "voices", "length_scale": 1.27, "noise_scale": 0.4, "noise_w_scale": 0.2}
            pending["speech_to_text"] = {"model": "small", "language": "de", "device": "cpu", "compute_type": "int8"}
        if search_url:
            try:
                search_url = configuration({}, search_url, "validation")["llm"]["base_url"]
            except ValueError as error:
                parser.error(str(error))
            pending["web"] = {"enabled": True, "searxng_url": search_url}
    elif args.port is not None:
        parser.error("Vorhandene eve.local.json bleibt erhalten; Port dort unter visual.port konfigurieren.")
    elif search_url:
        parser.error("Vorhandene eve.local.json bleibt erhalten; SearXNG dort konfigurieren.")
    if speech:
        verify_voice(ROOT)
    environment = ROOT / ".venv"
    print("Python-Umgebung einrichten …", flush=True)
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "-c", str(ROOT / "constraints-tested.txt"), "-e", str(ROOT)], check=True)
    cfg = pending if pending is not None else json.loads(config_path.read_text())
    embeddings = cfg.get("memory_search", {})
    if embeddings.get("model") == "intfloat/multilingual-e5-small" and embeddings.get("backend", "local_onnx") == "local_onnx":
        model_dir = ROOT / embeddings.get("model_dir", "data/models/multilingual-e5-small")
        subprocess.run([str(python), str(ROOT / "scripts/setup_embeddings.py"), "--output", str(model_dir)], check=True)
    if speech:
        whisper = cfg.get("speech_to_text", {}).get("model", "small")
        subprocess.run([str(python), "-c", "from faster_whisper import WhisperModel; import sys; WhisperModel(sys.argv[1], device='cpu', compute_type='int8')", whisper], check=True)
    if args.with_web_search:
        subprocess.run([str(python), str(ROOT / "scripts/setup_search.py"), "--port", str(args.search_port)], check=True)
    if pending is not None:
        # Never overwrite configuration from an earlier installation.
        with config_path.open("x", encoding="utf-8") as stream:
            json.dump(pending, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    existing = pending if pending is not None else json.loads(config_path.read_text())
    voice_path = ROOT / existing.get("text_to_speech", {}).get("data_dir", "voices") / (existing.get("text_to_speech", {}).get("voice", "de_DE-eve-medium") + ".onnx")
    port = existing.get("visual", {}).get("port", 8790)
    write_starters(ROOT, speech=speech or voice_path.exists(), port=port)
    starter = ROOT / ("EVE-starten.cmd" if os.name == "nt" else "eve-start")
    print(f"\nInstalliert. Starten: {starter}")
    print(f"Weboberfläche: http://127.0.0.1:{port}")
    print("Der konfigurierte Modellserver muss beim Start erreichbar sein.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Installation fehlgeschlagen: {error}", file=sys.stderr)
        raise SystemExit(1)
