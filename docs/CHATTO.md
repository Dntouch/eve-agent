# EVE in Chatto

Diese Anleitung beschreibt EVEs Bot-Anbindung. Ein Chatto-Server muss bereits
bereitstehen; dessen Adresse und ein eigener Bot werden in EVE konfiguriert.

EVE verbindet sich ausgehend per HTTPS/WebSocket mit Chatto 0.5.0-beta.19.
Der offizielle Client wird am Commit `cda6bf54bb5282752169adb376f03081c09f0d89`
gebaut. EVE bleibt eine Instanz mit gemeinsamem Gedächtnis. Die Nachrichten
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
Raum besitzen. Direkte Antworten benötigen `message.post`. Menschen eröffnen DMs.

**Online-Status anzeigen** meldet den verbundenen Bot als online und erneuert
die Präsenz alle 30 Sekunden, auch während eines längeren Modellaufrufs. Beim
normalen Stoppen wird offline gemeldet. Bei Verbindungsverlust stoppt der
Heartbeat; Chatto lässt die Präsenz nach etwa 60 Sekunden verfallen. Der Status
beschreibt die Bot-Verbindung und ist keine Garantie für die Modellverfügbarkeit.
Chatto zeigt bei Bots den grünen Online-Punkt und blendet den Punkt offline aus;
der Bot bleibt in der eigenen Mitgliedergruppe Bots.

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
Bildressourcen der Antwort werden umgekehrt als echte Chatto-Anhänge in genau
denselben Raum hochgeladen und zusammen mit dem Antworttext versendet. Nur
inline bereitgestellte Bildbytes werden übertragen; lokale Pfade und beliebige
Bild-URLs werden dafür nicht gelesen. Provider-interne Pfade bleiben lokal.
In einer persönlichen DM dürfen weiterhin die persönlichen EVE-Werkzeuge
genutzt werden, einschließlich Home Assistant. Die Channel-Sperren gelten nur
für die freigegebenen Channels.
Bei Unterbrechungen können Nachrichten fehlen; Echtzeit ist keine dauerhafte
Warteschlange. Erkannte Lücken werden im Status gemeldet.

Prüfung ohne Modellaufrufe (HTTP-Tests verwenden einen lokalen Testserver):

```bash
PYTHONPATH=src:tests .venv/bin/python -m unittest test_chatto test_native_runtime test_config test_assist_api
node --test tests/js/chatto-bot.test.mjs tests/js/chatto-routing.test.mjs tests/js/chatto-images.test.mjs tests/js/chatto-output.test.mjs
```

## Konfigurierbare MCP-Werkzeuge und Auftrags-Threads

Externe MCP-Server, etwa SolidCraft, werden zentral in EVE konfiguriert.
Die [MCP-Anleitung](MCP.md) beschreibt Einrichtung, getrennte Sitzungen,
Dateianhänge und Channel-Freigaben. Der allgemeine Antwortmodus kann `chat` bleiben. Mit `thread` unter der
jeweiligen Integration erhält nur deren Verwendung einen eigenen Thread und
EVE-Verlauf. Der sichtbare Arbeitsstatus in Threads lässt sich im Chatto-Abschnitt
aktivieren. Eine stabile `EVE-<UUID>`-Referenz
verbindet den Thread technisch mit den Herkunftsdaten für das Memory-Lernen.
Die Bedeutung und fachlichen Beziehungen bestimmt weiterhin das Modell.
