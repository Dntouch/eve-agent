# Dienststatus und Steuerung

Die Anzeige **Dienste** oben in EVE zeigt den überwachten Gesamtzustand. Ein Klick
öffnet die Dienstübersicht direkt in EVE. Gestörte Dienste und Hinweise stehen
oben, jeweils mit konkreter Meldung und den verfügbaren Steuerknöpfen.
Der Link **Unabhängige Konsole** im Kopf der Übersicht öffnet die auch ohne EVE
erreichbare Steuerung. Bei EVE auf Port 8790 liegt sie unter
`https://127.0.0.1:8792/`, im LAN unter demselben Hostnamen wie EVE mit Port 8792.
Sie verwendet EVEs Hostfreigaben und TLS-Zertifikat. Die Browseroberfläche akzeptiert
Dienstaktionen ausschließlich als JSON über die eigene Origin.

Die unabhängige Konsole wird vom lokalen `desktop-start.sh` in einer eigenen Sitzung gestartet
und bleibt beim Stoppen und Neustarten von EVE erreichbar. Manuell:

```sh
PYTHONPATH=src .venv/bin/python -m eve_agent.services --config eve.json --ensure
```

Standardport: EVE-Port + 2. `EVE_SERVICE_PORT` überschreibt ihn; diese Variable
bei beiden Prozessen setzen. `EVE_SERVICE_CONSOLE=0` unterdrückt den automatischen
Start durch den Desktoplauncher. Die Konsole ist Teil der lokalen Installation;
nach einem Rechnerneustart startet sie beim nächsten EVE-Desktopstart.

Die Prüfung erfolgt alle 15 Sekunden, parallel und mit Zeitlimits. SearXNG wird
dabei über seine lokale JSON-Konfiguration geprüft. Eine tatsächliche Suchprobe
erfolgt höchstens alle fünf Minuten, um externe Suchmaschinen nicht mit
Überwachungsanfragen zu belasten. Die Ansicht
fragt den letzten Prüfstand alle zwei Sekunden ab. Veraltete oder nicht mehr
erreichbare Prüfstände werden als unbekannt dargestellt.

| Dienst | Prüfung | Steuerung |
| --- | --- | --- |
| EVE | Prozess erreichbar und Bereitschaft des konfigurierten Modells | Starten, Stoppen, Neustarten über die lokalen Desktoplauncher |
| LLM | `/models` enthält das konfigurierte Modell | Lokaler Container `eve-strata`, wenn seine Portbindung oder sein Hostnetzwerk-`PORT` zur konfigurierten URL passt |
| SearXNG | Echte JSON-Suche einschließlich Ergebnissen und gestörter Suchmaschinen | Installationscontainer `eve-search-<Hash>` oder lokaler `eve-searxng`, jeweils nur bei passender Portbindung |
| Web-Werkzeuge im Chat | Registrierung im laufenden Prozess, Freigaben je Transport und letzter Web-Aufruf | Diagnose; ein Suchdienstneustart behebt keinen ungültigen Funktionsnamen |
| Chatto | Botstatus im laufenden EVE-Prozess | Starten, Stoppen, Neustarten, wenn Chatto konfiguriert und EVE erreichbar ist |
| Home Assistant und Bildgenerierung | Konfigurierte API | Auf dem jeweiligen Dienst-Host verwalten |
| Sprachausgabe | Piper-Stimmdateien oder HTTP-Status des konfigurierten Sprachservers | In EVE integriert beziehungsweise zusammen mit EVE verwaltet |

Die Konsole legt keine Container an, lädt keine Modelle herunter und führt keine
vom Browser gelieferten Shellbefehle aus. Externe LLM- und Suchendpunkte bekommen
keine lokalen Containerknöpfe. EVE stoppen beendet EVE und ihre Kindprozesse;
LLM und SearXNG bleiben separat steuerbar. Das vollständige Stoppen des Stacks
über `eve-control.sh stop` bleibt verfügbar. Die Dienstkonsole bleibt auch dabei aktiv.

Dienstaktionen laufen im Hintergrund und sind serialisiert. Der Abschluss eines
Steuerbefehls und die danach gemessene Betriebsbereitschaft werden getrennt
angezeigt. Das Laden eines Modells kann nach erfolgreichem Startbefehl noch dauern.
Protokolle: `runtime/services/console.log` und `runtime/services/actions.jsonl`.

`unpublished_tool` bedeutet: Der Modellaufruf verwendet keinen aktuell
veröffentlichten Funktionsnamen. Der Provider wurde nicht aufgerufen. EVE erhält
hierzu die verfügbaren Fähigkeiten und die Anweisung, zunächst über
`eve__load_capabilities` den Vertrag zu laden und anschließend den exakten
Funktionsnamen zu verwenden. Das erweitert keine Gesprächsrechte und ersetzt
keinen echten Berechtigungsfehler.
