# EVE

Lokaler Sprachassistent mit Texteingabe, persistentem Gedächtnis und einer Weboberfläche.
EVE nutzt einen OpenAI-kompatiblen Modellserver und kann Home Assistant, Websuche
und lokale Werkzeuge anbinden. Brainwatch macht Gedächtnis und Verarbeitung sichtbar;
die NeuroCloud lässt sich auch in VR und Mixed Reality betrachten.

Quellcode: `src/eve_agent` · Weboberfläche: `web` · Tests: `tests`

## Installation

Voraussetzungen: Git, Python 3.11 oder neuer und ein OpenAI-kompatibler
Modellserver. Bei einem privaten Repository benötigt das verwendete GitHub-Konto Zugriffsrechte.

Linux / macOS:

```bash
git clone https://github.com/Dntouch/eve-agent.git EVE && python3 EVE/install.py
```

Windows PowerShell:

```powershell
git clone https://github.com/Dntouch/eve-agent.git EVE; if ($LASTEXITCODE -eq 0) { py -3 EVE/install.py }
```

Der Installer fragt nach Modelladresse und Modellname, richtet eine Python-Umgebung
ein, lädt die geprüften lokalen Embeddings für die Gedächtnissuche und bietet die Einrichtung der Sprachfunktionen an. Bestehende Einstellungen bleiben
erhalten. Unter Linux muss das Python-Paket für virtuelle Umgebungen installiert sein.
Für Linux x86_64 mit Python 3.14 fixiert `constraints-tested.txt` die praktisch
geprüften Paketversionen. Andere Plattformen verwenden die Versionsbereiche aus
`pyproject.toml`; ihre native Installation ist gesondert zu prüfen.

Starten: unter Windows `EVE-starten.cmd` öffnen,
unter Linux / macOS `eve-start` ausführen.
Die Weboberfläche liegt unter `http://127.0.0.1:8790`. Zum Beenden im Startfenster
Strg+C drücken.

### Zweite Testinstanz

Installiere den bereinigten Export oder einen frischen Git-Klon in einem eigenen
Ordner. Verwende einen anderen Webport als bei der laufenden EVE:

```bash
python3 install.py --non-interactive --llm-url http://127.0.0.1:1234/v1 --model MODELLNAME --port 8791
./eve-start
```

Die neue Oberfläche liegt unter `http://127.0.0.1:8791`. Unter Windows entsprechend
`py -3 install.py` und `EVE-starten.cmd` verwenden. Jede Installation hat eine eigene
`eve.local.json`, `.venv`, Datenbank (`data/eve.db`) und Laufzeitdateien (`runtime/`).
Keine Daten oder `.env` aus der produktiven Instanz kopieren. Bereits gesetzte
`EVE_*`-Umgebungsvariablen können Einstellungen überschreiben; für den Test nur die
gewünschten Variablen setzen. Eine vorhandene lokale Konfiguration wird erhalten;
den Port dann direkt unter `visual.port` ändern.

Ein Dialog-LLM oder Modellserver ist nicht enthalten und wird vom Installer nicht
heruntergeladen. Beide Instanzen dürfen denselben OpenAI-kompatiblen Server nutzen
oder unterschiedliche Server und Modelle ansprechen. Werkzeugaufrufe und Bildverarbeitung
hängen von den Fähigkeiten des gewählten Modells ab. Die neue EVE beginnt mit leerem
Gedächtnis. Sprache ist optional; `--with-speech` richtet Whisper und Piper ein.

### Sprache und Websuche

- **Whisper:** `faster-whisper` mit dem Modell `small`; der Installer lädt es auf Wunsch herunter.
- **Piper:** EVEs trainierte Stimme `de_DE-eve-medium` liegt bei (etwa 61 MB). Der Installer prüft die Dateien und übernimmt EVEs Sprechparameter.
- **Gedächtnissuche:** Der Installer lädt `intfloat/multilingual-e5-small` (etwa 487 MB) für die lokale CPU-Suche. Revision und SHA-256-Prüfsummen sind festgelegt. Das ist ein Embedding-Modell, kein Dialog-LLM. `--without-embeddings` erlaubt ausdrücklich eine reduzierte Installation.
- **Websuche:** `--with-web-search` richtet eine eigene SearXNG-Instanz mit festem Container-Image, zufälligem Secret und lokaler JSON-API ein. Docker oder Podman muss vorhanden sein. Alternativ `--searxng-url URL` für einen bestehenden Dienst verwenden. Für Parallelbetrieb einen freien `--search-port`, etwa `8889`, wählen.

Whisper benötigt beim Download Internet. Danach laufen Whisper und Piper
lokal auf der CPU. Mikrofon und Audiogeräte lassen sich auf dem Zielrechner über
`eve doctor` in der installierten Umgebung prüfen. Native Windows-Installation
und Audiobetrieb sind noch auf einem Windows-Rechner zu testen.

Für unbeaufsichtigte Einrichtung:

```bash
python3 install.py --non-interactive --llm-url http://127.0.0.1:1234/v1 --model MODELLNAME --with-speech --searxng-url http://127.0.0.1:8888
```

Zugangsdaten werden über Umgebungsvariablen oder eine lokale `.env` gesetzt;
[`.env.example`](.env.example) nennt die Variablen.
Home Assistant, Shellzugriff und Desktopsteuerung sind zunächst ausgeschaltet.

Für eine eigene EVE einschließlich Sprache, Gedächtnissuche und Websuche:

```bash
python3 install.py --non-interactive --llm-url http://127.0.0.1:1234/v1 --model MODELLNAME --port 8791 --with-speech --with-web-search --search-port 8889
```

Der Suchcontainer gehört ausschließlich zu diesem Installationsordner. Er läuft
unabhängig vom EVE-Prozess weiter. Mit `python3 scripts/setup_search.py --port 8889`
wieder starten und mit `python3 scripts/setup_search.py --stop` stoppen. Die Einrichtung
ersetzt oder stoppt keine vorhandenen Suchcontainer.

### Weitere Funktionen einrichten

Der Quellcode aller EVE-Funktionen wird mitgeliefert. Persönliche Konten, Geräte,
Serveradressen und Berechtigungen muss jede Installation selbst konfigurieren.

| Funktion | Einrichtung |
| --- | --- |
| Chat, Gedächtnis, Lernen, Aufgaben, Brainwatch, NeuroCloud und XR | Bestandteil der Anwendung; XR benötigt einen kompatiblen Browser und Headset. |
| Sprache | `--with-speech`; Mikrofon im Browser freigeben. Für Linux-Audiogeräte muss die Systembibliothek PortAudio vorhanden sein. |
| Home Assistant | Eigene Integration: [eve-home-assistant](https://github.com/Dntouch/eve-home-assistant). Installation und Updates über HACS (benutzerdefiniertes Repository, Typ Integration); Einrichtung und Tokens gemäß der dortigen Anleitung. |
| Chatto-Bot-Anbindung | EVE als Bot mit einem bestehenden Chatto-Server verbinden: Node 22.13+ und npm, `python3 scripts/setup_chatto.py`, anschließend Serveradresse und eigenen Bot konfigurieren. Siehe [Chatto-Anleitung](docs/CHATTO.md). |
| Lokale Dateien und Shell | Eigene Verzeichnisse beziehungsweise Shell in der Konfiguration freigeben. |
| Desktopsteuerung | Linux/Wayland mit Desktop-Portal; separates Paket `wayland-mcp-kurojs==0.6.1` in `.venv-wayland-mcp` installieren und dort `scripts/patch_wayland_mcp_keyboard.py` ausführen. Benötigt die Systemabhängigkeiten von PyGObject, PyWayland und das Portal des Desktops. Die Desktop-Freigabe erfolgt lokal über das Portal. |
| Nova-Wartung | Eigenen Coding-Agenten samt Anmeldung konfigurieren; für isolierten Linux-Betrieb wird Bubblewrap benötigt. |
| Netzwerkscan | Docker oder Podman und die Netzwerkkonfiguration in EVE einrichten. |

Für die optionale Wayland-Steuerung im EVE-Anwendungsordner:

```bash
python3 -m venv --system-site-packages .venv-wayland-mcp
.venv-wayland-mcp/bin/python -m pip install wayland-mcp-kurojs==0.6.1 pywayland==0.4.19
.venv-wayland-mcp/bin/python scripts/patch_wayland_mcp_keyboard.py
```

Der System-Python muss PyGObject/GStreamer und die Wayland-Bibliotheken des Desktops
bereitstellen; außerdem wird `libxkbcommon` benötigt. Erst danach die Desktopsteuerung
in EVE aktivieren. Der Patch prüft die Paketversion und den ursprünglichen Quellhash;
er verändert ausschließlich die separate `.venv-wayland-mcp`.

Externe Dienste und Zugangsdaten sind keine Bestandteile des Repositorys. Das
Dialogmodell muss Werkzeugaufrufe unterstützen, damit EVE ihre Werkzeuge nutzen
kann; Bilder benötigen zusätzlich ein multimodales Modell. Welche Fähigkeiten
verfügbar sind, hängt außerdem vom Zielbetriebssystem und den Freigaben ab.

### Mit einem Coding-Agenten

Den [Installationsauftrag](INSTALL-AGENT.md) in Codex,
OpenClaw oder einen anderen Coding-Agenten kopieren und die Repository-Adresse
einsetzen. Er beschreibt Installation, Websuche und Funktionstests.

## Entwicklung

```bash
.venv/bin/python -m unittest discover -s tests
```

Die GitHub-Actions-Prüfung installiert die Anwendung unter Linux für Python
3.11, 3.12 und 3.14 und führt Python- und JavaScript-Tests aus. Lokal zusätzlich:

```bash
node --test tests/js/*.test.*
```

Integrationstests für Home Assistant, Wayland und TLS benötigen die jeweilige
Testumgebung. Tests der lokalen Entwicklungslauncher werden im bereinigten Export
übersprungen, weil dort die portablen, vom Installer erzeugten Starter verwendet
werden. Die übrigen Tests dürfen keine laufende EVE oder externe Geräte verändern.


Lizenz: [MIT](LICENSE). Fremdbibliotheken behalten ihre eigenen Lizenzen.
