# Bildgenerierung

EVE bindet einen separat betriebenen Bildserver an. Unter **Konfiguration →
Bildgenerierung** werden Aktivierung, API-Format, Basis-URL, Modell, Bildmaße,
Sampling-Schritte, Guidance, Zeitlimit und zusätzliche Serverparameter eingestellt.
Änderungen erfordern einen EVE-Neustart. Standardmäßig ist die Funktion deaktiviert.
EVE lädt selbst keine Bildmodelle herunter. Die Integration ist unabhängig von
CPU/GPU, Betriebssystem und Modellanbieter; diese werden am Bildserver eingerichtet.

Unterstützte Protokolle:

| API-Format | Basis-URL als Beispiel | Aufruf / Antwort |
| --- | --- | --- |
| `sdapi` | `http://127.0.0.1:1235` | `POST /sdapi/v1/txt2img`; `images[0]` als Base64-PNG |
| `openai` | `http://127.0.0.1:8000/v1` | `POST /images/generations`; `data[0].b64_json` als Base64-PNG |

Das Format `openai` bezeichnet das kompatible HTTP-Protokoll, keinen bestimmten
Anbieter. Es kann vollständig lokal genutzt werden. Es werden keine Ergebnis-URLs
nachgeladen. Der Server muss ein PNG mit höchstens 20 MiB als Base64 zurückgeben.
ComfyUI-Workflows sind kein Bestandteil dieser beiden Protokolle; dafür weiterhin
die allgemeine MCP-Anbindung verwenden.

Beispiel in `eve.local.json` bzw. `eve.json` für einen lokalen CPU-Bildserver:

```json
{
  "image_generation": {
    "enabled": true,
    "api_format": "sdapi",
    "base_url": "http://127.0.0.1:1235",
    "model": "",
    "width": 1024,
    "height": 1024,
    "steps": 4,
    "guidance_scale": 1.0,
    "timeout_seconds": 3600,
    "extra_parameters": {"sampler_name": "Euler", "seed": -1}
  }
}
```

`steps` und `guidance_scale` gelten für `sdapi`. Beim kompatiblen
`openai`-Format werden `model`, `size`, `prompt`, `n: 1` und
`response_format: b64_json` gesendet. Zusätzliche, vom jeweiligen Server
unterstützte Felder können unter `extra_parameters` gesetzt werden. Standardfelder
dürfen dort nicht überschrieben werden. Zugangsdaten gehören ausschließlich in
`EVE_IMAGE_API_KEY` bzw. das geheime Schlüsselfeld in der Oberfläche (Speicherung
in `.env`). Requests verwenden keinen Umgebungsproxy und folgen keinen Redirects.

## Aufträge und Ergebnisse

Standard sind 1024 × 1024 Pixel. Die Bildmaße in der Konfiguration bleiben
änderbar. Im Chat können andere Maße beauftragt werden, zum Beispiel
„Erzeuge eine Berglandschaft mit 1536 × 1024 Pixeln“ oder
„Diesmal nur 768 × 512“. Diese Angaben gelten nur für den jeweiligen Auftrag;
die nächste Anfrage ohne Größenangabe verwendet wieder die konfigurierten
Standardmaße. Unterstützt werden 64 bis 4096 Pixel pro Seite in Schritten von 64;
zusätzlich gelten die Größenbeschränkungen des gewählten Bildservers und Modells.
Ungültige Maße werden abgelehnt und nicht stillschweigend gerundet.

Die Fähigkeit `image_generation` bietet `submit(prompt, width?, height?)` und
`status(job_id, wait_seconds=0)`. Ein Auftrag startet im Hintergrund; EVE bleibt
für weitere Gespräche verfügbar. Pro EVE-Instanz läuft höchstens ein Bildauftrag.
`status` kann bis zu 20 Sekunden auf dessen Ende warten. Das Bild wird beim Abruf
des fertigen Auftrags über EVEs vorhandenen Dateiausgabepfad bereitgestellt, im
Webchat als Download und in Chatto als Asset. Es gibt keine automatische
Fertigmeldung; nach dem Stand oder dem fertigen Bild fragen.
Die tatsächlich angeforderten Maße stehen in Auftrag und Statusantwort und
bleiben mit dem Auftrag gespeichert. Eine einzeln angegebene Breite oder Höhe
ersetzt nur diese Dimension; für die andere gilt der konfigurierte Standard.

Aufträge sind an das auslösende Gespräch gebunden. In Chatto-Channels muss
`image_generation` ausdrücklich unter **Erlaubte Channel-Werkzeuge** freigegeben
werden. Standardmäßig ist die Fähigkeit dort nicht freigegeben.

Auftragsdaten und PNGs bleiben unter `data/generated-images/` erhalten. Nach einem
EVE-Neustart sind fertige Bilder weiter abrufbar; unterbrochene Aufträge werden
als fehlgeschlagen mit unklarem Serverausgang markiert und nie automatisch erneut
gestartet. Auch bei einem HTTP-Zeitlimit kann der Bildserver noch arbeiten. Es gibt
keinen automatischen Abbruch am Server und keine automatische Wiederholung.

## Lokaler CPU-Dienst als Beispiel

[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) bietet einen
CPU-Build und beide hier unterstützten HTTP-Protokolle. Für diesen Zweck ohne
CUDA, Vulkan, Metal oder andere GPU-Backends bauen. Die
[Server-API](https://github.com/leejet/stable-diffusion.cpp/blob/master/examples/server/api.md)
beschreibt die Endpunkte. Ein kleineres Modell wie
[SD-Turbo](https://huggingface.co/stabilityai/sd-turbo) eignet sich für einen ersten
CPU-Versuch. Für SD-Turbo mit 512 × 512 Pixeln, 1–4 Schritten und niedriger Guidance
beginnen. Modellqualität und Laufzeit müssen mit dem gewählten Rechner geprüft
werden; EVE gibt keine Laufzeitzusage.

Den Bildserver an Loopback binden, beispielsweise Port 1235. EVE startet oder
beendet diesen externen Dienst nicht. Der Dienst kann auf demselben Rechner oder
einem freigegebenen Rechner im lokalen Netz laufen. Nach dem einmaligen Download
der Laufzeit und Gewichte benötigt die lokale Generierung keinen Internetzugang.

Der hier geprüfte CPU-Build stammt von Commit
`e41fbcf455e0fbb45e08bd535b00d6cba865e921`. CMake-Konfiguration:

```bash
cmake -S runtime/imagegen/stable-diffusion.cpp -B runtime/imagegen/stable-diffusion.cpp/build \
  -DCMAKE_BUILD_TYPE=Release -DSD_CUDA=OFF -DSD_VULKAN=OFF -DSD_METAL=OFF \
  -DSD_WEBP=OFF -DSD_WEBM=OFF -DSD_SERVER_BUILD_FRONTEND=OFF
cmake --build runtime/imagegen/stable-diffusion.cpp/build --target sd-cli sd-server --parallel 2
```

Für diesen Versuch wurde die offizielle Datei `sd_turbo.safetensors` aus
`stabilityai/sd-turbo`, Revision `b261bac6fd2cf515557d5d0707481eafa0485ec2`,
heruntergeladen und ihre SHA-256-Prüfsumme
`3f067a1b943cf162f2b8f8588f6cf5824bd5b4c7d1d88d87164b9ca123616549`
geprüft. Quantisierung und Start aus dem EVE-Anwendungsordner:

```bash
runtime/imagegen/stable-diffusion.cpp/build/bin/sd-cli -M convert \
  -m runtime/imagegen/sd_turbo.safetensors --type q8_0 \
  -o runtime/imagegen/sd-turbo-q8_0.gguf
runtime/imagegen/stable-diffusion.cpp/build/bin/sd-server \
  -m runtime/imagegen/sd-turbo-q8_0.gguf \
  --listen-ip 127.0.0.1 --listen-port 1235 -t 4 --vae-tiling
```

Die Laufzeit und Gewichte sind externe, nicht mit dem Repository ausgelieferte
Dateien. Eigene Modelle, Server und Installationspfade können verwendet werden.
Ein erster CLI-Test auf dem Ryzen 7 5700X erzeugte ein PNG mit 512 × 512 Pixeln
bei einem Sampling-Schritt in 38,22 Sekunden reiner Generierungszeit. Das ist eine
Einzelmessung mit SD-Turbo Q8 und vier CPU-Threads, keine allgemeine Laufzeitzusage.
Der anschließende vollständige Test über `sd-server` und EVEs `submit`/`status`
lieferte dasselbe Format in 36,76 Sekunden als Antwortdatei zurück. Der Testserver
wurde danach beendet; die laufende EVE-Konfiguration wurde nicht geändert.

Nach der Erweiterung um Auftragsmaße wurde auch die native Standardgröße
1024 × 1024 über den echten EVE-Chat geprüft. Der Bildserver benötigte mit
SD-Turbo Q8 und vier CPU-Threads 211,12 Sekunden reine Generierungszeit.
Das erzeugte PNG wurde auf seine tatsächlichen Pixelmaße geprüft. Im Motiv
waren bei dieser höheren Auflösung wiederholte Landschaftsbereiche sichtbar;
die größere Pixelzahl garantiert mit diesem kleinen Modell keine bessere
Bildkomposition. Für andere Modelle gelten deren jeweilige Empfehlungen.

### Vergleich mit FLUX.2 Klein 4B

Am 25.10.2026 wurde dasselbe englische Berghütten-Motiv mit identischem Seed 42
und nativen 1024 × 1024 Pixeln mit FLUX.2 Klein 4B verglichen. Verwendet wurden
`leejet/FLUX.2-klein-4B-GGUF` (`flux-2-klein-4b-Q4_0.gguf`),
`unsloth/Qwen3-4B-GGUF` (`Qwen3-4B-Q4_K_M.gguf`) und
`black-forest-labs/FLUX.2-small-decoder`
(`full_encoder_small_decoder.safetensors`). Die Dateien wurden anhand der
SHA-256-Werte der festgehaltenen Repository-Revisionen geprüft.

Der CPU-Test nutzte vier Threads, vier Euler-Schritte, CFG 1, Flash Attention,
Memory-Mapping und VAE-Tiling. Gemessen wurden 790,87 Sekunden Gesamtlaufzeit
(etwa 13 Minuten 11 Sekunden) und 4,77 GiB maximaler Prozess-RSS mit
`/usr/bin/time -v`. Die Bildberechnung dauerte 675,41 Sekunden, die
PNG-Dekodierung 108,17 Sekunden. Der bisherige SD-Turbo-Test benötigte
211,12 Sekunden reine Generierungszeit bei einem Schritt; die Modelle wurden
also in unterschiedlichen, jeweils für den Test gewählten Schrittzahlen geprüft.

Das FLUX-Testbild zeigte eine zusammenhängende Landschaft mit einer einzelnen
Hütte und plausibler Spiegelung, während im SD-Turbo-Test Landschaftsbereiche
wiederholt waren. Dies ist eine visuelle Beurteilung eines einzelnen Motivs,
keine allgemeine Qualitätsmessung. Zunächst wurde das Modell wegen der langen
CPU-Laufzeit nicht als Standard aktiviert. Nach Sichtung des Ergebnisses wurde
FLUX.2 Klein 4B auf ausdrücklichen Benutzerwunsch als lokales Bildmodell aktiviert:
vier Euler-Schritte, CFG 1, zunächst vier CPU-Threads, Flash Attention,
Memory-Mapping und VAE-Tiling. Nach dem unten beschriebenen CPU-Test werden
acht Threads und 512er-VAE-Kacheln verwendet.
Der Server bleibt unter `http://127.0.0.1:1235` erreichbar;
die EVE-Standardmaße bleiben 1024 × 1024, mit Größenangaben pro Chat-Auftrag.
Der frühere SD-Turbo-Startbefehl ist für einen Rückwechsel lokal unter
`runtime/imagegen/previous-server-command.json` abgelegt, der aktuelle Befehl
unter `runtime/imagegen/server-command.json`. Wie zuvor läuft der Bildserver
als separater lokaler Prozess; eine automatische Einrichtung als Systemdienst
ist damit nicht verbunden. Startbeispiel aus dem EVE-Anwendungsordner:

```bash
OMP_NUM_THREADS=8 runtime/imagegen/stable-diffusion.cpp/build/bin/sd-server \
  --diffusion-model runtime/imagegen/flux-klein/flux-2-klein-4b-Q4_0.gguf \
  --llm runtime/imagegen/flux-klein/Qwen3-4B-Q4_K_M.gguf \
  --vae runtime/imagegen/flux-klein/full_encoder_small_decoder.safetensors \
  --listen-ip 127.0.0.1 --listen-port 1235 -t 8 \
  --steps 4 --cfg-scale 1 --sampling-method euler \
  --flash-attn on --mmap --vae-tiling --vae-tile-size 512
```

Lokale Messdaten, Modellrevisionen und Bilder liegen unter
`runtime/imagegen/flux-klein-benchmark.json`, `runtime/imagegen/flux-klein/manifest.json`
und `runtime/imagegen/flux-klein-comparison.png`; diese Laufzeitdateien werden
nicht mit dem Quellcode ausgeliefert.

### CPU-Optimierung bei gleicher Schrittzahl und Auflösung

Am 25.10.2026 wurde die Rechenzeit mit demselben Motiv, Seed 42 und 1024 × 1024
Pixeln mit vier, sechs und acht Threads verglichen. Die kurzen Proben nutzten
jeweils einen Sampling-Schritt und wurden nach dessen gemessener Fertigstellung
vor der Bilddekodierung beendet. Es sind Einzelmessungen, keine statistischen
Mittelwerte oder Qualitätsvergleiche von Ein-Schritt-Bildern.

| Threads | Sampling-Zeit für einen Schritt |
| --- | ---: |
| 4 | 164,74 s |
| 6 | 125,01 s |
| 8 | 99,12 s |

Anschließend wurde mit acht Threads, weiterhin vier Euler-Schritten und nativen
1024 × 1024 Pixeln ein vollständiges Bild erzeugt. Die VAE-Kacheln wurden dabei
von 256 auf 512 Pixel vergrößert, bei weiterhin 50 % Überlappung. Die größere
Kachelgröße wurde tatsächlich verwendet; der Decoder verarbeitete neun statt
49 Kacheln. Die Bilddatei wurde visuell auf auffällige Kachelartefakte geprüft.

| Messung | Bisher: 4 Threads, Kachel 256 | Optimiert: 8 Threads, Kachel 512 |
| --- | ---: | ---: |
| Gesamtlaufzeit inklusive Laden | 790,87 s | 454,69 s |
| Sampling, vier Schritte | 675,41 s | 397,59 s |
| Bilddekodierung | 108,17 s | 52,46 s |
| Maximaler Prozess-RSS | 4,77 GiB | 5,42 GiB |

Der neue Durchlauf war rund 43 % kürzer (7 Minuten 35 Sekunden statt
13 Minuten 11 Sekunden). Beide Messungen erfolgten mit derselben quantisierten
Modellkombination, CPU-Ausführung, Flash Attention und Memory-Mapping. Die
Messprogramme liefen mit niedriger Prozesspriorität (`nice 10`). Hintergrundlast
und Motiv können weitere Laufzeiten beeinflussen; pixelidentische Ergebnisse
durch verschiedene Thread- und Kachelgrößen werden nicht zugesichert.

Das geprüfte Profil wurde im lokalen Bildserver übernommen. EVE selbst musste
dafür nicht neu gestartet werden; Modell, Endpunkt, vier Schritte und
Standardauflösung blieben erhalten. Der Startbefehl steht oben. Zusätzlich ist
`OMP_NUM_THREADS=8` lokal unter `runtime/imagegen/server-env.json` festgehalten.
Messprotokolle und Vergleichsbild liegen unter `runtime/imagegen/cpu-tuning/`
(`probes.json`, `result.json`, `optimized.png`).
