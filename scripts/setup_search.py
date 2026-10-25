#!/usr/bin/env python3
"""Run a separate, pinned SearXNG container for this EVE installation."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'docker.io/searxng/searxng@sha256:4f74bc40fe934c083cd7c42840b2c8f1b532c2ef907514e3e67e0e7c61a8bd13'


def instance_name(root):
    return 'eve-search-' + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('podman', 'docker'))
    parser.add_argument('--port', type=int, default=8888)
    parser.add_argument('--stop', action='store_true', help='Nur den Suchcontainer dieser Installation stoppen')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port muss zwischen 1 und 65535 liegen')
    engine = shutil.which(args.engine) if args.engine else shutil.which('podman') or shutil.which('docker')
    if not engine:
        parser.error('Docker oder Podman fehlt. Container-Laufzeit installieren oder vorhandene SearXNG-URL verwenden.')
    name = instance_name(ROOT)
    lookup = subprocess.run([engine, 'container', 'inspect', name, '--format', '{{index .Config.Labels "org.eve.instance"}}'], capture_output=True, text=True)
    exists = lookup.returncode == 0
    if exists and lookup.stdout.strip() != name:
        parser.error('Containername ist bereits durch eine fremde Instanz belegt')
    if args.stop:
        if exists:
            subprocess.run([engine, 'stop', name], check=True)
        return
    base = f'http://127.0.0.1:{args.port}'
    if exists:
        binding = subprocess.check_output([engine, 'port', name, '8080/tcp'], text=True).strip()
        if binding != f'127.0.0.1:{args.port}':
            parser.error('Vorhandener Suchcontainer verwendet einen anderen Port; den ursprünglichen --port verwenden.')
        subprocess.run([engine, 'start', name], check=True)
    else:
        private = ROOT / 'runtime/web-search'
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        private.chmod(0o700)
        settings = private / 'settings'
        settings.mkdir(exist_ok=True, mode=0o755)
        path = settings / 'settings.yml'
        if not path.exists():
            path.write_text('use_default_settings: true\nsearch:\n  formats: [html, json]\nserver:\n  secret_key: ' + json.dumps(secrets.token_hex(32)) + '\n  limiter: false\n  bind_address: "0.0.0.0"\n  port: 8080\n', encoding='utf-8')
            path.chmod(0o644)
        subprocess.run([engine, 'run', '--detach', '--name', name,
                        '--label', f'org.eve.instance={name}', '--publish', f'127.0.0.1:{args.port}:8080',
                        '--volume', f'{settings}:/etc/searxng:ro,Z', IMAGE], check=True)
    for _ in range(45):
        try:
            with urllib.request.urlopen(base + '/search?q=EVE&format=json', timeout=5) as response:
                result = json.load(response)
            if isinstance(result.get('results'), list):
                print('SearXNG JSON-API bereit:', base)
                return
        except (OSError, ValueError):
            time.sleep(1)
    raise SystemExit('Suchcontainer wurde gestartet, aber die JSON-API ist noch nicht bereit. Container-Logs prüfen: ' + name)


if __name__ == '__main__':
    main()
