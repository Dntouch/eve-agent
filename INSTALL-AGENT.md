# EVE durch einen Coding-Agenten installieren

Diesen Auftrag in Codex, OpenClaw oder einen anderen Agenten mit Terminalzugriff
kopieren. Das verwendete GitHub-Konto benötigt Zugriff auf das Repository.

```text
Installiere EVE aus https://github.com/Dntouch/eve-agent.git auf diesem Rechner.

1. Prüfe Betriebssystem, Python (mindestens 3.11), Git und freien Speicher.
   Klone das Repository in einen neuen Ordner. Nutze keine bestehende
   EVE-Installation als Ziel und überschreibe keine Konfiguration.
   Liegt install.py unter outputs/eve-local-agent, ist das der Anwendungsordner;
   andernfalls ist es das Repository-Hauptverzeichnis.

2. Kläre, welcher OpenAI-kompatible Modellserver verwendet werden soll.
   Verwende eine vorhandene Installation. Falls keine existiert, frage nach,
   bevor du ein Sprachmodell oder GPU-Treiber installierst. Ermittle Modelladresse
   und Modellname; prüfe GET <base_url>/models. Zugangsdaten gehören in die lokale
   .env oder Prozessumgebung, niemals ins Repository oder in deinen Bericht.

3. Führe im Anwendungsordner aus:
   python install.py --non-interactive --llm-url BASE_URL --model MODELLNAME --with-speech
   Wenn bereits eine EVE läuft, ergänze --port 8791 (oder einen anderen freien
   Port). Behalte den separaten Installationsordner und kopiere keine Datenbank
   oder .env aus der laufenden EVE.
   Verwende je nach System python3 oder py -3. Der Installer prüft das mitgelieferte
   EVE-Piper-Modell, lädt Whisper small und richtet die fest versionierten CPU-Embeddings ein. Ersetze die EVE-Stimme nicht durch eine
   andere Stimme. Verwende für Python-Pakete die angelegte .venv.

4. Richte die Websuche ein. Verwende eine vorhandene SearXNG-Instanz mit JSON-API.
   Fehlt sie, prüfe Docker oder Podman und führe scripts/setup_search.py aus
   (bei Parallelbetrieb beispielsweise --port 8889). Übernimm die ausgegebene URL.
   Das Skript verwendet ein festes Image und erzeugt ein eigenes Secret. Binde den Port
   ausschließlich an 127.0.0.1 und verwende einen zufälligen Server-Secret-Key.
   Frage nach, wenn dafür erst eine Container-Laufzeit oder Virtualisierung
   installiert werden muss. Ergänze in eve.local.json web.enabled=true und
   web.searxng_url. Prüfe /search?q=EVE&format=json auf gültige Suchergebnisse.
   Falls SearXNG nicht eingerichtet werden kann, benenne Websuche als offen.

5. Prüfe die Konfiguration mit eve doctor --config eve.local.json in der .venv.
   Starte EVE über EVE-starten.cmd unter Windows oder ./eve-start unter Unix.
   Prüfe http://127.0.0.1:8790/health/live und /health/ready, öffne die Weboberfläche
   (bei --port 8791 entsprechend Port 8791)
   und teste eine Textantwort. Prüfe Piper durch Erzeugen einer WAV-Datei mit
   der EVE-Stimme und Whisper anhand einer kurzen Aufnahme, soweit Audiozugriff
   möglich ist. Aktiviere keine Shell-, Desktop- oder Home-Assistant-Steuerung.

6. Nenne den Startbefehl und die Webadresse. Berichte knapp, welche Prüfungen
   bestanden sind und was noch fehlt. Behaupte keinen erfolgreichen Audio- oder
   Windows-Test, wenn du ihn nicht ausgeführt hast. Lasse laufende Dienste und
   lokale Daten anderer Anwendungen unverändert.
```
