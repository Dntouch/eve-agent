# EVE in Chatto

Diese Anleitung beschreibt EVEs Bot-Anbindung. Ein Chatto-Server muss bereits
bereitstehen; dessen Adresse und ein eigener Bot werden in EVE konfiguriert.

EVE verbindet sich ausgehend per HTTPS/WebSocket mit Chatto 0.5.0-beta.19.
Der offizielle Client wird am Commit `cda6bf54bb5282752169adb376f03081c09f0d89`
gebaut. Die optionale Bot-Aktivität benötigt den eigenen Server-Build
`0.5.0-beta.24+hakkerwerkstatt.3` oder neuer. Normale Verbindungen behalten
ihre bisherige Mindestversion; ein SDK-Update ist dafür nicht nötig.
EVE bleibt eine Instanz mit gemeinsamem Gedächtnis. Die Nachrichten
bekommen technische Herkunftsdaten (Server, Raum, Absender und Zugriffsprofil).
Es gibt keine Klassifikation des Nachrichtentexts und keine Prompt-Änderung.

## Einrichtung und Konfiguration

Node 22.13 oder neuer mit `node:sqlite`, npm, Git und Python werden benötigt.
Im EVE-Anwendungsordner den Client einmal bauen:

```bash
python3 scripts/setup_chatto.py
```

Der Build lädt npm-Abhängigkeiten ohne Installationsskripte. Client, Quellen,
Lizenzhinweise und npm-Lockdatei liegen privat unter `runtime/chatto/`.

In EVEs Konfiguration den Abschnitt **Chatto** öffnen. Dort werden Aktivierung,
HTTPS-Serveradresse, Node-Programm, feste Eigentümer-Konto-ID, persönliche DMs,
freigegebene Channels, Erwähnungsmodus, Antwortmodus und Channel-Werkzeuge
konfiguriert. Sichtbare Channels lassen sich nach Namen auswählen. Der
Bot-Schlüssel kann im geschützten Eingabefeld gesetzt oder ersetzt werden.
Der gespeicherte Wert wird nicht zurückgegeben. Er liegt als
`EVE_CHATTO_BOT_KEY` in der privaten `.env` (0600), nicht in `eve.json`.
Ein leeres Eingabefeld behält den bestehenden Schlüssel bei.

Änderungen an Chatto werden beim Speichern übernommen. Channel-Freigaben,
Werkzeugrechte und Antwortmodus gelten ab der nächsten Nachricht ohne
Verbindungsneustart. Server, Schlüssel, Node-Programm, Eigentümer, Aktivierung
oder Präsenzmodus verbinden bei Bedarf nur den Bot neu; EVE selbst läuft weiter.
Ein bereits laufender Turn verwendet sein beim Start gültiges Werkzeugprofil.
Neue sichtbare Räume werden alle 30 Sekunden eingelesen; die Konfiguration
erneut öffnen, um die Auswahl zu aktualisieren. Der Bot startet und stoppt
weiterhin zusammen mit EVE. Anzeigename und Benutzername sind keine Autoritätsmerkmale;
Umbenennungen verändern die Bindung an Konto- und Raum-IDs nicht.
In Chatto muss der Bot Mitglied sein und Lese-/Antwortrechte im jeweiligen
Raum besitzen. Direkte Antworten benötigen `message.post`. Menschen eröffnen DMs;
danach kann EVE dort auch ohne neue eingehende Nachricht Erinnerungen zustellen.

**Online-Status anzeigen** meldet den verbundenen Bot im Leerlauf als online
(grüner Punkt). Während einer Chatto-Anfrage, eines lokalen Text- oder Sprachgesprächs
oder einer geplanten EVE-Aufgabe wechselt der Punkt auf Gelb/Orange;
dafür nutzt EVE Chattos vorhandenen Status „Abwesend“ (`Away`). Die Chatto-Oberfläche
kann diesen Status entsprechend als „Abwesend“ beschriften. Der Farbwechsel umfasst
das Laden von Bildern, Modell- und Werkzeugaufrufe sowie das Versenden der Antwort.
Nach Abschluss, Fehler oder Abbruch wechselt EVE wieder auf Grün, sobald alle
gleichzeitig laufenden Anfragen beendet sind. Lokale Spracheingaben zählen ab der
Transkription; lokale Browser-Turns einschließlich ausstehender Antwortaufbereitung
und Audioerzeugung bleiben bis zum Abschluss beschäftigt. Der Bot fragt den
zusammengefassten Arbeitsstatus ungefähr jede Sekunde über die geschützte lokale
Bridge ab. Dabei werden keine Gesprächsinhalte, Personen, Räume oder Aufgabendetails
übermittelt. Schlägt die Abfrage fehl, bleibt der zuletzt bekannte Arbeitsstatus
bis zur nächsten erfolgreichen Abfrage erhalten. Stilles Mitlernen und interne
Gedächtniswartung verändern die Farbe nicht. Browser-Audiowiedergabe nach dem
Abschluss der serverseitigen Verarbeitung zählt nicht als laufende Arbeit.
Die Präsenz wird alle 30 Sekunden erneuert, auch während eines längeren Modellaufrufs. Beim
normalen Stoppen wird offline gemeldet. Bei Verbindungsverlust stoppt der
Heartbeat; Chatto lässt die Präsenz nach etwa 60 Sekunden verfallen. Der Status
beschreibt die Bot-Verbindung und ist keine Garantie für die Modellverfügbarkeit.
Chatto zeigt bei Bots den farbigen Statuspunkt und blendet den Punkt offline aus;
der Bot bleibt in der eigenen Mitgliedergruppe Bots.

## Bot-Aktivität während der Bearbeitung

Nach Aktualisierung EVE einschließlich des Bots einmal neu starten. Es gibt
keinen zusätzlichen Dienst und keinen neuen Schlüssel. Die Aktivitätsanzeige
arbeitet unabhängig von Online-Farbpunkt und Profilstatus. Sie erzeugt keine
Fortschrittsnachrichten. Der frühere Schalter `thread_status_enabled` wird beim
Einlesen alter Konfigurationen weiterhin akzeptiert, hat aber keine Wirkung mehr
und wird nicht mehr in der Konfiguration angeboten. Bereits vorhandene alte
Statusnachrichten werden nicht verändert.

Die vorhandene Bot-Authentifizierung sendet Connect-JSON an
`/api/connect/chatto.api.v1.RoomService/RefreshTypingIndicator` mit
`Connect-Protocol-Version: 1`. Nur `roomId`, gegebenenfalls
`threadRootEventId` und `botActivity` werden übertragen. Für Raumantworten fehlt
das Thread-Feld vollständig. Eine Thread-Wurzel kommt ausschließlich aus dem
verifizierten Eingang beziehungsweise dem tatsächlichen Ausgabeziel. Eröffnet
eine MCP-Integration einen Thread, wird die ursprüngliche Chatto-Nachricht dessen
Wurzel; die Aktivität im bisherigen Raum wird beendet. EVE-Gesprächs-IDs und
Antwort-IDs werden dafür nicht verwendet.

Tatsächlich verwendete Laufzeitereignisse:

| Ereignis / Einstiegspunkt | Aktivität |
| --- | --- |
| Annahmeverarbeitung, wartender/laufender Auftrag, Beginn eines Modell-Transportversuchs (`_request_lifecycle`) | `THINKING` |
| Eintritt in `NativeToolRuntime._execute_direct`, einschließlich Capability-Loader und bestätigter Wiederverwendung | `TOOL_USE` |
| Derselbe Dispatcher mit Capability `web`, einschließlich Suche und Seitenabruf | `WEB_RESEARCH` |
| Erster nichtleerer Content-Delta im nativen Modellstream oder Antwortstream | `WRITING` |
| Ende eines Werkzeugaufrufs, auch bei Fehler oder Abbruch | Verbleibende Werkzeuge, sonst aktuelle Modellphase |
| Abschluss, Modellfehler, Abbruch, abgelaufener Auftragsstand, Shutdown | Letzte Aufgabe im Ziel beendet: `IDLE` |

Chatto-Turns und geplante Aufgaben mit Chatto-Ausgabeziel verwenden den vorhandenen
Modellstream intern, damit der Beginn der Texterzeugung beobachtbar ist. Die
fertige Antwort wird weiterhin über die bestehende Zustellwarteschlange versandt.
Bei einem gepufferten Modellaufruf lässt sich `WRITING` erst bei Empfang der
Antwort feststellen. Reine Reasoning-Deltas ändern die Kategorie nicht. Weder
Reasoning noch Content-Deltas werden als Aktivitätsdaten übertragen.

Der Bot liest den aktuellen Auftragsstand alle 500 ms über die geschützte lokale
Bridge. Sehr kurze Zwischenphasen können zusammengefasst werden. Die jeweils
aktuelle Kategorie wird alle drei Sekunden erneuert. Pro Server, Bot, Raum und
optionaler Thread-Wurzel werden parallele Aufgaben aggregiert. Priorität:
`WEB_RESEARCH`, dann `TOOL_USE`, dann `WRITING`, dann `THINKING`. Werkzeugstarts
besitzen interne Aufruf-IDs; doppelte oder verspätete Werkzeugenden entfernen
keinen anderen laufenden Aufruf. Geplante Aufgaben melden im konfigurierten
Ausgabeziel, ohne aus diesem Ziel zusätzliche Werkzeugrechte abzuleiten.

Requests laufen je Ziel nacheinander. Ausstehende Zwischenstände werden
zusammengefasst, auch während einer Berechtigungsprüfung. Ein regulärer Refresh
hat insgesamt 1,5 Sekunden Timeout, `IDLE` eine eigene Sekunde unabhängig vom
Abbruchsignal. Vor nichtleerer Aktivität werden Bot-Konto, freigegebenes Ziel,
Mitgliedschaft, Leserechte und gegebenenfalls Lesbarkeit der Thread-Wurzel geprüft.
Eine Schreibberechtigung wird für Aktivität nicht zusätzlich verlangt. Der
Server bleibt für die endgültige Zugriffskontrolle zuständig. Es werden keine
Rechte erweitert und keine Request-Inhalte oder Schlüssel zusätzlich geloggt.

Netzwerkfehler und fehlende Berechtigungen beeinflussen die Antwort nicht. Es gibt
keine eigene Wiederholungsschleife; nur weiterhin aktive Arbeit wird beim nächsten
Heartbeat erneut gemeldet. Nach 4,5 Sekunden ohne frischen Bridge-Auftragsstand
wird dessen Aktivität beendet. Bei Chatto-Verbindungsverlust werden alte
Auftragssnapshots verworfen. Nach Wiederverbindung zählen nur neue Snapshots;
Antworten und Werkzeugaktionen werden dafür nicht wiederholt. Timer und
Abbruchlistener werden am Ende entfernt. Nach einem harten Prozessabbruch gilt
Chattos serverseitiger Ablauf sechs Sekunden nach dem letzten Refresh. Wenn ein
Server nach einem Client-Timeout einen Request trotzdem verspätet verarbeitet,
kann der Client ohne serverseitige Versionsnummer keine absolute Commit-Reihenfolge
garantieren; Serialisierung und abschließendes `IDLE` begrenzen diesen Fall.

## Gesprächskontext und Werkzeuge

Die persönliche Eigentümer-DM ist auf den konfigurierten menschlichen
Bot-Eigentümer und exakt zwei Teilnehmer beschränkt. Sie behält EVEs bestehende Werkzeugrechte.
Mit „Private Chats für andere Mitglieder“ (`member_dm_enabled`) können auch
andere menschliche Mitglieder EVE in einem Zweierchat anschreiben, ohne
Erwähnung. Jeder DM-Raum hat einen eigenen Verlauf; die Backend-Bindung für
Mitglieder enthält zusätzlich die Absender-ID. Gruppen-DMs und Bot-Absender
bleiben ausgeschlossen. Mitglieder-DMs erhalten ausschließlich Memory,
Bedeutungslernen, Arbeitsgedächtnis, Web, Uhrzeit und Rechner, unabhängig von
eventuell erweiterten Channel-Werkzeugen. Die Eigentümer-DM behält unverändert
ihre bisherigen Rechte. Der Schalter wirkt ohne Neustart ab der nächsten
Nachricht. Auch diese Gespräche verwenden EVEs gemeinsamen dauerhaften
Wissensbestand und den bestehenden Lernprozess; getrennte Verläufe sind keine
getrennten Gedächtnisse.
Die Gesprächsliste im EVE-Webfrontend blendet private Mitglieder-DMs standardmäßig
aus. Unter Konfiguration → Chatto lassen sie sich mit „Private Mitglieder-Chats im
Webfrontend anzeigen“ (`show_member_dms_in_web`) wieder einblenden. Die Änderung
gilt beim nächsten Laden der Liste ohne Neustart und auch für bestehende Verläufe.
Eigentümer-DMs (`show_owner_dms_in_web`) und Channels (`show_channels_in_web`)
lassen sich dort unabhängig davon ein- und ausblenden; beide sind standardmäßig
sichtbar. Dies ist ein Anzeigefilter für die
Gesprächsliste, keine zusätzliche Zugriffssperre; Speicherung und Lernen bleiben
unverändert.

In freigegebenen Channels können alle menschlichen Teilnehmer EVE ansprechen.
Standardmäßig antwortet sie nur auf vom Server bestätigte Erwähnungen.
Bot-Nachrichten werden nicht verarbeitet. Optional können alle neuen
Textnachrichten in freigegebenen Channels verarbeitet werden.

Standardmäßig erscheinen Antworten direkt im Chat. `reply_mode=thread` schaltet
auf Thread-Antworten um. Der laufende Kontext gehört zum jeweiligen Raum und
Zugriffsprofil, in Channels gemeinsam für dessen Teilnehmer. Das dauerhafte
Gedächtnis bleibt dasselbe. Dies ist keine automatische Datenschutzentscheidung
über den Inhalt von Erinnerungen.
Chatto-Gespräche durchlaufen dieselbe nachgelagerte Lernauswertung wie lokale
Gespräche. Die gespeicherten Absender- und Raumdaten werden der Auswertung
übergeben und bleiben an den Lernbelegen erhalten. Das Modell entscheidet,
welche Aussagen dauerhaftes Wissen darstellen. Nachrichten ohne Erwähnung
werden nur in separat ausgewählten `channel_learning_ids`
(„Mitlernkanäle“) übernommen. Ein Raum muss zusätzlich unter `channel_ids`
freigegeben sein. Diese Auswahl gilt sofort ab der nächsten Nachricht.
Stilles Mitlernen übernimmt neue Textnachrichten menschlicher Mitglieder mit
Absender und Raum, erzeugt keine Assistentenantwort und führt keine Werkzeuge
aus. Anhänge werden dabei nicht heruntergeladen. Die spätere Lernauswertung
entscheidet weiterhin über dauerhaftes Wissen; historische Nachrichten werden
nicht nachträglich eingelesen. Leere Mitlernauswahl deaktiviert stilles Lernen.
Die echten Memory-Werkzeuge werden bereits im ersten Modellaufruf angeboten;
sie benötigen keinen vorgeschalteten Loader-Aufruf. Andere Anbieter wählt das
Modell über den vorhandenen Capability-Loader selbst aus.

Die Channel-Freigabeliste enthält standardmäßig nur Gedächtnis,
Bedeutungslernen, Arbeitsgedächtnis, Webrecherche, Uhrzeit und Rechner.
Home Assistant einschließlich Hausinventar und Ereignissen, lokale Dateien und
Suche, Shell, Nova, Desktop, lokales Netzwerk sowie geplante und delegierte
Aufträge sind damit gesperrt. Die Freigabeliste ist in der Konfiguration
bearbeitbar. Rechte werden nicht aus Nachrichtentext oder Prompt abgeleitet.
Die native Werkzeugliste wird gefiltert und der Dispatcher prüft jeden Aufruf
noch einmal. Unbekannte oder später hinzugefügte Werkzeuge sind im Channel
standardmäßig gesperrt. Die Sperre wird pro Turn gesetzt und danach verworfen.

Die lokale Chatto-API verwendet einen eigenen zufälligen Schlüssel, unabhängig
vom Assist-Token. Nur der lokale Bot erhält ihn. Gesprächs-IDs sind serverseitig
an Server, Bot, Raum und Zugriffsprofil gebunden. Ein Channel kann damit keine
persönliche DM-Unterhaltung fortsetzen. Der Modelltext kann kein Profil wählen.
Der lokale Transport nutzt Loopback; bei HTTPS wird EVEs Zertifikat geprüft.

## Diagnose und Grenzen

Der Abschnitt Chatto zeigt den Verbindungsstatus beim Laden der Konfiguration.
`GET /api/chatto/status` liefert denselben Betriebsstatus. Lokale Dateien:

- `runtime/chatto/status.json`: Verbindung, fehlende Rechte oder Turn-Fehler
- `runtime/chatto/bot.log`: technische Meldungen ohne Nachrichten und Schlüssel
- `runtime/chatto/state.sqlite`: Gesprächszuordnung und verarbeitete Nachrichten-IDs

Normale Chatto-Aufträge werden über `POST /api/chatto/submit` dauerhaft angenommen
und sofort mit HTTP 202 bestätigt. EVE arbeitet die Aufträge der Reihe nach im
Hintergrund ab. Die ursprüngliche HTTP-Anfrage und eine durchgehende
Chatto-Verbindung sind für die Bearbeitung nicht erforderlich. Eine wiederholte
Übergabe derselben Server-/Bot-/Raum-/Nachrichten-ID führt keinen zweiten
Modell- oder Werkzeugaufruf aus. Stilles Mitlernen behält seinen bisherigen Weg.

Die Tabelle `chatto_jobs` in `data/eve.db` speichert Aufträge, Ziel und Zustellstand.
Nach Abschluss werden Antwort und Anhänge atomar für den bestehenden
Bot-Zustellweg bereitgestellt. Gespeichert sind Server, Bot, Channel beziehungsweise
DM, Absender, Ursprungsnachricht und gegebenenfalls Thread; auch ein erst durch
ein MCP-Werkzeug eröffneter Thread bleibt erhalten. Vor dem Versand prüft der Bot
die aktuelle Konfiguration, Eigentümerschaft, Mitgliedschaft, Zielthread und
Schreibrechte. Nach bestätigter Zustellung wird die zusätzliche Kopie des
Antwortinhalts aus der Warteschlange entfernt; die Gesprächshistorie bleibt erhalten.

Bei einem Bot-Neustart oder Verbindungsverlust arbeitet EVE weiter. Fertige
Antworten warten dauerhaft auf die Wiederverbindung. Der Bot fragt alle drei
Sekunden nach Ergebnissen. Vorübergehende Fehler vor dem Versand werden mit
15 Sekunden Abstand erneut versucht. Eine noch nicht zum Versand gestartete
Reservierung läuft nach 60 Sekunden ab und kann sicher neu übernommen werden.
Fehlende Rechte oder nicht mehr freigegebene Ziele führen zu `blocked`.
Nach Korrektur lässt sich ausschließlich diese Zustellung über den geschützten
Bridge-Endpunkt `POST /api/chatto/job-retry` mit `{"id":"chatto-job:…"}` erneut
freigeben. Das führt den Auftrag nicht erneut aus.

Unmittelbar vor der ersten Antwortnachricht wird `sending` dauerhaft gespeichert.
Geht danach die Verbindung oder Bestätigung verloren, wird die Antwort nicht
automatisch wiederholt; ihr Zustand bleibt `sending` oder wird `uncertain`.
Das gilt auch für teilweise versandte, aufgeteilte Antworten. Chattos
Nachrichten-API bietet dafür keinen Idempotenzschlüssel. Ein unklarer Versand
muss deshalb geprüft werden, um doppelte Antworten zu vermeiden.

Bei einem vollständigen EVE-Neustart bleiben fertige Antworten erhalten und noch
nicht begonnene Aufträge werden wieder aufgenommen. Zuvor laufende Aufträge
werden nicht erneut ausgeführt; EVE stellt stattdessen einen Hinweis auf die
Unterbrechung zu. Bereits erfolgte Werkzeugaktionen müssen dann geprüft werden.
`POST /api/chatto/jobs` zeigt die offenen Auftrags- und Zustellstände ohne
Nachrichteninhalte; alle genannten Bridge-Endpunkte benötigen den eigenen
Bridge-Schlüssel. Bot-Aktivität wird unabhängig von der Annahme-Anfrage
aktualisiert. Die oben beschriebene Präsenzlogik bleibt bestehen. Zur Aktivierung
dieser Änderung EVE einschließlich Bot einmal neu starten.

Der Bot sendet beim Start keine Begrüßung oder Testnachricht. Nach einem
unklaren Fehler wird dieselbe Nachricht nicht automatisch erneut ausgeführt,
da eine Werkzeugaktion oder Antwort bereits erfolgt sein könnte. Eine neue
Nachricht startet einen neuen Turn. Bildanhänge werden über Chattos autorisierte
Asset-API gelesen und an EVEs vorhandene native Bildeingabe übergeben, auch bei
bildreinen DMs. Unterstützt werden bis zu vier Bilder mit je höchstens 5 MB;
Chatto liefert eine Variante mit maximal 2048 Pixeln Kantenlänge. MIME-Typ,
Base64 und Bildsignatur werden vor dem Modellaufruf geprüft. Diese Übertragung
erteilt keine lokalen Dateirechte. Audio und sonstige Dateiinhalte werden
weiterhin nicht verarbeitet.
Bild- und Dateiressourcen der Antwort werden umgekehrt als echte Chatto-Anhänge
in genau denselben Raum und Thread hochgeladen und mit dem Antworttext versendet.
Das umfasst lokale Dateien (auch PDFs, ZIPs und CAD-Dateien) über `local_files.open_resource`,
MCP-Exporte über `eve_attach_file` und erzeugte Downloads, etwa Python- oder
YAML-Dateien. Dateien behalten ihren Dateinamen; doppelt als Ressource und Download
bereitgestellte Dateien werden nur einmal angehängt. Es gelten höchstens acht
Anhänge, davon maximal vier Bilder. Dateien sind auf je 20 MiB, Bilder auf je
5 MiB begrenzt; zusätzlich gelten die Upload-Rechte und Grenzen des Chatto-Servers.
Die PDF-Abrufgrenze von 50 MiB für die Webrecherche ist davon unabhängig.
Nur inline bereitgestellte Bytes werden übertragen. Lokale Dateien müssen zuerst
über das freigegebene Dateiwerkzeug geöffnet werden; lokale Pfade und beliebige
URLs werden vom Bot nicht gelesen. Provider-interne Pfade bleiben lokal.
In einer persönlichen DM dürfen weiterhin die persönlichen EVE-Werkzeuge
genutzt werden, einschließlich Home Assistant. Die Channel-Sperren gelten nur
für die freigegebenen Channels.
Vor der dauerhaften Annahme durch EVE können bei Unterbrechungen Nachrichten
fehlen; Chattos Echtzeit-Empfang ist keine dauerhafte Eingangswarteschlange.
Erkannte Lücken werden im Status gemeldet.

Prüfung ohne Modellaufrufe (HTTP-Tests verwenden einen lokalen Testserver):

```bash
PYTHONPATH=src:tests .venv/bin/python -m unittest test_bot_activity test_chatto test_chatto_jobs test_native_runtime test_llm test_config test_assist_api test_scheduler
node --test tests/js/chatto-*.test.mjs
```

## Konfigurierbare MCP-Werkzeuge und Auftrags-Threads

Externe MCP-Server, etwa SolidCraft, werden zentral in EVE konfiguriert.
Die [MCP-Anleitung](MCP.md) beschreibt Einrichtung, getrennte Sitzungen,
Dateianhänge und Channel-Freigaben. Der allgemeine Antwortmodus kann `chat` bleiben. Mit `thread` unter der
jeweiligen Integration erhält nur deren Verwendung einen eigenen Thread und
EVE-Verlauf. Die Bot-Aktivität folgt dabei dem tatsächlichen Thread-Ziel. Eine stabile `EVE-<UUID>`-Referenz
verbindet den Thread technisch mit den Herkunftsdaten für das Memory-Lernen.
Die Bedeutung und fachlichen Beziehungen bestimmt weiterhin das Modell.

## Geplante Aufgaben und Ausgabeziele

Geplante Aufgaben besitzen ein strukturiertes `output_target` unabhängig vom
Herkunftsgespräch und dem gespeicherten `execution_context`. `scheduled_tasks`
veröffentlicht `list_output_targets`; `create` und `update` akzeptieren
`output_target_id`. Ohne Auswahl gilt `current`: das aktuelle EVE-Gespräch oder
der verifizierte Chatto-Raum einschließlich Thread. Verfügbare Ziele werden aus
lokalen Gesprächen, den vom Bot entdeckten freigegebenen Channels und bekannten
Chatto-Gesprächen/Threads gebildet. Raumbezeichnungen werden nicht in Python aus
dem Auftrag herausinterpretiert. Die Entscheidung trifft das Modell anhand der
veröffentlichten Ressourcen und ihrer Referenzen.

Bei Fälligkeit erhält das Modell ausdrücklich einen geplanten Ausführungsturn:
Aufgaben-ID, Lauf-ID, Fälligkeit, Herkunft und Ausgabeziel stehen unter
`scheduled_execution`. Bei Erinnerungen ist die Antwort die jetzt zuzustellende
Erinnerung, keine erneute Bestätigung ihrer Einrichtung. Die Herkunft bleibt auch
im Verlauf und nach einem Kontextwechsel erhalten; der automatische Auftrag wird
nicht als neue menschliche Chatto-Nachricht ausgegeben. Die Werkzeugrechte werden
weiterhin ausschließlich aus dem geprüften Herkunftskontext wiederhergestellt.

`schedule.ends_at` setzt optional ein Enddatum mit Uhrzeit (ISO 8601; bevorzugt mit
UTC-Offset). Im Webfrontend steht das Feld unter „Geplante Aufgabe → Ändern“.
Leer beziehungsweise `null` entfernt die Begrenzung. Termine genau am Endzeitpunkt
sind eingeschlossen; danach beginnt keine weitere Ausführung. Nach einer
Unterbrechung werden abgelaufene Aufgaben ohne Nachholen abgeschlossen. Eine schon
laufende Ausführung wird durch das Enddatum nicht abgebrochen. Bestehende Aufgaben
ohne `ends_at` bleiben unbegrenzt. Beim Erstellen oder Ändern muss mindestens der
nächste Termin vor oder auf dem Endzeitpunkt liegen. Ein Tagesende lässt sich mit
23:59 Uhr am gewünschten letzten Tag setzen.

Der lokale Benutzer und Owner-DMs können andere verfügbare Ziele wählen.
Öffentliche Channels und Member-DMs können neben dem aktuellen Gespräch die
persönliche DM des verifizierten Absenders wählen (`chatto:dm:self`). Andere
DMs und lokale Gespräche werden dort nicht als Ziele veröffentlicht. Für eine
DM-Erinnerung wie „EVE, erinnere mich um 16:00 Uhr per DM an den Termin“ wählt
das Modell dieses Ziel und speichert die gewünschte Uhrzeit im Zeitplan.
Im Channel muss dafür `scheduled_tasks` unter `chatto.channel_capabilities`
freigegeben sein. Für den Owner muss `owner_dm_enabled`, für andere Benutzer
`member_dm_enabled` aktiv sein. Die bestehende Standardfreigabe für Member-DMs
enthält keine Aufgabenverwaltung; die Channel-Freigabe gilt nur im Channel.

Chatto verbietet Bots das Eröffnen einer DM, auch über `StartDM`. Jeder Empfänger
muss deshalb einmal selbst eine Zweier-DM mit EVE in Chatto eröffnen. Eine
vorherige Unterhaltung oder ein gespeicherter EVE-Verlauf dort ist nicht nötig.
Beim Versand sucht EVE diese DM über das authentifizierte Raumverzeichnis,
einschließlich weiterer Ergebnisseiten, und prüft die beiden Teilnehmer sowie
die aktuellen Rechte erneut. Gruppen-DMs werden nicht verwendet. Fehlt die DM
oder wurde ihre Freigabe widerrufen, wird die Zustellung blockiert; sie wird
nicht ersatzweise im Channel veröffentlicht. Nach Eröffnen der DM kann die
blockierte Ausgabe über `retry_delivery` erneut freigegeben werden.
Channel-Thread und Ursprungsnachricht werden nicht als DM-Ziel übernommen.
Die automatische Erinnerung wird als neue Nachricht in der persönlichen DM
zugestellt, auch bei geschlossenem Browser. EVE und der Chatto-Bot müssen laufen;
fertige Ausgaben überstehen Neustarts in der vorhandenen Warteschlange.

Aufgaben mit persönlichem DM-Ziel können im Ursprungschannel nur vom jeweiligen
Empfänger gelesen oder geändert werden; die Verwaltung über die lokale EVE
beziehungsweise die Owner-DM bleibt möglich. Channel-Verläufe bleiben gemeinsam
sichtbar, einschließlich des ursprünglichen Erinnerungsauftrags. Bei geplanten
Chatto-Turns werden die aktuellen Capability-Freigaben des Herkunftskontexts
wiederhergestellt; ein Ausgabeziel verleiht keine zusätzlichen Werkzeugrechte.

Chatto-Ergebnisse einschließlich Anhängen landen nach Ausführung in einer
persistenten Zustellwarteschlange (`scheduled_deliveries`). Der Bot holt sie
über die ausschließlich mit dem Bridge-Token zugänglichen Endpunkte ab und
prüft vor Versand die aktuelle Konfiguration, Bot-Eigentümerschaft,
Raummitgliedschaft, Lese-/Schreibrechte und gegebenenfalls den Zielthread.
Ein offener Browser ist dafür nicht erforderlich. Der Auftrag bestimmt weiterhin,
welche Ergebnisse und Änderungen EVE melden soll; die Zustellung vergleicht keine
Nachrichtentexte und baut keine eigene inhaltliche Benachrichtigungslogik ein.

Die Ausführung geplanter Aufgaben hält keine Sperre auf der Zustellwarteschlange.
Abholungen, lokale Benachrichtigungsabfragen und Aufgabenänderungen bleiben während
eines laufenden Modellaufrufs verfügbar. Im Dienstbetrieb führt ausschließlich
der Hintergrundmonitor fällige Aufgaben aus; Browser-Polling liest fertige
Ergebnisse. Startseite und statische Dateien belegen keine API-Anfrageplätze.

`list_deliveries(task_id)` zeigt Zustellstatus und Fehler. Mit
`retry_delivery(task_id, delivery_id)` lässt sich eine vor dem Versand blockierte
Zustellung erneut anstoßen, ohne den Task erneut auszuführen. Eine Abholung
reserviert zunächst nur die Ausgabe (`claimed`). Bricht der Bot vor dem
gespeicherten Versandbeginn ab, wird die Reservierung nach spätestens fünf
Minuten oder beim EVE-Neustart freigegeben. Vorübergehende Fehler bei der
Zielprüfung führen mit Wartezeit zu einem erneuten Zustellversuch.
Nach einem möglicherweise begonnenen Versand lautet der Status bei Abbruch
oder ausbleibender Bestätigung `uncertain`. Diese Ausgabe wird zur Vermeidung
doppelter Nachrichten nicht automatisch wiederholt. Alte, verwaiste
`sending`-Einträge werden beim Neustart ebenfalls als `uncertain` übernommen.
Der Bot wiederholt verlorene Zustellbestätigungen getrennt vom Versand.
`notification.delivered` ist erst nach bestätigter Chatto-Zustellung wahr;
ein erfolgreicher Aufgabenlauf allein bestätigt noch keinen Empfang.
Bereits bestehende Aufgaben ohne Ausgabeziel behalten ihre lokale Zustellung;
ein Ziel lässt sich nachträglich setzen. Ein Neustart von EVE samt Bot lädt die
Erweiterung. Für die Tests ist kein Versand an einen echten Chatto-Server nötig.

## Änderungen und Abnahme der Bot-Aktivität

- `src/eve_agent/bot_activity.py`: Inhaltsfreie Ereignisse und Aggregation laufender Werkzeuge.
- `src/eve_agent/llm.py`, `minimal.py`, `transport_access.py`: Modellbeginn, Content-Deltas und garantierte Werkzeugenden.
- `src/eve_agent/chatto.py`, `chatto_jobs.py`, `cli.py`: Aktuelle Kategorien in der Bridge, vollständige Sicht auf aktive Aufträge, geplante Ausgabeziele und interne Modellstreams.
- `scripts/chatto-activity.mjs`, `chatto-bot.mjs`, `chatto-state.mjs`, `chatto-output.mjs`: Reporter, Laufzeit-Anbindung und Leserechteprüfung.
- `scripts/chatto-delivery.mjs`: Entfernen der bisherigen Fortschrittsnachrichten; `chatto-progress.mjs` entfällt.
- `src/eve_agent/config.py`: Alten Statusnachrichten-Schalter aus der Oberfläche entfernen; gespeicherte Konfiguration bleibt lesbar.
- `tests/test_bot_activity.py`, `test_chatto_jobs.py`, `tests/js/chatto-activity.test.mjs`, `chatto-scheduled.test.mjs`, `chatto-delivery.test.mjs`: Laufzeit-, Parallelitäts-, Fehler-, Timeout-, Abbruch-, Berechtigungs-, Wiederverbindungs- und lokale HTTP-Vertragstests. Der frühere Test für Statusnachrichten entfällt. `tests/test_runtime.py` und `tests/test_scheduled_delivery.py` ergänzen die Testfixtures um Warteschlangendatenbank und Modellstream.
- `scripts/prepare_release.py`, `tests/test_prepare_release.py` im Repository-Hauptordner: Neues Modul im Quellcodeexport und gelöschte Altdateien korrekt behandeln.
- `docs/CHATTO.md`: Einrichtung, Ereigniszuordnung und Grenzen.

Der lokale HTTP-Testserver prüft URL, Header, JSON-Felder, fehlendes Thread-Feld
bei Raumantworten und Weiterarbeit nach HTTP 403. Die Zustandsprüfungen decken
zwei parallele Threads, überlappende Web-/andere Werkzeuge, alte Auftragsenden,
verspätete Requests, dynamische Thread-Ziele, Neustart und unabhängiges `IDLE` ab.

Ausgeführte Prüfungen (31.10.2026):

- Vollständige Python-Suite: `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` — 1.254 Tests, erfolgreich, drei bestehende bedingte Übersprünge.
- Vollständige JavaScript-Suite: `node --test tests/js/*.test.*` — 100 Tests erfolgreich; der Reporter-Test wurde nach der letzten Timer-Bereinigung zusätzlich erneut geprüft (neun Tests erfolgreich).
- Release-Export: im Repository-Hauptordner `python3 -m unittest discover -s tests` — beide Tests erfolgreich.
- Typprüfung: `mypy --follow-imports=silent --strict src/eve_agent/bot_activity.py` — erfolgreich. Es besteht keine konfigurierte projektweite Typprüfung.
- Ruff: Neues Aktivitätsmodul und dessen Tests ohne Befund. Die übrigen betroffenen Python-Dateien bestehen die Prüfung mit `--isolated --select E4,E7,E9,F`, mit Ausnahme der unveränderten Altbefunde in `cli.py` (14), `llm.py` (9) und `minimal.py` (1). Ein Vergleich gegen den vorherigen Git-Stand bestätigt: keine neuen Befunde in diesen Dateien.
- `node --check` für die acht betroffenen JavaScript-Module/Tests und `git diff --check` — erfolgreich.

Ruff und Mypy wurden nur temporär unter `/tmp` installiert; die Abhängigkeiten
der EVE-Laufzeit wurden nicht verändert. Die Socket-Tests liefen mit lokalen
Loopback-Servern. Für diese Prüfungen wurde keine produktive EVE neu gestartet.

Noch ausstehend ist die Sichtprüfung gegen einen dafür vorgesehenen echten
Chatto-Testserver mit dem genannten Build: zweites leseberechtigtes Konto prüft
Gespräch, Avatar und Profil in zwei Threads; ein Konto ohne Raum-/Thread-Leserecht
darf die Aktivität nicht sehen. Auch der reale Ablauf nach hartem Prozessabbruch
ist dort zu prüfen. Ein lokaler HTTP-Vertragstest ersetzt diese Server-/UI-Abnahme
nicht. Auf dem Produktivserver wurden keine Testkonten oder Testnachrichten angelegt.
