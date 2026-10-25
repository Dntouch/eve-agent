# Externe MCP-Server in EVE

EVE kann lokale stdio-MCP-Server als eigene Fähigkeiten bereitstellen. Programm,
Argumente, Prozessumgebung, Arbeitsverzeichnis, Sitzungsumfang und Zeitlimit sind
konfigurierbar. Werkzeugnamen, Beschreibungen, JSON-Schemas, Server-Anleitungen und
Ergebnisse stammen vom jeweiligen Server. EVE interpretiert keine CAD-Befehle in
Python und erweitert ihren Systemprompt nicht um Fachanweisungen.

Jeder konfigurierte Server hat unter **Konfiguration** eine eigene Kategorie,
beispielsweise **SolidCraft**. Programm, Argumente, Sitzung und Dateifreigaben
werden dort über Eingabefelder bearbeitet. **Integrationen → Integration hinzufügen**
legt weitere Server an. Alle Kategorien einschließlich Community-Training werden
alphabetisch nach ihrem sichtbaren Namen sortiert. Alternativ den Abschnitt
`mcp.servers` in der eigenen Konfigurationsdatei bearbeiten. Anschließend
EVE neu starten. Das Serverprogramm muss auf dem Rechner laufen können, auf dem EVE
läuft; absolute Programmpfade funktionieren auch ohne PATH-Eintrag. Es gibt keine
Abhängigkeit von einem bestimmten Betriebssystem oder Benutzerverzeichnis.

## SolidCraft als Beispiel

SolidCraft und `solidcraft-cli` separat installieren. Die folgenden Einstellungen
gehören unter `mcp` in EVEs Konfigurationsdatei:

```json
{
  "mcp": {
    "max_sessions": 8,
    "servers": {
      "solidcraft": {
        "enabled": true,
        "description": "SolidCraft: parametrische CAD-Modelle erstellen, bearbeiten, prüfen und exportieren",
        "command": "solidcraft-cli",
        "args": ["mcp", "--headless", "--allow-path", "{workspace}"],
        "scope": "conversation",
        "timeout_seconds": 330,
        "startup": [
          {
            "tool": "open",
            "arguments": {"path": "{workspace}/project.solidcraft"},
            "if_exists": "{workspace}/project.solidcraft"
          }
        ],
        "after_write": [
          {"tool": "save", "arguments": {"path": "{workspace}/project.solidcraft"}}
        ]
      }
    }
  }
}
```

Die Weboberfläche bietet für diese Werte einzelne Felder. Start- und
Speicheraufrufe stehen unter **Erweiterte Einstellungen** als bearbeitbare
Aufruflisten; Werkzeugargumente bleiben dort im nativen JSON-Format.
Die Fähigkeit heißt `mcp_solidcraft`. Der Name nach `mcp_` entspricht dem
konfigurierten Servernamen. Weitere MCP-Programme werden genauso eingerichtet.

`conversation` startet einen eigenen Serverprozess pro EVE-Gespräch. Die
Arbeitsverzeichnisse liegen stabil unter `data/mcp/<server>/<gesprächshash>`.
`{workspace}` bezeichnet diesen absoluten Pfad, `{root}` den EVE-Anwendungsordner.
Beide Platzhalter sind in Programm, Argumenten, Umgebung, Arbeitsverzeichnis und
Lebenszyklus-Aufrufen verfügbar. Ohne `cwd` startet der Prozess im Workspace.

`startup` und `after_write` sind optionale Listen nativer Werkzeugaufrufe; sie
werden gegen die vom Server gelieferten Schemas geprüft. `if_exists` führt den
Aufruf nur aus, wenn die angegebene Datei existiert. Im Beispiel wird ein bereits
gespeichertes Modell beim Sitzungsstart geöffnet und nach Schreibaufrufen gesichert.
Das ist eine deklarative Einstellung, keine fest eingebaute SolidCraft-Logik.
Andere Server brauchen andere oder keine Lebenszyklus-Aufrufe.

Ein Fehler beim Sichern wird getrennt vom Ergebnis der eigentlichen Operation
zurückgegeben. Die Operation wird nicht erneut ausgeführt. Bei unklarem
Ausführungsstand sperrt EVE weitere Schreibaufrufe dieser Sitzung; lesende
Werkzeuge bleiben verfügbar. Vor einem Neustart den tatsächlichen Serverzustand
prüfen. Ein Neustart verwirft nicht gespeicherten Prozesszustand.

## Geöffnete Desktop-App steuern

Für eine bewusst gemeinsam verwendete SolidCraft-App eine **alternative**
Serverkonfiguration verwenden:

```json
{
  "solidcraft": {
    "command": "solidcraft-cli",
    "args": ["mcp", "--connect", "127.0.0.1:27878", "--allow-path", "{workspace}"],
    "scope": "shared",
    "description": "SolidCraft: gemeinsam geöffnete Desktop-Konstruktion bearbeiten",
    "timeout_seconds": 330
  }
}
```

Den tatsächlichen Kontrollport der installierten App verwenden. Das Beispiel
nutzt den in der aktuellen upstream-Dokumentation genannten Standardport. Die CLI
liest das lokale App-Token selbst. Eine geöffnete App besitzt einen gemeinsamen
Konstruktionszustand: `shared` ist daher ausdrücklich eine gemeinsame Sitzung für
alle berechtigten Gespräche. Für voneinander getrennte Chatto-Aufträge das erste
Beispiel mit `--headless` verwenden. Mehrere mit derselben App verbundene Prozesse
würden keine getrennten CAD-Projekte herstellen.

Das Beispiel für die Desktop-Verbindung enthält absichtlich keine automatischen
Öffnen-/Sichern-Aufrufe: vorhandene Konstruktionen der App sollen nur durch die
beauftragten nativen Werkzeugaufrufe ersetzt oder gespeichert werden.

## Dateien und Vorschauen

Native MCP-Bildblöcke werden als echte Bildressourcen an EVEs vorhandenen
Modell- und Ausgabepfad weitergegeben. Die technische Operation `eve_attach_file`
fügt eine bereits erzeugte Datei als Antwortanhang hinzu; sie modelliert und
exportiert selbst nichts. EVE muss zuerst das native Exportwerkzeug verwenden.
Dateien sind auf 20 MiB begrenzt. Im Web erscheinen sie als herunterladbare
Artefakte, in Chatto als echte Assets im selben Raum und Thread.

Der Workspace ist für diese Dateiübernahme freigegeben. Zusätzliche Verzeichnisse
können pro Server über `attachment_roots` gesetzt werden. Symlinks und `..` werden
vor dem Vergleich aufgelöst. Serverantworten mit lokalen Pfaden oder URLs werden
nicht automatisch heruntergeladen. Die Freigabe begrenzt EVEs Dateiübernahme;
sie isoliert nicht den gestarteten Prozess. Dessen eigene Dateirechte und
gegebenenfalls Sandbox-/Allow-Path-Optionen werden am Server konfiguriert.

Server mit MCP-Ressourcen erhalten außerdem `eve_list_resources` und
`eve_read_resource`. Server-Anleitungen und der konkrete Workspace werden beim
Laden der Fähigkeit als Laufzeitdaten bereitgestellt. Fachliche Anleitungen wie
SolidCrafts `skill_reference` bleiben native Serverwerkzeuge.

## Chatto-Aufträge und Memory

Die persönliche Eigentümer-DM behält die aktivierten EVE-Fähigkeiten. In Channels
muss `mcp_solidcraft` zusätzlich unter **Erlaubte Channel-Werkzeuge** ausgewählt
werden. Andere Mitglieder-DMs behalten ihr bestehendes eingeschränktes Profil.
Eine neue MCP-Integration wird dort nicht automatisch freigegeben.

Für SolidCraft unter **SolidCraft → Antworten in Chatto → thread** wählen.
Der allgemeine Chatto-Antwortmodus bleibt dabei **chat**. EVE wählt die Integration
über ihre regulären Werkzeugaufrufe. Erst wenn sie diese Fähigkeit auswählt,
wird die Antwort in einen eigenen Thread geleitet. Es gibt keine Erkennung von
CAD-Aufträgen über Schlüsselwörter in Python.

Die erste Anfrage bleibt als Herkunftsbeleg erhalten. Der neue Thread erhält
eine Kontextkopie dieser Anfrage und Antwort mit Verweisen auf den ursprünglichen
Turn. Das laufende MCP-Projekt bleibt dabei über eine stabile technische
Sitzungsreferenz erhalten. Folgeanfragen im Thread verwenden den eigenen Verlauf
und dasselbe Projekt. Die Kontextkopie erzeugt keinen zusätzlichen Lernauftrag.
In Channels gilt weiterhin die konfigurierte Erwähnungspflicht. Eingehende
Thread-Nachrichten werden im selben Thread beantwortet.

**Chatto → Arbeitsstatus in Threads anzeigen** aktiviert eine sichtbare
Statusnachricht. Während der Bearbeitung steht dort etwa „EVE arbeitet mit
SolidCraft …“. Bei Abschluss oder Fehler wird dieselbe Nachricht aktualisiert.
Der Status wird aus dem tatsächlich laufenden, an Raum und Nachricht gebundenen
Auftrag gelesen. Scheitert eine Statusübertragung, wird die Konstruktion nicht
automatisch wiederholt. Der native Schreibstatus bleibt zusätzlich aktiv.

Beim ersten Aufruf wird eine stabile, eindeutige Referenz `EVE-<UUID>` aus
Server-, Bot-, Raum- und Threadidentität gebildet. Sie erscheint im Gesprächstitel
und in der ersten Antwort. Alle Folgeturns tragen dieselbe Referenz in ihren
technischen Herkunftsdaten (`conversation_source.project_reference`), zusammen
mit der Thread-ID. Damit erhält auch die vorhandene Memory-Lernauswertung diesen
Bezug. Fachliche Namen, Fakten und Relationen bestimmt weiterhin das Modell;
Python leitet sie weder aus Schlüsselwörtern ab noch speichert es erfundene
fachliche Beziehungen. Der Thread-Modus ist allgemein und klassifiziert keine
Nachricht als CAD-Auftrag.

## Betrieb und Prüfung

`max_sessions` begrenzt gleichzeitig gestartete Serverprozesse. Ist die Grenze
erreicht, meldet EVE einen Fehler und verwirft keine Sitzung automatisch.
`enabled: false` deaktiviert einen Server. `env` ergänzt die Prozessumgebung;
Zugangsdaten möglichst über die Umgebung des EVE-Prozesses bereitstellen;
die zusätzlichen Prozessvariablen in der Webkonfiguration sind sichtbar. `protocol_version`
kann die bei der MCP-Initialisierung angebotene Version ändern.

Automatische Tests ohne SolidCraft oder Modellserver:

```bash
PYTHONPATH=src:tests .venv/bin/python -m unittest test_external_mcp test_config test_native_runtime test_chatto
node --test tests/js/chatto-bot.test.mjs tests/js/chatto-routing.test.mjs tests/js/chatto-output.test.mjs
```

Die stdio-Tests starten einen echten lokalen MCP-Testprozess. Ein vollständiger
CAD-Test benötigt zusätzlich die installierte SolidCraft-Version und ein
Werkzeugaufrufe unterstützendes Modell. Eine lokale Installation wird nicht
allein durch erfolgreich bestandene Transporttests bestätigt.

## Geprüfter lokaler Stand

Mit der vom Benutzer bereitgestellten SolidCraft-AppImage (CLI-Version 0.21.0)
wurde die echte Integration separat geprüft: parametrische Platte mit zwei
Bohrungen, Breitenänderung 40 → 50 mm, STEP-/STL-Export, Dateiübernahme,
Bildvorschau, getrennte zweite Sitzung und Wiederöffnung nach Prozessneustart.
Das gemeldete Volumen wurde mit dem analytischen Wert bei relativer Toleranz
`1e-4` verglichen; die Abweichung lag darunter. Das bestätigt den CAD-/MCP-Pfad,
keinen bereits ausgeführten Modellauftrag über einen echten Chatto-Server.

Bei einer AppImage muss `command` auf die CLI zeigen, nicht auf den grafischen
AppImage-Starter. Die CLI liegt im entpackten AppImage unter
`usr/bin/solidcraft-cli`. Ihr dauerhafter Zielpfad wird frei in der
Serverkonfiguration festgelegt; EVE speichert keinen persönlichen Downloadpfad
im allgemeinen Quellcode. Ein CLI-Update erfolgt durch Austausch dieser Datei
oder Änderung des konfigurierten Programmpfads.
