(() => {
  "use strict";

  const futureVisual = false;

  const $ = (selector) => document.querySelector(selector);
  const elements = {
    canvas: $("#neural"),
    mark: $("#mark"),
    avatarCloudCanvas: $("#eveAvatarCloud"),
    coreScene: $(".core-scene"),
    spectrum: $("#spectrum"),
    label: $("#label"),
    connection: $("#connection"),
    clock: $("#clock"),
    detail: $("#detail"),
    reply: $("#reply"),
    downloads: $("#downloads"),
    sources: $("#sources"),
    ptt: $("#ptt"),
    pttText: $("#pttText"),
    voiceMute: $("#voiceMute"),
    shareToggle: $("#shareToggle"),
    composer: $("#composer"),
    chatWorkspace: $(".chat-workspace"),
    composerScrim: $("#composerScrim"),
    messageText: $("#messageText"),
    composerActivity: $("#composerActivity"),
    composerActivityText: $("#composerActivityText"),
    turnCancel: $("#turnCancel"),
    composerVoiceSlot: $("#composerVoiceSlot"),
    messageQueue: $("#messageQueue"),
    dropzone: $("#dropzone"),
    imageInput: $("#imageInput"),
    previews: $("#previews"),
    sendMessage: $("#sendMessage"),
    conversationToggle: $("#conversationToggle"),
    conversationPanel: $("#conversationPanel"),
    conversationScrim: $("#conversationScrim"),
    conversationList: $("#conversationList"),
    conversationListEmpty: $("#conversationListEmpty"),
    panelTitle: $("#panelTitle"),
    scheduleViewToggle: $("#scheduleViewToggle"),
    taskViewToggle: $("#taskViewToggle"),
    scheduledTaskView: $("#scheduledTaskView"),
    taskList: $("#taskList"),
    taskListEmpty: $("#taskListEmpty"),
    scheduledTaskList: $("#scheduledTaskList"),
    scheduledTaskListEmpty: $("#scheduledTaskListEmpty"),
    workLists: $("#workLists"),
    workTaskError: $("#workTaskError"),
    newWorkList: $("#newWorkList"),
    newWorkListForm: $("#newWorkListForm"),
    newWorkListName: $("#newWorkListName"),
    newWorkListDescription: $("#newWorkListDescription"),
    taskEditor: $("#taskEditor"),
    taskEditorForm: $("#taskEditorForm"),
    taskEditorClose: $("#taskEditorClose"),
    taskEditorCancel: $("#taskEditorCancel"),
    taskEditorError: $("#taskEditorError"),
    taskMessage: $("#taskMessage"),
    taskScheduleType: $("#taskScheduleType"),
    taskOnceRow: $("#taskOnceRow"),
    taskOnceAt: $("#taskOnceAt"),
    taskTimeRow: $("#taskTimeRow"),
    taskTime: $("#taskTime"),
    taskWeekdays: $("#taskWeekdays"),
    taskIntervalRow: $("#taskIntervalRow"),
    taskIntervalValue: $("#taskIntervalValue"),
    taskIntervalUnit: $("#taskIntervalUnit"),
    taskActive: $("#taskActive"),
    newConversation: $("#newConversation"),
    renameConversation: $("#renameConversation"),
    deleteConversation: $("#deleteConversation"),
    exportConversation: $("#exportConversation"),
    chatExportStatus: $("#chatExportStatus"),
    conversationTitle: $("#conversationTitle"),
    chatActions: $(".chat-actions"),
    chatMessages: $("#chatMessages"),
    chatEmpty: $("#chatEmpty"),
    workspaceResize: $("#workspaceResize"),
    panelResize: $("#panelResize"),
    systemMenuToggle: $("#systemMenuToggle"),
    systemMenu: $("#systemMenu"),
    openConfig: $("#openConfig"),
    openBrainwatch: $("#openBrainwatch"),
    configView: $("#configView"),
    configClose: $("#configClose"),
    configForm: $("#configForm"),
    configSections: $("#configSections"),
    configStatus: $("#configStatus"),
    configSave: $("#configSave"),
    configResize: $("#configResize"),
    configHelpPopover: $("#configHelpPopover"),
    configHelpClose: $("#configHelpClose"),
    configHelpTitle: $("#configHelpTitle"),
    configHelpContent: $("#configHelpContent"),
    avatarModeToggle: $("#avatarModeToggle"),
    avatarModeState: $("#avatarModeState"),
    nerdModeToggle: $("#nerdModeToggle"),
    nerdModeState: $("#nerdModeState"),
    presentationMotionToggle: $("#presentationMotionToggle"),
    presentationMotionState: $("#presentationMotionState"),
    commandDock: $("#commandDock"),
    nerdView: $("#nerdView"),
    nerdTurns: $("#nerdTurns"),
    brainwatchView: $("#brainwatchView"),
    brainwatchStage: $("#brainwatchStage"),
    brainwatchClose: $("#brainwatchClose"),
    brainwatchSearchForm: $("#brainwatchSearchForm"),
    brainwatchSearchCollapse: $("#brainwatchSearchCollapse"),
    brainwatchSearch: $("#brainwatchSearch"),
    brainwatchStatus: $("#brainwatchStatus"),
    brainwatchResults: $("#brainwatchResults"),
    brainwatchCanvas: $("#brainwatchCanvas"),
    brainwatchEmpty: $("#brainwatchEmpty"),
    brainwatchInspector: $("#brainwatchInspector"),
    brainwatchInspectorShell: $("#brainwatchInspectorShell"),
    brainwatchInspectorCollapse: $("#brainwatchInspectorCollapse"),
    brainwatchNavigationResize: $("#brainwatchNavigationResize"),
    brainwatchInspectorResize: $("#brainwatchInspectorResize"),
    brainwatchGraphToolbar: $("#brainwatchGraphToolbar"),
    brainwatchZoomIn: $("#brainwatchZoomIn"),
    brainwatchZoomOut: $("#brainwatchZoomOut"),
    brainwatchCenter: $("#brainwatchCenter"),
    brainwatchContextView: $("#brainwatchContextView"),
    brainwatchFlowView: $("#brainwatchFlowView"),
    brainwatchOverviewView: $("#brainwatchOverviewView"),
    brainwatchToggleBranch: $("#brainwatchToggleBranch"),
    brainwatchReset: $("#brainwatchReset"),
    brainwatchPath: $("#brainwatchPath"),
    brainwatchLayoutReset: $("#brainwatchLayoutReset"),
    brainwatchGroups: $("#brainwatchGroups"),
    brainwatchMore: $("#brainwatchMore"),
    brainwatchInfoMode: $("#brainwatchInfoMode"),
    brainwatchMemoryMode: $("#brainwatchMemoryMode"),
    brainwatchSemanticMode: $("#brainwatchSemanticMode"),
    brainwatchEventsMode: $("#brainwatchEventsMode"),
    brainwatchEventsNavigation: $("#brainwatchEventsNavigation"),
    brainwatchEventsWorkspace: $("#brainwatchEventsWorkspace"),
    brainwatchEventsContent: $("#brainwatchEventsContent"),
    brainwatchEventsStatus: $("#brainwatchEventsStatus"),
    brainwatchEventsRefresh: $("#brainwatchEventsRefresh"),
    brainwatchEventsMore: $("#brainwatchEventsMore"),
    brainwatchStatisticsMode: $("#brainwatchStatisticsMode"),
    brainwatchInfoNavigation: $("#brainwatchInfoNavigation"),
    memoryExplorerNavigation: $("#memoryExplorerNavigation"),
    memoryExplorerForm: $("#memoryExplorerForm"),
    memoryExplorerSearch: $("#memoryExplorerSearch"),
    memoryExplorerScope: $("#memoryExplorerScope"),
    memoryExplorerKind: $("#memoryExplorerKind"),
    memoryExplorerLifecycle: $("#memoryExplorerLifecycle"),
    memoryExplorerStatus: $("#memoryExplorerStatus"),
    memoryExplorerResults: $("#memoryExplorerResults"),
    memoryExplorerMore: $("#memoryExplorerMore"),
    memoryCloudView: $("#memoryCloudView"),
    memoryTimelineView: $("#memoryTimelineView"),
    memoryCloudWorkspace: $("#memoryCloudWorkspace"),
    memoryCloudCanvas: $("#memoryCloudCanvas"),
    memoryCloudWorking: $("#memoryCloudWorking"),
    memoryCloudWorkingFocus: $("#memoryCloudWorkingFocus"),
    memoryCloudWorkingStatus: $("#memoryCloudWorkingStatus"),
    memoryCloudReset: $("#memoryCloudReset"),
    memoryCloudVR: $("#memoryCloudVR"),
    memoryCloudAR: $("#memoryCloudAR"),
    memoryCloudXREnd: $("#memoryCloudXREnd"),
    memoryCloudXRStatus: $("#memoryCloudXRStatus"),
    memoryCloudFocus: $("#memoryCloudFocus"),
    memoryCloudOverview: $("#memoryCloudOverview"),
    memoryCloudRelationType: $("#memoryCloudRelationType"),
    memoryCloudIntensity: $("#memoryCloudIntensity"),
    memoryCloudQuality: $("#memoryCloudQuality"),
    memoryCloudLearningFocus: $("#memoryCloudLearningFocus"),
    memoryCloudLearningTitle: $("#memoryCloudLearningTitle"),
    memoryCloudLearningDetail: $("#memoryCloudLearningDetail"),
    memoryCloudLearningClear: $("#memoryCloudLearningClear"),
    memoryCloudStatus: $("#memoryCloudStatus"),
    memoryCloudTooltip: $("#memoryCloudTooltip"),
    memoryCloudFallback: $("#memoryCloudFallback"),
    memoryCloudMore: $("#memoryCloudMore"),
    memoryCloudTurn: $("#memoryCloudTurn"),
    memoryCloudActivityLoad: $("#memoryCloudActivityLoad"),
    memoryCloudActivityCategory: $("#memoryCloudActivityCategory"),
    memoryCloudActivityPrevious: $("#memoryCloudActivityPrevious"),
    memoryCloudActivityPlay: $("#memoryCloudActivityPlay"),
    memoryCloudActivityNext: $("#memoryCloudActivityNext"),
    memoryCloudActivityClear: $("#memoryCloudActivityClear"),
    memoryCloudActivitySpeed: $("#memoryCloudActivitySpeed"),
    memoryCloudLive: $("#memoryCloudLive"),
    memoryCloudActivityPosition: $("#memoryCloudActivityPosition"),
    memoryTimelineForm: $("#memoryTimelineForm"),
    memoryTimelineSource: $("#memoryTimelineSource"),
    memoryTimelineCategory: $("#memoryTimelineCategory"),
    memoryTimelineProof: $("#memoryTimelineProof"),
    memoryTimelineKind: $("#memoryTimelineKind"),
    memoryTimelineFidelity: $("#memoryTimelineFidelity"),
    memoryTimelineFrom: $("#memoryTimelineFrom"),
    memoryTimelineTo: $("#memoryTimelineTo"),
    memoryTimelineClaim: $("#memoryTimelineClaim"),
    memoryTimelineTurn: $("#memoryTimelineTurn"),
    memoryTimelineScope: $("#memoryTimelineScope"),
    memoryTimelineConsumer: $("#memoryTimelineConsumer"),
    memoryTimelineStage: $("#memoryTimelineStage"),
    memoryTimelineTrace: $("#memoryTimelineTrace"),
    memoryTimelinePlannerRound: $("#memoryTimelinePlannerRound"),
    memoryTimelineLlmCall: $("#memoryTimelineLlmCall"),
    memoryTimelineAttempt: $("#memoryTimelineAttempt"),
    memoryTimelineOperation: $("#memoryTimelineOperation"),
    memoryTimelinePlan: $("#memoryTimelinePlan"),
    memoryTimelineAction: $("#memoryTimelineAction"),
    memoryTimelineStatus: $("#memoryTimelineStatus"),
    memoryTimelineWorkspace: $("#memoryTimelineWorkspace"),
    memoryTimelineList: $("#memoryTimelineList"),
    memoryTimelineMore: $("#memoryTimelineMore"),
    memoryTimelineFirst: $("#memoryTimelineFirst"),
    memoryTimelinePrevious: $("#memoryTimelinePrevious"),
    memoryTimelinePlay: $("#memoryTimelinePlay"),
    memoryTimelineNext: $("#memoryTimelineNext"),
    memoryTimelineSpeed: $("#memoryTimelineSpeed"),
    memoryTimelinePosition: $("#memoryTimelinePosition"),
    semanticNavigation: $("#semanticNavigation"),
    semanticWorkspace: $("#semanticWorkspace"),
    brainwatchStatisticsNavigation: $("#brainwatchStatisticsNavigation"),
    brainwatchStatisticsRefresh: $("#brainwatchStatisticsRefresh"),
    brainwatchStatisticsStatus: $("#brainwatchStatisticsStatus"),
    brainwatchStatisticsWorkspace: $("#brainwatchStatisticsWorkspace"),
    brainwatchStatisticsContent: $("#brainwatchStatisticsContent"),
    presentationView: $("#presentationView"),
    presentationTitle: $("#presentationTitle"),
    presentationComponents: $("#presentationComponents"),
    presentationClose: $("#presentationClose"),
    imageViewer: $("#imageViewer"),
    imageViewerTitle: $("#imageViewerTitle"),
    imageViewerStage: $("#imageViewerStage"),
    imageViewerImage: $("#imageViewerImage"),
    imageViewerDownload: $("#imageViewerDownload"),
    imageViewerClose: $("#imageViewerClose"),
  };

  const STATE_LABELS = {
    idle: "STANDBY",
    listening: "LISTENING",
    thinking: "THINKING",
    speaking: "SPEAKING",
    error: "FAULT",
    offline: "OFFLINE",
    "memory:read": "RECALLING",
    "memory:write": "REMEMBERING",
    "tool:web": "RESEARCH",
    "tool:home": "HOME LINK",
    "tool:network": "NETWORK",
    "tool:shell": "SHELL",
    "tool:nova": "NOVA LINK",
  };
  const KNOWN_STATES = new Set(Object.keys(STATE_LABELS));
  const MAX_AUDIO_QUEUE = 8;
  const MAX_IMAGES = 4;
  const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
  const MAX_TOTAL_IMAGE_BYTES = 17 * 1024 * 1024;
  const SAFE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
  const auth = {};

  const CONFIG_HELP = {
    "assist_api.enabled": {"title": "Home-Assistant Assist-API", "text": ["Stellt die EVE-Schnittstellen für Conversation, Spracherkennung und Sprachausgabe bereit, damit Home Assistant EVE in einer Assist-Pipeline verwenden kann.", "Home Assistant benötigt die Adresse von EVE und den separaten Assist-Token. Diese Freigabe ist unabhängig von EVEs Verbindung zum Home-Assistant-Inventar."]},
    "assist_api.token": {"title": "Zugriffstoken für die Assist-API", "text": ["Mit diesem separaten Schlüssel authentifiziert sich Home Assistant an EVEs Assist-Schnittstelle. Er ist nicht das Home-Assistant Access Token, mit dem EVE auf Home Assistant zugreift.", "Denselben Schlüssel in der EVE-Anbindung von Home Assistant eintragen. Ein nicht leeres Feld ersetzt den gespeicherten Wert; leer lassen behält ihn bei."]},
    "wayland_computer.enabled": {"title": "Desktopzugriff über Wayland", "text": ["Stellt EVE die eigene Wayland-MCP-Fähigkeit für Desktopzugriffe bereit. Dafür gelten die regulären Freigaben der Desktop-Portale.", "Das Aktivieren ersetzt keine Bildschirm- oder Eingabefreigabe des Desktops. Ohne erforderliche Freigaben stehen entsprechende Funktionen nicht zur Verfügung."]},
    "conversation_learning.enabled": {"title": "Aus Gesprächen lernen", "text": ["Sammelt abgeschlossene Gesprächsschritte als Evidenz. In einer Leerlaufphase bewertet Qwen diese gemeinsam und wertet sie für das Memory aus.", "Das Lernen benötigt Modellaufrufe im Hintergrund. Leerlauf und Paketgröße bestimmen, wann und in welchem Umfang die Auswertung stattfindet."]},
    "conversation_learning.idle_delay_seconds": {"title": "Wartezeit vor dem Gesprächslernen", "text": ["Sekunden ohne neue Benutzeraktivität, bevor offene Gesprächsevidenz gebündelt ausgewertet wird. Neue Eingaben pausieren einen laufenden Lernvorgang.", "Eine längere Wartezeit hält kurze Gesprächspausen frei von Lernarbeit. Eine kürzere Wartezeit verarbeitet Evidenz früher."]},
    "conversation_learning.batch_size": {"title": "Größe eines Lernpakets", "text": ["Anzahl offener Gesprächsschritte, die Qwen in einem gemeinsamen Modellaufruf bewertet.", "Kleine Pakete lassen sich schneller pausieren. Große Pakete sparen Aufrufe, benötigen aber mehr Kontext und können länger dauern."]},
    "working_memory.cleanup_enabled": {"title": "Arbeitsstände automatisch bereinigen", "text": ["Entfernt abgelaufene, nicht angeheftete Arbeitsstände aus der Datenbank. Laufende Vorgänge und Werkzeugaufrufe mit unklarem Ausgang bleiben geschützt.", "Die folgenden Aufbewahrungszeiten bestimmen, wann abgeschlossene Arbeitsstände und temporäre Lernmaterialien bereinigt werden dürfen."]},
    "working_memory.completed_retention_hours": {"title": "Erfolgreiche Arbeitsstände aufbewahren", "text": ["Aufbewahrungszeit in Stunden nach der letzten Nutzung eines erfolgreich abgeschlossenen, nicht angehefteten Arbeitsstands.", "Längere Zeiten erleichtern spätere Wiederaufnahme und Nachschlagen. Kürzere Zeiten geben früher Speicher frei. Die Entfernung erfolgt bei einer Bereinigungsprüfung."]},
    "working_memory.failed_retention_hours": {"title": "Fehlgeschlagene Arbeitsstände aufbewahren", "text": ["Aufbewahrungszeit in Stunden für abgebrochene oder fehlgeschlagene Arbeitsstände, damit Diagnose und Wiederaufnahme möglich bleiben.", "Kürzere Zeiten verkleinern das Diagnosefenster. Angeheftete Arbeitsstände und Vorgänge mit unklarem Werkzeugausgang bleiben geschützt."]},
    "working_memory.temporary_learning_retention_hours": {"title": "Temporäre Lernmaterialien aufbewahren", "text": ["Aufbewahrungszeit in Stunden für große ausgelagerte Lernmaterialien nach einem erfolgreichen Lernlauf.", "Die Bereinigung betrifft die temporären Materialien. Bereits im Memory gespeicherte Lernergebnisse werden dadurch nicht gelöscht."]},
    "working_memory.cleanup_interval_minutes": {"title": "Abstand zwischen Bereinigungen", "text": ["Minuten zwischen automatischen Prüfungen auf abgelaufene Arbeitsstände. Zusätzlich prüft EVE beim Start.", "Das Intervall gilt bei aktivierter automatischer Bereinigung. Ein abgelaufener Eintrag wird bei einer Prüfung entfernt, nicht zwingend exakt mit Ablauf seiner Aufbewahrungszeit."]},
    "text_to_speech.language": {"title": "Sprache der Sprachausgabe", "text": ["Optionaler Sprachcode für den ausgewählten TTS-Dienst, beispielsweise de für Deutsch. Ein leeres Feld überlässt die Sprachwahl dem Dienst.", "Die Unterstützung hängt von der Engine ab. Die Einstellung ändert weder die Sprache der Spracherkennung noch ersetzt sie die Auswahl einer passenden Stimme."]},
    "nova_maintenance.transport": {"title": "Weg für Nova-Wartungsaufträge", "text": ["Wählt, ob Wartungsaufträge in einem sichtbaren Codex-Projektchat oder als isolierter Hintergrundauftrag bearbeitet werden.", "shared_chat benötigt eine erreichbare lokale Codex-Verbindung. Der Socket lässt sich im folgenden Feld festlegen."], "options": ["shared_chat: sichtbarer gemeinsamer Codex-Projektchat.", "isolated: separater Hintergrundauftrag über den konfigurierten Befehl."]},
    "nova_maintenance.shared_chat_socket": {"title": "Lokaler Codex-Socket", "text": ["Pfad zum lokalen Socket für die Verbindung zum gemeinsamen Codex-Chat. Leer verwendet den Codex-Standardsocket.", "Nur für den Auftragsweg shared_chat relevant. Hier gehört ein lokaler Socketpfad hinein, keine HTTP-Adresse und kein API-Schlüssel."]},
    "semantic_similarity.enabled": { title: "Gelernte Varianten im Memory", text: ["EVE verknüpft formal ähnliche, bestätigte Formulierungen als Beziehungen in der Memory-Datenbank.", "Der Turn greift ausschließlich über die normale Memory-Suche darauf zu. Python wählt daraus keine Aktion und führt keine Zuordnung direkt aus. Das Ausschalten löscht kein gelerntes Wissen." ] },
    "semantic_similarity.mode": { title: "Betriebsart der Ähnlichkeitserkennung", text: ["„active“ pflegt ausreichend belegte Beziehungen im Memory. „shadow“ berechnet und protokolliert Kandidaten nur zur Beobachtung.", "Qwen entscheidet in beiden Fällen selbst anhand der tatsächlich abgerufenen Memory-Inhalte, des Verlaufs und der nativen Funktionen."], options: ["active: bestätigte Beziehungen im Memory pflegen.", "shadow: Kandidaten nur messen und in Brainwatch sichtbar machen."] },
    "semantic_similarity.threshold": { title: "Ähnlichkeitsschwelle", text: ["Mindestwert der formalen, zeichenbasierten Ähnlichkeit zwischen neuer und bestätigter Formulierung. Das ist keine vom LLM geschätzte Bedeutungswahrscheinlichkeit.", "Ein höherer Wert ist strenger und vermeidet eher falsche Zuordnungen; ein niedrigerer Wert erkennt mehr Schreib- und Flexionsvarianten, erhöht aber das Verwechslungsrisiko. Die Änderung gilt sofort."], options: ["0,95: sehr streng; vor allem kleine Schreibvarianten.", "0,85: EVE-Standard und ausgewogener Ausgangspunkt.", "0,70: deutlich toleranter; nur mit geprüften Lernbeispielen verwenden."] },
    "semantic_composition.enabled": { title: "Differenzielle Beziehungen im Memory", text: ["EVE kann aus unabhängig bestätigten Memory-Belegen weitere Beziehungen innerhalb der Memory-Datenbank ableiten.", "Sie werden nicht von Python ausgeführt. Qwen entscheidet über die normale Memory-Suche und die nativen Funktionen. Das Ausschalten löscht keine Lernbelege."] },
    "semantic_composition.mode": { title: "Betriebsart der Komposition", text: ["„active“ pflegt ausreichend belegte Beziehungen im Memory. „shadow“ berechnet sie nur für Diagnose und Training.", "Bei Unsicherheit, Widersprüchen oder fehlender Evidenz entsteht auch in active keine Beziehung."], options: ["active: belegte Beziehungen im Memory pflegen.", "shadow: Komposition nur beobachten und auswerten."] },
    "home_assistant.enabled": { title: "Home Assistant aktivieren", text: ["Schaltet die Verbindung zwischen EVE und Home Assistant ein oder aus. Ist sie aus, stehen Geräte, Sensoren und Automationen aus Home Assistant nicht zur Verfügung.", "Aktiviere sie nur, wenn URL und Access Token korrekt eingerichtet sind. Standardmäßig ist die Verbindung deaktiviert."] },
    "home_assistant.url": { title: "Home-Assistant-URL", text: ["Die vollständige HTTP- oder HTTPS-Adresse deiner Home-Assistant-Instanz. EVE nutzt sie für Zustände, Dienste und weitere Home-Assistant-Funktionen.", "Eine lokale Adresse wie http://192.168.1.20:8123 ist üblich. Sie muss vom EVE-Rechner aus erreichbar sein; ein falscher Endpunkt führt zu Verbindungsfehlern und Timeouts."] },
    "home_assistant.language": { title: "Sprache des HA-Inventars", text: ["Der Sprachcode steuert, wie EVE Namen und Aliasformen der entdeckten Home-Assistant-Entitäten normalisiert und im Memory verknüpft. Er ändert weder die Home-Assistant-Oberfläche noch die STT-Sprache.", "Für deutsch benannte Räume und Geräte ist „de“ richtig. Nach einer Änderung EVE neu starten und die Entitäten erneut entdecken, damit das Inventar mit der neuen Sprache aktualisiert wird."] },
    "home_assistant.timeout_seconds": { title: "Home-Assistant-Timeout", text: ["Bestimmt, wie lange EVE auf eine Antwort von Home Assistant wartet, bevor der Vorgang als fehlgeschlagen gilt.", "Der Standardwert ist 12 Sekunden. Kürzere Werte melden Netzwerkprobleme schneller, können langsame Systeme aber vorschnell abbrechen; längere Werte wirken robuster, lassen Fehler jedoch später sichtbar werden."] },
    "home_assistant.token": { title: "Home-Assistant Access Token", text: ["Ein langlebiges Zugriffstoken, mit dem sich EVE gegenüber Home Assistant authentifiziert. Seine Rechte bestimmen, welche Zustände EVE lesen und welche Aktionen EVE ausführen darf.", "Behandle das Token wie ein Passwort. Ein neues, nicht leeres Token ersetzt das vorhandene; ein leeres Feld behält den bereits konfigurierten Wert bei."] },
    "llm.base_url": { title: "LLM-API-Endpunkt", text: ["Die Basisadresse der OpenAI-kompatiblen API, über die EVE das Sprachmodell anspricht. Typisch ist ein lokaler Server wie LM Studio, llama.cpp oder ein kompatibler Dienst.", "Standard ist http://127.0.0.1:1234/v1. Netzwerkentfernte Endpunkte erhöhen meist die Latenz und müssen vom EVE-Rechner erreichbar sein."] },
    "llm.model": { title: "LLM-Modell", text: ["Der Modellname, den EVE an den konfigurierten API-Endpunkt sendet. Er muss zu einem dort verfügbaren beziehungsweise geladenen Modell passen.", "Größere Modelle liefern oft bessere Antworten, benötigen aber mehr RAM oder VRAM und reagieren langsamer. Der Standard-Platzhalter ist „local-model“; viele Server erwarten stattdessen ihren konkreten Modellnamen."] },
    "llm.timeout_seconds": { title: "LLM-Timeout", text: ["Maximale Wartezeit eines einzelnen Modellaufrufs. Nach Ablauf bricht EVE diesen Aufruf ab und behandelt ihn als fehlgeschlagen.", "Standard sind 180 Sekunden. Für große lokale Modelle oder kalte Modellstarts kann ein höherer Wert nötig sein; ein niedriger Wert macht Ausfälle schneller sichtbar, kann aber laufende Antworten vorschnell abbrechen."] },
    "llm.use_server_limits": { title: "Modellgrenzen vom Server übernehmen", text: ["Ist die Option aktiv, sendet EVE kein künstliches Ausgabelimit und verwendet die tatsächlich geladene Kontextgröße des Modellservers.", "Das ist für LM Studio der empfohlene Modus. Änderungen am geladenen Modell oder seiner Kontextgröße erfordern dann keine parallele Grenze in EVE."] },
    "llm.max_tokens": { title: "Manuelles Ausgabe-Fallback", text: ["Dieses Limit wird nur gesendet, wenn „Modellgrenzen vom Server übernehmen“ deaktiviert ist. Tokens sind Textbausteine und nicht exakt mit Wörtern gleichzusetzen.", "Ein zu kleiner Wert kann Antworten oder Tool-Aufrufe abschneiden. Im empfohlenen Servermodus bleibt dieser Wert ohne Wirkung."] },
    "llm.api_key": { title: "LLM API-Key", text: ["Authentifiziert EVE am LLM-Endpunkt, sofern dieser einen Schlüssel verlangt. Rein lokale Server akzeptieren häufig einen beliebigen Wert oder benötigen gar keinen echten geheimen Schlüssel.", "Der Default ist „local“. Ein neues, nicht leeres Secret ersetzt den vorhandenen Wert; leer lassen bedeutet beibehalten."] },
    "speech_to_text.model": { title: "Faster-Whisper-Modell", text: ["EVE übergibt diesen Wert direkt an Faster Whisper. Möglich sind eine eingebaute Kurzbezeichnung, der Pfad zu einem lokal konvertierten Modell oder eine CTranslate2-kompatible Hugging-Face-Modell-ID. Ein Kurzname wird beim ersten Einsatz automatisch heruntergeladen, falls er noch nicht im lokalen Cache liegt.", "„small“ ist Eves mehrsprachiger Standard. Für Deutsch sind reguläre Varianten ohne „.en“ oder turbo sinnvoll. Die derzeit von Faster Whisper angebotenen Distil-Whisper-Kurznamen sind für englische Spracherkennung trainiert und passen daher nicht zur voreingestellten Sprache „de“. Größere Modelle benötigen deutlich mehr RAM beziehungsweise VRAM und verlängern den ersten Start."], options: ["tiny / base: sehr schnell und sparsam, geringere Erkennungsqualität.", "small: EVE-Standard; guter lokaler Kompromiss für Deutsch.", "medium: genauer, aber wesentlich größer und langsamer.", "large-v1 / large-v2 / large-v3 / large: höchste reguläre Whisper-Klasse; „large“ verweist auf large-v3.", "turbo / large-v3-turbo: beschleunigte große mehrsprachige Variante.", "Alle distil-*-Kurzmodelle und alle .en-Modelle: ausschließlich für Englisch verwenden."] },
    "speech_to_text.language": { title: "STT-Sprache", text: ["Gibt der Spracherkennung die erwartete Sprache vor. Das vermeidet eine zusätzliche Spracherkennung und kann kurze oder undeutliche Aufnahmen stabiler machen.", "Für deutsche Sprache ist „de“ sinnvoll und voreingestellt. Eine falsche Sprache verschlechtert die Erkennung deutlich."] },
    "speech_to_text.device": { title: "STT-Rechengerät", text: ["Dieser Wert wird direkt beim Laden des Faster-Whisper-Modells verwendet. „auto“ lässt CTranslate2 die verfügbare Hardware wählen, „cpu“ erzwingt den Prozessor und „cuda“ eine unterstützte NVIDIA-GPU.", "CUDA funktioniert nur mit passendem NVIDIA-Treiber und den von Faster Whisper benötigten CUDA-Bibliotheken. Eine nicht verfügbare Auswahl führt beim ersten Sprach-Turn zu einem klaren Ladefehler."], options: ["auto: verfügbare Hardware automatisch wählen.", "cpu: breite Kompatibilität, je nach Modell langsamer.", "cuda: NVIDIA-GPU ausdrücklich verwenden."] },
    "speech_to_text.compute_type": { title: "STT-Rechentyp", text: ["Dieser Wert wird direkt an CTranslate2 übergeben. „auto“ wählt den schnellsten auf Gerät und System unterstützten Typ; „default“ bevorzugt das Format, in dem das Modell gespeichert wurde. Nicht jede Kombination ist auf jeder CPU oder GPU verfügbar.", "Welche festen Typen tatsächlich unterstützt werden, hängt vom Prozessor beziehungsweise von GPU, Treibern und CTranslate2-Build ab. Eine inkompatible Auswahl kann beim Modellladen automatisch umgesetzt werden oder mit einem Fehler enden; „auto“ ist deshalb der portable Standard."], options: ["int8: geringer Speicherbedarf; oft eine gute CPU-Wahl.", "int8_float32: INT8-Gewichte mit Float32-Berechnungsteilen.", "int8_float16 / int8_bfloat16: vor allem für passende neuere GPUs.", "float16 / bfloat16: reduzierte Gleitkommapräzision für unterstützte GPUs.", "float32: hohe Kompatibilität, hoher Speicher- und Rechenbedarf.", "int16: hardwareabhängig und selten die beste allgemeine Wahl."] },
    "speech_to_text.initial_prompt": { title: "Initial Prompt", text: ["Ein kurzer Text, der der Spracherkennung Kontext, Schreibweise und erwartetes Vokabular vorgibt. Er wird nicht gesprochen, sondern dient als Startkontext für die Transkription.", "Nützlich sind Eigennamen oder eine knappe Domänenbeschreibung. Ein zu langer oder unpassender Prompt kann die Erkennung in die falsche Richtung lenken; leer ist ein guter Standard."] },
    "speech_to_text.hotwords": { title: "Hotwords", text: ["Begriffe, die bei der Spracherkennung besonders erwartet werden, etwa „EVE“, Produktnamen oder seltene Eigennamen. Sie helfen vor allem bei Wörtern, die das Modell sonst häufig verwechselt.", "Trage nur wenige wirklich relevante Begriffe ein. Zu viele oder unpassende Hotwords können Fehlinterpretationen fördern; standardmäßig bleibt das Feld leer."] },
    "text_to_speech.engine": { title: "Sprachausgabe-Engine", text: ["Wählt das System, das EVE-Text in Sprache umwandelt. Die Engines unterscheiden sich bei Qualität, Geschwindigkeit, Hardwarebedarf und Installation.", "Standard ist Piper: lokal, schnell und ressourcenschonend. „auto“ wählt eine verfügbare Engine. Qwen3-TTS und Chatterbox können natürlicher klingen, benötigen aber eigene Dienste und mehr Ressourcen; spd-say und espeak-ng sind robuste, eher technische Fallbacks."], options: ["piper: schneller lokaler Standard.", "auto: automatisch verfügbare Engine wählen.", "qwen3_tts / chatterbox: höhere mögliche Qualität, zusätzlicher Dienst und Ressourcenbedarf.", "spd-say / espeak-ng: einfache System-Sprachausgabe als Fallback."] },
    "text_to_speech.voice": { title: "Piper-Stimme", text: ["Der Name des Piper-Stimmenmodells, das für die Sprachausgabe geladen wird. Sprache, Sprecher und Qualitätsstufe sind Bestandteil des Modellnamens.", "Standard ist „de_DE-eve-medium“. Die Stimme muss im Stimmenverzeichnis vorhanden sein; größere Qualitätsvarianten können natürlicher klingen, benötigen aber mehr Speicher und Rechenzeit."] },
    "text_to_speech.data_dir": { title: "Stimmenverzeichnis", text: ["Der Ordner, in dem EVE lokale Sprachmodelle und zugehörige Piper-Dateien sucht. Relative Pfade werden vom EVE-Projektverzeichnis aus aufgelöst.", "Standard ist „voices“. Ein falscher oder nicht lesbarer Pfad verhindert das Laden lokaler Stimmen."] },
    "text_to_speech.piper_chunk_chars": { title: "Piper Chunk-Größe", text: ["Teilt längere Antworten vor der Sprachausgabe in Textabschnitte ungefähr dieser Zeichenzahl. So kann EVE früher mit dem Sprechen beginnen, statt auf die gesamte Ausgabe zu warten.", "Standard sind 700 Zeichen. Kleinere Chunks starten schneller, können aber mehr hörbare Übergänge erzeugen; größere klingen zusammenhängender, erhöhen jedoch die Wartezeit bis zum ersten Ton."] },
    "web.enabled": { title: "Webrecherche aktivieren", text: ["Schaltet die Webrecherche über den konfigurierten SearXNG-Dienst frei. Ist sie aus, kann EVE keine aktuellen Informationen über diesen Suchpfad beschaffen.", "Standardmäßig ist die Funktion deaktiviert. Aktiviere sie erst, wenn der Suchdienst erreichbar und passend abgesichert ist."] },
    "web.searxng_url": { title: "SearXNG-Endpunkt", text: ["Die vollständige Adresse der SearXNG-Instanz, die EVE für Suchanfragen verwendet.", "Standard ist http://127.0.0.1:8888. Ein lokaler Dienst ist meist schnell und datensparsam; ein entfernter Dienst bringt Netzwerkabhängigkeit und möglicherweise eigene Datenschutzregeln mit."] },
    "web.image_results": { title: "Bilder pro Suche", text: ["Begrenzt die Anzahl gültiger Bildressourcen, die der Web-Provider pro strukturierter Bildsuche an EVE weitergibt.", "Standard sind 4 Bilder, erlaubt sind 1 bis 8. Einzelne fehlerhafte oder nicht unterstützte Treffer werden übersprungen; große Werte erhöhen Downloadmenge und Speicherbedarf."] },
    "web.timeout_seconds": { title: "Web-Timeout", text: ["Maximale Wartezeit für einzelne Such- und Seitenabrufe, bevor EVE den Netzwerkzugriff abbricht.", "Standard sind 12 Sekunden. Kürzere Werte halten Anfragen flott, sind bei langsamen Seiten aber anfälliger; längere Werte erhöhen Robustheit und Wartezeit."] },
    "nova_maintenance.enabled": { title: "Nova-Wartung aktivieren", text: ["Schaltet Eves lokalen Wartungs- und Entwicklungsweg über Nova frei. Darüber können autorisierte Wartungsaufgaben mit dem konfigurierten Befehl gestartet werden.", "Die Funktion ist standardmäßig deaktiviert. Aktiviere sie nur in einer kontrollierten lokalen Umgebung, in der der ausgeführte Befehl und seine Berechtigungen bekannt sind."] },
    "nova_maintenance.command": { title: "Nova-Befehl", text: ["Der ausführbare Befehl, den Nova für Wartungsaufgaben startet. Er muss auf dem EVE-System installiert und über den Dienstkontext auffindbar sein.", "Standard ist „codex“. Ein falscher Befehl verhindert Wartungsaufgaben; zusätzliche Shell-Logik gehört nicht in dieses Feld."] },
    "nova_maintenance.timeout_seconds": { title: "Nova-Timeout", text: ["Begrenzt die Laufzeit einer Nova-Wartungsaufgabe. Nach Ablauf wird der Vorgang als Zeitüberschreitung behandelt.", "Der Standard ist 180 Sekunden; erlaubt sind 15 bis 900 Sekunden. Komplexe Aufgaben können mehr Zeit benötigen, während hohe Werte hängende Prozesse länger bestehen lassen."] },
    "shell.enabled": { title: "Shellzugriff", text: ["EVE führt echte Shellbefehle unter dem Linux-Benutzer ihres Prozesses aus. Es gelten dessen normale Dateirechte und Umgebung.", "Die Einstellung wirkt sofort auf neue Werkzeugaufrufe. Bereits gestartete Prozesse laufen weiter und werden beim EVE-Stop beendet."] },
    "shell.executable": { title: "Shellprogramm", text: ["Dieses Programm erhält den übergebenen Befehl mit -c. Standard ist /bin/bash.", "Eine Änderung gilt für neue Prozesse. Laufende Sitzungen behalten ihr Shellprogramm."] },
    "shell.forbidden_commands": { title: "Befehlssperrliste", text: ["Eine gesperrte Wortfolge pro Zeile, zum Beispiel rm -rf. Leere Liste erlaubt alle Befehle. Die Liste wirkt sofort für neue Befehle und übergebene Standardeingaben.", "Leerzeichen, Anführungszeichen und kurze Optionsgruppen werden normalisiert: rm -rf erfasst auch rm -fr, rm -r -f und rm -rfv. Geprüft wird der übergebene Text; Variablen, indirekte Skriptwirkungen und über mehrere Eingaben zusammengesetzte Befehle werden nicht aufgelöst."] },
    "local_files.roots": { title: "Freigegebene lokale Verzeichnisse", text: ["Das Werkzeug für lokalen Dateizugriff darf Dateien ausschließlich innerhalb dieser Verzeichnisse und ihrer Unterordner lesen. Shellbefehle verwenden unabhängig davon die Linux-Dateirechte. Trage pro Zeile einen absoluten Ordnerpfad ein; das Dateisystem-Wurzelverzeichnis wird aus Sicherheitsgründen abgelehnt.", "Die Freigaben gelten sofort für neue Dateianfragen. Das Hinzufügen eines Pfades kopiert keine Dateien, gibt keine Schreibrechte und verändert keine Inhalte."] },
    "training_packages.provider": { title: "Provider-Adapter", text: ["Wählt aus, für welchen technischen Provider das Trainingspaket bestimmt ist. Ein Provider-Adapter kennt die erlaubten Operationen und kann generisches Wissen mit den lokal vorhandenen Fähigkeiten dieses Providers verknüpfen.", "Ein Paket für Home Assistant kann beispielsweise nicht als Web-Trainingspaket importiert werden. Weitere vorhandene und zukünftige Provider erscheinen hier, sobald ihr Trainingsadapter installiert ist."] },
    "training_packages.kind": { title: "Art des Trainingspakets", text: ["Sprachpakete enthalten generische Bezeichnungen, Aktionen, Eigenschaften und Parameter. Mehrdeutigkeitspakete beschreiben Ausdrücke mit mehreren möglichen technischen Bedeutungen und die dazu passende Rückfrage.", "Beide Paketarten übertragen Wissen, aber weder lokale Gerätekennungen noch die Freigabe, eine Aktion auszuführen."], options: ["Sprachpaket: Vokabular und technische Bedeutungszuordnung.", "Mehrdeutigkeiten: bekannte Konflikte, Auswahlmöglichkeiten und Rückfragen."] },
    "training_packages.entry": { title: "Umfang des Exports", text: ["Wählt entweder alle Einträge der Paketart oder genau einen Trainingsbaustein für den Export. So lassen sich kleine, gezielte Community-Pakete erstellen, ohne den gesamten lokalen Lernstand zu teilen.", "Die Auswahl enthält ausschließlich portable Einträge. Lokale Entities, Areas, Endpunkte, Zustände und Zugangsdaten werden nicht aufgenommen."] },
    "training_packages.refresh": { title: "Lokale Verknüpfungen aktualisieren", text: ["Verknüpft vorhandene portable Trainingsdaten erneut mit den bereits im Memory bekannten Ressourcen des ausgewählten Providers. Dabei entstehen nachvollziehbare Memory-Relationen.", "Der Vorgang verwendet das gespeicherte Inventar, ruft kein LLM auf und führt keine Provider-Aktion aus. Eine neue Provider-Inventur wird dadurch nicht gestartet."] },
    "training_packages.export": { title: "Trainingspaket exportieren", text: ["Erstellt eine formatierte JSON-Datei aus der gewählten Paketart und dem gewählten Umfang. Das Paket enthält eine SHA-256-Prüfsumme und kann vor einem späteren Import vollständig geprüft werden.", "Vor dem Export gelten die Redaction- und Datenschutzregeln. Konkrete lokale Ressourcen und Geheimnisse gehören nicht zum portablen Paketvertrag."] },
    "training_packages.file": { title: "Trainingspaket auswählen", text: ["Wählt eine lokale JSON-Datei im Format eve-training-package-v1 aus. Die Auswahl allein liest das Paket noch nicht in EVEs Memory ein.", "Pakete sind auf 2 MB begrenzt. Prüfe insbesondere bei Community-Dateien Herausgeber, Inhalt und Signaturstatus, bevor du den Import ausführst."] },
    "training_packages.preview": { title: "Paket vorab prüfen", text: ["Validiert Format, erlaubte Felder, Prüfsumme, Redaction-Regeln und Provider-Zuordnung. Danach zeigt EVE neue, geänderte und unveränderte Einträge sowie lokal nutzbare und fehlende Domains.", "Die Vorschau ist rein lesend: Sie verändert das Memory nicht, ruft kein LLM auf und greift nicht auf den Provider zu."] },
    "training_packages.import": { title: "Paket importieren und verknüpfen", text: ["Speichert die zuvor erfolgreich geprüften Einträge als normale Memory-Claims mit Herkunftsbeleg und verknüpft sie mit bereits bekannten lokalen Provider-Ressourcen.", "Der Import übernimmt keine fremden Entity-IDs und keine Ausführungsfreigabe. Er löst weder Geräteaktionen noch LLM-Aufrufe aus; Schreibaktionen unterliegen weiterhin EVEs normaler Planung und Bestätigung."] },
  };

  let currentState = "idle";
  let previousState = "idle";
  let requestBusy = false;
  let activeBackendTurnId = null;
  let backendTurnCancellable = false;
  let latestVisibleTurnId = null;
  const queuedMessages = [];
  let captureBusy = false;
  let playingAudio = false;
  let voiceMuted = window.localStorage.getItem("eve.voiceMuted") === "true";
  let audioQueued = 0;
  let recorder = null;
  let chunks = [];
  let stream = null;
  let recordingTimer = null;
  let pressActive = false;
  let activePointerId = null;
  let stopRecordingPromise = null;
  let audioQueue = Promise.resolve();
  let audioCtx = null;
  let outputAnalyser = null;
  let micAnalyser = null;
  let micSource = null;
  let activeOutputSource = null;
  let activeOutputTurnId = null;
  const cancelledAudioTurns = new Set();
  let attachedImages = [];
  let notificationBusy = false;
  let notificationPresenting = false;
  let llmReady = true;
  let activeConversationId = null;
  let conversationRolloverTimer = 0;
  let conversationSessionTimeoutSeconds = null;
  let conversationLifecycleBusy = false;
  let explicitConversationResume = false;
  let conversations = [];
  let chatScrollFrame = 0;
  let scheduledTasks = [];
  let panelView = window.localStorage.getItem("eve.panelView");
  if (!["conversations", "schedules", "tasks"].includes(panelView)) {
    panelView = window.localStorage.getItem("eve.showingTasks") === "true" ? "tasks" : "conversations";
  }
  let showingTasks = panelView === "tasks";
  let showingSchedules = panelView === "schedules";
  let editingTaskId = null;
  let workLists = [];
  let workItems = [];
  let editingWorkItemId = null;
  const expandedWorkItems = new Set();
  let addingToWorkListId = null;
  let workMutationBusy = false;
  let workRefreshBusy = false;
  let workDataRevision = "";
  let workDrag = null;
  let chatOpen = window.localStorage.getItem("eve.chatOpen") === "true";
  let sidebarOpen = window.localStorage.getItem("eve.sidebarOpen") !== "false";
  let coreLayoutFrame = 0;
  let configOpen = false;
  let systemMenuOpen = false;
  let avatarMode = window.localStorage.getItem("eve.avatarMode") === "logo" ? "logo" : "brainwatch";
  let nerdMode = window.localStorage.getItem("eve.nerdMode") === "true";
  let presentationMotion = window.localStorage.getItem("eve.presentationMotion") !== "false";
  let nerdTimer = 0;
  const restoreBrainwatchOpen = window.localStorage.getItem("eve.brainwatchOpen") === "true";
  const storedBrainwatchMode = window.localStorage.getItem("eve.brainwatchMode");
  const restoreBrainwatchMode = new Set(["information", "memory", "semantic", "statistics", "events"]).has(storedBrainwatchMode)
    ? storedBrainwatchMode : "information";
  let brainwatchOpen = false;
  let presentationRevision = -1;
  let presentationObjectUrls = [];
  let presentationRenderGeneration = 0;
  const presentationTurnStates = new Map();
  let configValues = new Map();
  let configHelpAnchor = null;
  const notificationBacklog = [];

  const systemReducedMotionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  const reducedMotionQuery = {
    get matches() { return systemReducedMotionQuery.matches || !presentationMotion; },
    addEventListener(...args) { return systemReducedMotionQuery.addEventListener?.(...args); },
  };
  const finePointerQuery = matchMedia("(hover: hover) and (pointer: fine)");
  const mobileChatQuery = matchMedia("(max-width: 899px)");

  function stateLabel(state) {
    if (STATE_LABELS[state]) return STATE_LABELS[state];
    if (state.startsWith("tool:")) return "TOOL LINK";
    if (state.startsWith("memory:")) return "MEMORY";
    return state.toUpperCase();
  }

  function normalizeState(value) {
    if (typeof value !== "string") return "error";
    const state = value.trim().toLowerCase();
    if (KNOWN_STATES.has(state) || state.startsWith("tool:") || state.startsWith("memory:")) {
      return state;
    }
    return "error";
  }

  function triggerDecisionPulse() {
    elements.coreScene.classList.remove("decision");
    void elements.coreScene.offsetWidth;
    elements.coreScene.classList.add("decision");
    window.setTimeout(() => elements.coreScene.classList.remove("decision"), 620);
    canvasEngine.transitionPulse = 1;
  }

  function showState(value) {
    const state = normalizeState(value);
    previousState = currentState;
    currentState = state;
    document.body.dataset.state = state;
    elements.label.textContent = stateLabel(state);
    updateComposerActivity();
    if (previousState === "thinking" && state === "speaking") triggerDecisionPulse();
    canvasEngine.requestDraw();
  }

  function setConnection(online, label = null) {
    elements.connection.textContent = label || (online ? "LOCAL // ONLINE" : "LOCAL // OFFLINE");
    elements.connection.dataset.online = online ? "true" : "false";
  }

  function updateClock() {
    const now = new Date();
    elements.clock.dateTime = now.toISOString();
    elements.clock.textContent = now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  }

  updateClock();
  window.setInterval(updateClock, 1000);

  function setDetail(message) {
    elements.detail.textContent = typeof message === "string" ? message : "";
    updateComposerActivity();
  }

  function composerActivityLabel() {
    if (queuedMessages.length) {
      return `${queuedMessages.length} Nachricht${queuedMessages.length === 1 ? "" : "en"} vorgemerkt …`;
    }
    const detail = elements.detail.textContent.trim();
    if (detail && requestBusy) return detail;
    const labels = {
      "tool:home": "Home Assistant …",
      "tool:web": "Websuche und Quellen lesen …",
      "tool:nova": "Nova-EVE …",
      speaking: "Natürliche Sprechfassung wird vorbereitet …",
      thinking: "EVE denkt …",
    };
    return labels[currentState] || "EVE verarbeitet …";
  }

  function backendTurnStatusLabel(status) {
    const labels = {
      accepted: "EVE hat den Auftrag angenommen …",
      queued: "EVE bereitet den Auftrag vor …",
      waiting: "EVE wartet auf eine freie Verarbeitung …",
      running: "EVE arbeitet im Hintergrund …",
      cancelling: "Der laufende Turn wird abgebrochen …",
      cancelled: "Der laufende Turn wurde abgebrochen.",
    };
    return labels[String(status || "").toLowerCase()] || "EVE arbeitet im Hintergrund …";
  }

  function updateComposerActivity() {
    if (!elements.composerActivity) return;
    const hasDraft = Boolean(elements.messageText.value);
    const visible = requestBusy;
    elements.composerActivity.hidden = !visible;
    elements.composerActivity.classList.toggle("has-draft", visible && hasDraft);
    elements.composerActivityText.textContent = visible ? composerActivityLabel() : "";
    elements.turnCancel.hidden = !(visible && activeBackendTurnId && backendTurnCancellable);
    elements.turnCancel.disabled = !backendTurnCancellable;
    elements.messageText.setAttribute("aria-busy", String(requestBusy));
  }

  async function cancelActiveBackendTurn() {
    const turnId = activeBackendTurnId;
    if (!turnId || !backendTurnCancellable) return;
    backendTurnCancellable = false;
    elements.turnCancel.disabled = true;
    elements.turnCancel.textContent = "Wird abgebrochen …";
    setDetail("Backend-Turn wird abgebrochen …");
    cancelTurnAudio(turnId);
    try {
      const response = await fetchWithTimeout(`/api/backend-turns/${encodeURIComponent(turnId)}/cancel`, {
        method: "POST", headers: auth,
      }, 12000);
      const data = await readJsonResponse(response, "Turn-Abbruch");
      if (!response.ok) throw new Error(data.error || "Turn konnte nicht abgebrochen werden.");
      backendTurnCancellable = Boolean(data.cancellable && !data.cancel_requested);
      updateComposerActivity();
    } catch (error) {
      backendTurnCancellable = true;
      elements.turnCancel.textContent = "Abbrechen";
      updateComposerActivity();
      setDetail(`Abbruch fehlgeschlagen: ${error.message}`);
    }
  }

  elements.turnCancel.addEventListener("click", cancelActiveBackendTurn);

  function renderMessageQueue() {
    elements.messageQueue.replaceChildren();
    elements.messageQueue.hidden = queuedMessages.length === 0;
    queuedMessages.forEach((message, index) => {
      const item = document.createElement("div");
      item.className = "message-queue-item";
      const copy = document.createElement("span");
      copy.textContent = message.text || `${message.images.length} Screenshot(s)`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.dataset.queueIndex = String(index);
      remove.setAttribute("aria-label", `Vorgemerkte Nachricht entfernen: ${copy.textContent}`);
      const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.setAttribute("viewBox", "0 0 16 16");
      icon.setAttribute("aria-hidden", "true");
      const iconPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
      iconPath.setAttribute("d", "M3.5 4.5h9M6 2.5h4l.5 2h-5l.5-2Zm-1 2 .6 9h4.8l.6-9M7 7v4M9 7v4");
      icon.append(iconPath);
      remove.append(icon);
      item.append(copy, remove);
      elements.messageQueue.append(item);
    });
  }

  function setReply(message) {
    elements.reply.textContent = typeof message === "string" ? message : "";
  }

  function messageTime(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.valueOf())) return "";
    const day = date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
    const time = date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    return `${day}, ${time}`;
  }

  function conversationTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return "Unbekannter Zeitpunkt";
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    const time = date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    return sameDay
      ? `Heute, ${time}`
      : `${date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" })}, ${time}`;
  }

  function escapeChatHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function safeChatLink(anchor) {
    const raw = anchor.getAttribute("href") || "";
    try {
      const url = new URL(raw, window.location.href);
      if (!new Set(["http:", "https:"]).has(url.protocol)) throw new Error("unsafe protocol");
      anchor.href = url.href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
    } catch (_) {
      anchor.replaceWith(document.createTextNode(anchor.textContent || ""));
    }
  }

  function renderAssistantMarkdown(target, source) {
    const markdown = String(source || "");
    if (!window.marked?.parse || !window.DOMPurify?.sanitize) {
      target.textContent = markdown;
      return;
    }
    try {
      const renderer = new window.marked.Renderer();
      renderer.html = (token) => escapeChatHtml(typeof token === "string" ? token : token?.text);
      const parsed = window.marked.parse(markdown, {
        renderer,
        breaks: true,
        gfm: true,
        async: false,
      });
      const fragment = window.DOMPurify.sanitize(parsed, {
        RETURN_DOM_FRAGMENT: true,
        ALLOWED_TAGS: ["p", "br", "strong", "em", "h1", "h2", "h3", "h4", "h5", "h6",
          "ul", "ol", "li", "code", "pre", "blockquote", "a", "hr"],
        ALLOWED_ATTR: ["href", "title", "target", "rel"],
        ALLOW_DATA_ATTR: false,
      });
      fragment.querySelectorAll("a").forEach(safeChatLink);
      target.replaceChildren(fragment);
    } catch (_) {
      target.textContent = markdown;
    }
  }

  const DIAGNOSTIC_REDACTION = "[REDACTED]";
  // Keep these patterns aligned with memory.redact_sensitive and telemetry._safe.
  const DIAGNOSTIC_SECRET_KEY = /^(?:local[\s_-]?key|(?:x[\s_-]?)?api[\s_-]?key|private[\s_-]?key|secret[\s_-]?key|access[\s_-]?token|refresh[\s_-]?token|id[\s_-]?token|session[\s_-]?token|csrf[\s_-]?token|client[\s_-]?secret|authorization|proxy[\s_-]?authorization|password|passwort|passwd|passphrase|credentials?|cookies?|set[\s_-]?cookie|token|secret)$/i;

  function redactDiagnosticText(value) {
    const secretNames = "local[\\s_-]?key|access[\\s_-]?token|refresh[\\s_-]?token|api[\\s_-]?key|client[\\s_-]?secret|authorization|password|passwort|passwd|token";
    let text = String(value);
    text = text.replace(/(\bauthorization\b\s*[:=]\s*)(?:bearer\s+)?[^\s,}\]"']+/gi, `$1${DIAGNOSTIC_REDACTION}`);
    text = text.replace(
      new RegExp(`(\\b(?:${secretNames})\\b\\s*["']?\\s*(?::|=|\\b(?:ist|lautet)\\b)\\s*)(["'])(.*?)\\2`, "gi"),
      (_match, prefix, quote) => `${prefix}${quote}${DIAGNOSTIC_REDACTION}${quote}`,
    );
    text = text.replace(
      new RegExp(`(\\b(?:${secretNames})\\b\\s*["']?\\s*(?::|=|\\b(?:ist|lautet)\\b)\\s*["']?)(?!\\[REDACTED\\])([^\\s,"']+)`, "gi"),
      `$1${DIAGNOSTIC_REDACTION}`,
    );
    text = text.replace(/\b(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}/gi, `$1${DIAGNOSTIC_REDACTION}`);
    return text.replace(/\b(?:eyJ[A-Za-z0-9_-]{40,}|[A-Fa-f0-9]{32,}|[A-Za-z0-9_-]{64,})\b/g, DIAGNOSTIC_REDACTION);
  }

  function redactDiagnosticData(value, key = "", ancestors = null) {
    ancestors ||= new WeakSet();
    if (DIAGNOSTIC_SECRET_KEY.test(key)) return DIAGNOSTIC_REDACTION;
    if (typeof value === "string") return redactDiagnosticText(value);
    if (value === null || typeof value !== "object") return value;
    if (ancestors.has(value)) throw new Error("Die Rohdaten enthalten eine zirkuläre Referenz.");
    ancestors.add(value);
    let redacted;
    if (Array.isArray(value)) {
      redacted = value.map((item) => redactDiagnosticData(item, "", ancestors));
    } else {
      redacted = Object.fromEntries(
        Object.entries(value).map(([itemKey, item]) => [
          itemKey,
          redactDiagnosticData(item, itemKey, ancestors),
        ]),
      );
    }
    ancestors.delete(value);
    return redacted;
  }

  function formatDiagnosticJson(value) {
    if (value === null || value === undefined) throw new Error("Keine Rohdaten verfügbar.");
    const json = JSON.stringify(redactDiagnosticData(value), null, 2);
    if (json === undefined) throw new Error("Die Rohdaten können nicht als JSON ausgegeben werden.");
    return json;
  }

  function createDiagnosticCopyControl(value, label = "Rohdaten kopieren") {
    const control = document.createElement("div");
    control.className = "diagnostic-copy-control";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "diagnostic-copy-button eve-button eve-button--ghost";
    button.textContent = label;
    const status = document.createElement("span");
    status.className = "diagnostic-copy-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const available = value !== null && value !== undefined;
    button.disabled = !available;
    if (!available) button.title = "Keine Rohdaten verfügbar.";
    let resetTimer = null;
    button.addEventListener("click", async () => {
      if (resetTimer !== null) window.clearTimeout(resetTimer);
      status.textContent = "";
      button.removeAttribute("data-copy-state");
      button.disabled = true;
      try {
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
          throw new Error("Die Zwischenablage ist in diesem Browser nicht verfügbar.");
        }
        await navigator.clipboard.writeText(formatDiagnosticJson(value));
        button.dataset.copyState = "success";
        status.textContent = "Kopiert";
      } catch (error) {
        button.dataset.copyState = "error";
        const reason = error instanceof Error && error.message
          ? error.message
          : "Der Zugriff auf die Zwischenablage ist fehlgeschlagen.";
        status.textContent = `Kopieren fehlgeschlagen: ${reason}`;
      } finally {
        button.disabled = !available;
        resetTimer = window.setTimeout(() => {
          status.textContent = "";
          button.removeAttribute("data-copy-state");
        }, 3500);
      }
    });
    control.append(button, status);
    return control;
  }

  function createMessageNode(message) {
    const article = document.createElement("article");
    const role = message.role === "user" ? "user" : "assistant";
    article.className = `chat-message ${role}`;
    article.dataset.messageId = message.id || "";
    article.dataset.messageOrdinal = Number.isInteger(message.ordinal) ? String(message.ordinal) : "";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const author = document.createElement("strong");
    const source = message.metadata?.conversation_source;
    author.textContent = role === "assistant" ? "EVE"
      : source?.transport === "chatto" ? (source.sender_name?.trim() || "Chatto-Nutzer")
      : "DU";
    const time = document.createElement("time");
    time.textContent = messageTime(message.created_at);
    meta.append(author, time);
    const content = document.createElement("div");
    content.className = "message-content";
    if (message.role === "assistant") {
      content.classList.add("assistant-markdown");
      renderAssistantMarkdown(content, message.content);
    } else {
      content.textContent = String(message.content || "");
    }
    article.append(meta, content);
    const feedback = createActionFeedbackControl(message);
    if (feedback) article.append(feedback);
    const attachments = Array.isArray(message.attachments) ? message.attachments : [];
    if (attachments.length) {
      const media = document.createElement("div");
      media.className = "message-attachments";
      attachments.forEach((attachment) => {
        if (!attachment?.url) return;
        if (String(attachment.media_type || "").startsWith("image/")) {
          const image = document.createElement("img");
          image.src = attachment.url;
          image.alt = role === "user" ? "Gespeichertes Bild des Benutzers" : "Gespeichertes Tool-Bild";
          image.loading = "lazy";
          image.tabIndex = 0;
          image.classList.add("expandable-image");
          const filename = attachment.filename || "eve-bild";
          image.title = "In Originalgröße öffnen";
          image.addEventListener("click", () => openImageViewer(attachment.url, filename));
          image.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openImageViewer(attachment.url, filename);
            }
          });
          media.append(image);
        } else {
          const link = document.createElement("a");
          link.href = attachment.url;
          link.download = attachment.filename || "eve-download";
          link.textContent = attachment.filename || "ATTACHMENT";
          media.append(link);
        }
      });
      if (media.childElementCount) article.append(media);
    }
    const toolEvents = Array.isArray(message.tool_events) ? message.tool_events : [];
    if (toolEvents.length) {
      const details = document.createElement("details");
      details.className = "message-tool-events";
      const summary = document.createElement("summary");
      summary.textContent = `${toolEvents.length} ${toolEvents.length === 1 ? "Tool-Ereignis" : "Tool-Ereignisse"}`;
      const list = document.createElement("ul");
      toolEvents.forEach((toolEvent) => {
        const item = document.createElement("li");
        const eventSummary = document.createElement("span");
        eventSummary.className = "message-tool-event-summary";
        eventSummary.textContent = `${toolEvent.tool} · ${toolEvent.status} · ${toolEvent.summary}`;
        item.append(eventSummary, createDiagnosticCopyControl(toolEvent));
        list.append(item);
      });
      details.append(summary);
      if (toolEvents.length > 1) {
        details.append(createDiagnosticCopyControl(toolEvents, "Alle Rohdaten kopieren"));
      }
      details.append(list);
      article.append(details);
    }
    const sources = Array.isArray(message.metadata?.sources) ? message.metadata.sources : [];
    if (sources.length) {
      const sourceRow = document.createElement("details");
      sourceRow.className = "message-sources";
      const summary = document.createElement("summary");
      summary.textContent = `${sources.length} ${sources.length === 1 ? "Quelle" : "Quellen"}`;
      const sourceLinks = document.createElement("div");
      sourceLinks.className = "message-source-links";
      sources.forEach((source, index) => {
        const url = safeSourceUrl(source?.url);
        if (!url) return;
        const link = document.createElement("a");
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `[${index + 1}] ${source.title || url.hostname}`;
        sourceLinks.append(link);
      });
      if (sourceLinks.childElementCount) {
        sourceRow.append(summary, sourceLinks);
        article.append(sourceRow);
      }
    }
    const storedReasoning = role === "assistant" && typeof message.metadata?.reasoning === "string"
      ? message.metadata.reasoning.trim()
      : "";
    if (storedReasoning) article.append(createReasoningDisclosure(storedReasoning));
    return article;
  }

  function createActionFeedbackControl(message) {
    const details = message?.metadata?.turn_state_details;
    const claimId = details?.semantic_link_candidate_id || details?.semantic_link_id;
    if (message?.role !== "assistant" || !message.id || !message.conversation_id) return null;
    const semantic = Boolean(message.metadata?.semantic_feedback || (!message.metadata?.answer_feedback
      && message.metadata?.turn_state === "operational_resolved"
      && details?.operational_execution === true && claimId));
    const feedbackKey = semantic ? "semantic_feedback" : "answer_feedback";
    const subject = semantic ? "Aktion" : "Antwort";

    const control = document.createElement("div");
    control.className = "action-feedback";
    control.setAttribute("aria-label", `${subject} bewerten`);
    const status = document.createElement("span");
    status.className = "action-feedback-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    let busy = false;
    let editingExplanation = false;
    let explanationDraft = String(message.metadata?.[feedbackKey]?.explanation || "");

    const submit = async (decision, explanation = null) => {
      if (busy) return;
      busy = true;
      control.querySelectorAll("button").forEach((button) => { button.disabled = true; });
      status.textContent = decision === "undo" ? "Wird zurückgenommen …" : "Wird gespeichert …";
      try {
        const url = `/api/conversations/${encodeURIComponent(message.conversation_id)}`
          + `/messages/${encodeURIComponent(message.id)}/feedback`;
        const response = await fetchWithTimeout(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...auth },
          body: JSON.stringify({ decision, ...(explanation ? { explanation } : {}) }),
        });
        const data = await readJsonResponse(response, "Antwortbewertung");
        if (!response.ok) throw new Error(data.error || "Feedback konnte nicht gespeichert werden.");
        if (!message.metadata) message.metadata = {};
        message.metadata[feedbackKey] = data.feedback?.decision
          ? {
              status: "active",
              decision: data.feedback.decision,
              ...(data.feedback.explanation ? { explanation: data.feedback.explanation } : {}),
            }
          : null;
        explanationDraft = String(data.feedback?.explanation || "");
        editingExplanation = false;
        render();
        status.textContent = decision === "undo" ? "Rückgängig gemacht" : "Gespeichert";
      } catch (error) {
        status.textContent = `Fehler: ${error.message || error}`;
        control.dataset.feedbackState = "error";
      } finally {
        busy = false;
        control.querySelectorAll("button").forEach((button) => { button.disabled = false; });
      }
    };

    const button = (label, title, decision, action = null) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "action-feedback-link";
      element.textContent = label;
      element.title = title;
      element.setAttribute("aria-label", title);
      element.addEventListener("click", () => action ? action() : submit(decision));
      return element;
    };

    const render = () => {
      const selected = message.metadata?.[feedbackKey]?.status === "active"
        ? message.metadata[feedbackKey].decision : null;
      control.dataset.feedbackState = selected || "unrated";
      control.replaceChildren();
      if (editingExplanation) {
        const form = document.createElement("form");
        form.className = "action-feedback-explanation-form";
        const input = document.createElement("textarea");
        input.className = "action-feedback-explanation-input";
        input.rows = 2;
        if (semantic) input.maxLength = 1000;
        input.required = true;
        input.placeholder = "Was war falsch? Zum Beispiel: Die Antwort ging an meiner Frage vorbei.";
        input.setAttribute("aria-label", `Erklären, was an der ${subject} falsch war`);
        input.value = explanationDraft;
        const save = document.createElement("button");
        save.type = "submit";
        save.className = "action-feedback-link";
        save.textContent = semantic ? "Falsch speichern" : "Bewertung speichern";
        const cancel = button("Abbrechen", "Erklärung verwerfen", "", () => {
          editingExplanation = false;
          render();
        });
        form.append(input, save, cancel);
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          const explanation = input.value.trim();
          if (!explanation) {
            status.textContent = "Bitte kurz beschreiben, was falsch war.";
            input.focus();
            return;
          }
          explanationDraft = explanation;
          submit("incorrect", explanation);
        });
        control.append(form, status);
        window.requestAnimationFrame(() => input.focus());
        return;
      }
      if (selected === "correct" || selected === "incorrect") {
        const result = document.createElement("span");
        result.className = "action-feedback-result";
        result.textContent = semantic ? (selected === "correct" ? "👍 Korrekt" : "👎 Falsch")
          : (selected === "correct" ? "👍 Hilfreich" : "👎 Nicht hilfreich");
        control.append(result);
        if (selected === "incorrect") {
          const explanation = message.metadata?.[feedbackKey]?.explanation;
          if (explanation) {
            const text = document.createElement("span");
            text.className = "action-feedback-explanation";
            text.textContent = explanation;
            control.append(text);
          }
          control.append(button(
            explanation ? "Erklärung ändern" : "Erklären",
            `Beschreiben, was an der ${subject} falsch war`, "", () => {
              editingExplanation = true;
              render();
            },
          ));
        }
        control.append(button("Rückgängig", "Bewertung rückgängig machen", "undo"), status);
      } else {
        const prompt = document.createElement("span");
        prompt.className = "action-feedback-prompt";
        prompt.textContent = semantic ? "Aktion korrekt?" : "Antwort hilfreich?";
        control.append(
          prompt,
          button("👍", `${subject} war hilfreich / korrekt`, "correct"),
          button("👎", `${subject} war nicht hilfreich / falsch`, "", () => {
            if (!semantic) { submit("incorrect"); return; }
            editingExplanation = true;
            render();
          }),
          status,
        );
      }
    };
    render();
    return control;
  }

  function scrollChatToLatest() {
    const apply = () => {
      elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    };
    window.cancelAnimationFrame(chatScrollFrame);
    apply();
    chatScrollFrame = window.requestAnimationFrame(() => {
      apply();
      chatScrollFrame = window.requestAnimationFrame(() => {
        apply();
        chatScrollFrame = 0;
      });
    });
  }

  function appendChatMessage(message) {
    const node = createMessageNode(message);
    elements.chatMessages.append(node);
    elements.chatEmpty.hidden = true;
    scrollChatToLatest();
    return node;
  }

  function liveReasoningState() {
    return {
      article: null, badge: null, details: null, summary: null, content: null,
      text: "", finished: false, linked: false,
    };
  }

  function createReasoningDisclosure(reasoning) {
    const details = document.createElement("details");
    details.className = "message-reasoning";
    const summary = document.createElement("summary");
    summary.title = "EVEs Gedankengang anzeigen";
    summary.setAttribute("aria-label", "EVEs Gedankengang anzeigen");
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.classList.add("message-reasoning-icon");
    icon.setAttribute("viewBox", "0 0 24 22");
    icon.setAttribute("aria-hidden", "true");
    const cloud = document.createElementNS("http://www.w3.org/2000/svg", "path");
    cloud.setAttribute("d", "M7.2 15.5h9.6a4.2 4.2 0 0 0 .6-8.35A6.1 6.1 0 0 0 6 5.7a4.9 4.9 0 0 0 1.2 9.8Z");
    const bubble = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    bubble.setAttribute("cx", "5");
    bubble.setAttribute("cy", "18.2");
    bubble.setAttribute("r", "1.35");
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", "2.1");
    dot.setAttribute("cy", "20.4");
    dot.setAttribute("r", ".65");
    icon.append(cloud, bubble, dot);
    summary.append(icon);
    const content = document.createElement("pre");
    content.className = "message-reasoning-content";
    content.textContent = reasoning;
    details.append(summary, content);
    return details;
  }

  function attachReasoningLink(state, message) {
    if (!state || state.linked || !state.text || !message) return;
    message.append(createReasoningDisclosure(state.text));
    state.article?.remove();
    state.article = null;
    state.linked = true;
  }

  function appendLiveReasoning(state, chunk) {
    if (!state || state.finished || typeof chunk !== "string" || !chunk) return;
    if (!state.article) {
      const article = document.createElement("article");
      article.className = "chat-message assistant live-reasoning";
      const meta = document.createElement("div");
      meta.className = "message-meta";
      const author = document.createElement("strong");
      author.textContent = "EVE";
      const live = document.createElement("span");
      live.className = "live-reasoning-badge";
      live.textContent = "LIVE";
      meta.append(author, live);
      const details = document.createElement("details");
      details.className = "live-reasoning-details";
      details.open = true;
      const summary = document.createElement("summary");
      summary.textContent = "EVE denkt …";
      const content = document.createElement("pre");
      content.className = "live-reasoning-content";
      details.append(summary, content);
      article.append(meta, details);
      elements.chatMessages.append(article);
      elements.chatEmpty.hidden = true;
      Object.assign(state, { article, badge: live, details, summary, content });
    }
    state.text += chunk;
    state.content.textContent = state.text;
    state.content.scrollTop = state.content.scrollHeight;
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  }

  function finishLiveReasoning(state, outcome = "complete") {
    if (!state || state.finished) return;
    state.finished = true;
    if (!state.article) return;
    state.article.dataset.status = outcome;
    state.badge.textContent = outcome === "cancelled" ? "ABBRUCH" : outcome === "failed" ? "FEHLER" : "FERTIG";
    state.details.open = false;
    state.summary.textContent = outcome === "cancelled"
      ? "EVEs Gedanken bis zum Abbruch"
      : outcome === "failed"
        ? "EVEs Gedanken vor dem Fehler"
        : "EVEs Gedanken";
  }

  function ensureBackendUserMessage(turnId, transcript) {
    const text = String(transcript || "").trim();
    if (!text) return null;
    const users = [...elements.chatMessages.querySelectorAll(".chat-message.user")];
    const existing = users.find((node) => node.dataset.backendTurnId === turnId);
    if (existing) return existing;
    const latest = users.at(-1);
    if (latest?.querySelector(".message-content")?.textContent === text) {
      latest.dataset.backendTurnId = turnId;
      return latest;
    }
    const node = appendChatMessage({ role: "user", content: text, created_at: new Date().toISOString() });
    node.dataset.backendTurnId = turnId;
    return node;
  }

  function messageNodeById(messageId) {
    if (!messageId) return null;
    return [...elements.chatMessages.querySelectorAll(".chat-message.assistant")]
      .find((node) => node.dataset.messageId === messageId) || null;
  }

  function renderPresentationTurnStatus(state) {
    if (!state || state.conversationId !== activeConversationId) return;
    const message = messageNodeById(state.messageId);
    if (!message) return;
    message.dataset.turnId = state.turnId;
    let indicator = [...message.querySelectorAll(".presentation-work-status")]
      .find((node) => node.dataset.turnId === state.turnId);
    if (indicator) return;
    indicator = document.createElement("div");
    indicator.className = "presentation-work-status";
    indicator.dataset.turnId = state.turnId;
    indicator.setAttribute("role", "status");
    indicator.setAttribute("aria-live", "polite");
    const pulse = document.createElement("span");
    pulse.className = "presentation-work-pulse";
    pulse.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = "Darstellung wird vorbereitet …";
    indicator.append(pulse, label);
    message.append(indicator);
  }

  function restorePresentationTurnStatuses() {
    presentationTurnStates.forEach(renderPresentationTurnStatus);
  }

  function startPresentationTurnStatus(data) {
    if (!data.presentation_pending || !data.turn_id || !data.assistant_message_id) return;
    const state = {
      turnId: data.turn_id,
      messageId: data.assistant_message_id,
      conversationId: data.conversation_id,
    };
    presentationTurnStates.set(data.turn_id, state);
    renderPresentationTurnStatus(state);
  }

  function clearPresentationTurnStatus(turnId) {
    presentationTurnStates.delete(turnId);
    elements.chatMessages.querySelectorAll(".presentation-work-status").forEach((node) => {
      if (node.dataset.turnId === turnId) node.remove();
    });
  }

  function streamFailure(event) {
    const error = new Error(event.error || "Der Vorgang konnte nicht abgeschlossen werden.");
    error.backendTerminal = true;
    error.failureReport = event.failure_report || null;
    return error;
  }

  function createFailureCard(report, images = []) {
    const card = document.createElement("article");
    card.className = "chat-message assistant turn-failure";
    card.dataset.failureTurnId = report.turn_id || "";
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", "Fehlgeschlagener Vorgang");
    const title = document.createElement("strong");
    title.textContent = report.title || "Die Aufgabe konnte nicht abgeschlossen werden.";
    const reason = document.createElement("p");
    reason.textContent = report.reason;
    const activity = report.execution_observation;
    const observation = document.createElement("p");
    if (activity) {
      const facts = [];
      if (activity.repeated_material_selections) facts.push(`${activity.repeated_material_selections} wiederholte Abrufversuche mit derselben gespeicherten Auswahl`);
      if (activity.fresh_contexts) facts.push(`${activity.fresh_contexts} Wechsel in einen frischen Kontext`);
      if (activity.checkpoint_missing) facts.push("kein gespeicherter Arbeitsstand des Modells vorhanden");
      observation.textContent = facts.length ? `Im Ablauf beobachtet: ${facts.join("; ")}. Dies ist keine gesicherte Erklärung für den Abbruch.` : "";
    }
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Details";
    details.append(summary);
    const fields = [["Aufgabe", report.input_text], ["Vorgang", report.turn_id],
      ["Zeitpunkt", report.created_at ? new Date(report.created_at).toLocaleString() : null]];
    if (report.last_step) {
      const step = report.last_step;
      fields.push(["Letzter Werkzeugschritt", [step.tool, step.operation, step.path].filter(Boolean).join(" · ")]);
      fields.push(["Ergebnis", [step.status, step.http_status ? `HTTP ${step.http_status}` : null,
        step.result_count != null ? `${step.result_count} Einträge` : null].filter(Boolean).join(" · ")]);
    }
    if (report.tool_steps?.length > 1) {
      fields.push(["Bisherige Werkzeugergebnisse", report.tool_steps.map(step =>
        [step.tool, step.operation, step.path, step.status,
          step.http_status ? `HTTP ${step.http_status}` : null].filter(Boolean).join(" · ")).join("\n")]);
    }
    if (report.model_response_evidence) {
      fields.push(["Modellantwort (beobachtet)", JSON.stringify(report.model_response_evidence)]);
    }
    fields.push(["Technische Meldung", report.technical]);
    for (const [label, value] of fields) {
      if (!value) continue;
      const row = document.createElement("p");
      row.textContent = `${label}: ${value}`;
      details.append(row);
    }
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Mit Hinweis fortsetzen";
    const editor = document.createElement("div");
    editor.className = "failure-retry-editor";
    editor.hidden = true;
    const label = document.createElement("label");
    label.textContent = "Dein Korrekturhinweis";
    const hint = document.createElement("textarea");
    hint.rows = 3;
    hint.value = report.retry_hint || "Prüfe den Fehlerbericht und korrigiere die Vorgehensweise.";
    label.append(hint);
    const send = document.createElement("button");
    send.type = "button";
    send.textContent = "Fortsetzen";
    send.addEventListener("click", async () => {
      if (requestBusy) {
        setDetail("Bitte warte, bis der laufende Vorgang beendet ist.");
        return;
      }
      send.disabled = true;
      try {
        if (report.conversation_id && report.conversation_id !== activeConversationId) {
          await selectConversation(report.conversation_id, false, true);
        }
        const text = report.input_text || "Aufgabe fortsetzen";
        await submitMessage({ text, submittedText: text, images, retryContext: { source_turn_id: report.turn_id, correction: hint.value.trim() } });
      } catch (error) {
        setDetail(error.message);
      } finally {
        send.disabled = false;
      }
    });
    editor.append(label, send);
    retry.addEventListener("click", () => {
      editor.hidden = !editor.hidden;
      retry.setAttribute("aria-expanded", String(!editor.hidden));
      if (!editor.hidden) hint.focus();
    });
    retry.setAttribute("aria-expanded", "false");
    const reload = document.createElement("button");
    reload.type = "button";
    reload.textContent = "Antwort nachladen";
    reload.addEventListener("click", async () => {
      if (requestBusy) return;
      reload.disabled = true;
      try {
        if (!await recoverStoredAnswer(report.turn_id, report.conversation_id || activeConversationId)) {
          setDetail("Die gespeicherte Antwort ist noch nicht verfügbar oder EVE ist nicht erreichbar.");
        }
      } finally {
        reload.disabled = false;
      }
    });
    card.append(title, reason);
    if (observation.textContent) card.append(observation);
    if (report.working_memory) {
      const resume = document.createElement("button");
      resume.type = "button";
      resume.textContent = "Fortsetzen";
      resume.addEventListener("click", async () => {
        if (requestBusy) return;
        resume.disabled = true;
        try {
          if (report.conversation_id && report.conversation_id !== activeConversationId) {
            await selectConversation(report.conversation_id, false, true);
          }
          const text = report.input_text || "Aufgabe fortsetzen";
          await submitMessage({ text, submittedText: text, images,
            retryContext: { source_turn_id: report.turn_id, correction: "" } });
        } catch (error) { setDetail(error.message); }
        finally { resume.disabled = false; }
      });
      card.append(resume);
    }
    card.append(retry, reload, editor, details);
    return card;
  }

  async function recoverStoredAnswer(turnId, conversationId = activeConversationId) {
    if (!turnId || !conversationId || conversationId !== activeConversationId) return false;
    try {
      const response = await fetchWithTimeout(`/api/conversations/${encodeURIComponent(conversationId)}?limit=200`, {
        cache: "no-store", headers: auth,
      }, 5000);
      const data = await readJsonResponse(response, "Gespeicherte Antwort");
      if (!response.ok || conversationId !== activeConversationId) return false;
      const saved = (data.messages || []).find(message => message.role === "assistant" && message.turn_id === turnId);
      if (!saved) return false;
      const timeline = [
        ...(data.messages || []),
        ...(data.failures || []).map(report => ({ created_at: report.created_at, failure_report: report })),
      ].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
      renderMessages(timeline);
      setReply(saved.content || "");
      return true;
    } catch (_) {
      // Keep the current partial answer and composer when recovery is offline.
      return false;
    }
  }

  function showTurnFailure(error, turnId, inputText = "", images = []) {
    const report = error.failureReport || {
      turn_id: turnId, conversation_id: activeConversationId, input_text: inputText,
      created_at: new Date().toISOString(),
      reason: "Der Vorgang konnte nicht abgeschlossen oder sein Ergebnis nicht empfangen werden. Der genaue Grund ist noch unbekannt.",
      technical: error.message,
    };
    if ([...elements.chatMessages.querySelectorAll("[data-failure-turn-id]")]
        .some(node => node.dataset.failureTurnId && node.dataset.failureTurnId === report.turn_id)) return;
    elements.chatMessages.append(createFailureCard(report, images));
    elements.chatEmpty.hidden = true;
    scrollChatToLatest();
  }

  function renderMessages(messages = []) {
    elements.chatMessages.replaceChildren(...messages.map(message => message.failure_report ? createFailureCard(message.failure_report) : createMessageNode(message)));
    restorePresentationTurnStatuses();
    elements.chatEmpty.hidden = messages.length > 0;
    scrollChatToLatest();
  }

  async function exportConversationPng() {
    const status = elements.chatExportStatus;
    status.hidden = false;
    if (requestBusy) { status.textContent = "Bitte warte, bis EVE ihre Antwort abgeschlossen hat."; return; }
    if (!activeConversationId) { status.textContent = "Bitte öffne zuerst einen Chat."; return; }
    const conversationId = activeConversationId;
    const button = elements.exportConversation;
    if (button.disabled) return;
    button.disabled = true;
    let root;
    try {
      status.textContent = "Vollständigen Chatverlauf laden …";
      const { conversation, timeline } = await EveChatExport.loadConversation(async before => {
        const params = new URLSearchParams({ limit: "200" });
        if (before !== undefined) params.set("before", String(before));
        const response = await fetchWithTimeout(`/api/conversations/${encodeURIComponent(conversationId)}?${params}`, { cache: "no-store", headers: auth });
        const page = await readJsonResponse(response, "Chatexport");
        if (!response.ok) throw new Error(page.error || "Der Chat konnte nicht geladen werden.");
        return page;
      });
      if (!timeline.length) throw new Error("Dieser Chat enthält noch keine Nachrichten.");
      root = document.createElement("section"); root.className = "chat-export";
      root.setAttribute("aria-hidden", "true"); root.inert = true;
      const header = document.createElement("header"); header.className = "chat-export-heading";
      const brand = document.createElement("span"); brand.textContent = "EVE · UNTERHALTUNG";
      const title = document.createElement("h1"); title.textContent = conversation.title || "Unterhaltung mit EVE";
      const timestamp = document.createElement("p"); timestamp.textContent = `Exportiert am ${new Date().toLocaleString("de-DE")}`;
      header.append(brand, title, timestamp); root.append(header);
      const messages = document.createElement("div"); messages.className = "chat-export-messages";
      for (const message of timeline) messages.append(message.failure_report ? createFailureCard(message.failure_report) : createMessageNode(message));
      // Closed disclosures retain their current default presentation; interactive
      // controls are omitted from the shareable snapshot.
      messages.querySelectorAll("button, .action-feedback, .message-reasoning, .presentation-work-status").forEach(node => node.remove());
      messages.querySelectorAll("details:not([open])").forEach(details => {
        [...details.children].filter(child => child.tagName !== "SUMMARY").forEach(child => child.remove());
      });
      root.append(messages); document.body.append(root);
      const blob = await EveChatExport.renderPng(root, { headers: auth, progress: value => { status.textContent = `PNG erstellen … ${value} %`; } });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url;
      const filename = (conversation.title || "chat").replace(/[^\p{L}\p{N}_-]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 100) || "chat";
      link.download = `eve-${filename}-${new Date().toISOString().slice(0, 10)}.png`;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      status.textContent = "Chat als PNG exportiert.";
    } catch (error) { status.textContent = `PNG-Export fehlgeschlagen: ${error.message}`; }
    finally { root?.remove(); button.disabled = false; }
  }

  function renderConversationList() {
    const ordered = [...conversations].sort(
      (first, second) => new Date(second.updated_at).valueOf() - new Date(first.updated_at).valueOf(),
    );
    const nodes = ordered.map((conversation) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "conversation-item";
      button.dataset.active = conversation.id === activeConversationId ? "true" : "false";
      const title = document.createElement("strong");
      title.textContent = conversation.title;
      const meta = document.createElement("span");
      const count = Number(conversation.message_count || 0);
      meta.textContent = `${conversationTime(conversation.updated_at)} · ${count} ${count === 1 ? "Nachricht" : "Nachrichten"}`;
      button.append(title, meta);
      button.addEventListener("click", () => selectConversation(conversation.id));
      return button;
    });
    elements.conversationList.replaceChildren(...nodes);
    elements.conversationListEmpty.hidden = panelView !== "conversations" || conversations.length > 0;
  }

  async function loadConversations(preferredId = null) {
    const response = await fetchWithTimeout("/api/conversations?limit=100", { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Conversation-Liste");
    if (!response.ok) throw new Error(data.error || "Unterhaltungen konnten nicht geladen werden.");
    conversations = Array.isArray(data.conversations) ? data.conversations : [];
    const candidate = [preferredId, activeConversationId, data.active_id]
      .find(id => id && conversations.some(item => item.id === id)) || conversations[0]?.id;
    renderConversationList();
    if (candidate) await selectConversation(candidate, false, true);
    else {
      activeConversationId = null;
      explicitConversationResume = false;
      elements.conversationTitle.textContent = "Neue Unterhaltung";
      renderMessages([]);
    }
  }

  async function selectConversation(conversationId, closePanel = true, force = false) {
    if ((!force && requestBusy) || !conversationId) return;
    window.clearTimeout(conversationRolloverTimer);
    conversationRolloverTimer = 0;
    const response = await fetchWithTimeout(`/api/conversations/${encodeURIComponent(conversationId)}?limit=200`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Unterhaltung");
    if (!response.ok) throw new Error(data.error || "Unterhaltung konnte nicht geladen werden.");
    activeConversationId = data.conversation.id;
    // A visible browser chat is an explicit, persistent conversation choice.
    // Refreshing its data must not silently turn that choice into an expiring
    // ambient session.
    explicitConversationResume = true;
    elements.conversationTitle.textContent = data.conversation.title;
    const timeline = [
      ...(data.messages || []),
      ...(data.failures || []).map(report => ({ created_at: report.created_at, failure_report: report })),
    ].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    renderMessages(timeline);
    if (!requestBusy && data.active_turn_id) {
      window.localStorage.setItem("eve.activeBackendTurn", data.active_turn_id);
      scheduleBackendReconnect(0);
    }
    renderConversationList();
    if (closePanel && window.innerWidth < 900) toggleConversationPanel(false);
  }

  async function openTaskContext(link) {
    if (!link?.conversation_id) return;
    await toggleTaskView(false);
    await selectConversation(link.conversation_id, false, true);
    const messages = [...elements.chatMessages.querySelectorAll(".chat-message")];
    const start = messages.find((node) => node.dataset.messageId === link.start_message_id);
    const end = messages.find((node) => node.dataset.messageId === link.end_message_id);
    const firstOrdinal = Number(start?.dataset.messageOrdinal);
    const endOrdinal = Number(end?.dataset.messageOrdinal);
    const targets = start
      ? messages.filter((node) => {
          const ordinal = Number(node.dataset.messageOrdinal);
          return !end || (ordinal >= firstOrdinal && ordinal <= endOrdinal);
        })
      : [];
    targets.forEach((node) => node.classList.add("context-highlight"));
    (start || elements.chatMessages.firstElementChild)?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => targets.forEach((node) => node.classList.remove("context-highlight")), 4500);
  }

  function scheduleConversationRollover(lifecycle = null, userInput = false) {
    window.clearTimeout(conversationRolloverTimer);
    conversationRolloverTimer = 0;
    const configured = Number(lifecycle?.configured_session_timeout_seconds);
    if (Number.isFinite(configured) && configured > 0) conversationSessionTimeoutSeconds = configured;
    const timeout = conversationSessionTimeoutSeconds;
    if (!Number.isFinite(timeout) || timeout <= 0 || !activeConversationId) return;
    const rawIdle = lifecycle?.idle_time_seconds;
    const idle = userInput ? 0 : Number(rawIdle);
    if (!userInput && (lifecycle?.new_session || rawIdle == null || !Number.isFinite(idle))) return;
    const remaining = Math.max(0, timeout - idle);
    conversationRolloverTimer = window.setTimeout(() => {
      synchronizeConversationLifecycle().catch(() => {
        conversationRolloverTimer = window.setTimeout(() => {
          synchronizeConversationLifecycle().catch(() => {});
        }, 5000);
      });
    }, Math.max(250, Math.ceil(remaining * 1000)));
  }

  async function synchronizeConversationLifecycle() {
    if (conversationLifecycleBusy || !activeConversationId) return;
    if (explicitConversationResume) return;
    if (requestBusy || captureBusy || recorder?.state === "recording") {
      window.clearTimeout(conversationRolloverTimer);
      conversationRolloverTimer = window.setTimeout(() => {
        synchronizeConversationLifecycle().catch(() => {});
      }, 1000);
      return;
    }
    conversationLifecycleBusy = true;
    try {
      const response = await fetchWithTimeout("/api/conversations/active", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ conversation_id: activeConversationId }),
      });
      const data = await readJsonResponse(response, "Aktive Unterhaltung");
      if (!response.ok) throw new Error(data.error || "Aktive Unterhaltung konnte nicht geladen werden.");
      if (data.active_id && data.active_id !== activeConversationId) {
        activeConversationId = data.active_id;
        await loadConversations(activeConversationId);
      }
      scheduleConversationRollover(data.lifecycle);
    } finally {
      conversationLifecycleBusy = false;
    }
  }

  async function createConversation() {
    const response = await fetchWithTimeout("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...auth },
      body: JSON.stringify({ title: "Neue Unterhaltung" }),
    });
    const data = await readJsonResponse(response, "Neue Unterhaltung");
    if (!response.ok) throw new Error(data.error || "Unterhaltung konnte nicht angelegt werden.");
    await loadConversations(data.conversation.id);
    openComposer();
  }

  async function openCurrentChat() {
    await synchronizeConversationLifecycle();
    setChatOpen(true);
  }

  function taskSchedule(task) {
    const date = task.next_run_at ? new Date(task.next_run_at) : null;
    const next = date && !Number.isNaN(date.valueOf())
      ? conversationTime(date.toISOString())
      : "Kein nächster Termin";
    const labels = { once: "Einmalig", delay: "Einmalig verzögert", daily: "Täglich", weekly: "Wöchentlich", interval: "Intervall", event: "Ereignis" };
    return `${labels[task.schedule_type] || task.schedule_type} · ${next}`;
  }

  function renderTaskList() {
    const nodes = scheduledTasks.map((task) => {
      const article = document.createElement("article");
      article.className = "task-item";
      article.dataset.status = task.status;
      const body = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = task.name;
      const meta = document.createElement("span");
      meta.textContent = taskSchedule(task);
      body.append(title);
      const request = task.action?.request || task.action?.message;
      if (request && request !== task.name) {
        const reminder = document.createElement("p");
        reminder.className = "task-reminder-text";
        reminder.textContent = request;
        body.append(reminder);
      }
      body.append(meta);
      const actions = document.createElement("div");
      actions.className = "task-item-actions";
      const pause = document.createElement("button");
      pause.type = "button";
      pause.textContent = task.status === "paused" ? "FORTSETZEN" : "PAUSE";
      pause.addEventListener("click", async () => {
        try {
          await updateTask(task.id, { status: task.status === "paused" ? "active" : "paused" });
        } catch (error) {
          window.alert(error.message);
        }
      });
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "ÄNDERN";
      edit.addEventListener("click", () => editTask(task));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "LÖSCHEN";
      remove.addEventListener("click", () => deleteTask(task));
      actions.append(pause, edit, remove);
      article.append(body, actions);
      return article;
    });
    elements.scheduledTaskList.replaceChildren(...nodes);
    elements.scheduledTaskListEmpty.hidden = scheduledTasks.length > 0 || !showingSchedules;
  }

  async function loadTasks() {
    const response = await fetchWithTimeout("/api/tasks?limit=100", { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Aufgabenliste");
    if (!response.ok) throw new Error(data.error || "Aufgaben konnten nicht geladen werden.");
    scheduledTasks = Array.isArray(data.tasks) ? data.tasks : [];
    renderTaskList();
  }

  async function updateTask(taskId, changes) {
    const response = await fetchWithTimeout(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...auth },
      body: JSON.stringify(changes),
    });
    const data = await readJsonResponse(response, "Aufgabe ändern");
    if (!response.ok) throw new Error(data.error || "Aufgabe konnte nicht geändert werden.");
    await loadTasks();
  }

  function localDateTimeValue(value) {
    const date = value ? new Date(value) : new Date(Date.now() + 3600000);
    if (Number.isNaN(date.valueOf())) return "";
    return new Date(date.valueOf() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }

  function updateTaskEditorFields() {
    const type = elements.taskScheduleType.value;
    elements.taskOnceRow.hidden = type !== "once";
    elements.taskTimeRow.hidden = !["daily", "weekly"].includes(type);
    elements.taskWeekdays.hidden = type !== "weekly";
    elements.taskIntervalRow.hidden = !["delay", "interval"].includes(type);
  }

  function editTask(task) {
    editingTaskId = task.id;
    elements.taskEditorError.textContent = "";
    elements.taskMessage.value = task.action?.request || task.action?.raw_message || task.action?.message || task.name;
    elements.taskScheduleType.value = ["once", "delay", "daily", "weekly", "interval"].includes(task.schedule_type)
      ? task.schedule_type : "once";
    elements.taskOnceAt.value = localDateTimeValue(task.schedule?.at || task.next_run_at);
    const hour = String(task.schedule?.hour ?? new Date(task.next_run_at).getHours()).padStart(2, "0");
    const minute = String(task.schedule?.minute ?? new Date(task.next_run_at).getMinutes()).padStart(2, "0");
    elements.taskTime.value = `${hour}:${minute}`;
    const selectedDays = new Set(task.schedule?.weekdays || []);
    elements.taskWeekdays.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = selectedDays.has(Number(input.value));
    });
    const seconds = Number(task.schedule?.seconds || 1800);
    const unit = seconds % 86400 === 0 ? 86400 : seconds % 3600 === 0 ? 3600 : 60;
    elements.taskIntervalUnit.value = String(unit);
    elements.taskIntervalValue.value = String(Math.max(1, Math.round(seconds / unit)));
    elements.taskActive.checked = task.status === "active";
    updateTaskEditorFields();
    elements.taskEditor.showModal();
    elements.taskMessage.focus();
  }

  function closeTaskEditor() {
    editingTaskId = null;
    elements.taskEditor.close();
  }

  function taskSchedulePayload() {
    const type = elements.taskScheduleType.value;
    if (type === "once") {
      const date = new Date(elements.taskOnceAt.value);
      if (Number.isNaN(date.valueOf())) throw new Error("Bitte Datum und Uhrzeit auswählen.");
      return { type, schedule: { at: date.toISOString() } };
    }
    if (["delay", "interval"].includes(type)) {
      const seconds = Number(elements.taskIntervalValue.value) * Number(elements.taskIntervalUnit.value);
      if (!Number.isFinite(seconds) || seconds < 60) throw new Error("Das Intervall muss mindestens eine Minute betragen.");
      return { type, schedule: { seconds } };
    }
    const [hour, minute] = elements.taskTime.value.split(":").map(Number);
    if (!Number.isInteger(hour) || !Number.isInteger(minute)) throw new Error("Bitte eine Uhrzeit auswählen.");
    if (type === "daily") return { type, schedule: { hour, minute } };
    const weekdays = [...elements.taskWeekdays.querySelectorAll('input[type="checkbox"]:checked')].map((input) => Number(input.value));
    if (!weekdays.length) throw new Error("Bitte mindestens einen Wochentag auswählen.");
    return { type, schedule: { weekdays, hour, minute } };
  }

  async function deleteTask(task) {
    if (!window.confirm(`Geplante Aufgabe „${task.action?.request || task.action?.message || task.name}“ löschen?`)) return;
    try {
      const response = await fetchWithTimeout(`/api/tasks/${encodeURIComponent(task.id)}`, { method: "DELETE", headers: auth });
      const data = await readJsonResponse(response, "Aufgabe löschen");
      if (!response.ok) throw new Error(data.error || "Aufgabe konnte nicht gelöscht werden.");
      await loadTasks();
    } catch (error) {
      window.alert(error.message);
    }
  }

  function storedWorkDisclosures(key) {
    try {
      const value = JSON.parse(window.localStorage.getItem(key) || "[]");
      return new Set(Array.isArray(value) ? value.map(String) : []);
    } catch (_) {
      return new Set();
    }
  }

  const openWorkLists = storedWorkDisclosures("eve.openWorkLists");
  const openCompletedLists = storedWorkDisclosures("eve.openCompletedWorkLists");

  function persistWorkDisclosures(key, values) {
    window.localStorage.setItem(key, JSON.stringify([...values]));
  }

  function setWorkTaskError(message = "") {
    elements.workTaskError.textContent = message;
    elements.workTaskError.hidden = !message;
  }

  async function workTaskRequest(path, options, label) {
    const response = await fetchWithTimeout(path, { cache: "no-store", headers: auth, ...options });
    const data = await readJsonResponse(response, label);
    if (!response.ok) throw new Error(data.error || `${label} ist fehlgeschlagen.`);
    return data;
  }

  function workActionButton(label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", action);
    return button;
  }

  function workDeleteIcon() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const lid = document.createElementNS("http://www.w3.org/2000/svg", "path");
    lid.setAttribute("d", "M4 7h16M9 7V4h6v3");
    const bin = document.createElementNS("http://www.w3.org/2000/svg", "path");
    bin.setAttribute("d", "M7 7l1 13h8l1-13M10 11v5M14 11v5");
    svg.append(lid, bin);
    return svg;
  }

  async function deleteWorkItem(item) {
    if (!window.confirm(`Arbeitsaufgabe „${item.title}“ wirklich löschen?`)) return;
    if (workMutationBusy) return;
    try {
      workMutationBusy = true;
      setWorkTaskError();
      await workTaskRequest(`/api/work-items/${encodeURIComponent(item.id)}`, {
        method: "DELETE",
        headers: auth,
      }, "Arbeitsaufgabe löschen");
      editingWorkItemId = null;
      await loadWorkTasks();
    } catch (error) {
      setWorkTaskError(error.message);
    } finally {
      workMutationBusy = false;
    }
  }

  async function deleteWorkList(workList, itemCount) {
    const suffix = itemCount === 1 ? "eine enthaltene Aufgabe" : `${itemCount} enthaltene Aufgaben`;
    if (!window.confirm(`Arbeitsliste „${workList.name}“ und ${suffix} wirklich löschen?`)) return;
    if (workMutationBusy) return;
    try {
      workMutationBusy = true;
      setWorkTaskError();
      await workTaskRequest(`/api/work-lists/${encodeURIComponent(workList.id)}`, {
        method: "DELETE",
        headers: auth,
      }, "Arbeitsliste löschen");
      openWorkLists.delete(workList.id);
      openCompletedLists.delete(workList.id);
      persistWorkDisclosures("eve.openWorkLists", openWorkLists);
      persistWorkDisclosures("eve.openCompletedWorkLists", openCompletedLists);
      await loadWorkTasks();
    } catch (error) {
      setWorkTaskError(error.message);
    } finally {
      workMutationBusy = false;
    }
  }

  function sizeWorkDescription(field) {
    if (!field.clientWidth) return;
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight + field.offsetHeight - field.clientHeight}px`;
  }

  function sizeWorkDescriptions() {
    elements.taskList.querySelectorAll(".work-inline-form textarea").forEach(sizeWorkDescription);
  }

  const workFormResizeObserver = new ResizeObserver(sizeWorkDescriptions);
  workFormResizeObserver.observe(elements.taskList);
  elements.taskList.addEventListener("input", (event) => {
    if (event.target.matches(".work-inline-form textarea")) sizeWorkDescription(event.target);
  });
  elements.taskList.addEventListener("toggle", () => window.requestAnimationFrame(sizeWorkDescriptions), true);

  function workItemForm(item, defaultListId, onCancel) {
    const form = document.createElement("form");
    form.className = "work-inline-form work-item-form";
    const titleLabel = document.createElement("label");
    titleLabel.textContent = "Titel";
    const title = document.createElement("input");
    title.name = "title";
    title.maxLength = 240;
    title.required = true;
    title.autocomplete = "off";
    title.value = item?.title || "";
    titleLabel.append(title);
    const descriptionLabel = document.createElement("label");
    descriptionLabel.textContent = "Beschreibung";
    const description = document.createElement("textarea");
    description.name = "description";
    description.maxLength = 5000;
    description.rows = 3;
    description.value = item?.description || "";
    description.placeholder = "Formatierung wie im Chat: **fett**, *kursiv*, Listen und Code";
    const hint = document.createElement("small");
    hint.className = "work-editor-hint";
    hint.textContent = "Formatierung wie im Chat: Markdown wird beim Lesen dargestellt.";
    descriptionLabel.append(description, hint);
    form.append(titleLabel, descriptionLabel);
    let listSelect = null;
    if (item) {
      const listLabel = document.createElement("label");
      listLabel.textContent = "Arbeitsliste";
      listSelect = document.createElement("select");
      listSelect.name = "list_id";
      for (const workList of workLists) {
        const option = document.createElement("option");
        option.value = workList.id;
        option.textContent = workList.name;
        option.selected = workList.id === item.list_id;
        listSelect.append(option);
      }
      listLabel.append(listSelect);
      form.append(listLabel);
    }
    const actions = document.createElement("div");
    actions.className = "work-form-actions";
    if (item) {
      const remove = workActionButton("", () => deleteWorkItem(item));
      remove.className = "work-delete-item work-delete-action";
      remove.setAttribute("aria-label", `Arbeitsaufgabe „${item.title}“ löschen`);
      remove.title = "Arbeitsaufgabe löschen";
      remove.append(workDeleteIcon());
      actions.append(remove);
    }
    actions.append(workActionButton("ABBRECHEN", onCancel));
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = item ? "SPEICHERN" : "HINZUFÜGEN";
    actions.append(save);
    form.append(actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (workMutationBusy) return;
      const payload = {
        title: title.value.trim(),
        description: description.value.trim() ? description.value.replace(/^\n+|\n+$/g, "") : null,
      };
      if (item) payload.list_id = listSelect.value;
      else payload.list_id = defaultListId;
      if (item && payload.title === item.title
          && payload.description === (item.description || null)
          && payload.list_id === item.list_id) {
        editingWorkItemId = null;
        renderWorkLists();
        return;
      }
      try {
        workMutationBusy = true;
        setWorkTaskError();
        await workTaskRequest(
          item ? `/api/work-items/${encodeURIComponent(item.id)}` : "/api/work-items",
          {
            method: item ? "PATCH" : "POST",
            headers: { "Content-Type": "application/json", ...auth },
            body: JSON.stringify(payload),
          },
          item ? "Arbeitsaufgabe ändern" : "Arbeitsaufgabe anlegen",
        );
        editingWorkItemId = null;
        addingToWorkListId = null;
        await loadWorkTasks();
      } catch (error) {
        setWorkTaskError(error.message);
      } finally {
        workMutationBusy = false;
      }
    });
    window.requestAnimationFrame(() => { sizeWorkDescription(description); title.focus(); });
    return form;
  }

  function clearWorkDropFeedback() {
    elements.workLists.querySelectorAll(".work-drop-before, .work-drop-at-end, .work-drop-list")
      .forEach((node) => node.classList.remove("work-drop-before", "work-drop-at-end", "work-drop-list"));
  }

  function updateWorkDropTarget(clientX, clientY) {
    if (!workDrag) return;
    clearWorkDropFeedback();
    workDrag.targetListId = null;
    workDrag.targetPosition = null;
    const hovered = document.elementFromPoint(clientX, clientY);
    const targetList = hovered?.closest(".work-list[data-list-id]");
    if (!targetList) return;
    const listId = targetList.dataset.listId;
    const targetItems = workItems.filter((candidate) => (
      candidate.list_id === listId && candidate.status === "open" && candidate.id !== workDrag.item.id
    ));
    workDrag.targetListId = listId;
    if (!targetList.open) {
      workDrag.targetPosition = targetItems.length;
      targetList.classList.add("work-drop-list");
      return;
    }
    const rows = [...targetList.querySelectorAll('.work-items > .work-item-row[data-status="open"]')]
      .filter((row) => row.dataset.itemId !== workDrag.item.id);
    const before = rows.find((row) => clientY < row.getBoundingClientRect().top + row.offsetHeight / 2);
    workDrag.targetPosition = before ? rows.indexOf(before) : rows.length;
    if (before) before.classList.add("work-drop-before");
    else targetList.querySelector(":scope > .work-items")?.classList.add("work-drop-at-end");
  }

  async function persistWorkItemMove(item, listId, position) {
    try {
      workMutationBusy = true;
      setWorkTaskError();
      await workTaskRequest(`/api/work-items/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ list_id: listId, position }),
      }, "Arbeitsaufgabe verschieben");
      await loadWorkTasks();
    } catch (error) {
      await loadWorkTasks().catch(() => {});
      setWorkTaskError(error.message);
    } finally {
      workMutationBusy = false;
    }
  }

  function startWorkItemDrag(event, item, row, handle) {
    if (event.button !== 0 || item.status !== "open" || workMutationBusy || workDrag) return;
    event.preventDefault();
    workDrag = { item, row, handle, pointerId: event.pointerId, startX: event.clientX,
      startY: event.clientY, moved: false, targetListId: null, targetPosition: null };
    row.classList.add("work-dragging");
    handle.setPointerCapture(event.pointerId);
    const move = (moveEvent) => {
      if (!workDrag.moved && Math.hypot(
        moveEvent.clientX - workDrag.startX, moveEvent.clientY - workDrag.startY,
      ) < 6) return;
      workDrag.moved = true;
      updateWorkDropTarget(moveEvent.clientX, moveEvent.clientY);
    };
    const finish = (finishEvent) => {
      const cancelled = finishEvent.type === "pointercancel";
      const moved = workDrag?.moved;
      const targetListId = workDrag?.targetListId;
      const targetPosition = workDrag?.targetPosition;
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      if (handle.hasPointerCapture(finishEvent.pointerId)) handle.releasePointerCapture(finishEvent.pointerId);
      row.classList.remove("work-dragging");
      clearWorkDropFeedback();
      workDrag = null;
      if (!cancelled && moved && targetListId !== null && Number.isInteger(targetPosition)) {
        persistWorkItemMove(item, targetListId, targetPosition);
      }
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  }

  function workItemNode(item) {
    if (editingWorkItemId === item.id) {
      return workItemForm(item, item.list_id, () => {
        editingWorkItemId = null;
        renderWorkLists();
      });
    }
    const row = document.createElement("article");
    row.className = "work-item-row";
    row.dataset.status = item.status;
    row.dataset.itemId = item.id;
    const expanded = expandedWorkItems.has(item.id);
    const heading = document.createElement("div");
    heading.className = "work-item-heading";
    if (item.status === "open") {
      const handle = document.createElement("button");
      handle.type = "button";
      handle.className = "work-drag-handle";
      handle.setAttribute("aria-label", `„${item.title}“ verschieben`);
      handle.title = "Aufgabe verschieben";
      const grip = document.createElement("span");
      grip.setAttribute("aria-hidden", "true");
      handle.append(grip);
      handle.addEventListener("pointerdown", (event) => startWorkItemDrag(event, item, row, handle));
      heading.append(handle);
    }
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = item.status === "completed";
    checkbox.setAttribute("aria-label", `„${item.title}“ ${checkbox.checked ? "wieder öffnen" : "abschließen"}`);
    checkbox.addEventListener("change", async () => {
      if (workMutationBusy) return renderWorkLists();
      try {
        workMutationBusy = true;
        checkbox.disabled = true;
        setWorkTaskError();
        await workTaskRequest(`/api/work-items/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...auth },
          body: JSON.stringify({ status: checkbox.checked ? "completed" : "open" }),
        }, checkbox.checked ? "Arbeitsaufgabe abschließen" : "Arbeitsaufgabe wieder öffnen");
        await loadWorkTasks();
      } catch (error) {
        renderWorkLists();
        setWorkTaskError(error.message);
      } finally {
        workMutationBusy = false;
      }
    });
    const content = document.createElement("button");
    content.type = "button";
    content.className = "work-item-content";
    content.setAttribute("aria-expanded", String(expanded));
    content.setAttribute("aria-controls", `work-item-details-${item.id}`);
    content.setAttribute("aria-label", `${item.title} ${expanded ? "zuklappen" : "aufklappen"}`);
    const title = document.createElement("strong");
    title.textContent = item.title;
    content.append(title);
    if (item.description && !expanded) {
      const description = document.createElement("span");
      const preview = document.createElement("div");
      renderAssistantMarkdown(preview, item.description);
      description.textContent = preview.textContent.replace(/\s+/g, " ").trim();
      content.append(description);
    }
    const contextLinks = Array.isArray(item.context_links) ? item.context_links : [];
    let context = null;
    if (contextLinks.length) {
      context = document.createElement("span");
      context.className = "work-context-links";
      const compactLabel = document.createElement("span");
      compactLabel.className = "work-context-text";
      compactLabel.textContent = "Kontext";
      const decorateTrigger = (button) => {
        button.className = "work-context-link";
        button.setAttribute("aria-label", contextLinks.length === 1
          ? "Chat-Kontext öffnen" : `${contextLinks.length} Chat-Kontexte auswählen`);
        button.append(document.createTextNode("↗ "), compactLabel);
        if (contextLinks.length > 1) button.append(document.createTextNode(` · ${contextLinks.length}`));
      };
      if (contextLinks.length === 1) {
        const link = contextLinks[0];
        const button = document.createElement("button");
        button.type = "button";
        const scope = link.end_message_id ? "Bereich" : (link.start_message_id ? "Nachricht" : "Chat");
        button.title = `${scope} in „${link.conversation_title || "Unterhaltung"}“ öffnen`;
        decorateTrigger(button);
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          openTaskContext(link).catch((error) => setWorkTaskError(error.message));
        });
        context.append(button);
      } else {
        const chooser = document.createElement("details");
        chooser.className = "work-context-chooser";
        const summary = document.createElement("summary");
        decorateTrigger(summary);
        const menu = document.createElement("span");
        menu.className = "work-context-menu";
        contextLinks.forEach((link, index) => {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "work-context-option";
          const scope = link.end_message_id ? "Bereich" : (link.start_message_id ? "Nachricht" : "Chat");
          option.textContent = link.label || link.conversation_title || `${scope} ${index + 1}`;
          option.setAttribute("aria-label", `${scope} in „${link.conversation_title || "Unterhaltung"}“ öffnen`);
          option.title = `${scope} · ${conversationTime(link.created_at)}`;
          option.addEventListener("click", (event) => {
            event.stopPropagation();
            chooser.open = false;
            openTaskContext(link).catch((error) => setWorkTaskError(error.message));
          });
          menu.append(option);
        });
        chooser.append(summary, menu);
        context.append(chooser);
      }
    }
    content.addEventListener("click", () => {
      if (expanded) expandedWorkItems.delete(item.id);
      else expandedWorkItems.add(item.id);
      const replacement = workItemNode(item);
      row.replaceWith(replacement);
      replacement.querySelector(".work-item-content").focus({ preventScroll: true });
    });
    heading.append(checkbox, content);
    if (context) heading.append(context);
    row.append(heading);
    if (expanded) {
      const details = document.createElement("section");
      details.className = "work-item-details";
      details.id = `work-item-details-${item.id}`;
      const description = document.createElement("div");
      description.className = "work-item-description assistant-markdown";
      renderAssistantMarkdown(description, item.description || "Noch keine Beschreibung.");
      const actions = document.createElement("div");
      actions.className = "work-detail-actions";
      actions.append(workActionButton("BEARBEITEN", () => {
        editingWorkItemId = item.id;
        addingToWorkListId = null;
        renderWorkLists();
      }));
      details.append(description, actions);
      row.append(details);
    }
    return row;
  }

  function renderWorkLists() {
    const nodes = workLists.map((workList) => {
      const items = workItems.filter((item) => item.list_id === workList.id);
      const openItems = items.filter((item) => item.status === "open");
      const completedItems = items.filter((item) => item.status === "completed");
      const disclosure = document.createElement("details");
      disclosure.className = "work-list";
      disclosure.dataset.listId = workList.id;
      disclosure.open = openWorkLists.has(workList.id);
      const summary = document.createElement("summary");
      const heading = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = workList.name;
      const count = document.createElement("small");
      count.textContent = `${openItems.length} offen`;
      heading.append(name, count);
      summary.append(heading);
      disclosure.append(summary);
      const removeList = workActionButton("", () => deleteWorkList(workList, items.length));
      removeList.className = "work-delete-list work-delete-action";
      removeList.setAttribute("aria-label", `Arbeitsliste „${workList.name}“ löschen`);
      removeList.title = "Arbeitsliste löschen";
      removeList.append(workDeleteIcon());
      disclosure.append(removeList);
      disclosure.addEventListener("toggle", () => {
        if (disclosure.open) openWorkLists.add(workList.id);
        else openWorkLists.delete(workList.id);
        persistWorkDisclosures("eve.openWorkLists", openWorkLists);
      });
      if (workList.description) {
        const description = document.createElement("p");
        description.className = "work-list-description";
        description.textContent = workList.description;
        disclosure.append(description);
      }
      const openContainer = document.createElement("div");
      openContainer.className = "work-items";
      openContainer.append(...openItems.map(workItemNode));
      if (!openItems.length) {
        const empty = document.createElement("p");
        empty.className = "work-list-empty";
        empty.textContent = "Keine offenen Aufgaben.";
        openContainer.append(empty);
      }
      disclosure.append(openContainer);
      if (addingToWorkListId === workList.id) {
        disclosure.append(workItemForm(null, workList.id, () => {
          addingToWorkListId = null;
          renderWorkLists();
        }));
      } else {
        const add = workActionButton("＋ AUFGABE", () => {
          addingToWorkListId = workList.id;
          editingWorkItemId = null;
          renderWorkLists();
        });
        add.className = "work-add-item";
        disclosure.append(add);
      }
      if (completedItems.length) {
        const completed = document.createElement("details");
        completed.className = "work-completed";
        completed.open = openCompletedLists.has(workList.id);
        const completedSummary = document.createElement("summary");
        completedSummary.textContent = `ERLEDIGT · ${completedItems.length}`;
        completed.append(completedSummary, ...completedItems.map(workItemNode));
        completed.addEventListener("toggle", () => {
          if (completed.open) openCompletedLists.add(workList.id);
          else openCompletedLists.delete(workList.id);
          persistWorkDisclosures("eve.openCompletedWorkLists", openCompletedLists);
        });
        disclosure.append(completed);
      }
      return disclosure;
    });
    elements.workLists.replaceChildren(...nodes);
    window.requestAnimationFrame(sizeWorkDescriptions);
    elements.taskListEmpty.hidden = !showingTasks || workLists.length > 0;
  }

  function workTaskRevision(lists, items) {
    return JSON.stringify({
      lists: lists.map((item) => [item.id, item.name, item.description, item.status, item.updated_at, item.open_count]),
      items: items.map((item) => [item.id, item.list_id, item.title, item.description,
        item.status, item.position, item.updated_at,
        (item.context_links || []).map((link) => [link.id, link.conversation_id,
          link.start_message_id, link.end_message_id, link.label])]),
    });
  }

  async function loadWorkTasks(onlyIfChanged = false) {
    setWorkTaskError();
    const [listData, itemData] = await Promise.all([
      workTaskRequest("/api/work-lists?limit=200", {}, "Arbeitslisten laden"),
      workTaskRequest("/api/work-items?status=all&limit=200", {}, "Arbeitsaufgaben laden"),
    ]);
    const nextLists = Array.isArray(listData.lists) ? listData.lists : [];
    const nextItems = Array.isArray(itemData.items) ? itemData.items : [];
    const nextRevision = workTaskRevision(nextLists, nextItems);
    if (onlyIfChanged && nextRevision === workDataRevision) return false;
    workLists = nextLists;
    workItems = nextItems;
    workDataRevision = nextRevision;
    renderWorkLists();
    return true;
  }

  async function refreshWorkTasksIfVisible() {
    if (!chatOpen || !showingTasks || document.hidden || workMutationBusy || workRefreshBusy
        || workDrag || editingWorkItemId || addingToWorkListId || !elements.newWorkListForm.hidden) return;
    workRefreshBusy = true;
    try {
      await loadWorkTasks(true);
    } catch (error) {
      setWorkTaskError(error.message);
    } finally {
      workRefreshBusy = false;
    }
  }

  async function setPanelView(view) {
    panelView = ["conversations", "schedules", "tasks"].includes(view) ? view : "conversations";
    showingTasks = panelView === "tasks";
    showingSchedules = panelView === "schedules";
    window.localStorage.setItem("eve.panelView", panelView);
    window.localStorage.setItem("eve.showingTasks", String(showingTasks));
    elements.panelTitle.textContent = showingTasks ? "Arbeitsaufgaben" : showingSchedules ? "Zeitpläne" : "Unterhaltungen";
    elements.taskViewToggle.textContent = showingTasks ? "CHATS" : "AUFGABEN";
    elements.scheduleViewToggle.textContent = showingSchedules ? "CHATS" : "ZEITPLÄNE";
    elements.taskViewToggle.setAttribute("aria-pressed", String(showingTasks));
    elements.scheduleViewToggle.setAttribute("aria-pressed", String(showingSchedules));
    elements.conversationList.hidden = panelView !== "conversations";
    elements.conversationListEmpty.hidden = panelView !== "conversations" || conversations.length > 0;
    elements.scheduledTaskView.hidden = !showingSchedules;
    elements.taskList.hidden = !showingTasks;
    elements.taskListEmpty.hidden = !showingTasks || workLists.length > 0;
    if (showingTasks) {
      try { await loadWorkTasks(); } catch (error) { setWorkTaskError(error.message); }
    } else if (showingSchedules) {
      await loadTasks();
    }
  }

  function toggleTaskView(show) {
    const target = typeof show === "boolean" ? (show ? "tasks" : "conversations")
      : (showingTasks ? "conversations" : "tasks");
    return setPanelView(target);
  }

  function toggleScheduleView(show) {
    const target = typeof show === "boolean" ? (show ? "schedules" : "conversations")
      : (showingSchedules ? "conversations" : "schedules");
    return setPanelView(target);
  }

  function toggleConversationPanel(open) {
    if (window.innerWidth < 900) {
      const visible = typeof open === "boolean" ? open : !elements.conversationPanel.classList.contains("open");
      elements.conversationPanel.classList.toggle("open", visible);
      elements.conversationScrim.hidden = !visible;
      elements.conversationToggle.setAttribute("aria-expanded", String(visible));
      if (visible && showingTasks) loadWorkTasks().catch((error) => setWorkTaskError(error.message));
      if (visible && showingSchedules) loadTasks().catch((error) => setDetail(error.message));
      return;
    }
    setSidebarOpen(typeof open === "boolean" ? open : !sidebarOpen);
  }

  function setSidebarOpen(open) {
    sidebarOpen = Boolean(open);
    window.localStorage.setItem("eve.sidebarOpen", String(sidebarOpen));
    document.body.classList.toggle("sidebar-hidden", !sidebarOpen);
    if (!sidebarOpen) elements.conversationPanel.classList.remove("open");
    elements.conversationScrim.hidden = true;
    if (window.innerWidth >= 900) elements.conversationToggle.setAttribute("aria-expanded", String(sidebarOpen));
    elements.conversationToggle.setAttribute(
      "aria-label", sidebarOpen ? "Unterhaltungen und Arbeitsaufgaben ausblenden" : "Unterhaltungen und Arbeitsaufgaben einblenden",
    );
    if (sidebarOpen && showingTasks) loadWorkTasks().catch((error) => setWorkTaskError(error.message));
    if (sidebarOpen && showingSchedules) loadTasks().catch((error) => setDetail(error.message));
    if (window.innerWidth >= 900) applyDesktopChatWidths(desktopChatWidth(), historyWidth());
    else syncCoreLayout();
  }

  function setChatOpen(open) {
    chatOpen = Boolean(open);
    window.localStorage.setItem("eve.chatOpen", String(chatOpen));
    document.body.classList.toggle("chat-open", chatOpen);
    // The logo is moved by a CSS transition, while its neural field is drawn
    // on the full-screen canvas. Keep the canvas' core bounds locked to the
    // moving DOM scene for the complete drawer animation.
    canvasEngine.syncCoreBounds();
    elements.shareToggle.setAttribute("aria-expanded", String(chatOpen));
    elements.shareToggle.setAttribute(
      "aria-label", chatOpen ? "Seitenbereich schließen" : "Seitenbereich öffnen",
    );
    elements.shareToggle.title = chatOpen ? "Seitenbereich schließen" : "Seitenbereich öffnen";
    if (!chatOpen) {
      elements.conversationPanel.classList.remove("open");
      elements.conversationScrim.hidden = true;
    } else {
      setSidebarOpen(sidebarOpen);
    }
    syncIntegratedChatControls();
    if (chatOpen) {
      scrollChatToLatest();
      window.requestAnimationFrame(() => elements.messageText.focus());
    }
  }

  function syncIntegratedChatControls() {
    if (chatOpen) {
      if (elements.ptt.parentElement !== elements.composerVoiceSlot) elements.composerVoiceSlot.append(elements.ptt);
      if (elements.voiceMute.parentElement !== elements.chatActions) elements.chatActions.append(elements.voiceMute);
      if (elements.shareToggle.parentElement !== elements.chatActions) elements.chatActions.append(elements.shareToggle);
      return;
    }
    elements.commandDock.append(elements.voiceMute, elements.ptt, elements.shareToggle);
  }

  async function fetchWithTimeout(url, options = {}, timeout = 12000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function readJsonResponse(response, context = "Antwort") {
    const body = await response.text();
    try {
      return JSON.parse(body);
    } catch (_) {
      const contentType = response.headers.get("Content-Type") || "";
      if (response.status === 404 && !contentType.includes("application/json")) {
        throw new Error("Die Conversation-API ist noch nicht aktiv. Bitte EVE einmal neu starten.");
      }
      throw new Error(`${context} enthielt kein gültiges JSON (HTTP ${response.status}).`);
    }
  }

  function localPresentationLocked() {
    return playingAudio || captureBusy || recorder?.state === "recording";
  }

  async function tick() {
    try {
      const [response, readinessResponse] = await Promise.all([
        fetchWithTimeout("/api/state", { cache: "no-store", headers: auth }, 2500),
        fetchWithTimeout("/health/ready", { cache: "no-store" }, 2500),
      ]);
      const state = await readJsonResponse(response, "EVE-Status");
      if (!response.ok) throw new Error(state.error || `HTTP ${response.status}`);
      const readiness = await readinessResponse.json().catch(() => ({}));
      llmReady = readinessResponse.ok && readiness.llm !== "not_ready" && readiness.ready !== false;
      updatePTT();
      elements.sendMessage.disabled = !llmReady;
      if (!llmReady) {
        setConnection(false, "LOCAL // LLM OFFLINE");
        if (!localPresentationLocked()) {
          showState("offline");
          setDetail("Das lokale Sprachmodell ist nicht erreichbar.");
        }
        return;
      }
      setConnection(true);
      if (!localPresentationLocked()) {
        showState(state.state);
        if (typeof state.detail === "string" && state.detail) setDetail(state.detail);
      }
    } catch (error) {
      llmReady = false;
      updatePTT();
      elements.sendMessage.disabled = true;
      setConnection(false);
      if (!localPresentationLocked()) {
        showState("offline");
        setDetail(error.name === "AbortError" ? "EVE antwortet nicht." : (error.message || "Verbindung unterbrochen."));
      }
    }
  }

  async function stateLoop() {
    await tick();
    window.setTimeout(stateLoop, 500);
  }

  function presentationResource(value, mediaType) {
    if (typeof value !== "string") return "";
    const inline = value.match(/^data:(image|video)\/([a-z0-9.+-]+);base64,([a-z0-9+/=\s]+)$/i);
    if (inline && inline[1].toLowerCase() === mediaType) {
      try {
        const raw = atob(inline[3].replace(/\s/g, ""));
        const bytes = new Uint8Array(raw.length);
        for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
        const objectUrl = URL.createObjectURL(new Blob([bytes], { type: `${inline[1]}/${inline[2]}` }));
        presentationObjectUrls.push(objectUrl);
        return objectUrl;
      } catch (_) { return ""; }
    }
    try {
      const url = new URL(value, window.location.href);
      const allowed = ["http:", "https:", "blob:"];
      if (url.origin === window.location.origin || allowed.includes(url.protocol)) return url.href;
    } catch (_) { /* rejected below */ }
    return "";
  }

  function releasePresentationResources() {
    for (const objectUrl of presentationObjectUrls) URL.revokeObjectURL(objectUrl);
    presentationObjectUrls = [];
  }

  async function loadPresentationMedia(media, source, container, generation, expectedMediaType) {
    if (!source) throw new Error("Die Medienressource hat keine gültige Adresse.");
    const url = new URL(source, window.location.href);
    if (url.origin !== window.location.origin && url.protocol !== "blob:") {
      media.src = source;
      if (expectedMediaType === "image") makeImageExpandable(media, source, elements.presentationTitle.textContent || "eve-bild");
      return;
    }
    media.setAttribute("aria-busy", "true");
    try {
      const response = await fetchWithTimeout(url.href, { cache: "no-store", headers: auth }, 12000);
      if (!response.ok) throw new Error(`Medienabruf fehlgeschlagen (HTTP ${response.status}).`);
      const blob = await response.blob();
      const receivedType = (blob.type || "unbekannt").toLowerCase().split(";", 1)[0].trim();
      if (!receivedType.startsWith(`${expectedMediaType}/`)) {
        throw new Error(`Unerwarteter Medieninhalt: ${receivedType}.`);
      }
      if (generation !== presentationRenderGeneration || !media.isConnected) return;
      if (expectedMediaType === "image" && typeof window.createImageBitmap === "function") {
        const bitmap = await window.createImageBitmap(blob);
        if (generation !== presentationRenderGeneration || !media.isConnected) {
          bitmap.close?.();
          return;
        }
        const objectUrl = URL.createObjectURL(blob);
        presentationObjectUrls.push(objectUrl);
        const canvas = document.createElement("canvas");
        canvas.className = "presentation-bitmap";
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", media.alt || "Präsentationsbild");
        canvas.getContext("2d").drawImage(bitmap, 0, 0);
        bitmap.close?.();
        makeImageExpandable(canvas, objectUrl, elements.presentationTitle.textContent || "eve-bild");
        media.replaceWith(canvas);
        return;
      }
      const objectUrl = URL.createObjectURL(blob);
      presentationObjectUrls.push(objectUrl);
      const loaded = new Promise((resolve, reject) => {
        media.addEventListener("load", resolve, { once: true });
        media.addEventListener("loadeddata", resolve, { once: true });
        media.addEventListener("error", () => reject(new Error("Der Browser konnte die Medienressource nicht dekodieren.")), { once: true });
      });
      media.src = objectUrl;
      await loaded;
      if (generation !== presentationRenderGeneration || !media.isConnected) return;
      if (media.tagName === "IMG" && media.naturalWidth > 0 && media.naturalHeight > 0) {
        media.style.aspectRatio = `${media.naturalWidth} / ${media.naturalHeight}`;
      }
      media.dataset.loaded = "true";
      if (expectedMediaType === "image") makeImageExpandable(media, objectUrl, elements.presentationTitle.textContent || "eve-bild");
    } finally {
      media.removeAttribute("aria-busy");
    }
  }

  function normalizedDownloadName(value) {
    const cleaned = String(value || "eve-bild").trim().replace(/[\\/:*?"<>|]+/g, "-");
    return /\.[a-z0-9]{2,5}$/i.test(cleaned) ? cleaned : `${cleaned || "eve-bild"}.png`;
  }

  function openImageViewer(source, filename = "eve-bild") {
    if (!source) return;
    elements.imageViewerImage.src = source;
    elements.imageViewerTitle.textContent = filename || "Bild in Originalgröße";
    elements.imageViewerDownload.href = source;
    elements.imageViewerDownload.download = normalizedDownloadName(filename);
    elements.imageViewer.hidden = false;
    document.body.classList.add("image-viewer-open");
    elements.imageViewerStage.scrollTo(0, 0);
    elements.imageViewerClose.focus({ preventScroll: true });
  }

  function closeImageViewer() {
    elements.imageViewer.hidden = true;
    elements.imageViewerImage.removeAttribute("src");
    elements.imageViewerDownload.removeAttribute("href");
    document.body.classList.remove("image-viewer-open");
  }

  function makeImageExpandable(image, source, filename) {
    image.tabIndex = 0;
    image.classList.add("expandable-image");
    image.title = "In Originalgröße öffnen";
    image.addEventListener("click", () => openImageViewer(source, filename));
    image.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openImageViewer(source, filename);
      }
    });
  }

  function presentationLayout(element, layout = "vertical") {
    element.classList.add("presentation-layout", `layout-${["horizontal", "grid"].includes(layout) ? layout : "vertical"}`);
  }

  function renderPresentationComponent(component, generation) {
    const node = document.createElement(component.type === "divider" ? "hr" : "article");
    node.className = `presentation-component component-${component.type}`;
    if (component.label) {
      const label = document.createElement("span");
      label.className = "component-label";
      label.textContent = component.label;
      node.append(label);
    }
    if (["text", "markdown"].includes(component.type)) {
      const content = document.createElement(component.type === "markdown" ? "pre" : "p");
      content.textContent = component.content || "";
      node.append(content);
    } else if (["metric", "badge"].includes(component.type)) {
      const value = document.createElement("strong");
      value.textContent = String(component.value ?? component.content ?? "");
      node.append(value);
    } else if (component.type === "progress") {
      const progress = document.createElement("progress");
      progress.max = 100;
      progress.value = Number(component.value);
      progress.textContent = `${component.value}%`;
      node.append(progress);
    } else if (["image", "video"].includes(component.type)) {
      const source = presentationResource(component.content, component.type);
      const media = document.createElement(component.type);
      if (component.type === "image") media.alt = component.label || "";
      else media.controls = true;
      node.append(media);
      loadPresentationMedia(media, source, node, generation, component.type).catch((error) => {
        if (generation !== presentationRenderGeneration || !node.isConnected) return;
        const message = document.createElement("p");
        message.className = "component-media-error";
        message.textContent = error.message || "Die Medienressource konnte nicht geladen werden.";
        node.append(message);
      });
    } else if (component.type === "list") {
      const list = document.createElement("ul");
      list.className = "component-list";
      for (const item of component.items || []) {
        const entry = document.createElement("li");
        if (item && typeof item === "object" && !Array.isArray(item)
            && Object.hasOwn(item, "label") && Object.hasOwn(item, "value")) {
          entry.className = "component-list-row";
          const label = document.createElement("span");
          label.className = "component-list-label";
          label.textContent = String(item.label);
          const value = document.createElement("span");
          value.className = "component-list-value";
          value.textContent = item.value == null ? "—" : String(item.value);
          entry.append(label, value);
        } else if (item == null || ["string", "number", "boolean"].includes(typeof item)) {
          entry.className = "component-list-item";
          entry.textContent = item == null ? "—" : String(item);
        } else {
          entry.className = "component-list-invalid";
          entry.textContent = "Nicht unterstützter Listeneintrag";
        }
        list.append(entry);
      }
      node.append(list);
    } else if (component.type === "table") {
      const table = document.createElement("table");
      const columns = component.columns || [];
      if (columns.length) {
        const head = table.createTHead().insertRow();
        for (const column of columns) head.append(Object.assign(document.createElement("th"), { textContent: String(column) }));
      }
      const body = table.createTBody();
      for (const row of component.rows || []) {
        const tr = body.insertRow();
        const cells = Array.isArray(row) ? row : columns.map((column) => row?.[column]);
        for (const cell of cells) tr.insertCell().textContent = String(cell ?? "");
      }
      node.append(table);
    } else if (component.type === "chart") {
      const chart = document.createElement("div");
      chart.className = "component-chart";
      const points = (component.data || []).map((point, index) => ({
        label: point?.label ?? String(index + 1), value: Number(point?.value ?? point),
      })).filter((point) => Number.isFinite(point.value));
      const max = Math.max(1, ...points.map((point) => Math.abs(point.value)));
      for (const point of points) {
        const bar = document.createElement("div");
        bar.style.setProperty("--value", `${Math.max(0, Math.abs(point.value) / max * 100)}%`);
        bar.textContent = `${point.label}: ${point.value}`;
        chart.append(bar);
      }
      node.append(chart);
    } else if (component.type === "container") {
      presentationLayout(node, component.layout);
      for (const child of component.components || []) node.append(renderPresentationComponent(child, generation));
    }
    return node;
  }

  function renderPresentation(state) {
    releasePresentationResources();
    presentationRenderGeneration += 1;
    const generation = presentationRenderGeneration;
    presentationRevision = Number(state.revision ?? presentationRevision);
    const active = Boolean(state.active && state.presentation);
    elements.presentationView.hidden = !active;
    document.body.classList.toggle("presentation-open", active);
    syncAvatarCloudVisibility();
    if (!active) return;
    if (nerdMode) setNerdMode(false);
    elements.presentationTitle.textContent = state.presentation.title || "Präsentation";
    elements.presentationComponents.replaceChildren();
    presentationLayout(elements.presentationComponents, state.presentation.layout);
    for (const component of state.presentation.components || []) {
      elements.presentationComponents.append(renderPresentationComponent(component, generation));
    }
  }

  async function loadPresentation() {
    const response = await fetchWithTimeout("/api/presentation", { cache: "no-store", headers: auth }, 2500);
    const state = await readJsonResponse(response, "Präsentation");
    if (!response.ok) throw new Error(state.error || "Präsentation konnte nicht geladen werden.");
    if (Number(state.revision ?? 0) !== presentationRevision) renderPresentation(state);
  }

  async function presentationLoop() {
    try { await loadPresentation(); } catch (_) { /* state loop reports connectivity */ }
    window.setTimeout(presentationLoop, 500);
  }

  function createSpectrum() {
    const fragment = document.createDocumentFragment();
    for (let index = 0; index < 56; index += 1) {
      const bar = document.createElement("i");
      bar.className = "spectrum-bar";
      bar.style.setProperty("--angle", `${(index / 56) * 360}deg`);
      bar.style.setProperty("--level", "0");
      fragment.append(bar);
    }
    elements.spectrum.replaceChildren(fragment);
  }

  createSpectrum();
  const spectrumBars = [...elements.spectrum.children];

  async function unlockAudio() {
    const AudioEngine = window.AudioContext || window.webkitAudioContext;
    if (!AudioEngine) throw new Error("Dieser Browser unterstützt keine Audioausgabe.");
    audioCtx ??= new AudioEngine();
    if (audioCtx.state !== "running") await audioCtx.resume();
    return audioCtx;
  }

  function getOutputAnalyser() {
    if (!audioCtx) return null;
    if (!outputAnalyser) {
      outputAnalyser = audioCtx.createAnalyser();
      outputAnalyser.fftSize = 256;
      outputAnalyser.smoothingTimeConstant = 0.76;
      outputAnalyser.connect(audioCtx.destination);
    }
    return outputAnalyser;
  }

  function updatePTT() {
    const unavailable = !llmReady || requestBusy || captureBusy || audioQueued > 0 || playingAudio;
    // Disabling a pressed native button can make touch browsers drop pointer
    // capture before pointerup. Keep the active control enabled until release.
    elements.ptt.disabled = unavailable && !pressActive;
  }

  function updateVoiceMute() {
    elements.voiceMute.setAttribute("aria-pressed", String(voiceMuted));
    elements.voiceMute.setAttribute(
      "aria-label",
      voiceMuted ? "EVEs Sprachausgabe einschalten" : "EVEs Sprachausgabe stummschalten",
    );
    elements.voiceMute.title = voiceMuted ? "Sprachausgabe einschalten" : "Sprachausgabe stummschalten";
    elements.voiceMute.classList.toggle("muted", voiceMuted);
  }

  function toggleVoiceMute() {
    voiceMuted = !voiceMuted;
    window.localStorage.setItem("eve.voiceMuted", String(voiceMuted));
    if (voiceMuted && activeOutputSource) {
      try { activeOutputSource.stop(); } catch (_) { /* already stopped */ }
    }
    updateVoiceMute();
  }

  async function waitUntilRecordingStops() {
    while (captureBusy || recorder?.state === "recording") {
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
  }

  function cancelTurnAudio(turnId) {
    if (!turnId) return;
    cancelledAudioTurns.add(turnId);
    if (activeOutputTurnId === turnId && activeOutputSource) {
      try { activeOutputSource.stop(); } catch (_) { /* already stopped */ }
    }
  }

  async function playReply(bytes, turnId = null) {
    if (voiceMuted || (turnId && cancelledAudioTurns.has(turnId))) return;
    await waitUntilRecordingStops();
    if (voiceMuted || (turnId && cancelledAudioTurns.has(turnId))) return;
    await unlockAudio();
    const bufferData = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const buffer = await audioCtx.decodeAudioData(bufferData);
    const source = audioCtx.createBufferSource();
    getOutputAnalyser();
    source.buffer = buffer;
    source.connect(outputAnalyser);
    activeOutputSource = source;
    activeOutputTurnId = turnId;
    playingAudio = true;
    updatePTT();
    showState("speaking");
    try {
      await new Promise((resolve, reject) => {
        source.onended = resolve;
        source.onerror = reject;
        try {
          source.start(0);
        } catch (error) {
          reject(error);
        }
      });
    } finally {
      try { source.disconnect(); } catch (_) { /* already disconnected */ }
      if (activeOutputSource === source) activeOutputSource = null;
      if (activeOutputTurnId === turnId) activeOutputTurnId = null;
      playingAudio = false;
      updatePTT();
      showState("idle");
      flushNotifications();
    }
  }

  function queueReply(bytes, turnId = null) {
    if (voiceMuted || (turnId && cancelledAudioTurns.has(turnId))) return Promise.resolve();
    if (!turnId && audioQueued >= MAX_AUDIO_QUEUE) {
      return Promise.reject(new Error("Zu viele Audioausgaben warten."));
    }
    audioQueued += 1;
    updatePTT();
    const playback = audioQueue.then(() => playReply(bytes, turnId));
    audioQueue = playback.catch(() => {}).then(() => {
      audioQueued = Math.max(0, audioQueued - 1);
      updatePTT();
    });
    return playback;
  }

  function decodeAudio(value) {
    const raw = atob(value);
    const bytes = new Uint8Array(raw.length);
    for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
    return bytes;
  }

  function audioError(prefix, error) {
    setDetail(`${prefix}: ${error.message || error}`);
  }

  async function followTurnCompletion(data) {
    if (data.audio_wav_base64) {
      await queueReply(decodeAudio(data.audio_wav_base64));
      return;
    }
    if (!data.turn_id || !data.postprocess_url) return;
    startPresentationTurnStatus(data);
    let presentationSettled = !data.presentation_pending;
    const deadline = Date.now() + 240000;
    try {
      while (Date.now() < deadline) {
        const response = await fetchWithTimeout(data.postprocess_url, {
          cache: "no-store", headers: auth,
        }, 5000);
        const result = await readJsonResponse(response, "Turn-Nachbearbeitung");
        if (!response.ok) throw new Error(result.error || "Turn-Nachbearbeitung konnte nicht gelesen werden.");
        if (result.turn_id !== data.turn_id) throw new Error("Turn-Korrelation ist ungültig.");
        const presentationStatus = result.presentation?.status;
        if (!presentationSettled && presentationStatus && presentationStatus !== "pending") {
          presentationSettled = true;
          try {
            if (presentationStatus === "success" && result.presentation.action !== "none") {
              await loadPresentation();
            } else if (presentationStatus === "error" && latestVisibleTurnId === data.turn_id) {
              setDetail("Textantwort ist da; die Bildschirmdarstellung ist fehlgeschlagen.");
            }
          } finally {
            clearPresentationTurnStatus(data.turn_id);
          }
        }
        if (result.status === "complete") {
          if (result.audio?.status === "success" && result.audio.audio_wav_base64) {
            await queueReply(decodeAudio(result.audio.audio_wav_base64));
          } else if (result.audio?.status === "error" && latestVisibleTurnId === data.turn_id) {
            setDetail("Textantwort ist da; Audio konnte nicht erzeugt werden.");
          }
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
      throw new Error("Turn-Nachbearbeitung hat das Zeitlimit überschritten.");
    } finally {
      clearPresentationTurnStatus(data.turn_id);
    }
  }

  function busyForNotifications() {
    return requestBusy || captureBusy || playingAudio || recorder?.state === "recording";
  }

  async function presentNotification(item) {
    setReply(item.message || "Erinnerung");
    if (item.persisted && item.conversation_id === activeConversationId) {
      await selectConversation(activeConversationId, false, true);
    } else if (!item.persisted) {
      appendChatMessage({ role: "assistant", content: item.message || "Erinnerung", created_at: new Date().toISOString() });
    } else {
      await loadConversations(activeConversationId);
    }
    setDetail(item.kind === "scheduled_result" ? "ZEITPLAN // AUSGEFÜHRT" : "ERINNERUNG // JETZT");
    renderArtifacts([]);
    renderSources([]);
    if (item.audio_wav_base64) {
      queueReply(decodeAudio(item.audio_wav_base64)).catch((error) => {
        audioError("Erinnerung ist da; Audio konnte nicht abgespielt werden", error);
      });
    }
  }

  function flushNotifications() {
    if (busyForNotifications() || notificationPresenting || !notificationBacklog.length) return;
    notificationPresenting = true;
    presentNotification(notificationBacklog.shift()).catch((error) => {
      setDetail(error.message);
    }).finally(() => {
      notificationPresenting = false;
      flushNotifications();
    });
  }

  async function checkNotifications() {
    if (notificationBusy) return;
    notificationBusy = true;
    try {
      const response = await fetchWithTimeout("/api/notifications", {
        method: "POST",
        cache: "no-store",
        headers: auth,
      }, 210000);
      if (!response.ok) return;
      const data = await readJsonResponse(response, "Benachrichtigungen");
      for (const item of data.notifications || []) notificationBacklog.push(item);
      flushNotifications();
    } catch (error) {
      if (error.name !== "AbortError") console.debug("notification poll failed", error);
    } finally {
      notificationBusy = false;
    }
  }

  window.setInterval(checkNotifications, 1500);

  function renderArtifacts(items = []) {
    const links = items.flatMap((item) => {
      if (!item || typeof item.base64 !== "string") return [];
      const link = document.createElement("a");
      const mime = typeof item.mime === "string" && /^[\w.+-]+\/[\w.+-]+$/.test(item.mime)
        ? item.mime
        : "application/octet-stream";
      link.href = `data:${mime};base64,${item.base64}`;
      link.download = item.filename || "eve-download.txt";
      link.textContent = item.filename || "DOWNLOAD";
      return [link];
    });
    elements.downloads.replaceChildren(...links);
  }

  function safeSourceUrl(value) {
    try {
      const url = new URL(value, window.location.href);
      return url.protocol === "http:" || url.protocol === "https:" ? url : null;
    } catch (_) {
      return null;
    }
  }

  function renderSources(items = []) {
    const links = items.flatMap((item, index) => {
      const url = safeSourceUrl(item?.url);
      if (!url) return [];
      const link = document.createElement("a");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `[${index + 1}] ${item.title || url.hostname}`;
      link.title = item.url;
      return [link];
    });
    elements.sources.replaceChildren(...links);
  }

  function openComposer() {
    elements.composer.hidden = false;
    elements.composerScrim.hidden = true;
    setChatOpen(true);
    window.requestAnimationFrame(() => elements.messageText.focus());
  }

  function closeComposer({ reset = false, hide = false } = {}) {
    if (reset) {
      elements.messageText.value = "";
      resizeMessageInput();
      attachedImages = [];
      renderPreviews();
    }
    if (hide) {
      setChatOpen(false);
      elements.shareToggle.focus({ preventScroll: true });
    }
  }

  function resizeMessageInput() {
    elements.messageText.style.height = "auto";
    const minimum = 40;
    const limit = Math.max(minimum, Math.min(144, (window.visualViewport?.height || window.innerHeight) * .2));
    const height = Math.max(minimum, Math.min(elements.messageText.scrollHeight, limit));
    elements.messageText.style.height = `${height}px`;
    elements.messageText.style.overflowY = elements.messageText.scrollHeight > limit ? "auto" : "hidden";
  }

  function renderPreviews() {
    const previews = attachedImages.map((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "preview";
      button.setAttribute("aria-label", `${item.name || `Screenshot ${index + 1}`} entfernen`);
      const image = document.createElement("img");
      image.src = item.data;
      image.alt = "";
      button.append(image);
      button.addEventListener("click", () => {
        attachedImages.splice(index, 1);
        renderPreviews();
      });
      return button;
    });
    elements.previews.replaceChildren(...previews);
  }

  function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error || new Error("Bild konnte nicht gelesen werden."));
      reader.readAsDataURL(file);
    });
  }

  async function addImages(files) {
    for (const file of [...files]) {
      if (!SAFE_IMAGE_TYPES.has(file.type)) continue;
      if (attachedImages.length >= MAX_IMAGES) {
        setDetail("Maximal vier Screenshots gleichzeitig.");
        break;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        setDetail(`${file.name} ist größer als 5 MB.`);
        continue;
      }
      const total = attachedImages.reduce((sum, item) => sum + item.size, 0);
      if (total + file.size > MAX_TOTAL_IMAGE_BYTES) {
        setDetail("Die Screenshots sind zusammen zu groß. Bitte ein Bild entfernen.");
        break;
      }
      attachedImages.push({ data: await readFileAsDataURL(file), name: file.name, size: file.size });
    }
    renderPreviews();
  }

  function configEntriesControl(field) {
    const control = document.createElement("div");
    control.className = "config-entry-list";
    const entries = document.createElement("div");
    const dirty = () => control.dispatchEvent(new Event("input", { bubbles: true }));
    const addRow = (value = {}) => {
      const row = document.createElement("div");
      row.className = "config-entry-row";
      const input = (key, placeholder, initial) => {
        const element = document.createElement(key === "arguments" ? "textarea" : "input");
        element.dataset.entryKey = key;
        element.placeholder = placeholder;
        element.setAttribute("aria-label", placeholder);
        element.value = initial ?? "";
        row.append(element);
        return element;
      };
      if (field.type === "key_value") {
        input("key", "Variable", value.key);
        input("value", "Wert", value.value);
      } else {
        input("tool", "Natives Werkzeug", value.tool);
        input("arguments", "Werkzeugargumente (JSON)", JSON.stringify(value.arguments || {}, null, 2));
        input("if_exists", "Nur wenn Datei existiert (optional)", value.if_exists);
      }
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "eve-button eve-button--ghost";
      remove.textContent = "Entfernen";
      remove.addEventListener("click", () => { row.remove(); dirty(); });
      row.append(remove);
      entries.append(row);
    };
    const initial = field.type === "key_value"
      ? Object.entries(field.value || {}).map(([key, value]) => ({ key, value })) : field.value || [];
    initial.forEach(addRow);
    const add = document.createElement("button");
    add.type = "button";
    add.className = "eve-button eve-button--ghost";
    add.textContent = field.type === "key_value" ? "Variable hinzufügen" : "Aufruf hinzufügen";
    add.addEventListener("click", () => { addRow(); dirty(); });
    control.append(entries, add);
    return control;
  }

  function configControl(field) {
    let control;
    if (field.choices) {
      control = document.createElement("div");
      control.dataset.configChoices = "true";
      control.className = "config-choices";
      control.setAttribute("role", "group");
      control.setAttribute("aria-label", field.label);
      const selectionCount = document.createElement("small");
      selectionCount.className = "config-choices-count";
      selectionCount.setAttribute("aria-live", "polite");
      const updateSelectionCount = () => {
        const selected = control.querySelectorAll('input[type="checkbox"]:checked').length;
        selectionCount.textContent = `${selected} von ${field.choices.length} ausgewählt`;
      };
      control.append(selectionCount);
      const sortedChoices = [...field.choices].sort((a, b) => a.label.localeCompare(b.label, "de", { sensitivity: "base", numeric: true }));
      for (const choice of sortedChoices) {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = choice.value;
        checkbox.checked = (field.value || []).includes(choice.value);
        checkbox.disabled = Boolean(field.locked);
        checkbox.addEventListener("change", updateSelectionCount);
        const text = document.createElement("span");
        text.textContent = choice.label;
        label.append(checkbox, text);
        control.append(label);
      }
      updateSelectionCount();
    } else if (["key_value", "mcp_calls"].includes(field.type)) {
      control = configEntriesControl(field);
    } else if (field.type === "json") {
      control = document.createElement("textarea");
      control.rows = 16;
      control.spellcheck = false;
    } else if (["path_list", "string_list"].includes(field.type)) {
      control = document.createElement("textarea");
      control.rows = 5;
      control.placeholder = field.placeholder || (field.type === "path_list" ? "/home/name/Downloads\n/mnt/projekte" : "Ein Eintrag pro Zeile");
    } else if (field.type === "select") {
      control = document.createElement("select");
      for (const value of field.options || []) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        control.append(option);
      }
    } else {
      control = document.createElement("input");
      control.type = field.type === "boolean" ? "checkbox" : ["integer", "number"].includes(field.type) ? "number" : field.type === "secret" ? "password" : field.type === "url" ? "url" : "text";
      if (field.min !== undefined) control.min = field.min;
      if (field.max !== undefined) control.max = field.max;
      if (field.step !== undefined) control.step = field.step;
      else if (field.type === "number") control.step = "any";
      if (field.type === "secret") control.placeholder = field.configured ? "Gesetzt – leer lassen zum Beibehalten" : "Neuen Wert setzen";
    }
    control.dataset.configField = field.id;
    control.dataset.configType = field.type;
    control.disabled = Boolean(field.locked);
    if (field.locked) control.title = "Dieser Wert wird außerhalb von EVE durch die Umgebung vorgegeben.";
    if (field.type === "boolean") control.checked = Boolean(field.value);
    else if (["path_list", "string_list"].includes(field.type)) control.value = (field.value || []).join("\n");
    else if (field.type === "json") control.value = JSON.stringify(field.value ?? {}, null, 2);
    else if (field.type !== "secret") control.value = field.value ?? "";
    return control;
  }

  function storedConfigSections() {
    try {
      const stored = JSON.parse(window.localStorage.getItem("eve.openConfigSections") || "[]");
      return new Set(Array.isArray(stored) ? stored.filter((item) => typeof item === "string") : []);
    } catch (_) {
      return new Set();
    }
  }

  function configSectionIcon(sectionId) {
    const paths = {
      home_assistant: ["M3.5 11.5 12 4l8.5 7.5", "M5.5 10v10h13V10", "M9 20v-6h6v6"],
      llm: ["M8 6.5A3 3 0 0 1 14 7v1a3 3 0 0 1 2 5.2V15a3 3 0 0 1-3 3h-1", "M8 6.5A3 3 0 0 0 5 9v1.2A3 3 0 0 0 6 16v.5A2.5 2.5 0 0 0 8.5 19H12V5"],
      speech_to_text: ["M4 12h2l1.5-5 3 10 3-12 3 14 1.5-7H20", "M5 21h14"],
      text_to_speech: ["M4 10v4h4l5 4V6l-5 4H4", "M16 9a4 4 0 0 1 0 6", "M18.5 6.5a7.5 7.5 0 0 1 0 11"],
      web: ["M3 12h18", "M12 3a14 14 0 0 1 0 18", "M12 3a14 14 0 0 0 0 18", "M4.5 7.5h15M4.5 16.5h15"],
      nova_maintenance: ["M14.5 6.5a4 4 0 0 0-5 5L4 17l3 3 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-3-3z", "M17 4v4M15 6h4"],
      conversation: ["M12 21a9 9 0 1 0-9-9", "M12 7v5l3 2", "M3 17v4h4"],
      shell: ["M5 6l5 6-5 6", "M12 18h7"],
      local_files: ["M3.5 6.5h6l2 2h9v10h-17z", "M8 13h8M8 16h5"],
    };
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("config-section-icon");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    for (const data of paths[sectionId] || ["M5 7h14M5 12h14M5 17h14", "M8 5v4M16 10v4M11 15v4"]) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", data);
      svg.append(path);
    }
    return svg;
  }

  function closeConfigHelp() {
    if (configHelpAnchor) configHelpAnchor.setAttribute("aria-expanded", "false");
    configHelpAnchor = null;
    elements.configHelpPopover.hidden = true;
  }

  function positionConfigHelp() {
    if (!configHelpAnchor || elements.configHelpPopover.hidden || !configHelpAnchor.isConnected) return;
    const margin = 10;
    const gap = 8;
    const anchor = configHelpAnchor.getBoundingClientRect();
    const popover = elements.configHelpPopover;
    popover.style.left = "0px";
    popover.style.top = "0px";
    const bounds = popover.getBoundingClientRect();
    let left = anchor.left;
    let top = anchor.bottom + gap;
    if (left + bounds.width > window.innerWidth - margin) left = window.innerWidth - bounds.width - margin;
    if (top + bounds.height > window.innerHeight - margin) top = anchor.top - bounds.height - gap;
    left = Math.max(margin, left);
    top = Math.max(margin, Math.min(top, window.innerHeight - bounds.height - margin));
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  function configDisplayValue(value) {
    if (value === true) return "aktiviert";
    if (value === false) return "deaktiviert";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "keine";
    if (value === "") return "leer";
    return String(value ?? "nicht gesetzt");
  }

  function openConfigHelp(button, field) {
    if (configHelpAnchor === button && !elements.configHelpPopover.hidden) {
      closeConfigHelp();
      return;
    }
    const help = field.help || CONFIG_HELP[field.id] || { title: field.label, text: [field.description || "Für diese Einstellung ist noch keine Detailbeschreibung hinterlegt."] };
    closeConfigHelp();
    configHelpAnchor = button;
    button.setAttribute("aria-expanded", "true");
    elements.configHelpTitle.textContent = help.title;
    elements.configHelpPopover.dataset.helpContext = field.help ? "HILFE // LERNEN" : "HILFE // EINSTELLUNG";
    const content = document.createDocumentFragment();
    for (const paragraph of help.text || []) {
      const node = document.createElement("p");
      node.textContent = paragraph;
      content.append(node);
    }
    if (help.options?.length) {
      const list = document.createElement("ul");
      for (const option of help.options) {
        const item = document.createElement("li");
        item.textContent = option;
        list.append(item);
      }
      content.append(list);
    }
    if (!field.hide_facts) {
      const facts = document.createElement("dl");
      facts.className = "config-help-facts";
      const addFact = (label, value) => {
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = label;
        detail.textContent = value;
        facts.append(term, detail);
      };
      if (field.type !== "secret") {
        addFact("Aktuell wirksam", configDisplayValue(field.value));
        addFact("EVE-Standard", configDisplayValue(field.default));
      }
      addFact("Änderung", field.restart_required ? "nach einem EVE-Neustart wirksam" : "sofort wirksam");
      addFact("Quelle", field.source || "unbekannt");
      if (field.min != null || field.max != null) {
        addFact("Wertebereich", `${field.min ?? "offen"} bis ${field.max ?? "offen"}`);
      }
      if (field.options?.length) addFact("Zulässige Werte", field.options.join(", "));
      if (field.locked) addFact("Bearbeitung", "hier gesperrt, weil die Umgebung den Wert vorgibt");
      content.append(facts);
    }
    elements.configHelpContent.replaceChildren(content);
    elements.configHelpPopover.hidden = false;
    positionConfigHelp();
  }

  function homeAssistantInventoryAction() {
    const panel = document.createElement("div");
    panel.className = "config-provider-action";
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = "Entitäten kennenlernen";
    const description = document.createElement("small");
    description.textContent = "Liest Home Assistant ohne Geräteaktion und aktualisiert belegte Entitäten im Memory.";
    copy.append(title, description);
    const controls = document.createElement("div");
    controls.className = "config-provider-action-controls";
    const status = document.createElement("span");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "eve-button eve-button--ghost";
    button.textContent = "ENTITÄTEN ENTDECKEN";
    button.title = "Home Assistant rein lesend inventarisieren";
    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = "Inventur läuft …";
      try {
        const response = await fetchWithTimeout("/api/home-assistant/inventory", {
          method: "POST", headers: auth,
        }, 60000);
        const data = await readJsonResponse(response, "Home-Assistant-Inventur");
        if (!response.ok) throw new Error(data.error || "Inventur konnte nicht abgeschlossen werden.");
        const counts = data.inventory?.counts || {};
        status.textContent = `${counts.total ?? 0} Entitäten · ${counts.created ?? 0} neu · ${counts.updated ?? 0} geändert · ${counts.retired ?? 0} entfernt`;
        window.dispatchEvent(new Event("eve:home-assistant-inventory-updated"));
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
    controls.append(status, button);
    panel.append(copy, controls);
    return panel;
  }

  function homeAssistantPolicyAction() {
    const panel = document.createElement("section");
    panel.className = "config-memory-policy";
    const heading = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = "Bereiche bei Sammelaktionen";
    const description = document.createElement("small");
    description.textContent = "Ausgewählte Areas werden bei nicht ausdrücklich benannten Sammel-Schreibaufträgen ausgelassen. Direkt genannte Geräte und Bereiche bleiben verwendbar.";
    heading.append(title, description);
    const status = document.createElement("p");
    status.className = "config-memory-policy-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const areas = document.createElement("div");
    areas.className = "config-memory-policy-areas";
    const controls = document.createElement("div");
    controls.className = "config-provider-action-controls";
    const save = document.createElement("button");
    save.type = "button";
    save.className = "eve-button eve-button--ghost";
    save.textContent = "REGEL IM MEMORY SPEICHERN";
    save.disabled = true;
    controls.append(save);
    panel.append(heading, status, areas, controls);

    let initial = [];
    const selected = () => [...areas.querySelectorAll("input[type=checkbox]:checked")]
      .map((control) => control.value).sort((left, right) => left.localeCompare(right, "de"));
    const updateDirty = () => {
      save.disabled = JSON.stringify(selected()) === JSON.stringify(initial);
    };
    const render = (data) => {
      areas.replaceChildren();
      for (const item of data.areas || []) {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = item.area;
        checkbox.checked = Boolean(item.excluded);
        checkbox.addEventListener("change", updateDirty);
        const copy = document.createElement("span");
        const name = document.createElement("strong");
        name.textContent = item.area;
        const meta = document.createElement("small");
        meta.textContent = `${item.entity_count} Entitäten · ${item.domain_count} Domains`;
        copy.append(name, meta);
        label.append(checkbox, copy);
        areas.append(label);
      }
      initial = selected();
      save.disabled = true;
      const claim = data.policy?.claim_id;
      status.textContent = claim
        ? `${initial.length} Bereich(e) ausgeschlossen · als Memory-Policy gespeichert`
        : "Noch keine Bereichsregel gespeichert.";
      if (!(data.areas || []).length) status.textContent = "Zuerst eine Home-Assistant-Inventur durchführen.";
    };
    const load = async () => {
      status.textContent = "Memory-Policy wird gelesen …";
      const response = await fetchWithTimeout("/api/home-assistant/policy", { cache: "no-store", headers: auth });
      const data = await readJsonResponse(response, "Home-Assistant-Bereichsregel");
      if (!response.ok) throw new Error(data.error || "Bereichsregel konnte nicht gelesen werden.");
      render(data);
    };
    save.addEventListener("click", async () => {
      save.disabled = true;
      status.textContent = "Bereichsregel wird im Memory gespeichert …";
      try {
        const response = await fetchWithTimeout("/api/home-assistant/policy", {
          method: "PATCH", headers: { "Content-Type": "application/json", ...auth },
          body: JSON.stringify({ excluded_areas: selected() }),
        });
        const data = await readJsonResponse(response, "Home-Assistant-Bereichsregel");
        if (!response.ok) throw new Error(data.error || "Bereichsregel konnte nicht gespeichert werden.");
        render(data);
      } catch (error) {
        status.textContent = error.message;
        save.disabled = false;
      }
    });
    window.addEventListener("eve:home-assistant-inventory-updated", () => {
      if (panel.isConnected) load().catch((error) => { status.textContent = error.message; });
    }, { once: true });
    load().catch((error) => { status.textContent = error.message; });
    return panel;
  }

  function downloadTrainingPackage(packageData) {
    const provider = String(packageData.provider || "provider").replace(/[^a-z0-9_-]+/gi, "-");
    const kind = String(packageData.kind || "training").replace(/[^a-z0-9_-]+/gi, "-");
    const locale = String(packageData.locale || "und").replace(/[^a-z0-9_-]+/gi, "-");
    const blob = new Blob([`${JSON.stringify(packageData, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `eve-${provider}-${kind}-${locale}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function trainingPackagesSection(openSections) {
    const card = document.createElement("details");
    card.className = "config-section";
    card.dataset.configSection = "training_packages";
    card.open = openSections.has("training_packages");
    card.addEventListener("toggle", () => {
      if (card.open) openSections.add("training_packages");
      else openSections.delete("training_packages");
      window.localStorage.setItem("eve.openConfigSections", JSON.stringify([...openSections]));
    });
    const summary = document.createElement("summary");
    const heading = document.createElement("span");
    heading.className = "config-section-heading";
    const title = document.createElement("span");
    title.textContent = "Community-Training";
    heading.append(configSectionIcon("training_packages"), title);
    const count = document.createElement("small");
    count.textContent = "portable Memory-Pakete";
    summary.append(heading, count);
    const body = document.createElement("div");
    body.className = "config-section-body training-packages";
    const intro = document.createElement("p");
    intro.className = "training-package-intro";
    intro.textContent = "Generisches Wissen einzeln prüfen, importieren und teilen. Lokale Geräte, Bereiche, Endpunkte und Zugangsdaten sind im Paketformat nicht erlaubt.";
    const toolbar = document.createElement("div");
    toolbar.className = "training-package-toolbar";
    const helpButton = (id, label) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "config-help-trigger";
      button.textContent = "i";
      button.title = `Detailhilfe: ${label}`;
      button.setAttribute("aria-label", `Hilfe zu ${label}`);
      button.setAttribute("aria-controls", "configHelpPopover");
      button.setAttribute("aria-expanded", "false");
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openConfigHelp(button, { id, hide_facts: true });
      });
      return button;
    };
    const fieldControl = (labelText, control, helpId) => {
      const wrapper = document.createElement("div");
      wrapper.className = "training-package-control";
      const heading = document.createElement("div");
      const label = document.createElement("label");
      const controlId = `config-${helpId.replaceAll(".", "-")}`;
      control.id = controlId;
      label.htmlFor = controlId;
      label.textContent = labelText;
      heading.append(label, helpButton(helpId, labelText));
      control.title = CONFIG_HELP[helpId]?.text?.[0] || labelText;
      wrapper.append(heading, control);
      return wrapper;
    };
    const actionControl = (button, helpId, label) => {
      const wrapper = document.createElement("div");
      wrapper.className = "training-package-action";
      button.title = CONFIG_HELP[helpId]?.text?.[0] || label;
      wrapper.append(button, helpButton(helpId, label));
      return wrapper;
    };
    const provider = document.createElement("select");
    provider.setAttribute("aria-label", "Trainingsprovider");
    const kind = document.createElement("select");
    kind.setAttribute("aria-label", "Paketart");
    for (const [value, label] of [["language", "Sprachpaket"], ["ambiguities", "Mehrdeutigkeiten"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      kind.append(option);
    }
    const entry = document.createElement("select");
    entry.setAttribute("aria-label", "Einzelner Trainingsbaustein");
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.className = "eve-button eve-button--ghost";
    refresh.textContent = "VERKNÜPFUNGEN AKTUALISIEREN";
    refresh.title = "Vorhandenes portables Wissen mit lokal bekannten Provider-Ressourcen verknüpfen";
    const exportButton = document.createElement("button");
    exportButton.type = "button";
    exportButton.className = "eve-button eve-button--ghost";
    exportButton.textContent = "PAKET EXPORTIEREN";
    toolbar.append(
      fieldControl("Provider", provider, "training_packages.provider"),
      fieldControl("Paketart", kind, "training_packages.kind"),
      fieldControl("Exportumfang", entry, "training_packages.entry"),
      actionControl(refresh, "training_packages.refresh", "Verknüpfungen aktualisieren"),
      actionControl(exportButton, "training_packages.export", "Paket exportieren"),
    );
    const importRow = document.createElement("div");
    importRow.className = "training-package-import";
    const file = document.createElement("input");
    file.type = "file";
    file.accept = "application/json,.json";
    file.setAttribute("aria-label", "EVE-Trainingspaket auswählen");
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "eve-button eve-button--ghost";
    preview.textContent = "PAKET PRÜFEN";
    preview.disabled = true;
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "eve-button eve-button--ghost";
    apply.textContent = "IMPORTIEREN UND VERKNÜPFEN";
    apply.disabled = true;
    importRow.append(
      fieldControl("JSON-Paket", file, "training_packages.file"),
      actionControl(preview, "training_packages.preview", "Paket prüfen"),
      actionControl(apply, "training_packages.import", "Paket importieren und verknüpfen"),
    );
    const status = document.createElement("p");
    status.className = "training-package-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const details = document.createElement("div");
    details.className = "training-package-preview";
    details.hidden = true;
    body.append(intro, toolbar, importRow, status, details);
    card.append(summary, body);

    let selectedPackage = null;
    let providerOverviews = [];
    const providerLabel = (id) => ({ home_assistant: "Home Assistant" })[id]
      || id.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    const setBusy = (busy) => {
      refresh.disabled = busy || !provider.value;
      exportButton.disabled = busy || !provider.value;
      preview.disabled = busy || !file.files?.length;
      apply.disabled = busy || !selectedPackage;
    };
    const renderEntries = () => {
      const current = providerOverviews.find((item) => item.provider === provider.value);
      const entries = (current?.export_entries || []).filter((item) => item.kind === kind.value);
      entry.replaceChildren();
      const all = document.createElement("option");
      all.value = "";
      all.textContent = `Alle ${kind.value === "language" ? "Sprachprofile" : "Mehrdeutigkeiten"}`;
      entry.append(all);
      for (const item of entries) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.label;
        entry.append(option);
      }
    };
    const showPreview = (data) => {
      const changes = data.changes || {};
      const signature = data.signature === "unsigned"
        ? "nicht signiert – Herkunft vor dem Import prüfen"
        : data.signature === "present_unverified" ? "Signatur vorhanden, noch nicht verifiziert" : data.signature;
      details.replaceChildren();
      const items = [
        ["Paket", `${data.metadata?.name || "Unbenannt"} · ${data.metadata?.version || "ohne Version"}`],
        ["Herausgeber", data.metadata?.publisher || "nicht angegeben"],
        ["Inhalt", `${data.entry_count ?? 0} Einträge · ${changes.new ?? 0} neu · ${changes.updated ?? 0} geändert · ${changes.unchanged ?? 0} unverändert`],
        ["Lokal nutzbar", (data.applicable_domains || []).join(", ") || "derzeit keine passende Provider-Ressource"],
        ["Noch nicht lokal vorhanden", (data.missing_domains || []).join(", ") || "keine"],
        ["Vertrauen", signature || "unbekannt"],
      ];
      for (const [label, value] of items) {
        const row = document.createElement("p");
        const key = document.createElement("strong");
        key.textContent = label;
        const text = document.createElement("span");
        text.textContent = value;
        row.append(key, text);
        details.append(row);
      }
      details.hidden = false;
    };
    const readSelected = async () => {
      const selected = file.files?.[0];
      if (!selected) throw new Error("Bitte zuerst ein JSON-Paket auswählen.");
      if (selected.size > 2 * 1024 * 1024) throw new Error("Das Paket ist größer als 2 MB.");
      const parsed = JSON.parse(await selected.text());
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Das Trainingspaket muss ein JSON-Objekt sein.");
      }
      return parsed;
    };
    const post = async (payload, label) => {
      const response = await fetchWithTimeout("/api/training-packages", {
        method: "POST", headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(payload),
      }, 30000);
      const data = await readJsonResponse(response, label);
      if (!response.ok) throw new Error(data.error || `${label} ist fehlgeschlagen.`);
      return data;
    };
    const load = async () => {
      status.textContent = "Trainingsadapter werden gelesen …";
      const response = await fetchWithTimeout("/api/training-packages?action=overview&locale=de", { cache: "no-store", headers: auth });
      const data = await readJsonResponse(response, "Community-Training");
      if (!response.ok) throw new Error(data.error || "Trainingsadapter konnten nicht gelesen werden.");
      provider.replaceChildren();
      providerOverviews = data.providers || [];
      for (const item of providerOverviews) {
        const option = document.createElement("option");
        option.value = item.provider;
        option.textContent = providerLabel(item.provider);
        provider.append(option);
      }
      renderEntries();
      status.textContent = (data.providers || []).length
        ? `${data.providers.length} Provider-Adapter · Import prüft zuerst Schema, Privatsphäre und Integrität.`
        : "Noch kein Provider-Adapter installiert.";
      setBusy(false);
    };
    file.addEventListener("change", () => {
      selectedPackage = null;
      details.hidden = true;
      status.textContent = file.files?.length ? "Paket ausgewählt – vor dem Import bitte prüfen." : "";
      setBusy(false);
    });
    provider.addEventListener("change", renderEntries);
    kind.addEventListener("change", renderEntries);
    preview.addEventListener("click", async () => {
      setBusy(true);
      status.textContent = "Paket wird lokal geprüft …";
      try {
        const candidate = await readSelected();
        const result = await post({ action: "preview", package: candidate }, "Paketprüfung");
        selectedPackage = candidate;
        showPreview(result);
        status.textContent = "Paket ist gültig. Der Import führt keine Provider-Aktion und keinen LLM-Aufruf aus.";
      } catch (error) {
        selectedPackage = null;
        details.hidden = true;
        status.textContent = error.message;
      } finally {
        setBusy(false);
      }
    });
    apply.addEventListener("click", async () => {
      if (!selectedPackage) return;
      setBusy(true);
      status.textContent = "Paket wird im Memory gespeichert und lokal verknüpft …";
      try {
        const result = await post({ action: "import", package: selectedPackage }, "Paketimport");
        showPreview(result);
        status.textContent = "Importiert und mit vorhandenen lokalen Provider-Ressourcen verknüpft.";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        setBusy(false);
      }
    });
    refresh.addEventListener("click", async () => {
      setBusy(true);
      status.textContent = "Vorhandenes Trainingswissen wird lokal verknüpft …";
      try {
        const result = await post({
          action: "train", provider: provider.value, locale: "de", refresh_inventory: false,
        }, "Training");
        status.textContent = `${result.grounding?.active ?? 0} Sprachprofile aktiv verknüpft · ${result.ambiguities?.active ?? 0} Mehrdeutigkeiten erkannt · 0 LLM-Aufrufe.`;
      } catch (error) {
        status.textContent = error.message;
      } finally {
        setBusy(false);
      }
    });
    exportButton.addEventListener("click", async () => {
      setBusy(true);
      status.textContent = "Portables Paket wird erstellt …";
      try {
        const selectedEntry = entry.value ? `&entry_id=${encodeURIComponent(entry.value)}` : "";
        const url = `/api/training-packages?action=export&provider=${encodeURIComponent(provider.value)}&kind=${encodeURIComponent(kind.value)}&locale=de${selectedEntry}`;
        const response = await fetchWithTimeout(url, { cache: "no-store", headers: auth }, 30000);
        const data = await readJsonResponse(response, "Paketexport");
        if (!response.ok) throw new Error(data.error || "Paket konnte nicht exportiert werden.");
        downloadTrainingPackage(data);
        status.textContent = `${data.entries?.length ?? 0} generische Einträge exportiert.`;
      } catch (error) {
        status.textContent = error.message;
      } finally {
        setBusy(false);
      }
    });
    load().catch((error) => { status.textContent = error.message; setBusy(false); });
    return card;
  }

  function renderConfig(data) {
    closeConfigHelp();
    elements.configSections.replaceChildren();
    configValues = new Map();
    const openSections = storedConfigSections();
    for (const section of data.sections || []) {
      const card = document.createElement("details");
      card.className = "config-section";
      card.dataset.configSection = section.id;
      card.open = openSections.has(section.id);
      card.addEventListener("toggle", () => {
        if (card.open) openSections.add(section.id);
        else openSections.delete(section.id);
        window.localStorage.setItem("eve.openConfigSections", JSON.stringify([...openSections]));
      });
      const fields = [...section.fields, ...section.secrets];
      const summary = document.createElement("summary");
      const heading = document.createElement("span");
      heading.className = "config-section-heading";
      const title = document.createElement("span");
      title.textContent = section.title;
      heading.append(configSectionIcon(section.id), title);
      const count = document.createElement("small");
      count.textContent = `${fields.length} ${fields.length === 1 ? "Einstellung" : "Einstellungen"}`;
      summary.append(heading, count);
      const body = document.createElement("div");
      body.className = "config-section-body";
      const advanced = document.createElement("details");
      const advancedTitle = document.createElement("summary");
      advancedTitle.textContent = "Erweiterte Einstellungen";
      advanced.append(advancedTitle);
      card.append(summary, body);
      if (section.id === "chatto") {
        const status = document.createElement("p");
        const names = { ready: "verbunden", disabled: "deaktiviert", stopped: "gestoppt", starting: "startet", connecting: "verbindet", reconnecting: "verbindet erneut", permissions_missing: "Lese- oder Schreibberechtigung fehlt", turn_failed: "Verarbeitung fehlgeschlagen", connection_failed: "Verbindung fehlgeschlagen" };
        status.textContent = `Chatto: ${names[data.chatto_status?.state] || "Status unbekannt"}`;
        body.append(status);
      }
      for (const field of fields) {
        const row = document.createElement("div");
        row.className = "config-field";
        if (field.choices) row.classList.add("config-field--choices");
        const head = document.createElement("div");
        head.className = "config-field-head";
        const nameLine = document.createElement("div");
        nameLine.className = "config-field-name";
        const name = document.createElement("label");
        name.textContent = field.label;
        const control = configControl(field);
        control.id = `config-${field.id}`;
        name.htmlFor = control.id;
        nameLine.append(name);
        if (CONFIG_HELP[field.id] || field.description) {
          const help = document.createElement("button");
          help.className = "config-help-trigger";
          help.type = "button";
          help.textContent = "i";
          help.setAttribute("aria-label", `Hilfe zu ${field.label}`);
          help.setAttribute("aria-controls", "configHelpPopover");
          help.setAttribute("aria-expanded", "false");
          help.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            openConfigHelp(help, field);
          });
          nameLine.append(help);
        }
        if (field.description) {
          const description = document.createElement("small");
          description.className = "config-field-description";
          description.textContent = field.description;
          head.append(nameLine, description);
        } else {
          head.append(nameLine);
        }
        const source = document.createElement("small");
        source.textContent = field.type === "secret"
          ? `${field.configured ? "konfiguriert" : "nicht konfiguriert"} · ${field.source} · ${field.restart_required ? "nach Neustart" : "beim Speichern wirksam"}`
          : `Quelle: ${field.source}${field.overridden ? " · überschreibt eve.json" : ""} · ${field.restart_required ? "nach Neustart" : "sofort wirksam"}`;
        head.append(source);
        row.append(head, control);
        if (field.suggestions?.length && control instanceof HTMLInputElement) {
          const suggestions = document.createElement("datalist");
          suggestions.id = `${control.id}-suggestions`;
          control.setAttribute("list", suggestions.id);
          for (const value of field.suggestions) {
            const option = document.createElement("option");
            option.value = value;
            suggestions.append(option);
          }
          row.append(suggestions);
        }
        (field.advanced ? advanced : body).append(row);
        configValues.set(field.id, field.type === "secret" ? "" : field.value);
      }
      if (advanced.childElementCount > 1) body.append(advanced);
      if (section.id === "mcp") {
        const add = document.createElement("button");
        add.type = "button";
        add.className = "eve-button eve-button--ghost";
        add.textContent = "Integration hinzufügen";
        add.addEventListener("click", () => {
          const name = window.prompt("Eindeutiger Integrationsname (Kleinbuchstaben, Ziffern, Unterstriche):");
          if (name === null) return;
          if (!/^[a-z][a-z0-9_]{0,39}$/.test(name) || data.sections.some(item => item.mcp_server === name)) {
            elements.configStatus.textContent = "Bitte einen freien Namen mit maximal 40 Zeichen verwenden.";
            return;
          }
          const baseline = new Map(configValues);
          const secretValues = new Map([...elements.configForm.querySelectorAll('[data-config-type="secret"]')]
            .map(control => [control.dataset.configField, control.value]));
          try {
            for (const section of data.sections) for (const field of section.fields) {
              const control = [...elements.configForm.querySelectorAll("[data-config-field]")]
                .find(item => item.dataset.configField === field.id);
              if (control) field.value = readConfigValue(control);
            }
          } catch (error) { elements.configStatus.textContent = error.message; return; }
          const section = JSON.parse(JSON.stringify(data.mcp_server_template).replaceAll("{name}", name));
          section.fields.find(field => field.id.endsWith(".title")).value = name;
          section.pending_create = true;
          data.sections.push(section);
          renderConfig(data);
          for (const [id, value] of baseline) configValues.set(id, value);
          for (const pending of data.sections.filter(item => item.pending_create))
            for (const field of pending.fields) configValues.delete(field.id);
          for (const control of elements.configForm.querySelectorAll('[data-config-type="secret"]'))
            control.value = secretValues.get(control.dataset.configField) || "";
          const card = [...elements.configSections.children].find(item => item.dataset.configSection === section.id);
          card.open = true;
          card.querySelector('input[data-config-field$=".command"]')?.focus();
          elements.configSave.disabled = false;
          elements.configStatus.textContent = "Neue Integration: Programm eintragen und speichern.";
        });
        body.append(add);
      }
      if (section.id === "home_assistant") {
        body.append(homeAssistantInventoryAction(), homeAssistantPolicyAction());
      }
      elements.configSections.append(card);
    }
    elements.configSections.append(trainingPackagesSection(openSections));
    const sorted = [...elements.configSections.children].sort((left, right) =>
      (left.querySelector(".config-section-heading")?.textContent || "").localeCompare(
        right.querySelector(".config-section-heading")?.textContent || "", "de", { sensitivity: "base" }));
    elements.configSections.replaceChildren(...sorted);
    elements.configSave.disabled = true;
  }

  async function loadConfig() {
    elements.configStatus.textContent = "Konfiguration wird geladen …";
    const response = await fetchWithTimeout("/api/config", { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Konfiguration");
    if (!response.ok) throw new Error(data.error || "Konfiguration konnte nicht geladen werden.");
    renderConfig(data);
    elements.configStatus.textContent = "Dateifreigaben und dynamische Semantik gelten sofort; andere Änderungen nach einem Neustart.";
  }

  function setSystemMenuOpen(open) {
    systemMenuOpen = Boolean(open);
    elements.systemMenu.hidden = !systemMenuOpen;
    elements.systemMenuToggle.setAttribute("aria-expanded", String(systemMenuOpen));
    elements.systemMenuToggle.classList.toggle("active", systemMenuOpen);
  }

  function setConfigOpen(open) {
    configOpen = Boolean(open);
    if (configOpen && brainwatchOpen) setBrainwatchOpen(false);
    if (!configOpen) closeConfigHelp();
    setSystemMenuOpen(false);
    document.body.classList.toggle("config-open", configOpen);
    syncAvatarCloudVisibility();
    elements.configView.hidden = !configOpen;
    if (configOpen) {
      toggleConversationPanel(false);
      loadConfig().catch((error) => { elements.configStatus.textContent = error.message; });
    }
  }

  function readConfigValue(control) {
    if (control.dataset.configChoices === "true") return [...control.querySelectorAll("input:checked")].map(input => input.value);
    if (["key_value", "mcp_calls"].includes(control.dataset.configType)) {
      const rows = [...control.querySelectorAll(".config-entry-row")].map(row =>
        Object.fromEntries([...row.querySelectorAll("[data-entry-key]")].map(input => [input.dataset.entryKey, input.value])));
      if (control.dataset.configType === "key_value") {
        if (rows.some(row => !row.key) || new Set(rows.map(row => row.key)).size !== rows.length)
          throw new Error("Umgebungsvariablen benötigen eindeutige, nichtleere Namen.");
        return Object.fromEntries(rows.map(row => [row.key, row.value]));
      }
      return rows.map(row => ({ tool: row.tool, arguments: JSON.parse(row.arguments),
        ...(row.if_exists ? { if_exists: row.if_exists } : {}) }));
    }
    if (control.dataset.configType === "json") return JSON.parse(control.value);
    if (control.dataset.configType === "boolean") return control.checked;
    if (["integer", "number"].includes(control.dataset.configType)) return Number(control.value);
    if (["path_list", "string_list"].includes(control.dataset.configType)) {
      return control.value.split("\n").map((value) => value.trim()).filter(Boolean);
    }
    return control.value;
  }

  async function saveConfig(event) {
    event.preventDefault();
    const values = {};
    const secrets = {};
    for (const control of elements.configForm.querySelectorAll("[data-config-field]")) {
      let value;
      try { value = readConfigValue(control); }
      catch (error) { elements.configStatus.textContent = `Konfiguration prüfen: ${error.message}`; return; }
      if (control.dataset.configType === "secret") {
        if (String(value).trim()) secrets[control.dataset.configField] = value;
      } else if (JSON.stringify(value) !== JSON.stringify(configValues.get(control.dataset.configField))) {
        values[control.dataset.configField] = value;
      }
    }
    if (!Object.keys(values).length && !Object.keys(secrets).length) {
      elements.configSave.disabled = true;
      elements.configStatus.textContent = "Keine Änderungen zu speichern.";
      return;
    }
    elements.configSave.disabled = true;
    elements.configStatus.textContent = "Wird geprüft und gespeichert …";
    try {
      const response = await fetchWithTimeout("/api/config", {
        method: "PATCH", headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ values, secrets }),
      });
      const data = await readJsonResponse(response, "Konfiguration");
      if (!response.ok) throw new Error(data.error || "Konfiguration konnte nicht gespeichert werden.");
      const changed = new Set([...Object.keys(values), ...Object.keys(secrets)]);
      const needsRestart = (data.sections || []).some(section => [...section.fields, ...section.secrets]
        .some(field => changed.has(field.id) && field.restart_required));
      renderConfig(data);
      elements.configStatus.textContent = needsRestart
        ? "Gespeichert – einige Änderungen benötigen einen EVE-Neustart."
        : "Gespeichert – Änderungen sind wirksam.";
    } catch (error) {
      elements.configStatus.textContent = error.message;
      elements.configSave.disabled = false;
    }
  }

  const BRAINWATCH_TYPE_MARKS = {
    conversation: "C", message: "M", turn: "T", memory: "MEM", asset: "IMG",
    "tool-event": "TOOL", "work-list": "LIST", "work-item": "TASK",
    "work-item-event": "EVT", "scheduled-task": "PLAN", "task-run": "RUN",
    approval: "OK", "audit-event": "AUD", "web-source": "WEB", claim: "CLM",
  };
  const BRAINWATCH_COLORS = {
    conversation: "#64d7cc", message: "#9ebbc1", turn: "#ecdd91", memory: "#a58bea",
    asset: "#e89f70", "tool-event": "#73addc", "work-list": "#62ca91",
    "work-item": "#83d59f", "work-item-event": "#6a9e7e", "scheduled-task": "#dbb46d",
    "task-run": "#c98f73", approval: "#79d5b4", "audit-event": "#cf8290", "web-source": "#66b9e8",
    claim: "#79ddd2",
  };
  const MEMORY_CLAIM_MARKS = { opaque_fact: "FAKT", provider_binding: "BIND", alias: "ALIAS" };
  const MEMORY_CLAIM_COLORS = { opaque_fact: "#8edbd2", provider_binding: "#e5c77b", alias: "#aa94e7" };
  const MEMORY_EVENT_LABELS = {
    claim_created: "Claim gespeichert", evidence_created: "Evidence gespeichert",
    observation_recorded: "Observation aufgezeichnet", relation_stored: "Relation gespeichert",
    learning_decision: "Lernentscheidung gespeichert", learning_job_accepted: "Learning Job angenommen",
    learning_job_started: "Learning Job gestartet", learning_job_completed: "Learning Job abgeschlossen",
    learning_job_updated: "Learning Job-Zustand gespeichert", compiler_evaluation: "Compiler-Evaluation",
    compiler_retrieved: "Compiler-Kandidat gefunden", compiler_eligible: "Compiler-Kandidat geeignet",
    compiler_would_present: "Für Präsentation ausgewählt", compiler_rejected: "Compiler-Kandidat abgelehnt",
    compiler_cancelled: "Compiler-Prüfung abgebrochen", compiler_error: "Compiler-Prüfung fehlgeschlagen",
    usage_presented: "Präsentation protokolliert", semantic_reuse_result: "Semantische Wiederverwendung",
    trace_started: "Trace begonnen", operation_started: "Operation begonnen",
    operation_completed: "Operation abgeschlossen", operation_aborted: "Operation abgebrochen",
    telemetry_persist_failed: "Telemetrie-Persistierung fehlgeschlagen",
    claim_query_started: "Claim-Abfrage begonnen", claim_retrieved: "Claim gefunden",
    claim_eligible: "Claim technisch geeignet", claim_selected_for_view: "Claim für View ausgewählt",
    claim_returned_to_consumer: "Claim an Consumer zurückgegeben",
    relation_traversed_for_retrieval: "Relation beim Retrieval traversiert",
    claim_added_to_prompt_context: "Claim in Prompt-Kontext eingebaut",
    claim_received_by_llm_client: "Claim vom LLM-Client übernommen",
    claim_serialized_for_transport: "Claim für Transport serialisiert",
    transport_failed: "Transport fehlgeschlagen", llm_transport_result: "LLM-Transportergebnis",
    claim_resolved: "Claim deterministisch aufgelöst",
    claim_technical_verification: "Claim technisch verifiziert",
    claim_bound_to_plan: "Claim an Plan gebunden", alias_read_for_stt: "Alias für STT gelesen",
    claim_bound_to_action: "Claim an Action gebunden",
    action_dispatch_attempted_with_claim: "Action dispatcht",
    action_provider_response_with_claim: "Providerantwort erhalten",
    action_verification_with_claim: "Action verifiziert",
    action_completed_with_claim: "Action abgeschlossen",
    relation_bound_to_plan: "Relation an Plan gebunden",
    claim_lifecycle_changed: "Claim-Lifecycle geändert",
  };
  const MEMORY_CATEGORY_LABELS = {
    retrieval: "Retrieval", llm_context: "LLM-Kontext", deterministic: "Deterministische Verarbeitung",
    actions: "Aktionen", memory_changes: "Gedächtnisänderungen", relations: "Relationen", system: "System",
  };
  const MEMORY_FIDELITY_LABELS = {
    direct_event: "Direktes Ereignis", state_timestamp: "Zustandszeitpunkt",
    derived_link: "Abgeleitete Verbindung",
  };
  const BRAINWATCH_SPATIAL_GROUPS = {
    origin: { label: "HERKUNFT", direction: "left" },
    consequence: { label: "FOLGE", direction: "right" },
    context: { label: "KONTEXT", direction: "up" },
    retrieval: { label: "RETRIEVAL", direction: "down" },
  };
  const BRAINWATCH_EVIDENCE_RELATIONS = new Set([
    "retrieved_for", "has_asset", "has_tool_event", "source_available_for_message",
    "has_event", "has_audit_event",
  ]);
  const BRAINWATCH_LINEAGE_RELATIONS = new Set(["input_of", "output_of", "generated_memory", "executed_as"]);
  const BRAINWATCH_CONTAINER_RELATIONS = new Set(["contains", "contains_turn", "has_task", "has_approval"]);
  const BRAINWATCH_FLOW_RELATIONS = new Set([...BRAINWATCH_LINEAGE_RELATIONS, "retrieved_for", "has_tool_event"]);

  function brainwatchSpatialGroup(edge, focusId) {
    if (edge.category === "retrieval" || BRAINWATCH_EVIDENCE_RELATIONS.has(edge.type)) return "retrieval";
    const focusIsTarget = edge.target === focusId;
    if (BRAINWATCH_CONTAINER_RELATIONS.has(edge.type) && focusIsTarget) return "context";
    if (BRAINWATCH_LINEAGE_RELATIONS.has(edge.type)) return focusIsTarget ? "origin" : "consequence";
    return focusIsTarget ? "origin" : "consequence";
  }

  class BrainwatchGraph {
    constructor(canvas, inspect) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.inspect = inspect;
      this.nodes = new Map();
      this.edges = new Map();
      this.expansions = new Map();
      this.anchors = new Set();
      this.focus = null;
      this.selected = null;
      this.hoveredEdge = null;
      this.viewMode = "context";
      this.isolated = false;
      this.animationFrame = 0;
      this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.scale = 1;
      this.offset = { x: 0, y: 0 };
      this.pointer = null;
      this.activePointers = new Map();
      this.pinchDistance = 0;
      this.drag = null;
      this.bind();
      new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
      this.resize();
    }

    bind() {
      this.canvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        const rect = this.canvas.getBoundingClientRect();
        this.zoom(event.deltaY < 0 ? 1.12 : .89, event.clientX - rect.left, event.clientY - rect.top);
      }, { passive: false });
      this.canvas.addEventListener("pointerdown", (event) => {
        this.canvas.setPointerCapture(event.pointerId);
        const point = this.screen(event);
        this.activePointers.set(event.pointerId, point);
        if (this.activePointers.size > 1) {
          const [first, second] = [...this.activePointers.values()];
          this.pinchDistance = Math.hypot(second.x-first.x, second.y-first.y);
          this.drag = null; this.pointer = null;
          return;
        }
        const node = this.hitNode(point);
        this.pointer = point;
        this.drag = node ? { kind: "node", node, moved: false } : { kind: "pan", moved: false };
        this.canvas.classList.add("dragging");
      });
      this.canvas.addEventListener("pointermove", (event) => {
        const point = this.screen(event);
        if (this.activePointers.has(event.pointerId)) this.activePointers.set(event.pointerId, point);
        if (this.activePointers.size > 1) {
          const [first, second] = [...this.activePointers.values()];
          const distance = Math.hypot(second.x-first.x, second.y-first.y);
          if (this.pinchDistance > 0) this.zoom(distance/this.pinchDistance, (first.x+second.x)/2, (first.y+second.y)/2);
          this.pinchDistance = distance;
          return;
        }
        if (!this.drag || !this.pointer) {
          const edge = this.hitEdge(point);
          this.hoveredEdge = edge?.data.id || null;
          this.draw();
          return;
        }
        const dx = point.x - this.pointer.x, dy = point.y - this.pointer.y;
        if (Math.abs(dx) + Math.abs(dy) > 2) this.drag.moved = true;
        if (this.drag.kind === "node") {
          this.drag.node.x += dx / this.scale;
          this.drag.node.y += dy / this.scale;
          this.drag.node.pinned = true;
        } else {
          this.offset.x += dx;
          this.offset.y += dy;
        }
        this.pointer = point;
        this.draw();
      });
      this.canvas.addEventListener("pointerup", (event) => {
        const point = this.screen(event);
        this.activePointers.delete(event.pointerId);
        if (this.activePointers.size) { this.pinchDistance = 0; this.drag = null; this.pointer = null; return; }
        const dragged = this.drag;
        this.drag = null; this.pointer = null;
        this.canvas.classList.remove("dragging");
        if (!dragged?.moved) {
          const node = this.hitNode(point);
          if (node) this.inspect({ kind: "node", value: node.data });
          else {
            const edge = this.hitEdge(point);
            if (edge) { this.selected = edge.data.id; this.inspect({ kind: "edge", value: edge.data }); }
          }
        }
      });
      this.canvas.addEventListener("pointercancel", (event) => {
        this.activePointers.delete(event.pointerId); this.drag=null; this.pointer=null; this.pinchDistance=0; this.canvas.classList.remove("dragging");
      });
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      this.canvas.width = Math.max(1, Math.round(rect.width * ratio));
      this.canvas.height = Math.max(1, Math.round(rect.height * ratio));
      this.width = rect.width; this.height = rect.height; this.ratio = ratio;
      if (!this.offset.x && !this.offset.y) this.offset = { x: rect.width / 2, y: rect.height / 2 };
      this.draw();
    }

    screen(event) {
      const rect = this.canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    }

    world(point) {
      return { x: (point.x - this.offset.x) / this.scale, y: (point.y - this.offset.y) / this.scale };
    }

    merge(payload, sourceId = payload.focus) {
      const focusId = payload.focus || this.focus;
      let sibling = 0;
      const introduced = new Set();
      for (const data of payload.nodes || []) {
        if (this.nodes.has(data.id)) {
          this.nodes.get(data.id).data = data;
          continue;
        }
        const focus = this.nodes.get(focusId);
        const originX = focus?.x || 0, originY = focus?.y || 0;
        const angle = sibling * 1.19 + (data.id < focusId ? Math.PI : 0);
        this.nodes.set(data.id, {
          data, x: focus ? originX + Math.cos(angle) * 220 : 0,
          y: focus ? originY + Math.sin(angle) * 145 : 0,
          fromX: originX, fromY: originY, born: performance.now(), pinned: false,
        });
        introduced.add(data.id);
        sibling += 1;
      }
      for (const data of payload.edges || []) if (!this.edges.has(data.id)) this.edges.set(data.id, { data });
      const previous = this.expansions.get(sourceId) || { nodes: new Set(), edges: new Set(), introduced: new Set() };
      for (const node of payload.nodes || []) previous.nodes.add(node.id);
      for (const edge of payload.edges || []) previous.edges.add(edge.id);
      for (const nodeId of introduced) if (nodeId !== sourceId) previous.introduced.add(nodeId);
      this.expansions.set(sourceId, previous);
      if (payload.focus) this.focus = payload.focus;
      this.layout(payload.focus, payload.edges || [], introduced);
      if (this.viewMode !== "overview") this.layoutFocusedNeighborhood();
      elements.brainwatchEmpty.hidden = this.nodes.size > 0;
      this.animate();
    }

    layout(focusId, newEdges, introduced = new Set()) {
      const parent = this.nodes.get(focusId);
      if (!parent) return;
      if (!parent.pinned && this.nodes.size === 1) parent.x = parent.y = 0;
      const groups = { origin: [], consequence: [], context: [], retrieval: [] };
      for (const edge of newEdges) {
        const otherId = edge.source === focusId ? edge.target : edge.source;
        const node = this.nodes.get(otherId);
        if (!node || node.pinned || !introduced.has(otherId)) continue;
        const group = brainwatchSpatialGroup(edge, focusId);
        if (!groups[group].includes(node)) groups[group].push(node);
      }
      const unplaced = new Set(introduced);
      const place = (items, group) => {
        const existing = [...this.nodes.values()].filter((node) => (
          !introduced.has(node.data.id) && node.layoutParent === focusId && node.spatialGroup === group
        )).length;
        items.forEach((node, index) => {
          unplaced.delete(node.data.id);
          const slot = existing + index;
          const position = this.localBranchPosition(parent, group, slot, unplaced);
          node.x = position.x;
          node.y = position.y;
          node.fromX = parent.x;
          node.fromY = parent.y;
          node.layoutParent = focusId;
          node.spatialGroup = group;
        });
      };
      for (const group of Object.keys(groups)) place(groups[group], group);
    }

    localBranchPosition(parent, group, slot, unplaced) {
      const horizontal = group === "origin" || group === "consequence";
      const sign = group === "origin" || group === "context" ? -1 : 1;
      const rank = slot === 0 ? 0 : Math.ceil(slot / 2) * (slot % 2 ? 1 : -1);
      const spread = horizontal ? 74 : 158;
      const baseDistance = horizontal ? 178 : 126;
      const sideSteps = [0, 1, -1, 2, -2, 3, -3];
      for (let attempt = 0; attempt < 9; attempt += 1) {
        const side = rank + sideSteps[attempt % sideSteps.length];
        const outward = baseDistance + Math.floor(attempt / sideSteps.length) * 42;
        const candidate = {
          x: parent.x + (horizontal ? sign * outward : side * spread),
          y: parent.y + (horizontal ? side * spread : sign * outward),
        };
        if (this.localPositionFree(candidate, unplaced, parent.data.id)) return candidate;
      }
      return {
        x: parent.x + (horizontal ? sign * (baseDistance + 84) : rank * spread),
        y: parent.y + (horizontal ? rank * spread : sign * (baseDistance + 84)),
      };
    }

    localPositionFree(candidate, unplaced, parentId) {
      for (const node of this.nodes.values()) {
        if (unplaced.has(node.data.id) || node.data.id === parentId) continue;
        if (Math.abs(node.x - candidate.x) < 158 && Math.abs(node.y - candidate.y) < 72) return false;
      }
      return true;
    }

    setFocus(nodeId) {
      if (!this.nodes.has(nodeId)) return;
      this.focus = nodeId;
      this.selected = nodeId;
      if (this.viewMode === "overview") this.ensureFocusVisible();
      else {
        this.layoutFocusedNeighborhood();
        this.centerOnFocus();
      }
      this.draw();
    }

    centerOnFocus() {
      const node = this.nodes.get(this.focus);
      if (!node) return;
      this.offset = { x: this.width / 2 - node.x * this.scale, y: this.height / 2 - node.y * this.scale };
    }

    layoutFocusedNeighborhood() {
      const focus = this.nodes.get(this.focus);
      if (!focus) return;
      const started = performance.now();
      const move = (node, x, y, depth, group, parentId) => {
        if (Math.abs(node.x - x) >= .5 || Math.abs(node.y - y) >= .5) {
          node.fromX = node.x; node.fromY = node.y; node.x = x; node.y = y;
          node.born = started;
        }
        node.pinned = false; node.layoutDepth = depth;
        node.spatialGroup = group; node.layoutParent = parentId;
      };
      move(focus, 0, 0, 0, "focus", null);
      const groups = { origin: new Map(), consequence: new Map(), context: new Map(), retrieval: new Map() };
      for (const edge of this.edges.values()) {
        if (edge.data.source !== this.focus && edge.data.target !== this.focus) continue;
        const otherId = edge.data.source === this.focus ? edge.data.target : edge.data.source;
        const other = this.nodes.get(otherId);
        if (other) groups[brainwatchSpatialGroup(edge.data, this.focus)].set(otherId, other);
      }
      const direct = new Map();
      const assignedDirect = new Set();
      const ordered = (items) => [...items.values()].sort((left, right) => (
        String(left.data.label).localeCompare(String(right.data.label), "de") || left.data.id.localeCompare(right.data.id)
      ));
      for (const [group, items] of Object.entries(groups)) {
        const nodes = ordered(items).filter((node) => !assignedDirect.has(node.data.id));
        nodes.forEach((node, index) => {
          assignedDirect.add(node.data.id);
          const centered = index - (nodes.length - 1) / 2;
          const horizontal = group === "origin" || group === "consequence";
          const sign = group === "origin" || group === "context" ? -1 : 1;
          const x = horizontal ? sign * 245 : centered * 178;
          const y = horizontal ? centered * 92 : sign * 158;
          move(node, x, y, 1, group, this.focus);
          direct.set(node.data.id, { node, group });
        });
      }
      const secondByParent = new Map();
      for (const { node, group } of direct.values()) {
        for (const edge of this.edges.values()) {
          let otherId = null;
          if (edge.data.source === node.data.id) otherId = edge.data.target;
          else if (edge.data.target === node.data.id) otherId = edge.data.source;
          if (!otherId || otherId === this.focus || direct.has(otherId)) continue;
          if (!secondByParent.has(node.data.id)) secondByParent.set(node.data.id, { parent: node, group, nodes: new Map() });
          const other = this.nodes.get(otherId);
          if (other) secondByParent.get(node.data.id).nodes.set(otherId, other);
        }
      }
      const placed = new Set();
      for (const { parent, group, nodes: items } of secondByParent.values()) {
        const nodes = ordered(items).filter((node) => !placed.has(node.data.id));
        nodes.forEach((node, index) => {
          placed.add(node.data.id);
          const centered = index - (nodes.length - 1) / 2;
          const horizontal = group === "origin" || group === "consequence";
          const sign = group === "origin" || group === "context" ? -1 : 1;
          const x = horizontal ? sign * 455 : parent.x + centered * 148;
          const y = horizontal ? parent.y + centered * 72 : sign * 305;
          move(node, x, y, 2, group, parent.data.id);
        });
      }
    }

    ensureFocusVisible() {
      const node = this.nodes.get(this.focus);
      if (!node) return;
      const point = this.nodePoint(node);
      const margin = 120;
      if (point.x < margin || point.x > this.width - margin || point.y < margin || point.y > this.height - margin) {
        this.offset = { x: this.width / 2 - node.x * this.scale, y: this.height / 2 - node.y * this.scale };
      }
    }

    isExpanded(nodeId) { return this.expansions.has(nodeId); }

    collapse(nodeId) {
      const removed = this.expansions.get(nodeId);
      if (!removed) return false;
      const prune = (owner, visited = new Set()) => {
        if (visited.has(owner)) return;
        visited.add(owner);
        const entry = this.expansions.get(owner);
        this.expansions.delete(owner);
        for (const candidate of entry?.introduced || []) {
          const shared = [...this.expansions.entries()].some(([other, contribution]) => other !== candidate && contribution.nodes.has(candidate));
          if (!shared && !this.anchors.has(candidate) && candidate !== this.focus) prune(candidate, visited);
        }
      };
      prune(nodeId);
      const keptEdges = new Set(), keptNodes = new Set(this.anchors);
      if (this.focus) keptNodes.add(this.focus);
      for (const [owner, entry] of this.expansions) {
        keptNodes.add(owner);
        for (const id of entry.nodes) keptNodes.add(id);
        for (const id of entry.edges) keptEdges.add(id);
      }
      for (const id of [...this.edges.keys()]) if (!keptEdges.has(id)) this.edges.delete(id);
      for (const id of [...this.nodes.keys()]) if (!keptNodes.has(id)) this.nodes.delete(id);
      this.selected = null;
      this.animate();
      return true;
    }

    toggleIsolation() {
      this.setViewMode(this.viewMode === "flow" ? "context" : "flow");
      return this.isolated;
    }

    setViewMode(mode) {
      if (!new Set(["context", "flow", "overview"]).has(mode)) return;
      this.viewMode = mode;
      this.isolated = mode === "flow";
      if (mode !== "overview") {
        this.layoutFocusedNeighborhood();
        this.centerOnFocus();
      }
      this.animate();
    }

    visibleGraph() {
      if (this.viewMode === "overview" || !this.focus) return { nodes: new Set(this.nodes.keys()), edges: new Set(this.edges.keys()) };
      if (this.viewMode === "context") return this.focusContext();
      const edgeIds = new Set(), nodeIds = new Set([this.focus]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const [id, edge] of this.edges) {
          if (!["lineage", "retrieval"].includes(edge.data.category) && !BRAINWATCH_FLOW_RELATIONS.has(edge.data.type)) continue;
          if (nodeIds.has(edge.data.source) || nodeIds.has(edge.data.target)) {
            if (!edgeIds.has(id)) { edgeIds.add(id); changed = true; }
            nodeIds.add(edge.data.source); nodeIds.add(edge.data.target);
          }
        }
      }
      return { nodes: nodeIds, edges: edgeIds };
    }

    animate() {
      if (this.reducedMotion) { this.draw(); return; }
      window.cancelAnimationFrame(this.animationFrame);
      const started = performance.now();
      const frame = () => {
        this.draw();
        if (performance.now() - started < 460) this.animationFrame = window.requestAnimationFrame(frame);
      };
      this.animationFrame = window.requestAnimationFrame(frame);
    }

    captureState() {
      return {
        nodes: new Map(this.nodes), edges: new Map(this.edges),
        expansions: new Map([...this.expansions].map(([key, value]) => [key, {
          nodes: new Set(value.nodes), edges: new Set(value.edges), introduced: new Set(value.introduced),
        }])),
        anchors: new Set(this.anchors), focus: this.focus, selected: this.selected,
        hoveredEdge: this.hoveredEdge, isolated: this.isolated, viewMode: this.viewMode,
        scale: this.scale, offset: { ...this.offset },
      };
    }

    restoreState(state) {
      if (!state) { this.clear(); return; }
      this.nodes = state.nodes; this.edges = state.edges; this.expansions = state.expansions;
      this.anchors = state.anchors; this.focus = state.focus; this.selected = state.selected;
      this.hoveredEdge = state.hoveredEdge; this.isolated = state.isolated;
      this.viewMode = state.viewMode || (state.isolated ? "flow" : "context");
      this.scale = state.scale; this.offset = { ...state.offset };
      elements.brainwatchEmpty.hidden = this.nodes.size > 0;
      this.draw();
    }

    clear() {
      this.nodes.clear(); this.edges.clear(); this.expansions.clear(); this.anchors.clear(); this.focus = this.selected = null; this.isolated = false; this.viewMode = "context";
      this.scale = 1; this.offset = { x: this.width / 2, y: this.height / 2 };
      elements.brainwatchEmpty.hidden = false;
      this.draw();
    }

    center() {
      const focus = this.nodes.get(this.focus) || [...this.nodes.values()][0];
      this.scale = 1;
      this.offset = focus ? { x: this.width / 2 - focus.x, y: this.height / 2 - focus.y } : { x: this.width / 2, y: this.height / 2 };
      this.draw();
    }

    zoom(factor, sx = this.width / 2, sy = this.height / 2) {
      const before = this.world({ x: sx, y: sy });
      this.scale = Math.max(.32, Math.min(2.8, this.scale * factor));
      this.offset.x = sx - before.x * this.scale; this.offset.y = sy - before.y * this.scale;
      this.draw();
    }

    nodePoint(node) {
      const age = performance.now() - (node.born || 0);
      const progress = this.reducedMotion || node.pinned || age >= 420 ? 1 : Math.max(0, Math.min(1, 1 - Math.pow(1 - age / 420, 3)));
      const x = (node.fromX ?? node.x) + (node.x - (node.fromX ?? node.x)) * progress;
      const y = (node.fromY ?? node.y) + (node.y - (node.fromY ?? node.y)) * progress;
      return { x: x * this.scale + this.offset.x, y: y * this.scale + this.offset.y, progress };
    }
    hitNode(point) {
      const visible = this.visibleGraph().nodes;
      for (const node of [...this.nodes.values()].reverse()) {
        if (!visible.has(node.data.id)) continue;
        const screen = this.nodePoint(node);
        const width=(node.data.id===this.focus?174:154)*this.scale, height=(node.data.id===this.focus?70:62)*this.scale;
        if (Math.abs(point.x-screen.x)<=width/2+4 && Math.abs(point.y-screen.y)<=height/2+4) return node;
      }
      return null;
    }
    hitEdge(point) {
      const visible = this.visibleGraph().edges;
      let best = null, distance = 9;
      for (const edge of this.edges.values()) {
        if (!visible.has(edge.data.id)) continue;
        const a = this.nodes.get(edge.data.source), b = this.nodes.get(edge.data.target);
        if (!a || !b) continue;
        const p1 = this.nodePoint(a), p2 = this.nodePoint(b);
        const length2 = (p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2 || 1;
        const t = Math.max(0, Math.min(1, ((point.x-p1.x)*(p2.x-p1.x)+(point.y-p1.y)*(p2.y-p1.y))/length2));
        const current = Math.hypot(point.x-(p1.x+t*(p2.x-p1.x)), point.y-(p1.y+t*(p2.y-p1.y)));
        if (current < distance) { distance = current; best = edge; }
      }
      return best;
    }

    draw() {
      const ctx = this.ctx;
      if (!ctx || !this.width) return;
      ctx.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
      ctx.clearRect(0, 0, this.width, this.height);
      this.drawSpace(ctx);
      const visible = this.visibleGraph();
      this.distanceCache = this.graphDistances();
      this.drawLaneGuides(ctx);
      for (const [id, edge] of this.edges) if (visible.edges.has(id)) this.drawEdge(edge);
      for (const [id, node] of this.nodes) if (visible.nodes.has(id)) this.drawNode(node);
      this.drawContinuationStubs(ctx);
      this.positionGroupOverlay();
    }

    positionGroupOverlay() {
      if (!elements.brainwatchGroups || elements.brainwatchGroups.hidden) return;
      const width = elements.brainwatchGroups.offsetWidth || 280;
      const left = Math.max(width / 2 + 10, Math.min(this.width - width / 2 - 10, this.width / 2));
      elements.brainwatchGroups.style.left = `${left}px`;
      elements.brainwatchGroups.style.top = "auto";
      elements.brainwatchGroups.style.bottom = "12px";
    }

    drawSpace(ctx) {
      const gradient = ctx.createRadialGradient(this.width*.52,this.height*.48,20,this.width*.52,this.height*.48,Math.max(this.width,this.height)*.65);
      gradient.addColorStop(0,"rgba(12,70,73,.1)"); gradient.addColorStop(.5,"rgba(3,20,27,.035)"); gradient.addColorStop(1,"rgba(0,0,0,0)");
      ctx.fillStyle=gradient; ctx.fillRect(0,0,this.width,this.height);
      ctx.save(); ctx.strokeStyle="rgba(82,197,190,.035)"; ctx.lineWidth=1;
      const horizon=this.height*.58;
      for(let i=-8;i<=8;i++){ctx.beginPath();ctx.moveTo(this.width*.5+i*18,horizon);ctx.lineTo(this.width*.5+i*this.width*.13,this.height);ctx.stroke();}
      for(let y=horizon;y<this.height;y+=18+(y-horizon)*.07){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(this.width,y);ctx.stroke();}
      ctx.restore();
    }

    focusContext() {
      const distances = this.graphDistances();
      const nodes = new Set([...distances].filter(([, distance]) => distance <= 2).map(([id]) => id));
      const edges = new Set();
      for (const [id, edge] of this.edges) if (nodes.has(edge.data.source) && nodes.has(edge.data.target)) edges.add(id);
      return { nodes, edges };
    }

    drawLaneGuides(ctx) {
      if (!this.focus || this.viewMode === "overview") return;
      const focus = this.nodes.get(this.focus);
      if (!focus) return;
      const point = this.nodePoint(focus);
      const groupPoints = (group) => [...this.nodes.values()]
        .filter((node) => node.layoutDepth === 1 && node.spatialGroup === group)
        .map((node) => this.nodePoint(node));
      const labelPosition = (group, fallbackX, fallbackY) => {
        const positions = groupPoints(group);
        if (!positions.length) return [fallbackX, fallbackY];
        const x = positions.reduce((sum, current) => sum + current.x, 0) / positions.length;
        const minY = Math.min(...positions.map((current) => current.y));
        const maxY = Math.max(...positions.map((current) => current.y));
        if (group === "retrieval") return [x, Math.min(this.height - 28, maxY + 52)];
        const above = minY - 52;
        return [x, above >= 104 ? above : Math.min(this.height - 28, maxY + 52)];
      };
      const labels = [
        ["HERKUNFT", ...labelPosition("origin", point.x - 245 * this.scale, Math.max(104, point.y - 220 * this.scale))],
        ["FOLGEN", ...labelPosition("consequence", point.x + 245 * this.scale, Math.max(104, point.y - 220 * this.scale))],
        ["KONTEXT", ...labelPosition("context", point.x, Math.max(104, point.y - 220 * this.scale))],
        ["RETRIEVAL", ...labelPosition("retrieval", point.x, Math.min(this.height - 28, point.y + 220 * this.scale))],
      ];
      ctx.save(); ctx.font = "650 9px ui-monospace, monospace"; ctx.textAlign = "center";
      for (const [label, x, y] of labels) {
        ctx.fillStyle = "rgba(4,16,24,.76)"; ctx.strokeStyle = "rgba(100,220,212,.1)"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.roundRect(x - 43, y - 11, 86, 22, 11); ctx.fill(); ctx.stroke();
        ctx.fillStyle = "rgba(124,174,179,.7)"; ctx.fillText(label, x, y + 3);
      }
      ctx.restore();
    }

    drawContinuationStubs(ctx) {
      if (!this.focus || this.viewMode === "overview") return;
      const groups = brainwatchPendingGroups.get(this.focus);
      const focus = this.nodes.get(this.focus);
      if (!groups || !focus) return;
      const point = this.nodePoint(focus);
      const vectors = { origin: [-1, 0], consequence: [1, 0], context: [0, -1], retrieval: [0, 1] };
      ctx.save(); ctx.font = "650 9px ui-monospace, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (const [group, [dx, dy]] of Object.entries(vectors)) {
        const pending = groups.get(group);
        const remaining = pending ? pending.edges.length - pending.revealed : 0;
        if (remaining <= 0) continue;
        const startX = point.x + dx * 94 * this.scale, startY = point.y + dy * 43 * this.scale;
        const endX = startX + dx * 42, endY = startY + dy * 42;
        ctx.setLineDash([3, 5]); ctx.strokeStyle = "rgba(113,210,203,.42)"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(startX, startY); ctx.lineTo(endX, endY); ctx.stroke();
        ctx.setLineDash([]); ctx.fillStyle = "rgba(130,204,199,.75)";
        ctx.fillText(`+${remaining}`, endX + (dy ? 18 : dx * 17), endY + (dx ? -10 : dy * 13));
      }
      ctx.restore();
    }

    graphDistances() {
      const distances = new Map();
      if (!this.focus || !this.nodes.has(this.focus)) return distances;
      distances.set(this.focus, 0);
      const queue = [this.focus];
      while (queue.length) {
        const current = queue.shift();
        const distance = distances.get(current);
        for (const edge of this.edges.values()) {
          let next = null;
          if (edge.data.source === current) next = edge.data.target;
          else if (edge.data.target === current) next = edge.data.source;
          if (next && !distances.has(next)) { distances.set(next, distance + 1); queue.push(next); }
        }
      }
      return distances;
    }

    drawEdge(edge) {
      const ctx = this.ctx, a = this.nodes.get(edge.data.source), b = this.nodes.get(edge.data.target);
      if (!a || !b) return;
      const p1 = this.nodePoint(a), p2 = this.nodePoint(b);
      const styles = {
        factual: ["rgba(117,201,196,.55)", []], lineage: ["rgba(236,211,129,.72)", []],
        retrieval: ["rgba(175,139,235,.7)", [7, 5]], semantic_similarity: ["rgba(89,156,205,.55)", [2, 6]],
        lexical_match: ["rgba(122,151,158,.55)", [10, 5, 2, 5]],
      };
      const [color, dash] = styles[edge.data.category] || styles.factual;
      const distances = this.distanceCache || this.graphDistances();
      const distance = Math.min(distances.get(edge.data.source) ?? 9, distances.get(edge.data.target) ?? 9);
      const active = distance === 0;
      const intensity = active ? 1 : distance === 1 ? .48 : distance === 2 ? .2 : .07;
      ctx.save(); ctx.globalAlpha = intensity; ctx.strokeStyle = color; ctx.fillStyle = color;
      ctx.lineWidth = edge.data.category === "lineage" ? (active ? 2.8 : distance === 1 ? 1.7 : 1.1) : (active ? 1.8 : distance === 1 ? 1.25 : .85); ctx.setLineDash(dash);
      if (distance === 1) ctx.setLineDash([4, 6]);
      if (active && edge.data.category === "lineage") { ctx.shadowColor="#65fff1"; ctx.shadowBlur=12; }
      if (active && edge.data.category === "retrieval") { ctx.shadowColor="#aa8cff"; ctx.shadowBlur=6; }
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y);
      if (Math.abs(p2.x-p1.x) >= Math.abs(p2.y-p1.y)) {
        ctx.bezierCurveTo((p1.x+p2.x)/2, p1.y, (p1.x+p2.x)/2, p2.y, p2.x, p2.y);
      } else {
        ctx.bezierCurveTo(p1.x, (p1.y+p2.y)/2, p2.x, (p1.y+p2.y)/2, p2.x, p2.y);
      }
      ctx.stroke();
      const angle = Math.atan2(p2.y-p1.y, p2.x-p1.x); const ex = p2.x-Math.cos(angle)*29*this.scale, ey=p2.y-Math.sin(angle)*29*this.scale;
      ctx.setLineDash([]); ctx.beginPath(); ctx.moveTo(ex,ey); ctx.lineTo(ex-Math.cos(angle-.55)*7,ey-Math.sin(angle-.55)*7); ctx.lineTo(ex-Math.cos(angle+.55)*7,ey-Math.sin(angle+.55)*7); ctx.closePath(); ctx.fill();
      if (this.scale > .55 && (active || this.selected === edge.data.id || this.hoveredEdge === edge.data.id)) {
        ctx.shadowBlur=0; ctx.globalAlpha=1; ctx.font = "500 10px system-ui"; ctx.textAlign = "center";
        const labelX=(p1.x+p2.x)/2, labelY=(p1.y+p2.y)/2-7;
        const labelWidth=Math.min(160,ctx.measureText(edge.data.label).width+14);
        ctx.fillStyle="rgba(2,12,18,.9)";ctx.strokeStyle="rgba(112,224,215,.16)";ctx.lineWidth=1;
        ctx.beginPath();ctx.roundRect(labelX-labelWidth/2,labelY-12,labelWidth,18,9);ctx.fill();ctx.stroke();
        ctx.fillStyle = "#b8ddda";ctx.fillText(edge.data.label,labelX,labelY+1,labelWidth-8);
      }
      ctx.restore();
    }

    drawNode(node) {
      const ctx = this.ctx, p = this.nodePoint(node), focused = node.data.id === this.focus;
      const distance = (this.distanceCache || this.graphDistances()).get(node.data.id) ?? 9;
      const neighbor = distance === 1;
      const intensity = focused ? 1 : neighbor ? .88 : distance === 2 ? .48 : .16;
      const width=(focused?172:148)*this.scale, height=(focused?68:58)*this.scale;
      const claimKind = node.data.type === "claim" ? node.data.metadata?.claim_kind : null;
      const color = MEMORY_CLAIM_COLORS[claimKind] || BRAINWATCH_COLORS[node.data.type] || "#74dcd2";
      ctx.save(); ctx.translate(p.x, p.y); ctx.globalAlpha=intensity*Math.max(.08,p.progress ?? 1);
      if (focused) { ctx.shadowColor="#62fff0";ctx.shadowBlur=24; }
      else if (neighbor) { ctx.shadowColor="rgba(85,235,222,.65)";ctx.shadowBlur=9; }
      const fill=ctx.createLinearGradient(-width/2,-height/2,width/2,height/2); fill.addColorStop(0,"rgba(7,28,36,.96)");fill.addColorStop(1,"rgba(3,13,22,.94)");
      ctx.fillStyle=fill;ctx.strokeStyle=focused?"#73fff0":color;ctx.lineWidth=focused?2.3:1;
      if(distance===2)ctx.setLineDash([4,5]);
      ctx.beginPath();ctx.roundRect(-width/2,-height/2,width,height,focused?15:12);ctx.fill();ctx.stroke();
      ctx.setLineDash([]);
      if(focused){ctx.shadowBlur=0;ctx.strokeStyle="rgba(112,255,241,.28)";ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(-width/2-6,-height/2-6,width+12,height+12,19);ctx.stroke();}
      const iconX=-width/2+22*this.scale;
      ctx.beginPath();ctx.arc(iconX,0,12*this.scale,0,Math.PI*2);ctx.fillStyle="rgba(79,220,210,.1)";ctx.fill();ctx.strokeStyle=color;ctx.stroke();
      const typeMark = MEMORY_CLAIM_MARKS[claimKind] || BRAINWATCH_TYPE_MARKS[node.data.type] || "?";
      ctx.fillStyle=color;ctx.textAlign="center";ctx.textBaseline="middle";ctx.font=`600 ${Math.max(6,7*this.scale)}px system-ui`;ctx.fillText(typeMark,iconX,0);
      const typeLabel = claimKind ? claimKind.replaceAll("_", " ") : node.data.type.replaceAll("-"," ");
      ctx.textAlign="left";ctx.textBaseline="alphabetic";ctx.fillStyle=focused?"#9dfff4":"#75c9c5";ctx.font=`650 ${Math.max(7,8*this.scale)}px system-ui`;ctx.fillText(typeLabel.toUpperCase(),-width/2+43*this.scale,-8*this.scale);
      const label=node.data.label.length>34?node.data.label.slice(0,33)+"…":node.data.label;
      ctx.fillStyle=focused?"#ecffff":"#c0d8d8";ctx.font=`500 ${Math.max(8,10*this.scale)}px system-ui`;ctx.fillText(label,-width/2+43*this.scale,11*this.scale,width-51*this.scale);
      const secondary = node.data.timestamp ? String(node.data.timestamp).replace("T", " · ").slice(0, 16) : (node.data.metadata?.role || "");
      if (secondary && this.scale > .62) { ctx.fillStyle="#587b80";ctx.font=`400 ${Math.max(6,7*this.scale)}px system-ui`;ctx.fillText(secondary,-width/2+43*this.scale,23*this.scale,width-55*this.scale); }
      const expanded=this.isExpanded(node.data.id);ctx.textAlign="center";ctx.fillStyle=expanded?"#77f4e7":"#628b91";ctx.font=`500 ${Math.max(8,10*this.scale)}px system-ui`;ctx.fillText(expanded?"−":"+",width/2-11*this.scale,-height/2+14*this.scale);
      ctx.restore();
    }
  }

  let brainwatchMode = "information";
  let brainwatchPage = null;
  let memoryClaimsCursor = null;
  let memoryRelationCache = { claimId: null, items: [] };
  let memoryExplorerSubview = "cloud";
  let memoryCloudRenderer = null;
  let avatarCloudRenderer = null;
  let avatarCloudLoad = null;
  let avatarCloudRefreshTimer = null;
  let avatarCloudActivityTimer = null;
  let avatarCloudActivityFinishTimer = null;
  let avatarCloudActivityBusy = false;
  let avatarCloudActivityTurn = "";
  let avatarCloudActivityCursor = "";
  let avatarCloudActivityEvents = [];
  let avatarCloudActivityIds = new Set();
  let avatarCloudActivityComplete = false;
  let avatarCloudImpulseQueue = [];
  let avatarCloudImpulseTimer = null;
  let avatarCloudDemoStarted = false;
  let avatarCloudDemoTimers = [];
  const BRAINWATCH_NEUROCLOUD_PROFILE = Object.freeze({
    quality: "medium",
    intensity: 1,
    haloStrength: .14,
    fogStrength: .38,
    densityAwareExposure: true,
    densityReference: 460,
    relationStrength: 2.4,
    boundedBaseBlend: true,
    additiveRelations: true,
  });
  let memoryCloudCursor = null;
  let memoryCloudAnchor = null;
  let memoryCloudNodes = new Map();
  let memoryCloudEdges = new Map();
  let memoryCloudPinnedSelection = null;
  let memoryCloudLearningHighlight = null;
  let memoryCloudLayoutVersion = "neurocloud-layout-v3-provenance-regions";
  let memoryCloudActivityEvents = [];
  let memoryCloudActivityPattern = null;
  let memoryCloudActivityIndex = -1;
  let memoryCloudActivityTimer = null;
  let memoryCloudActivityTurn = "";
  let memoryCloudActivityComplete = false;
  let memoryCloudLiveCursor = "";
  let memoryCloudLiveTimer = null;
  let memoryCloudLiveBusy = false;
  const MEMORY_CLOUD_ACTIVITY_LIMIT = 5000;
  let memoryWorkingLayer = null;
  let memoryTimelineCursor = { historical: null, runtime: null };
  let memoryTimelineHasMore = { historical: false, runtime: false };
  let memoryTimelineEvents = [];
  let memoryTimelineIndex = -1;
  let memoryTimelineTimer = null;
  const brainwatchViewStates = new Map();
  const brainwatchPendingGroups = new Map();
  const BRAINWATCH_DIRECT_LIMIT = 5;
  const BRAINWATCH_INITIAL_GROUP_LIMIT = 2;
  let brainwatchFocusHistory = [];

  function groupedBrainwatchPayload(data, nodeId) {
    const nodes = new Map((data.nodes || []).map((node) => [node.id, node]));
    const groups = new Map();
    for (const edge of data.edges || []) {
      const key = brainwatchSpatialGroup(edge, nodeId);
      if (!groups.has(key)) groups.set(key, { key, edges: [], nodes, revealed: 0 });
      groups.get(key).edges.push(edge);
    }
    return groups;
  }

  function brainwatchGroupSlice(nodeId, group, count = BRAINWATCH_DIRECT_LIMIT) {
    const edges = group.edges.slice(group.revealed, group.revealed + count);
    group.revealed += edges.length;
    const ids = new Set([nodeId]);
    for (const edge of edges) { ids.add(edge.source); ids.add(edge.target); }
    return {
      focus: nodeId,
      nodes: [...ids].map((id) => group.nodes.get(id)).filter(Boolean),
      edges,
    };
  }

  function renderBrainwatchGroups(nodeId) {
    const groups = brainwatchPendingGroups.get(nodeId);
    elements.brainwatchGroups.replaceChildren();
    if (!groups?.size || brainwatchGraph.focus !== nodeId) {
      elements.brainwatchGroups.hidden = true;
      elements.brainwatchGroups.removeAttribute("data-parent-id");
      return;
    }
    elements.brainwatchGroups.dataset.parentId = nodeId;
    for (const key of ["origin", "consequence", "context", "retrieval"]) {
      const group = groups.get(key);
      if (!group) continue;
      const remaining = group.edges.length - group.revealed;
      if (remaining <= 0) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `brainwatch-group eve-button eve-button--ghost group-${key}`;
      button.dataset.group = key;
      button.textContent = `${BRAINWATCH_SPATIAL_GROUPS[key].label} +${remaining}`;
      button.addEventListener("click", () => {
        const payload = brainwatchGroupSlice(nodeId, group);
        brainwatchGraph.merge(payload, nodeId);
        renderBrainwatchGroups(nodeId);
        const status = brainwatchMode === "memory" ? elements.memoryExplorerStatus : elements.brainwatchStatus;
        status.textContent = `${payload.edges.length} Beziehungen im Bereich ${BRAINWATCH_SPATIAL_GROUPS[key].label.toLowerCase()} geöffnet.`;
        updateBrainwatchControls();
      });
      elements.brainwatchGroups.append(button);
    }
    elements.brainwatchGroups.hidden = !elements.brainwatchGroups.childElementCount;
    brainwatchGraph.positionGroupOverlay();
  }

  function stageBrainwatchNeighbors(data, nodeId, cursor) {
    const edges = data.edges || [];
    if (cursor === 0 && edges.length <= BRAINWATCH_DIRECT_LIMIT) {
      brainwatchGraph.merge(data, nodeId);
      brainwatchPendingGroups.delete(nodeId);
      renderBrainwatchGroups(nodeId);
      return { grouped: false, count: edges.length };
    }
    if (cursor > 0 && brainwatchPendingGroups.has(nodeId)) {
      const current = brainwatchPendingGroups.get(nodeId);
      for (const [key, incoming] of groupedBrainwatchPayload(data, nodeId)) {
        const group = current.get(key);
        if (group) {
          for (const [id, node] of incoming.nodes) group.nodes.set(id, node);
          for (const edge of incoming.edges) if (!group.edges.some((item) => item.id === edge.id)) group.edges.push(edge);
        } else current.set(key, incoming);
      }
      renderBrainwatchGroups(nodeId);
      return { grouped: true, count: edges.length };
    }
    const focusNode = (data.nodes || []).find((node) => node.id === nodeId);
    if (focusNode) brainwatchGraph.merge({ focus: nodeId, nodes: [focusNode], edges: [] }, nodeId);
    const groups = groupedBrainwatchPayload(data, nodeId);
    brainwatchPendingGroups.set(nodeId, groups);
    for (const group of groups.values()) {
      const payload = brainwatchGroupSlice(nodeId, group, BRAINWATCH_INITIAL_GROUP_LIMIT);
      if (payload.edges.length) brainwatchGraph.merge(payload, nodeId);
    }
    renderBrainwatchGroups(nodeId);
    return { grouped: true, count: edges.length };
  }

  function rememberBrainwatchFocus(nodeId) {
    if (!nodeId) return;
    if (brainwatchFocusHistory.at(-1) !== nodeId) brainwatchFocusHistory.push(nodeId);
    brainwatchFocusHistory = brainwatchFocusHistory.slice(-6);
    renderBrainwatchPath();
  }

  function renderBrainwatchPath() {
    elements.brainwatchPath.replaceChildren();
    if (brainwatchMode !== "information" || brainwatchFocusHistory.length < 2) {
      elements.brainwatchPath.hidden = true;
      return;
    }
    brainwatchFocusHistory.forEach((nodeId, index) => {
      if (index) {
        const separator = document.createElement("span"); separator.textContent = "›"; separator.setAttribute("aria-hidden", "true");
        elements.brainwatchPath.append(separator);
      }
      const node = brainwatchGraph.nodes.get(nodeId)?.data;
      const button = document.createElement("button"); button.type = "button";
      button.className = "eve-button eve-button--ghost";
      button.textContent = node?.label || nodeId;
      button.title = node?.label || nodeId;
      button.setAttribute("aria-current", nodeId === brainwatchGraph.focus ? "location" : "false");
      button.addEventListener("click", () => {
        focusBrainwatchNode(nodeId).catch((error) => { elements.brainwatchStatus.textContent = error.message; });
      });
      elements.brainwatchPath.append(button);
    });
    elements.brainwatchPath.hidden = false;
  }

  function updateBrainwatchControls() {
    const focused = brainwatchGraph.focus;
    const expanded = focused && brainwatchGraph.isExpanded(focused);
    elements.brainwatchToggleBranch.disabled = !focused;
    elements.brainwatchToggleBranch.textContent = expanded ? "EINKLAPPEN" : "AUFKLAPPEN";
    elements.brainwatchContextView.disabled = !focused;
    elements.brainwatchFlowView.disabled = !focused;
    elements.brainwatchOverviewView.disabled = !focused;
    elements.brainwatchContextView.setAttribute("aria-pressed", String(brainwatchGraph.viewMode === "context"));
    elements.brainwatchFlowView.setAttribute("aria-pressed", String(brainwatchGraph.viewMode === "flow"));
    elements.brainwatchOverviewView.setAttribute("aria-pressed", String(brainwatchGraph.viewMode === "overview"));
    renderBrainwatchPath();
  }

  function renderBrainwatchInspector(selection) {
    const inspector = elements.brainwatchInspector;
    inspector.replaceChildren();
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = selection.kind === "edge" ? "WARUM VERBUNDEN?" : "AUSGEWÄHLTER KNOTEN";
    const value = selection.value;
    const title = document.createElement("h2"); title.textContent = selection.kind === "edge" ? value.label : value.label;
    const description = document.createElement("p");
    description.textContent = selection.kind === "edge"
      ? (value.metadata?.evidence || `Diese persistierte Relation verbindet Quelle und Ziel als „${value.label}“.`)
      : (value.preview || `${value.type} · persistent`);
    const details = document.createElement("dl");
    const sourceNode = selection.kind === "edge" ? brainwatchGraph.nodes.get(value.source)?.data : null;
    const targetNode = selection.kind === "edge" ? brainwatchGraph.nodes.get(value.target)?.data : null;
    const edgeArea = selection.kind === "edge" && [value.source, value.target].includes(brainwatchGraph.focus)
      ? BRAINWATCH_SPATIAL_GROUPS[brainwatchSpatialGroup(value, brainwatchGraph.focus)]?.label
      : value.category;
    const fields = selection.kind === "edge"
      ? [["Relation", value.type], ["Bereich", edgeArea], ["Quelle", sourceNode?.label || value.source], ["Ziel", targetNode?.label || value.target], ["Gespeichert", value.persistent ? "ja" : "nein"]]
      : [["Typ", value.type], ["ID", value.id], ["Zeit", value.timestamp || "nicht aufgezeichnet"], ["Persistent", value.persistent ? "ja" : "nein"]];
    for (const [key, fieldValue] of fields) {
      const dt = document.createElement("dt"); dt.textContent = key;
      const dd = document.createElement("dd"); dd.textContent = String(fieldValue ?? "–");
      details.append(dt, dd);
    }
    inspector.append(eyebrow, title, description, details);
    if (selection.kind === "node") {
      const counts = { origin: 0, consequence: 0, context: 0, retrieval: 0 };
      for (const edge of brainwatchGraph.edges.values()) {
        if (edge.data.source !== value.id && edge.data.target !== value.id) continue;
        counts[brainwatchSpatialGroup(edge.data, value.id)] += 1;
      }
      const summary = document.createElement("div"); summary.className = "brainwatch-relation-summary";
      for (const key of ["origin", "consequence", "context", "retrieval"]) {
        const item = document.createElement("span");
        const count = document.createElement("strong"); count.textContent = String(counts[key]);
        item.append(count, BRAINWATCH_SPATIAL_GROUPS[key].label);
        summary.append(item);
      }
      inspector.append(summary);
    }
    if (selection.kind === "node" && value.type === "message" && value.metadata?.turn_lineage_recorded === false) {
      const notice = document.createElement("p"); notice.textContent = "Für diesen historischen Eintrag wurde keine Turn-Lineage aufgezeichnet."; inspector.append(notice);
    }
    if (selection.kind === "node" && value.type === "asset" && value.metadata?.preview_url) {
      const image = document.createElement("img"); image.alt = value.label; image.src = value.metadata.preview_url; inspector.append(image);
    }
    const metadata = value.metadata || {};
    if (Object.keys(metadata).length) {
      const raw = document.createElement("details");
      const summary = document.createElement("summary"); summary.textContent = "Erlaubte Rohdetails";
      const pre = document.createElement("pre"); pre.textContent = JSON.stringify(metadata, null, 2);
      raw.append(summary, pre); inspector.append(raw);
    }
    if (selection.kind === "node" && value.type === "turn") {
      const participation = memorySection(inspector, "Memory-Beteiligung");
      const notice = document.createElement("p"); notice.className = "memory-participation-notice";
      notice.textContent = "Bei diesem Turn beteiligt ist nicht gleich von EVE tatsächlich verwendet.";
      const status = document.createElement("p"); status.textContent = "Persistente Memory-Verknüpfungen werden gelesen …";
      participation.append(notice, status);
      loadTurnMemoryParticipation(value.id, participation, status).catch((error) => {
        status.textContent = error.message;
      });
      const runtime = memorySection(inspector, "Memory-Runtime");
      const runtimeStatus = document.createElement("p"); runtimeStatus.textContent = "Persistierte Runtime-Ereignisse werden gelesen …";
      runtime.append(runtimeStatus);
      loadTurnRuntime(value.id, runtime, runtimeStatus).catch((error) => { runtimeStatus.textContent = error.message; });
    }
  }

  async function focusBrainwatchNode(nodeId, { cursor = 0, anchor = false } = {}) {
    brainwatchGraph.setFocus(nodeId);
    if (anchor) brainwatchGraph.anchors.add(nodeId);
    updateBrainwatchControls();
    elements.brainwatchStatus.textContent = "Beziehungen werden gelesen …";
    const query = new URLSearchParams({ limit: "30", cursor: String(cursor) });
    const response = await fetchWithTimeout(`/api/brainwatch/nodes/${encodeURIComponent(nodeId)}/neighbors?${query}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Brainwatch");
    if (!response.ok) throw new Error(data.error || "Beziehungen konnten nicht geladen werden.");
    const staged = stageBrainwatchNeighbors(data, nodeId, cursor);
    const node = brainwatchGraph.nodes.get(nodeId)?.data;
    if (node) renderBrainwatchInspector({ kind: "node", value: node });
    rememberBrainwatchFocus(nodeId);
    brainwatchPage = data.page?.has_more ? { nodeId, cursor: data.page.next_cursor } : null;
    elements.brainwatchMore.hidden = !brainwatchPage;
    elements.brainwatchMore.textContent = brainwatchPage ? "+ WEITERE BEZIEHUNGEN" : "";
    elements.brainwatchStatus.textContent = staged.grouped
      ? `${staged.count} Beziehungen nach räumlichen Bereichen verfügbar.`
      : `${staged.count} direkte Beziehungen geladen.`;
    updateBrainwatchControls();
  }

  function selectBrainwatchGraphItem(selection) {
    if (brainwatchMode === "memory") {
      if (selection.kind === "edge") {
        renderMemoryRelationInspector(selection.value);
        return;
      }
      if (selection.value.type === "claim") {
        brainwatchGraph.setFocus(selection.value.id);
        renderBrainwatchGroups(selection.value.id);
        updateBrainwatchControls();
        if (!brainwatchGraph.isExpanded(selection.value.id)) {
          focusMemoryClaim(selection.value.id).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
        }
        return;
      }
    }
    if (selection.kind === "node") {
      brainwatchGraph.setFocus(selection.value.id);
      rememberBrainwatchFocus(selection.value.id);
      renderBrainwatchGroups(selection.value.id);
      updateBrainwatchControls();
      if (!brainwatchGraph.isExpanded(selection.value.id)) {
        focusBrainwatchNode(selection.value.id).catch((error) => { elements.brainwatchStatus.textContent = error.message; });
        return;
      }
    }
    renderBrainwatchInspector(selection);
  }

  const brainwatchGraph = new BrainwatchGraph(elements.brainwatchCanvas, selectBrainwatchGraphItem);

  const BRAINWATCH_LAYOUT_KEY = "eve.brainwatchLayout.v1";
  const BRAINWATCH_LAYOUT_DEFAULTS = {
    information: { navigation: 266, inspector: 292, navigationCollapsed: false, inspectorCollapsed: false },
    memory: { navigation: 286, inspector: 330, navigationCollapsed: false, inspectorCollapsed: false },
    semantic: { navigation: 280, inspector: 340, navigationCollapsed: false, inspectorCollapsed: false },
    statistics: { navigation: 250, inspector: 300, navigationCollapsed: false, inspectorCollapsed: false },
    events: { navigation: 250, inspector: 300, navigationCollapsed: false, inspectorCollapsed: false },
  };

  function validBrainwatchLayout(value, defaults) {
    const navigation = Number(value?.navigation);
    const inspector = Number(value?.inspector);
    return {
      navigation: Number.isFinite(navigation) && navigation >= 210 && navigation <= 480 ? navigation : defaults.navigation,
      inspector: Number.isFinite(inspector) && inspector >= 230 && inspector <= 520 ? inspector : defaults.inspector,
      navigationCollapsed: typeof value?.navigationCollapsed === "boolean" ? value.navigationCollapsed : defaults.navigationCollapsed,
      inspectorCollapsed: typeof value?.inspectorCollapsed === "boolean" ? value.inspectorCollapsed : defaults.inspectorCollapsed,
    };
  }

  function loadBrainwatchLayouts() {
    let saved = {};
    try { saved = JSON.parse(window.localStorage.getItem(BRAINWATCH_LAYOUT_KEY) || "{}"); }
    catch (_) { saved = {}; }
    return Object.fromEntries(Object.entries(BRAINWATCH_LAYOUT_DEFAULTS).map(([mode, defaults]) => (
      [mode, validBrainwatchLayout(saved?.[mode], defaults)]
    )));
  }

  let brainwatchLayouts = loadBrainwatchLayouts();

  function saveBrainwatchLayouts() {
    try { window.localStorage.setItem(BRAINWATCH_LAYOUT_KEY, JSON.stringify(brainwatchLayouts)); }
    catch (_) { /* The layout remains usable for this session. */ }
  }

  function boundedBrainwatchWidths(layout, changed = "") {
    let navigation = Math.min(480, Math.max(210, Number(layout.navigation) || 266));
    let inspector = Math.min(520, Math.max(230, Number(layout.inspector) || 292));
    if (window.innerWidth >= 900) {
      const shellWidth = elements.brainwatchView.getBoundingClientRect().width || window.innerWidth - 36;
      const sideBudget = Math.max(440, shellWidth - 20 - 360);
      if (navigation + inspector > sideBudget) {
        if (changed === "navigation") {
          navigation = Math.max(210, sideBudget - inspector);
          if (navigation + inspector > sideBudget) inspector = Math.max(230, sideBudget - navigation);
        } else if (changed === "inspector") {
          inspector = Math.max(230, sideBudget - navigation);
          if (navigation + inspector > sideBudget) navigation = Math.max(210, sideBudget - inspector);
        }
        else {
          const excess = navigation + inspector - sideBudget;
          const navigationRoom = navigation - 210;
          const navigationCut = Math.min(navigationRoom, excess / 2);
          navigation -= navigationCut;
          inspector = Math.max(230, sideBudget - navigation);
        }
      }
    }
    return { navigation, inspector };
  }

  function applyBrainwatchLayout({ persist = true, changed = "" } = {}) {
    const layout = brainwatchLayouts[brainwatchMode];
    const bounded = boundedBrainwatchWidths(layout, changed);
    layout.navigation = bounded.navigation; layout.inspector = bounded.inspector;
    elements.brainwatchView.style.setProperty("--brainwatch-navigation-width", `${bounded.navigation}px`);
    elements.brainwatchView.style.setProperty("--brainwatch-inspector-width", `${bounded.inspector}px`);
    elements.brainwatchView.classList.toggle("navigation-collapsed", layout.navigationCollapsed);
    elements.brainwatchView.classList.toggle("inspector-collapsed", layout.inspectorCollapsed);
    elements.brainwatchSearchCollapse.setAttribute("aria-expanded", String(!layout.navigationCollapsed));
    elements.brainwatchSearchCollapse.setAttribute("aria-label", layout.navigationCollapsed ? "Navigation öffnen" : "Navigation einklappen");
    elements.brainwatchSearchCollapse.textContent = layout.navigationCollapsed ? "›" : "‹";
    elements.brainwatchInspectorCollapse.setAttribute("aria-expanded", String(!layout.inspectorCollapsed));
    elements.brainwatchInspectorCollapse.setAttribute("aria-label", layout.inspectorCollapsed ? "Inspektor öffnen" : "Inspektor einklappen");
    elements.brainwatchInspectorCollapse.textContent = layout.inspectorCollapsed ? "‹" : "›";
    elements.brainwatchNavigationResize.setAttribute("aria-valuenow", String(Math.round(bounded.navigation)));
    elements.brainwatchInspectorResize.setAttribute("aria-valuenow", String(Math.round(bounded.inspector)));
    if (persist) saveBrainwatchLayouts();
    window.requestAnimationFrame(() => brainwatchGraph.resize());
  }

  function setBrainwatchColumnWidth(side, width) {
    const layout = brainwatchLayouts[brainwatchMode];
    layout[side] = width;
    applyBrainwatchLayout({ changed: side });
  }

  function toggleBrainwatchColumn(side) {
    const key = `${side}Collapsed`;
    brainwatchLayouts[brainwatchMode][key] = !brainwatchLayouts[brainwatchMode][key];
    applyBrainwatchLayout();
  }

  function resetBrainwatchLayout(side = "") {
    const defaults = BRAINWATCH_LAYOUT_DEFAULTS[brainwatchMode];
    if (side) brainwatchLayouts[brainwatchMode][side] = defaults[side];
    else brainwatchLayouts[brainwatchMode] = { ...defaults };
    applyBrainwatchLayout({ changed: side });
  }

  function attachBrainwatchResize(handle, side) {
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || window.innerWidth < 900) return;
      event.preventDefault(); event.stopPropagation();
      const startX = event.clientX;
      const startWidth = brainwatchLayouts[brainwatchMode][side];
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("brainwatch-resizing"); handle.classList.add("resizing");
      const move = (moveEvent) => {
        const delta = moveEvent.clientX - startX;
        setBrainwatchColumnWidth(side, startWidth + (side === "navigation" ? delta : -delta));
      };
      const stop = () => {
        document.body.classList.remove("brainwatch-resizing"); handle.classList.remove("resizing");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        handle.removeEventListener("lostpointercapture", stop);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
      handle.addEventListener("lostpointercapture", stop);
    });
    handle.addEventListener("dblclick", () => resetBrainwatchLayout(side));
    handle.addEventListener("keydown", (event) => {
      if (!new Set(["ArrowLeft", "ArrowRight"]).has(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      setBrainwatchColumnWidth(side, brainwatchLayouts[brainwatchMode][side] + direction * (side === "navigation" ? 20 : -20));
    });
  }

  function storeBrainwatchViewState() {
    if (new Set(["semantic", "statistics", "events"]).has(brainwatchMode)) return;
    brainwatchViewStates.set(brainwatchMode, {
      graph: brainwatchGraph.captureState(), page: brainwatchPage,
      pending: new Map(brainwatchPendingGroups),
      memoryRelationCache: { claimId: memoryRelationCache.claimId, items: [...memoryRelationCache.items] },
      inspectorNodes: [...elements.brainwatchInspector.childNodes],
    });
  }

  function restoreBrainwatchViewState(mode) {
    const saved = brainwatchViewStates.get(mode);
    brainwatchGraph.restoreState(saved?.graph || null);
    brainwatchPage = saved?.page || null;
    brainwatchPendingGroups.clear();
    for (const [key, value] of saved?.pending || []) brainwatchPendingGroups.set(key, value);
    memoryRelationCache = saved?.memoryRelationCache || { claimId: null, items: [] };
    if (saved?.inspectorNodes?.length) elements.brainwatchInspector.replaceChildren(...saved.inspectorNodes);
    renderBrainwatchGroups(brainwatchGraph.focus);
    elements.brainwatchMore.hidden = !brainwatchPage;
    if (brainwatchPage) elements.brainwatchMore.textContent = mode === "memory" ? "+ WEITERE RELATIONS" : "+ WEITERE BEZIEHUNGEN";
    updateBrainwatchControls();
    return saved;
  }

  function renderBrainwatchResults(data) {
    elements.brainwatchResults.replaceChildren();
    for (const node of data.nodes || []) {
      const button = document.createElement("button"); button.type = "button"; button.className = "brainwatch-result eve-surface";
      const mark = document.createElement("span"); mark.className = "brainwatch-type-mark"; mark.textContent = BRAINWATCH_TYPE_MARKS[node.type] || "?";
      const copy = document.createElement("span");
      const title = document.createElement("strong"); title.textContent = node.label;
      const type = document.createElement("small"); type.textContent = `${node.type} · ${node.timestamp || "ohne Zeit"}`;
      copy.append(title, type); button.append(mark, copy);
      button.addEventListener("click", () => focusBrainwatchNode(node.id, { anchor: true }).catch((error) => { elements.brainwatchStatus.textContent = error.message; }));
      elements.brainwatchResults.append(button);
    }
    elements.brainwatchStatus.textContent = `${data.nodes?.length || 0} Treffer.`;
  }

  function memoryClaimNode(claim) {
    return {
      id: claim.id, type: "claim", label: claim.display_text || claim.claim_id,
      timestamp: claim.updated_at, persistent: true,
      preview: `${claim.claim_kind} · ${claim.scope} · ${claim.lifecycle}`,
      metadata: {
        claim_id: claim.claim_id, claim_kind: claim.claim_kind, scope: claim.scope,
        lifecycle: claim.lifecycle, verification_policy: claim.verification_policy,
        valid_from: claim.valid_from, valid_until: claim.valid_until,
      },
    };
  }

  function memoryRelationGraphPayload(claim, relations) {
    const nodes = new Map([[claim.id, memoryClaimNode(claim)]]);
    const edges = [];
    for (const relation of relations.items || []) {
      for (const related of [relation.from_claim, relation.to_claim]) nodes.set(related.id, memoryClaimNode(related));
      edges.push({
        id: relation.id, source: relation.from_claim.id, target: relation.to_claim.id,
        type: relation.relation_type, category: "lineage", label: relation.relation_type,
        persistent: true, metadata: { relation },
      });
    }
    return { focus: claim.id, nodes: [...nodes.values()], edges, page: relations.page };
  }

  function appendMemoryFields(parent, fields) {
    const list = document.createElement("dl");
    for (const [label, value] of fields) {
      const dt = document.createElement("dt"); dt.textContent = label;
      const dd = document.createElement("dd"); dd.textContent = value == null || value === "" ? "nicht aufgezeichnet" : String(value);
      list.append(dt, dd);
    }
    parent.append(list);
    return list;
  }

  function memorySection(parent, titleText) {
    const section = document.createElement("section"); section.className = "memory-inspector-section";
    const title = document.createElement("h3"); title.textContent = titleText;
    section.append(title); parent.append(section); return section;
  }

  function memoryClaimButton(claim, label = claim.display_text || claim.claim_id) {
    const button = document.createElement("button"); button.type = "button";
    button.className = "memory-link eve-button eve-button--ghost"; button.textContent = label;
    button.addEventListener("click", () => focusMemoryClaim(claim.id, { anchor: true }).catch((error) => {
      elements.memoryExplorerStatus.textContent = error.message;
    }));
    return button;
  }

  function memoryParticipationCard(item, direction) {
    const card = document.createElement("article"); card.className = `memory-participation origin-${item.origin_class}`;
    const heading = document.createElement("strong");
    heading.textContent = direction === "claim-to-turn"
      ? `${item.turn.conversation_title || "Conversation"} · ${item.turn.turn_id}`
      : (item.claim.display_text || item.claim.claim_id);
    const badge = document.createElement("span"); badge.className = "memory-origin-badge"; badge.textContent = item.origin_label;
    const context = document.createElement("p"); context.textContent = item.interpretation;
    const navigate = document.createElement("button"); navigate.type = "button"; navigate.className = "memory-link eve-button eve-button--ghost";
    if (direction === "claim-to-turn") {
      navigate.textContent = "TURN IM INFORMATIONSGRAPH ÖFFNEN";
      navigate.addEventListener("click", () => navigateBrainwatchTurn(item.turn.id));
    } else {
      navigate.textContent = "CLAIM IM MEMORY EXPLORER ÖFFNEN";
      navigate.addEventListener("click", () => navigateBrainwatchClaim(item.claim.id));
    }
    card.append(heading, badge, context, navigate);
    if (direction === "turn-to-claim") appendMemoryFields(card, [
      ["Claim-Art", item.claim.claim_kind], ["Scope", item.claim.scope],
      ["Lifecycle", item.claim.lifecycle],
    ]);
    else appendMemoryFields(card, [
      ["Turn", item.turn.turn_id], ["Conversation", item.turn.raw_conversation_id],
      ["Turn-Zeit", item.turn.created_at],
    ]);
    const technical = document.createElement("details"); const summary = document.createElement("summary");
    summary.textContent = "Technischer Herkunftsbeleg";
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify({
      origin_class: item.origin_class, consumer: item.consumer,
      compiler_stage: item.compiler_stage, source: item.source,
    }, null, 2);
    technical.append(summary, pre); card.append(technical);
    return card;
  }

  function appendMemoryParticipation(parent, page, direction) {
    for (const item of page.items || []) parent.append(memoryParticipationCard(item, direction));
  }

  function appendMemoryParticipationPage(parent, page, direction, loadMore) {
    appendMemoryParticipation(parent, page, direction);
    if (!(page.items || []).length && !parent.querySelector(".memory-participation")) {
      const empty = document.createElement("p");
      empty.textContent = direction === "claim-to-turn"
        ? "Für diesen Claim sind keine navigierbaren Turn-Verknüpfungen aufgezeichnet."
        : "Für diesen Turn sind keine Memory-V2-Beteiligungen aufgezeichnet.";
      parent.append(empty);
    }
    if (!page.page?.has_more) return;
    const more = document.createElement("button"); more.type = "button"; more.className = "eve-button"; more.textContent = "WEITERE HERKUNFTSBELEGE";
    more.addEventListener("click", async () => {
      more.disabled = true;
      try {
        const next = await loadMore(page.page.next_cursor);
        more.remove(); appendMemoryParticipationPage(parent, next, direction, loadMore);
      } catch (error) { more.disabled = false; more.textContent = error.message; }
    });
    parent.append(more);
  }

  async function navigateBrainwatchTurn(turnId) {
    setBrainwatchMode("information", { load: false });
    try { await focusBrainwatchNode(turnId, { anchor: true }); }
    catch (error) { elements.brainwatchStatus.textContent = `Turn konnte nicht geöffnet werden: ${error.message}`; }
  }

  async function navigateBrainwatchClaim(claimId) {
    setBrainwatchMode("memory", { load: false });
    setMemoryExplorerSubview("cloud", { load: false });
    try { await focusMemoryClaim(claimId, { anchor: true }); }
    catch (error) { elements.memoryExplorerStatus.textContent = `Claim konnte nicht geöffnet werden: ${error.message}`; }
  }

  async function runtimeEventRead(eventId) {
    return memoryExplorerRead(`runtime-events/${encodeURIComponent(String(eventId).replace(/^runtime-event:/, ""))}`);
  }

  function runtimeEventCard(event) {
    const card = document.createElement("article"); card.className = `memory-runtime-event category-${event.category}`;
    const heading = document.createElement("strong"); heading.textContent = MEMORY_EVENT_LABELS[event.event_kind] || event.event_kind;
    const badges = document.createElement("div"); badges.className = "memory-runtime-badges";
    for (const value of [MEMORY_CATEGORY_LABELS[event.category] || event.category, event.proof_level, event.event_status]) {
      if (!value) continue;
      const badge = document.createElement("span"); badge.textContent = value; badges.append(badge);
    }
    const summary = document.createElement("p");
    summary.textContent = `${event.timestamp} · ${event.consumer || "kein Consumer"}${event.outcome_status ? ` · ${event.outcome_status}` : ""}`;
    const open = document.createElement("button"); open.type = "button"; open.className = "memory-link eve-button eve-button--ghost";
    open.textContent = "VOLLSTÄNDIGEN EVENT ÖFFNEN";
    open.addEventListener("click", async () => {
      try { renderMemoryEventInspector(await runtimeEventRead(event.runtime_event_id)); }
      catch (error) { elements.memoryExplorerStatus.textContent = error.message; }
    });
    card.append(heading, badges, summary, open);
    return card;
  }

  function appendRuntimePage(parent, page, loadMore) {
    for (const event of page.items || []) parent.append(runtimeEventCard(event));
    if (!(page.items || []).length && !parent.querySelector(".memory-runtime-event")) {
      const empty = document.createElement("p"); empty.textContent = "Keine persistierten Runtime-Ereignisse vorhanden."; parent.append(empty);
    }
    if (!page.page?.has_more || !loadMore) return;
    const more = document.createElement("button"); more.type = "button"; more.className = "eve-button"; more.textContent = "WEITERE RUNTIME-EREIGNISSE";
    more.addEventListener("click", async () => {
      more.disabled = true;
      try { const next = await loadMore(page.page.next_cursor); more.remove(); appendRuntimePage(parent, next, loadMore); }
      catch (error) { more.disabled = false; more.textContent = error.message; }
    });
    parent.append(more);
  }

  function appendRuntimeCounts(parent, counts) {
    const labels = {
      retrieval: "Retrieval", consumer_return: "Consumer-Rückgabe", prompt_assembly: "Prompt-Assembly",
      client_handoff: "Clientübergabe", transport_serialization: "Transportserialisierung",
      plan_binding: "Planbindung", action_binding: "Action-Bindung", dispatch: "Tatsächlicher Dispatch",
      successful_action: "Erfolgreiche Action", relation_traversal: "Relations-Traversierung",
    };
    const list = document.createElement("dl"); list.className = "memory-runtime-counts";
    for (const [key, label] of Object.entries(labels)) {
      const dt = document.createElement("dt"); dt.textContent = label;
      const dd = document.createElement("dd"); dd.textContent = String(counts?.[key] || 0);
      list.append(dt, dd);
    }
    parent.append(list);
  }

  function appendEvidenceCards(parent, page) {
    const labels = { available: "Provenienz vorhanden", partial: "Provenienz teilweise vorhanden", not_recorded: "Provenienz nicht aufgezeichnet" };
    for (const evidence of page.items || []) {
      const card = document.createElement("article"); card.className = `memory-evidence provenance-${evidence.provenance_status}`;
      const heading = document.createElement("strong"); heading.textContent = `${evidence.stance} · ${evidence.evidence_type}`;
      const status = document.createElement("span"); status.className = "memory-provenance"; status.textContent = labels[evidence.provenance_status] || evidence.provenance_status;
      const excerpt = document.createElement("p"); excerpt.textContent = evidence.excerpt || evidence.observation?.excerpt || "Kein Auszug aufgezeichnet.";
      card.append(heading, status, excerpt);
      appendMemoryFields(card, [
        ["Evidence-ID", evidence.evidence_id], ["Observation", evidence.observation?.observation_id],
        ["Quelltyp", evidence.observation?.source_type], ["Source Ref", evidence.source_ref],
        ["Turn", evidence.source_turn_id || evidence.observation?.turn_id],
        ["Message", evidence.source_message_id || evidence.observation?.message_id],
        ["Tool-Event", evidence.tool_event_id || evidence.observation?.tool_event_id],
        ["Beobachtet", evidence.observed_at], ["Gespeichert", evidence.created_at],
      ]);
      const raw = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "Redigierte technische Details";
      const pre = document.createElement("pre"); pre.textContent = JSON.stringify({ payload: evidence.payload, observation: evidence.observation?.structured_value }, null, 2);
      raw.append(summary, pre); card.append(raw); parent.append(card);
    }
  }

  function appendRelationCards(parent, page, focusId) {
    for (const relation of page.items || []) {
      const card = document.createElement("article"); card.className = `memory-relation relation-${relation.direction}`;
      const heading = document.createElement("strong"); heading.textContent = `${relation.direction === "incoming" ? "Eingehend" : "Ausgehend"} · ${relation.relation_type}`;
      const source = document.createElement("div"); source.className = "memory-relation-path";
      source.append(memoryClaimButton(relation.from_claim), document.createTextNode(` → ${relation.relation_type} → `), memoryClaimButton(relation.to_claim));
      card.append(heading, source);
      appendMemoryFields(card, [
        ["Relations-ID", relation.relation_id], ["Gespeichert", relation.created_at],
        ["Evidence", relation.evidence?.evidence_id], ["Evidence-Typ", relation.evidence?.evidence_type],
      ]);
      if (relation.relation_type === "refines") {
        const note = document.createElement("p"); note.textContent = "Gespeicherte refines-Relation; ihre fachliche Bedeutung hängt vom jeweiligen Scope ab."; card.append(note);
      }
      parent.append(card);
    }
    if (!(page.items || []).length) {
      const empty = document.createElement("p"); empty.textContent = `Für ${focusId} sind keine gespeicherten Relations vorhanden.`; parent.append(empty);
    }
  }

  function renderMemoryClaimInspector(detail, evidence, relations, turns, runtime) {
    runtime ||= detail.runtime || { items: [], activity_counts: {}, page: {} };
    const inspector = elements.brainwatchInspector; inspector.replaceChildren();
    const claim = detail.claim;
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = "MEMORY-V2-CLAIM";
    const title = document.createElement("h2"); title.textContent = claim.display_text || claim.claim_id;
    const badges = document.createElement("p"); badges.className = "memory-claim-badges"; badges.textContent = `${claim.claim_kind} · ${claim.lifecycle} · ${claim.scope}`;
    inspector.append(eyebrow, title, badges);
    appendMemoryFields(inspector, [
      ["Claim-ID", claim.claim_id], ["Claim-Art", claim.claim_kind], ["Scope", claim.scope],
      ["Lifecycle", claim.lifecycle], ["Verification", claim.verification_policy],
      ["Canonical Key", claim.canonical_key], ["Slot Key", claim.slot_key],
      ["Gültig ab", claim.valid_from], ["Gültig bis", claim.valid_until],
      ["Erstellt", claim.created_at], ["Geändert", claim.updated_at],
      ["Evidenzen", detail.counts.evidence], ["Relationen eingehend", detail.counts.relations_incoming],
      ["Relationen ausgehend", detail.counts.relations_outgoing],
    ]);

    const runtimeSection = memorySection(inspector, "Runtime-Aktivität");
    const runtimeNotice = document.createElement("p"); runtimeNotice.className = "memory-participation-notice";
    runtimeNotice.textContent = "Zähler sind je Kategorie anhand persistierter technischer Identitäten dedupliziert; es gibt keine universelle Kennzahl ‚verwendet‘.";
    runtimeSection.append(runtimeNotice); appendRuntimeCounts(runtimeSection, runtime.activity_counts);
    appendRuntimePage(runtimeSection, runtime, (cursor) => memoryExplorerRead(
      `claims/${encodeURIComponent(claim.claim_id)}/runtime-events?${new URLSearchParams({ limit: "30", sort: "asc", cursor })}`,
    ));

    const turnSection = memorySection(inspector, "Zugehörige Turns");
    const turnNotice = document.createElement("p"); turnNotice.className = "memory-participation-notice";
    turnNotice.textContent = turns.semantics?.notice || "Eine Beteiligung belegt keine tatsächliche Verwendung.";
    turnSection.append(turnNotice);
    appendMemoryParticipationPage(turnSection, turns, "claim-to-turn", (cursor) => memoryExplorerRead(
      `claims/${encodeURIComponent(claim.claim_id)}/turns?${new URLSearchParams({ limit: "20", cursor })}`,
    ));

    const relationSection = memorySection(inspector, "Gespeicherte Beziehungen");
    appendRelationCards(relationSection, relations, claim.claim_id);
    const historyTitle = document.createElement("h4"); historyTitle.textContent = "Direkte supersedes-Historie"; relationSection.append(historyTitle);
    appendRelationCards(relationSection, { items: detail.history.items }, claim.claim_id);
    const history = document.createElement("p"); history.className = "memory-history-note";
    history.textContent = detail.history.items.length
      ? `${detail.history.items.length} direkte supersedes-Verknüpfung(en)${detail.history.truncated ? "; weitere sind vorhanden" : ""}. Angezeigt wird nur gespeicherte Historie.`
      : "Keine direkte supersedes-Verknüpfung. Eine vollständige Änderungshistorie ist nicht aufgezeichnet.";
    relationSection.append(history);

    const evidenceSection = memorySection(inspector, "Evidence und Provenienz");
    appendEvidenceCards(evidenceSection, evidence);
    if (!(evidence.items || []).length) {
      const empty = document.createElement("p"); empty.textContent = "Keine Evidence aufgezeichnet."; evidenceSection.append(empty);
    }
    if (evidence.page?.has_more) {
      const more = document.createElement("button"); more.type = "button"; more.className = "eve-button"; more.textContent = "WEITERE EVIDENZEN";
      let cursor = evidence.page.next_cursor;
      more.addEventListener("click", async () => {
        more.disabled = true;
        try {
          const page = await memoryExplorerRead(`claims/${encodeURIComponent(claim.claim_id)}/evidence?${new URLSearchParams({ limit: "20", cursor })}`);
          appendEvidenceCards(evidenceSection, page); evidenceSection.append(more);
          cursor = page.page.next_cursor; more.hidden = !page.page.has_more;
        } catch (error) { elements.memoryExplorerStatus.textContent = error.message; }
        finally { more.disabled = false; }
      }); evidenceSection.append(more);
    }
    const raw = document.createElement("details"); const rawTitle = document.createElement("summary"); rawTitle.textContent = "Redigiertes strukturiertes Claim-Payload";
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify(claim.payload, null, 2);
    raw.append(rawTitle, pre); inspector.append(raw);
  }

  function renderMemoryRelationInspector(edge) {
    const relation = edge.metadata?.relation;
    if (!relation) { renderBrainwatchInspector({ kind: "edge", value: edge }); return; }
    const inspector = elements.brainwatchInspector; inspector.replaceChildren();
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = "GESPEICHERTE MEMORY-RELATION";
    const title = document.createElement("h2"); title.textContent = relation.relation_type;
    const note = document.createElement("p"); note.textContent = relation.relation_type === "refines"
      ? "Die Relation wird ohne allgemeine semantische Deutung angezeigt. Ihre Bedeutung hängt von den beteiligten Scopes ab."
      : "Diese Kante entspricht genau einer gespeicherten memory_relations-Zeile.";
    inspector.append(eyebrow, title, note);
    appendMemoryFields(inspector, [["Relations-ID", relation.relation_id], ["Richtung am Fokus", relation.direction], ["Gespeichert", relation.created_at], ["Evidence", relation.evidence?.evidence_id]]);
    const path = memorySection(inspector, "Verbundene Claims");
    path.append(memoryClaimButton(relation.from_claim), document.createTextNode(" → "), memoryClaimButton(relation.to_claim));
    const runtime = memorySection(inspector, "Runtime-Aktivität");
    const status = document.createElement("p"); status.textContent = "Persistierte Relations-Ereignisse werden gelesen …"; runtime.append(status);
    memoryExplorerRead(`runtime-events?${new URLSearchParams({ relation_id: relation.relation_id, limit: "30", sort: "asc" })}`).then((page) => {
      status.remove(); appendRuntimePage(runtime, page, (cursor) => memoryExplorerRead(
        `runtime-events?${new URLSearchParams({ relation_id: relation.relation_id, limit: "30", sort: "asc", cursor })}`,
      ));
    }).catch((error) => { status.textContent = error.message; });
  }

  async function memoryExplorerRead(path) {
    const response = await fetchWithTimeout(`/api/brainwatch/memory/${path}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Memory Explorer");
    if (!response.ok) throw new Error(data.error || "Memory Explorer konnte nicht gelesen werden.");
    return data;
  }

  function avatarCloudShouldRender() {
    return avatarMode === "brainwatch" && !document.hidden && !brainwatchOpen && !configOpen && !nerdMode;
  }

  function ensureAvatarMemoryCloud() {
    if (avatarMode !== "brainwatch") return null;
    if (avatarCloudRenderer) return avatarCloudRenderer;
    if (!elements.avatarCloudCanvas || !window.EveNeuroCloud?.NeuroCloudRenderer) return null;
    avatarCloudRenderer = new window.EveNeuroCloud.NeuroCloudRenderer(elements.avatarCloudCanvas, {
      ...BRAINWATCH_NEUROCLOUD_PROFILE,
      intensity: .92,
      activityTimeScale: 2.2,
      spatialShape: "brain",
      orbitMode: "sway",
      cameraYaw: -.12,
      transparentBackground: true,
      autoRotateSpeed: .014,
      animationFps: 18,
      continuousAmbientMotion: true,
      depthMotion: true,
      powerPreference: "low-power",
    });
    if (!avatarCloudRenderer.supported) {
      elements.mark.classList.add("memory-avatar-unavailable");
      avatarCloudRenderer = null;
      return null;
    }
    avatarCloudRenderer.setVisible(avatarCloudShouldRender());
    return avatarCloudRenderer;
  }

  function syncAvatarCloudVisibility() {
    avatarCloudRenderer?.setVisible(avatarCloudShouldRender());
  }

  async function loadAvatarMemoryCloud() {
    if (avatarMode !== "brainwatch") return null;
    if (avatarCloudLoad) return avatarCloudLoad;
    avatarCloudLoad = (async () => {
      const nodes = new Map();
      const edges = new Map();
      const seenCursors = new Set();
      let cursor = "";
      let page = null;
      while (true) {
        const params = new URLSearchParams({ node_limit: "160", edge_limit: "320", depth: "2" });
        if (cursor) params.set("cursor", cursor);
        const current = await memoryExplorerRead(`graph?${params}`);
        if (!page) page = current;
        for (const node of current.nodes || []) nodes.set(node.id, node);
        for (const edge of current.edges || []) edges.set(edge.id, edge);
        const nextCursor = current.page?.next_cursor || "";
        if (!current.page?.has_more || !nextCursor || seenCursors.has(nextCursor)) break;
        seenCursors.add(nextCursor);
        cursor = nextCursor;
      }
      page ||= { nodes: [], edges: [], layout_contract: null };
      page.nodes = [...nodes.values()];
      const loadedNodeIds = new Set(page.nodes.map((node) => node.id));
      edges.clear();
      seenCursors.clear();
      cursor = "";
      while (true) {
        const params = new URLSearchParams({ limit: "200" });
        if (cursor) params.set("cursor", cursor);
        const current = await memoryExplorerRead(`graph/relations?${params}`);
        for (const edge of current.items || []) edges.set(edge.id, edge);
        const nextCursor = current.page?.next_cursor || "";
        if (!current.page?.has_more || !nextCursor || seenCursors.has(nextCursor)) break;
        seenCursors.add(nextCursor);
        cursor = nextCursor;
      }
      page.edges = [...edges.values()].filter((edge) => (
        loadedNodeIds.has(edge.from_claim_id) && loadedNodeIds.has(edge.to_claim_id)
      ));
      const renderer = ensureAvatarMemoryCloud();
      if (!renderer) return page;
      renderer.setData(page.nodes || [], page.edges || [], page.layout_contract?.version || "neurocloud-layout-v3-provenance-regions");
      if (avatarCloudActivityTurn && window.EveNeuroCloud?.projectRuntimeActivity) {
        renderer.setActivityPattern(window.EveNeuroCloud.projectRuntimeActivity(avatarCloudActivityEvents, {
          turnId: avatarCloudActivityTurn,
          complete: avatarCloudActivityComplete,
        }));
      }
      elements.avatarCloudCanvas.dataset.claims = String(page.nodes?.length || 0);
      elements.avatarCloudCanvas.dataset.relations = String(page.edges?.length || 0);
      elements.mark.classList.toggle("memory-avatar-ready", Boolean(page.nodes?.length));
      elements.mark.classList.toggle("memory-avatar-empty", !page.nodes?.length);
      document.body.classList.toggle("memory-avatar-active", Boolean(page.nodes?.length));
      syncAvatarCloudVisibility();
      if (!avatarCloudDemoStarted && new URLSearchParams(window.location.search).get("avatar_demo") === "1") {
        runAvatarCloudDemo(page.nodes || [], page.edges || []);
      }
      return page;
    })().catch((error) => {
      if (avatarMode !== "brainwatch") return null;
      elements.mark.classList.remove("memory-avatar-ready");
      elements.mark.classList.add("memory-avatar-unavailable");
      document.body.classList.remove("memory-avatar-active");
      throw error;
    }).finally(() => { avatarCloudLoad = null; });
    return avatarCloudLoad;
  }

  function scheduleAvatarMemoryCloudRefresh(delay = 500) {
    window.clearTimeout(avatarCloudRefreshTimer);
    if (avatarMode !== "brainwatch") return;
    avatarCloudRefreshTimer = window.setTimeout(() => {
      loadAvatarMemoryCloud().catch(() => {});
    }, delay);
  }

  function disposeAvatarMemoryCloud() {
    stopAvatarCloudDemo();
    stopAvatarCloudActivity({ clear: true });
    window.clearTimeout(avatarCloudRefreshTimer);
    avatarCloudRefreshTimer = null;
    avatarCloudRenderer?.dispose();
    avatarCloudRenderer = null;
    elements.mark.classList.remove("memory-avatar-ready", "memory-avatar-empty", "memory-avatar-unavailable", "memory-avatar-demo");
    if (elements.avatarCloudCanvas) {
      delete elements.avatarCloudCanvas.dataset.claims;
      delete elements.avatarCloudCanvas.dataset.relations;
      delete elements.avatarCloudCanvas.dataset.activitySource;
    }
    document.body.classList.remove("memory-avatar-active");
  }

  function setAvatarMode(mode, persist = true) {
    avatarMode = mode === "logo" ? "logo" : "brainwatch";
    if (persist) window.localStorage.setItem("eve.avatarMode", avatarMode);
    const cloudEnabled = avatarMode === "brainwatch";
    document.body.dataset.avatar = avatarMode;
    elements.avatarModeToggle.setAttribute("aria-pressed", String(cloudEnabled));
    elements.avatarModeToggle.setAttribute(
      "aria-label",
      cloudEnabled ? "Avatar: Brainwatch-Wolke. Zum Logo wechseln" : "Avatar: Logo. Zur Brainwatch-Wolke wechseln",
    );
    elements.avatarModeState.textContent = cloudEnabled ? "BRAINWATCH" : "LOGO";
    if (!cloudEnabled) {
      disposeAvatarMemoryCloud();
      return;
    }
    loadAvatarMemoryCloud().catch(() => {});
  }

  function stopAvatarCloudDemo({ clear = true } = {}) {
    for (const timer of avatarCloudDemoTimers) window.clearTimeout(timer);
    avatarCloudDemoTimers = [];
    elements.mark.classList.remove("memory-avatar-demo");
    delete elements.avatarCloudCanvas?.dataset.activitySource;
    if (clear) avatarCloudRenderer?.clearActivity();
  }

  function runAvatarCloudDemo(nodes, edges) {
    if (!avatarCloudRenderer || !nodes.length) return false;
    avatarCloudDemoStarted = true;
    stopAvatarCloudDemo();
    const turnId = "avatar-visual-demo";
    const kinds = [
      "claim_retrieved", "claim_added_to_prompt_context", "claim_resolved",
      "action_completed_with_claim", "claim_lifecycle_changed",
    ];
    const selectedNodes = nodes.filter((_, index) => index % Math.max(1, Math.floor(nodes.length / 16)) === 0).slice(0, 16);
    const firstWave = selectedNodes.map((node, index) => ({
      event_id: `runtime-event:avatar-demo-claim-${index}`,
      turn_id: `turn:${turnId}`,
      event_kind: kinds[index % kinds.length],
      claim_ids: [node.id],
      event_status: "completed",
      operation_id: `avatar-demo-operation-${index}`,
    }));
    const relationWave = edges.slice(0, 9).map((edge, index) => ({
      event_id: `runtime-event:avatar-demo-relation-${index}`,
      turn_id: `turn:${turnId}`,
      event_kind: index % 2 ? "relation_bound_to_plan" : "relation_traversed_for_retrieval",
      relation_id: edge.id,
      event_status: "completed",
      operation_id: `avatar-demo-relation-operation-${index}`,
    }));
    const secondWave = [...selectedNodes].reverse().slice(0, 10).map((node, index) => ({
      event_id: `runtime-event:avatar-demo-echo-${index}`,
      turn_id: `turn:${turnId}`,
      event_kind: kinds[(index + 2) % kinds.length],
      claim_ids: [node.id],
      event_status: "completed",
      operation_id: `avatar-demo-echo-operation-${index}`,
    }));
    const events = [...firstWave, ...relationWave, ...secondWave];
    const visibleEvents = [];
    avatarCloudRenderer.clearActivity();
    elements.mark.classList.add("memory-avatar-demo");
    elements.avatarCloudCanvas.dataset.activitySource = "visual-demo";
    for (const [index, event] of events.entries()) {
      avatarCloudDemoTimers.push(window.setTimeout(() => {
        visibleEvents.push(event);
        avatarCloudRenderer?.setActivityPattern(window.EveNeuroCloud.projectRuntimeActivity(
          visibleEvents, { turnId, complete: index === events.length - 1 },
        ));
        avatarCloudRenderer?.animateActivityEvent(event);
      }, 260 + index * 240));
    }
    avatarCloudDemoTimers.push(window.setTimeout(() => stopAvatarCloudDemo(), 12000));
    return true;
  }

  function applyAvatarCloudActivity(events) {
    const projector = window.EveNeuroCloud?.projectRuntimeActivity;
    if (!projector || !avatarCloudRenderer || !avatarCloudActivityTurn) return;
    avatarCloudRenderer.setActivityPattern(projector(avatarCloudActivityEvents, {
      turnId: avatarCloudActivityTurn,
      complete: avatarCloudActivityComplete,
    }));
    queueAvatarCloudActivityEvents(events);
    if (events.some((event) => event.event_kind === "claim_lifecycle_changed")) {
      scheduleAvatarMemoryCloudRefresh(350);
    }
  }

  function queueAvatarCloudActivityEvents(events) {
    avatarCloudImpulseQueue.push(...events);
    if (avatarCloudImpulseTimer || !avatarCloudImpulseQueue.length) return;
    const next = () => {
      avatarCloudImpulseTimer = null;
      const event = avatarCloudImpulseQueue.shift();
      if (!event) return;
      avatarCloudRenderer?.animateActivityEvent(event);
      if (avatarCloudImpulseQueue.length) {
        avatarCloudImpulseTimer = window.setTimeout(next, 220);
      }
    };
    next();
  }

  async function pollAvatarCloudActivity() {
    if (avatarMode !== "brainwatch" || avatarCloudActivityBusy || !avatarCloudActivityTurn || document.hidden) return;
    const turnId = avatarCloudActivityTurn;
    avatarCloudActivityBusy = true;
    try {
      const added = [];
      let hasMore = true;
      while (hasMore) {
        const page = await readMemoryCloudLivePage(turnId, avatarCloudActivityCursor);
        if (avatarCloudActivityTurn !== turnId) return;
        avatarCloudActivityCursor = page.page?.poll_cursor || avatarCloudActivityCursor;
        for (const event of page.items || []) {
          if (!event.event_id || avatarCloudActivityIds.has(event.event_id)) continue;
          avatarCloudActivityIds.add(event.event_id);
          avatarCloudActivityEvents.push(event);
          added.push(event);
        }
        hasMore = Boolean(page.page?.has_more);
      }
      if (added.length) applyAvatarCloudActivity(added);
    } finally {
      avatarCloudActivityBusy = false;
    }
  }

  function stopAvatarCloudActivity({ clear = false } = {}) {
    window.clearInterval(avatarCloudActivityTimer);
    window.clearTimeout(avatarCloudActivityFinishTimer);
    avatarCloudActivityTimer = null;
    avatarCloudActivityFinishTimer = null;
    if (!clear) return;
    window.clearTimeout(avatarCloudImpulseTimer);
    avatarCloudImpulseTimer = null;
    avatarCloudImpulseQueue = [];
    avatarCloudActivityTurn = "";
    avatarCloudActivityCursor = "";
    avatarCloudActivityEvents = [];
    avatarCloudActivityIds = new Set();
    avatarCloudActivityComplete = false;
    avatarCloudRenderer?.clearActivity();
  }

  async function startAvatarCloudActivity(turnId) {
    if (avatarMode !== "brainwatch") return;
    turnId = String(turnId || "").replace(/^turn:/, "").trim();
    if (!turnId) return;
    stopAvatarCloudDemo();
    stopAvatarCloudActivity({ clear: true });
    avatarCloudActivityTurn = turnId;
    await loadAvatarMemoryCloud().catch(() => null);
    await pollAvatarCloudActivity().catch(() => {});
    if (avatarCloudActivityTurn !== turnId) return;
    avatarCloudActivityTimer = window.setInterval(() => pollAvatarCloudActivity().catch(() => {}), 700);
  }

  function finishAvatarCloudActivity(turnId, complete = true) {
    if (avatarMode !== "brainwatch") return;
    turnId = String(turnId || "").replace(/^turn:/, "").trim();
    if (!turnId || turnId !== avatarCloudActivityTurn) return;
    window.clearTimeout(avatarCloudActivityFinishTimer);
    avatarCloudActivityFinishTimer = window.setTimeout(async () => {
      await pollAvatarCloudActivity().catch(() => {});
      if (avatarCloudActivityTurn !== turnId) return;
      avatarCloudActivityComplete = complete;
      applyAvatarCloudActivity([]);
      stopAvatarCloudActivity();
      scheduleAvatarMemoryCloudRefresh(0);
    }, 2600);
  }

  function memoryCloudRelationEdge(relation) {
    const from = memoryCloudNodes.get(relation.from_claim_id);
    const to = memoryCloudNodes.get(relation.to_claim_id);
    return {
      id: relation.id, source: relation.from_claim_id, target: relation.to_claim_id,
      type: relation.relation_type, category: "lineage", label: relation.relation_type,
      persistent: true,
      metadata: { relation: {
        id: relation.id, relation_id: relation.relation_id,
        relation_type: relation.relation_type, direction: "gespeichert",
        created_at: relation.created_at, evidence: null,
        from_claim: from, to_claim: to,
      } },
    };
  }

  function setMemoryStructureStatus(message) {
    elements.memoryCloudStatus.textContent = message;
    if (memoryExplorerSubview !== "timeline") elements.memoryExplorerStatus.textContent = message;
  }

  function ensureMemoryCloud() {
    if (memoryCloudRenderer) return memoryCloudRenderer;
    if (!window.EveNeuroCloud?.NeuroCloudRenderer) {
      elements.memoryCloudFallback.hidden = false;
      setMemoryStructureStatus("Der lokale 3D-Renderer konnte nicht geladen werden.");
      return null;
    }
    memoryCloudRenderer = new window.EveNeuroCloud.NeuroCloudRenderer(elements.memoryCloudCanvas, {
      ...BRAINWATCH_NEUROCLOUD_PROFILE,
      quality: elements.memoryCloudQuality.value,
      intensity: elements.memoryCloudIntensity.value,
      onClaimSelect: (claim) => {
        if (claim.node_kind === "working_material") {
          memoryCloudRenderer?.selectClaim(claim.id);
          renderWorkingMemoryInspector(claim);
          return;
        }
        pinMemoryCloudSelection("claim", claim.id);
        focusMemoryClaim(claim.id, { anchor: true }).catch((error) => { setMemoryStructureStatus(error.message); });
      },
      onRelationSelect: (relation) => {
        if (relation.node_kind === "working_link") {
          memoryCloudRenderer?.selectRelation(relation.id);
          renderWorkingMemoryInspector(relation);
          return;
        }
        pinMemoryCloudSelection("relation", relation.id);
        const edge = memoryCloudRelationEdge(relation);
        if (edge.metadata.relation.from_claim && edge.metadata.relation.to_claim) renderMemoryRelationInspector(edge);
      },
      onSelectionClear: () => { memoryCloudPinnedSelection = null; },
      onHover: (selection, event) => {
        if (!selection) { elements.memoryCloudTooltip.hidden = true; return; }
        elements.memoryCloudTooltip.textContent = selection.kind === "claim"
          ? `${selection.value.display_text || selection.value.claim_id} · ${selection.value.scope}`
          : `${selection.value.relation_type} · ${selection.value.relation_id}`;
        const bounds = elements.memoryCloudWorkspace.getBoundingClientRect();
        elements.memoryCloudTooltip.style.left = `${event.clientX - bounds.left + 14}px`;
        elements.memoryCloudTooltip.style.top = `${event.clientY - bounds.top + 14}px`;
        elements.memoryCloudTooltip.hidden = false;
      },
      onStats: (stats) => { elements.memoryCloudCanvas.dataset.drawCalls = String(stats.draw_calls); },
    });
    if (!memoryCloudRenderer.supported) {
      elements.memoryCloudFallback.hidden = false;
      elements.memoryCloudCanvas.hidden = true;
      elements.memoryCloudXRStatus.textContent = "VR / AR benötigt WebGL2.";
      setMemoryStructureStatus("WebGL2 ist nicht verfügbar. Claims bleiben über Suche und Inspektor zugänglich.");
    }
    if (memoryCloudRenderer.supported && window.EveNeuroCloudXR) {
      const xr = new window.EveNeuroCloudXR.NeuroCloudXR(memoryCloudRenderer, {
        inspector: elements.brainwatchInspector,
        getStatus: () => elements.memoryCloudActivityPosition.textContent,
        onState: ({ session, mode, busy, support, message }) => {
          elements.memoryCloudVR.disabled = busy || !support["immersive-vr"];
          elements.memoryCloudAR.disabled = busy || !support["immersive-ar"];
          elements.memoryCloudVR.setAttribute("aria-pressed", String(session && mode === "immersive-vr"));
          elements.memoryCloudAR.setAttribute("aria-pressed", String(session && mode === "immersive-ar"));
          elements.memoryCloudXREnd.hidden = !session;
          elements.memoryCloudXREnd.disabled = busy;
          if (message) elements.memoryCloudXRStatus.textContent = message;
        },
      });
      xr.detect().catch(error => { elements.memoryCloudXRStatus.textContent = error.message; });
    }
    return memoryCloudRenderer;
  }

  function pinMemoryCloudSelection(kind, id, options) {
    options ||= {};
    const focus = options.focus === true;
    if (!id || !new Set(["claim", "relation"]).has(kind)) return false;
    memoryCloudPinnedSelection = { kind, id };
    if (kind === "claim" && focus) memoryCloudRenderer?.focusClaim(id);
    else if (kind === "claim") memoryCloudRenderer?.selectClaim(id);
    else memoryCloudRenderer?.selectRelation(id);
    return true;
  }

  function restoreMemoryCloudSelection() {
    const selected = memoryCloudPinnedSelection;
    if (!selected || !memoryCloudRenderer) return false;
    if (selected.kind === "claim" && memoryCloudNodes.has(selected.id)) memoryCloudRenderer.selectClaim(selected.id);
    else if (selected.kind === "relation" && memoryCloudEdges.has(selected.id)) memoryCloudRenderer.selectRelation(selected.id);
    else {
      memoryCloudPinnedSelection = null;
      memoryCloudRenderer.clearSelection();
      return false;
    }
    return true;
  }

  function clearMemoryCloudLearningHighlight() {
    memoryCloudLearningHighlight = null;
    memoryCloudRenderer?.clearHighlightedClaims();
    elements.memoryCloudLearningFocus.hidden = true;
    setMemoryStructureStatus("Lernmarkierung entfernt. Die vollständige persistente Memory-Struktur bleibt sichtbar.");
  }

  function restoreMemoryCloudLearningHighlight(options) {
    options ||= {};
    if (!memoryCloudLearningHighlight || !memoryCloudRenderer) return false;
    const claimIds = memoryCloudLearningHighlight.claimIds.filter((id) => memoryCloudNodes.has(id));
    if (!claimIds.length) {
      elements.memoryCloudLearningFocus.hidden = true;
      return false;
    }
    memoryCloudRenderer.setHighlightedClaims(claimIds, { focus: options.focus === true });
    const evidence = Number(memoryCloudLearningHighlight.evidenceCount || 0);
    elements.memoryCloudLearningTitle.textContent = `LERN-TURN · ${memoryCloudLearningHighlight.turnId.slice(0, 12)}`;
    elements.memoryCloudLearningDetail.textContent = `${claimIds.length} Claim${claimIds.length === 1 ? "" : "s"} · ${evidence} Evidenz-Eintrag${evidence === 1 ? "" : "e"}`;
    elements.memoryCloudLearningFocus.hidden = false;
    return true;
  }

  function focusMemoryCloudActivityTarget(event) {
    if (memoryCloudPinnedSelection) return;
    const claimId = event.claim_id || event.claim_ids?.[0];
    if (claimId && memoryCloudNodes.has(claimId)) memoryCloudRenderer?.focusClaim(claimId);
    else if (event.relation_id && memoryCloudEdges.has(event.relation_id)) memoryCloudRenderer?.selectRelation(event.relation_id);
  }

  function disposeMemoryCloud() {
    memoryWorkingLayer?.clear();
    pauseMemoryCloudActivity();
    stopMemoryCloudLive();
    memoryCloudRenderer?.dispose();
    memoryCloudRenderer = null;
    elements.memoryCloudCanvas.hidden = false;
    elements.memoryCloudFallback.hidden = true;
  }

  function memoryCloudParameters(cursor = "", anchorClaimId = "") {
    const params = new URLSearchParams({ node_limit: "160", edge_limit: "320", depth: "2" });
    const filters = {
      scope: elements.memoryExplorerScope.value.trim(),
      claim_kind: elements.memoryExplorerKind.value,
      lifecycle: elements.memoryExplorerLifecycle.value,
      relation_type: elements.memoryCloudRelationType.value,
      anchor_claim_id: anchorClaimId,
      cursor,
    };
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    return params;
  }

  function memoryCloudRelationParameters(cursor = "") {
    const params = new URLSearchParams({ limit: "200" });
    const filters = {
      scope: elements.memoryExplorerScope.value.trim(),
      claim_kind: elements.memoryExplorerKind.value,
      lifecycle: elements.memoryExplorerLifecycle.value,
      relation_type: elements.memoryCloudRelationType.value,
      cursor,
    };
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    return params;
  }

  function updateMemoryCloudStatus(page) {
    const coverage = page.coverage || {};
    const complete = memoryCloudNodes.size >= Number(coverage.matching_claims || 0)
      && memoryCloudEdges.size >= Number(coverage.matching_relations || 0)
      ? "vollständig für diese Filter" : "wird vollständig geladen";
    setMemoryStructureStatus(`${memoryCloudNodes.size} von ${coverage.matching_claims ?? "?"} Claims · ${memoryCloudEdges.size} von ${coverage.matching_relations ?? "?"} Relations · ${complete}`);
    elements.memoryCloudMore.hidden = true;
  }

  let memoryStructureLoad = null;
  const memoryStructureRevisions = { avatar: null, explorer: null };
  let memoryStructurePolling = false;
  async function refreshPersistedMemoryClouds() {
    if (memoryStructurePolling || document.hidden) return;
    const avatar = avatarMode === "brainwatch";
    const explorer = brainwatchOpen && brainwatchMode === "memory" && memoryExplorerSubview === "cloud";
    if (!avatar && !explorer) return;
    memoryStructurePolling = true;
    try {
      const { revision } = await memoryExplorerRead("graph/revision");
      if (avatar && memoryStructureRevisions.avatar !== revision) {
        await loadAvatarMemoryCloud();
        memoryStructureRevisions.avatar = revision;
      }
      if (explorer && memoryStructureRevisions.explorer !== revision) {
        await loadMemoryStructure();
        memoryStructureRevisions.explorer = revision;
      }
    } catch (error) {
      if (explorer) setMemoryStructureStatus(`Aktualisierung fehlgeschlagen; erneuter Versuch folgt: ${error.message}`);
    } finally { memoryStructurePolling = false; }
  }
  window.setInterval(refreshPersistedMemoryClouds, 5000);

  function loadMemoryStructure(append = false, anchorClaimId = "") {
    if (memoryStructureLoad) return memoryStructureLoad;
    memoryStructureLoad = readMemoryStructure().finally(() => { memoryStructureLoad = null; });
    return memoryStructureLoad;
  }

  async function readMemoryStructure() {
    const nextNodes = new Map(), nextEdges = new Map();
    memoryCloudCursor = null; memoryCloudAnchor = null;
    setMemoryStructureStatus("Vollständige persistente Memory-Struktur wird gelesen …");
    let cursor = "";
    let page = null;
    const seenCursors = new Set();
    do {
      page = await memoryExplorerRead(`graph?${memoryCloudParameters(cursor, "")}`);
      memoryCloudLayoutVersion = page.layout_contract?.version || "neurocloud-layout-v3-provenance-regions";
      for (const node of page.nodes || []) nextNodes.set(node.id, node);
      for (const edge of page.edges || []) nextEdges.set(edge.id, edge);
      const nextCursor = page.page?.next_cursor || "";
      setMemoryStructureStatus(`${nextNodes.size} von ${page.coverage?.matching_claims ?? "?"} Claims werden geladen …`);
      if (!page.page?.has_more || !nextCursor || seenCursors.has(nextCursor)) break;
      seenCursors.add(nextCursor);
      cursor = nextCursor;
    } while (true);
    nextEdges.clear();
    cursor = "";
    seenCursors.clear();
    do {
      const relationPage = await memoryExplorerRead(`graph/relations?${memoryCloudRelationParameters(cursor)}`);
      for (const edge of relationPage.items || []) {
        if (nextNodes.has(edge.from_claim_id) && nextNodes.has(edge.to_claim_id)) {
          nextEdges.set(edge.id, edge);
        }
      }
      const nextCursor = relationPage.page?.next_cursor || "";
      setMemoryStructureStatus(`${nextNodes.size} Claims · ${nextEdges.size} von ${relationPage.matching_relations ?? "?"} Relations werden geladen …`);
      if (!relationPage.page?.has_more || !nextCursor || seenCursors.has(nextCursor)) break;
      seenCursors.add(nextCursor);
      cursor = nextCursor;
    } while (true);
    memoryCloudCursor = null;
    memoryCloudNodes = nextNodes;
    memoryCloudEdges = nextEdges;
    const renderer = ensureMemoryCloud();
    renderer?.setVisible(brainwatchOpen && brainwatchMode === "memory" && memoryExplorerSubview === "cloud");
    updateWorkingMemoryCloud();
    if (!restoreMemoryCloudSelection() && brainwatchGraph.focus && nextNodes.has(brainwatchGraph.focus)) renderer?.selectClaim(brainwatchGraph.focus);
    restoreMemoryCloudLearningHighlight({ focus: false });
    updateMemoryCloudStatus(page);
    return page;
  }

  async function loadMemoryCloud(append = false) {
    return loadMemoryStructure(false, "");
  }

  function memoryCloudTurnId(value = elements.memoryCloudTurn.value) {
    return String(value || "").replace(/^turn:/, "").trim();
  }

  function filteredMemoryCloudActivityEvents() {
    const category = elements.memoryCloudActivityCategory.value;
    return (memoryCloudActivityPattern?.events || []).filter((event) => category === "all" || event.category === category);
  }

  function renderMemoryCloudActivityStatus(message = "") {
    if (message) { elements.memoryCloudActivityPosition.textContent = message; return; }
    const events = filteredMemoryCloudActivityEvents();
    const position = memoryCloudActivityIndex >= 0 ? Math.min(memoryCloudActivityIndex + 1, events.length) : 0;
    const coverage = memoryCloudActivityComplete ? "vollständig geladen" : "unvollständig geladen";
    const live = elements.memoryCloudLive.checked ? " · LIVE" : "";
    elements.memoryCloudActivityPosition.textContent = memoryCloudActivityTurn
      ? `${position} / ${events.length} belegte Ereignisse · ${coverage}${live}`
      : "Kein Turn gewählt";
  }

  function applyMemoryCloudActivityPattern() {
    const projector = window.EveNeuroCloud?.projectRuntimeActivity;
    if (!projector || !memoryCloudActivityTurn) {
      memoryCloudActivityPattern = null;
      memoryCloudRenderer?.clearActivity();
      renderMemoryCloudActivityStatus();
      return null;
    }
    memoryCloudActivityPattern = projector(memoryCloudActivityEvents, {
      turnId: memoryCloudActivityTurn, complete: memoryCloudActivityComplete,
    });
    const renderer = ensureMemoryCloud();
    renderer?.setActivityPattern(memoryCloudActivityPattern);
    renderer?.setActivityFilter(elements.memoryCloudActivityCategory.value);
    renderMemoryCloudActivityStatus();
    return memoryCloudActivityPattern;
  }

  function pauseMemoryCloudActivity(pauseRenderer = true) {
    if (memoryCloudActivityTimer) window.clearInterval(memoryCloudActivityTimer);
    memoryCloudActivityTimer = null;
    elements.memoryCloudActivityPlay.setAttribute("aria-pressed", "false");
    elements.memoryCloudActivityPlay.textContent = "START";
    if (pauseRenderer) memoryCloudRenderer?.pauseActivity();
  }

  function selectMemoryCloudActivityEvent(index, options) {
    options ||= {};
    const events = filteredMemoryCloudActivityEvents();
    if (!events.length) { memoryCloudActivityIndex = -1; renderMemoryCloudActivityStatus(); return; }
    memoryCloudActivityIndex = Math.max(0, Math.min(index, events.length - 1));
    const event = events[memoryCloudActivityIndex];
    memoryCloudRenderer?.resumeActivity();
    memoryCloudRenderer?.animateActivityEvent(event);
    focusMemoryCloudActivityTarget(event);
    if (options.inspect !== false) renderMemoryEventInspector(event);
    renderMemoryCloudActivityStatus();
  }

  function playMemoryCloudActivity() {
    if (memoryCloudActivityTimer) { pauseMemoryCloudActivity(); return; }
    const events = filteredMemoryCloudActivityEvents();
    if (!events.length) return;
    memoryCloudRenderer?.resumeActivity();
    if (memoryCloudActivityIndex < 0 || memoryCloudActivityIndex >= events.length - 1) selectMemoryCloudActivityEvent(0);
    elements.memoryCloudActivityPlay.setAttribute("aria-pressed", "true");
    elements.memoryCloudActivityPlay.textContent = "PAUSE";
    memoryCloudActivityTimer = window.setInterval(() => {
      if (memoryCloudActivityIndex >= filteredMemoryCloudActivityEvents().length - 1) { pauseMemoryCloudActivity(false); return; }
      selectMemoryCloudActivityEvent(memoryCloudActivityIndex + 1);
    }, Number(elements.memoryCloudActivitySpeed.value) || 900);
  }

  function clearMemoryCloudActivity() {
    pauseMemoryCloudActivity();
    memoryCloudActivityEvents = []; memoryCloudActivityPattern = null;
    memoryCloudActivityIndex = -1; memoryCloudActivityTurn = "";
    memoryCloudActivityComplete = false; memoryCloudLiveCursor = "";
    elements.memoryCloudTurn.value = "";
    elements.memoryCloudLive.checked = false;
    stopMemoryCloudLive();
    memoryCloudRenderer?.clearActivity();
    renderMemoryCloudActivityStatus();
  }

  async function readMemoryCloudTurnPage(turnId, cursor = "") {
    const params = new URLSearchParams({ limit: "50", sort: "asc" });
    if (cursor) params.set("cursor", cursor);
    const response = await fetchWithTimeout(`/api/brainwatch/turns/${encodeURIComponent(turnId)}/runtime-events?${params}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Turn-Aktivität");
    if (!response.ok) throw new Error(data.error || "Turn-Aktivität konnte nicht gelesen werden.");
    return data;
  }

  async function loadMemoryCloudTurnActivity(turnId) {
    turnId = memoryCloudTurnId(turnId);
    if (!turnId) throw new Error("Bitte eine Turn-ID angeben.");
    pauseMemoryCloudActivity(); stopMemoryCloudLive();
    memoryCloudActivityTurn = turnId; elements.memoryCloudTurn.value = `turn:${turnId}`;
    memoryCloudActivityEvents = []; memoryCloudActivityPattern = null;
    memoryCloudActivityIndex = -1; memoryCloudActivityComplete = false; memoryCloudLiveCursor = "";
    renderMemoryCloudActivityStatus("Persistierte Turn-Ereignisse werden vollständig gelesen …");
    if (elements.memoryCloudLive.checked) {
      const tail = await readMemoryCloudLivePage(turnId, "", true);
      memoryCloudLiveCursor = tail.page?.poll_cursor || "";
    }
    let cursor = "", hasMore = true;
    const known = new Set();
    while (hasMore && memoryCloudActivityEvents.length < MEMORY_CLOUD_ACTIVITY_LIMIT) {
      const page = await readMemoryCloudTurnPage(turnId, cursor);
      for (const event of page.items || []) if (!known.has(event.event_id)) {
        known.add(event.event_id); memoryCloudActivityEvents.push(event);
      }
      hasMore = Boolean(page.page?.has_more);
      const next = page.page?.next_cursor || "";
      if (hasMore && (!next || next === cursor)) break;
      cursor = next;
    }
    memoryCloudActivityEvents.sort((left, right) => left.timestamp.localeCompare(right.timestamp) || left.event_id.localeCompare(right.event_id));
    memoryCloudActivityComplete = !hasMore && memoryCloudActivityEvents.length < MEMORY_CLOUD_ACTIVITY_LIMIT;
    applyMemoryCloudActivityPattern();
    if (elements.memoryCloudLive.checked) await startMemoryCloudLive();
    return memoryCloudActivityPattern;
  }

  async function readMemoryCloudLivePage(turnId, cursor = "", tail = false) {
    const params = new URLSearchParams({ limit: "50" });
    if (cursor) params.set("cursor", cursor);
    if (tail) params.set("tail", "true");
    const response = await fetchWithTimeout(`/api/brainwatch/turns/${encodeURIComponent(turnId)}/runtime-events/live?${params}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Live-Turn-Aktivität");
    if (!response.ok) throw new Error(data.error || "Live-Turn-Aktivität konnte nicht gelesen werden.");
    return data;
  }

  function stopMemoryCloudLive() {
    if (memoryCloudLiveTimer) window.clearInterval(memoryCloudLiveTimer);
    memoryCloudLiveTimer = null; memoryCloudLiveBusy = false;
  }

  async function pollMemoryCloudLive() {
    if (memoryCloudLiveBusy || !elements.memoryCloudLive.checked || !memoryCloudActivityTurn || (document.hidden && !memoryCloudRenderer?.xrSession)
      || !brainwatchOpen || brainwatchMode !== "memory" || memoryExplorerSubview !== "cloud") return;
    if (memoryCloudActivityEvents.length >= MEMORY_CLOUD_ACTIVITY_LIMIT) {
      memoryCloudActivityComplete = false; stopMemoryCloudLive();
      renderMemoryCloudActivityStatus(`Live-Nachlauf pausiert: Browsergrenze von ${MEMORY_CLOUD_ACTIVITY_LIMIT} Ereignissen erreicht.`);
      return;
    }
    memoryCloudLiveBusy = true;
    try {
      const added = [], known = new Set(memoryCloudActivityEvents.map((event) => event.event_id));
      let hasMore = true;
      while (hasMore && memoryCloudActivityEvents.length < MEMORY_CLOUD_ACTIVITY_LIMIT) {
        const page = await readMemoryCloudLivePage(memoryCloudActivityTurn, memoryCloudLiveCursor);
        memoryCloudLiveCursor = page.page?.poll_cursor || memoryCloudLiveCursor;
        for (const event of page.items || []) if (!known.has(event.event_id)) {
          known.add(event.event_id); memoryCloudActivityEvents.push(event); added.push(event);
        }
        hasMore = Boolean(page.page?.has_more);
      }
      if (added.length) {
        memoryCloudActivityEvents.sort((left, right) => left.timestamp.localeCompare(right.timestamp) || left.event_id.localeCompare(right.event_id));
        if (memoryCloudActivityEvents.length >= MEMORY_CLOUD_ACTIVITY_LIMIT) memoryCloudActivityComplete = false;
        applyMemoryCloudActivityPattern();
        for (const event of added) memoryCloudRenderer?.animateActivityEvent(event);
      } else renderMemoryCloudActivityStatus();
    } catch (error) {
      stopMemoryCloudLive();
      renderMemoryCloudActivityStatus(`Live-Nachlauf gestoppt: ${error.message}`);
    } finally { memoryCloudLiveBusy = false; }
  }

  async function startMemoryCloudLive() {
    stopMemoryCloudLive();
    if (!elements.memoryCloudLive.checked || !memoryCloudActivityTurn || (document.hidden && !memoryCloudRenderer?.xrSession)
      || !brainwatchOpen || brainwatchMode !== "memory" || memoryExplorerSubview !== "cloud") return;
    if (memoryCloudActivityEvents.length >= MEMORY_CLOUD_ACTIVITY_LIMIT) {
      memoryCloudActivityComplete = false;
      renderMemoryCloudActivityStatus(`LIVE nicht gestartet: Browsergrenze von ${MEMORY_CLOUD_ACTIVITY_LIMIT} Ereignissen erreicht.`);
      return;
    }
    if (!memoryCloudLiveCursor) {
      const tail = await readMemoryCloudLivePage(memoryCloudActivityTurn, "", true);
      memoryCloudLiveCursor = tail.page?.poll_cursor || "";
    }
    memoryCloudLiveTimer = window.setInterval(pollMemoryCloudLive, 1500);
    renderMemoryCloudActivityStatus();
  }

  function syncMemoryCloudLive() {
    syncWorkingMemoryCloud();
    if (elements.memoryCloudLive.checked && memoryCloudActivityTurn && (!document.hidden || memoryCloudRenderer?.xrSession)
      && brainwatchOpen && brainwatchMode === "memory" && memoryExplorerSubview === "cloud") {
      startMemoryCloudLive().catch((error) => renderMemoryCloudActivityStatus(`Live-Nachlauf gestoppt: ${error.message}`));
    } else stopMemoryCloudLive();
  }

  function updateWorkingMemoryCloud(snapshot = memoryWorkingLayer?.snapshot, impulses = []) {
    const show = elements.memoryCloudWorking.checked;
    const nodes = show ? snapshot?.nodes || [] : [];
    const edges = show ? snapshot?.edges || [] : [];
    if (memoryCloudRenderer?.selectedClaim?.startsWith("work:")
      && !nodes.some(node => node.id === memoryCloudRenderer.selectedClaim)) memoryCloudRenderer.clearSelection();
    if (memoryCloudRenderer?.selectedRelation?.startsWith("work-edge:")
      && !edges.some(edge => edge.id === memoryCloudRenderer.selectedRelation)) memoryCloudRenderer.clearSelection();
    memoryCloudRenderer?.setData([...memoryCloudNodes.values(), ...nodes],
      [...memoryCloudEdges.values(), ...edges], memoryCloudLayoutVersion);
    if (snapshot && show) {
      elements.memoryCloudWorkingStatus.textContent = window.EveWorkingMemoryCloud.summary(snapshot)
        + ` · ${nodes.length} temporäre Objekte gezeigt (begrenzter Ausschnitt)`;
      for (const event of impulses) memoryCloudRenderer?.animateWorkingEvent(event);
    }
    elements.memoryCloudWorkingStatus.hidden = !show;
  }

  function syncWorkingMemoryCloud() {
    if (!window.EveWorkingMemoryCloud) return;
    memoryWorkingLayer ||= new window.EveWorkingMemoryCloud.WorkingMemoryLayer({
      read: () => memoryExplorerRead("graph/working"),
      active: () => elements.memoryCloudWorking.checked && brainwatchOpen && brainwatchMode === "memory"
        && memoryExplorerSubview === "cloud" && (!document.hidden || Boolean(memoryCloudRenderer?.xrSession)),
      render: updateWorkingMemoryCloud,
      status: message => { elements.memoryCloudWorkingStatus.textContent = message; },
    });
    memoryWorkingLayer.sync();
  }

  function renderWorkingMemoryInspector(value) {
    const inspector = elements.brainwatchInspector;
    inspector.replaceChildren();
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow";
    eyebrow.textContent = "KURZZEITGEDÄCHTNIS · TEMPORÄR";
    const title = document.createElement("h2");
    title.textContent = value.display_text || value.relation_type || "Arbeitsobjekt";
    const text = document.createElement("p");
    text.textContent = "Dieser Arbeitsstand zeigt Material und protokollierte Werkzeugaufrufe beim Lernen. "
      + "Ein Lichtimpuls belegt einen Zugriff, noch keinen Lernerfolg. Abgeschlossene Arbeitsstände "
      + "bleiben bis zu 15 Minuten in dieser Ansicht; die Aufbewahrung der Daten ist davon unabhängig.";
    inspector.append(eyebrow, title, text);
    appendMemoryFields(inspector, [
      ["Objekt-ID", value.object_id || value.id], ["Art", value.kind || "Werkzeugverbindung"],
      ["Arbeitsstand", value.workspace_id], ["Status", value.work_status || value.status],
      ["Umfang", value.byte_count == null ? null : `${value.byte_count} Bytes`],
      ["Erstellt", value.created_at], ["Aufruf", value.call_id],
    ]);
  }

  function focusMemoryCloudClaim() {
    const claimId = brainwatchGraph.focus || memoryCloudRenderer?.selectedClaim;
    if (!claimId) { setMemoryStructureStatus("Wähle zuerst einen Claim."); return; }
    const focus = `claim:${String(claimId).replace(/^claim:/, "")}`;
    const ready = memoryCloudNodes.has(focus) ? Promise.resolve() : loadMemoryStructure(false, "");
    ready.then(() => pinMemoryCloudSelection("claim", focus, { focus: true }))
      .catch((error) => { setMemoryStructureStatus(error.message); });
  }

  function memoryEventDescription(event) {
    if (event.event_source === "runtime") return `Persistiertes Runtime-Ereignis der Kategorie ${MEMORY_CATEGORY_LABELS[event.category] || event.category}.`;
    if (event.event_kind === "compiler_retrieved") return "Der Claim erschien in dieser Compiler-Evaluation als Kandidat. Auswahl oder Verwendung ist damit nicht belegt.";
    if (event.event_kind === "compiler_would_present") return "Der Compiler hätte den Claim in dieser Evaluation präsentiert. Dies ist kein sicherer Nachweis eines konkreten Prompt-Kontexts.";
    if (event.event_kind === "usage_presented") return "Eine Präsentation wurde protokolliert. Tatsächliche Prompt-Aufnahme und Verwendung sind nicht zuverlässig belegt.";
    if (event.event_kind === "semantic_reuse_result") return "Gespeichertes scopespezifisches Ergebnis einer semantischen Wiederverwendung.";
    if (event.fidelity === "state_timestamp") return "Gespeicherter Zustandszeitpunkt ohne vollständigen Vorher-/Nachher-Verlauf.";
    if (event.fidelity === "derived_link") return "Aus persistenten Fremdschlüsseln abgeleitete Verbindung ohne zusätzliche Kausalitätsaussage.";
    return "Eigenständige persistente Ereigniszeile.";
  }

  function renderMemoryEventInspector(event) {
    const inspector = elements.brainwatchInspector; inspector.replaceChildren();
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = event.event_source === "runtime" ? "MEMORY-RUNTIME-EREIGNIS" : "HISTORISCHES MEMORY-EREIGNIS";
    const title = document.createElement("h2"); title.textContent = MEMORY_EVENT_LABELS[event.event_kind] || event.event_kind;
    const description = document.createElement("p"); description.textContent = memoryEventDescription(event);
    const fidelity = document.createElement("span"); fidelity.className = `memory-fidelity fidelity-${event.fidelity}`;
    fidelity.textContent = MEMORY_FIDELITY_LABELS[event.fidelity] || event.fidelity;
    inspector.append(eyebrow, title, fidelity, description);
    appendMemoryFields(inspector, [
      ["Zeitpunkt", event.timestamp], ["Event-ID", event.event_id],
      ["Persistiert", event.recorded_at], ["Write-Delay (ms)", event.write_delay_ms],
      ["Quelle", event.event_source], ["Kategorie", MEMORY_CATEGORY_LABELS[event.category] || event.category],
      ["Quelltabelle", event.source_table], ["Persistente Quell-ID", event.source_id],
      ["Compiler-Stufe", event.compiler_stage], ["Consumer", event.consumer],
      ["Proof-Level", event.proof_level], ["Eventstatus", event.event_status],
      ["Ergebnis", event.outcome_status], ["Verifikation", event.verification_status],
      ["Trace", event.trace_id], ["Tool-Runde", event.planner_round_id],
      ["LLM-Call", event.llm_call_id], ["Attempt", event.attempt_id],
      ["Operation", event.operation_id], ["Plan", event.plan_id],
      ["Action", event.action_id], ["Action-Position", event.action_index],
      ["Evidence-ID", event.evidence_id], ["Relations-ID", event.relation_id],
    ]);
    const navigation = memorySection(inspector, "Navigation");
    if (event.event_source === "runtime" && !event.causal_targets) {
      const full = document.createElement("button"); full.type = "button"; full.className = "memory-link eve-button eve-button--ghost";
      full.textContent = "VOLLSTÄNDIGEN EVENT UND ZIELSTATUS LADEN";
      full.addEventListener("click", async () => {
        try { renderMemoryEventInspector(await runtimeEventRead(event.runtime_event_id)); }
        catch (error) { elements.memoryExplorerStatus.textContent = error.message; }
      }); navigation.append(full);
    }
    for (const claimId of event.claim_ids || []) {
      const button = document.createElement("button"); button.type = "button";
      button.className = "memory-link eve-button eve-button--ghost";
      button.textContent = `${claimId} IM MEMORY EXPLORER ÖFFNEN`;
      button.addEventListener("click", () => navigateBrainwatchClaim(claimId)); navigation.append(button);
    }
    if (event.turn_id) {
      const button = document.createElement("button"); button.type = "button";
      button.className = "memory-link eve-button eve-button--ghost";
      button.textContent = `${event.turn_id} IM INFORMATIONSGRAPH ÖFFNEN`;
      button.addEventListener("click", () => navigateBrainwatchTurn(event.turn_id)); navigation.append(button);
    }
    if (event.tool_event_id) {
      const button = document.createElement("button"); button.type = "button"; button.className = "memory-link eve-button eve-button--ghost";
      button.textContent = `${event.tool_event_id} IM INFORMATIONSGRAPH ÖFFNEN`;
      button.addEventListener("click", () => { setBrainwatchMode("information", { load: false }); focusBrainwatchNode(event.tool_event_id, { anchor: true }).catch((error) => { elements.brainwatchStatus.textContent = error.message; }); });
      navigation.append(button);
    }
    for (const [field, value, label] of [
      ["trace_id", event.trace_id, "TRACE"], ["planner_round_id", event.planner_round_id, "PLANNER-RUNDE"],
      ["llm_call_id", event.llm_call_id, "LLM-CALL"], ["attempt_id", event.attempt_id, "ATTEMPT"],
      ["operation_id", event.operation_id, "OPERATION"], ["plan_id", event.plan_id, "PLAN"], ["action_id", event.action_id, "ACTION"],
    ]) if (value) {
      const button = document.createElement("button"); button.type = "button"; button.className = "memory-link eve-button eve-button--ghost";
      button.textContent = `${label}-EREIGNISSE ZEIGEN`; button.addEventListener("click", () => navigateRuntimeTimeline(field, value)); navigation.append(button);
    }
    if (event.parent_event_id) {
      const parent = document.createElement("button"); parent.type = "button"; parent.className = "memory-link eve-button eve-button--ghost";
      parent.textContent = "ÜBERGEORDNETES EVENT ÖFFNEN";
      parent.addEventListener("click", async () => { try { renderMemoryEventInspector(await runtimeEventRead(event.parent_event_id)); } catch (error) { elements.memoryExplorerStatus.textContent = error.message; } });
      navigation.append(parent);
    }
    if (!navigation.querySelector("button")) {
      const unavailable = document.createElement("p"); unavailable.textContent = "Keine Claim- oder Turn-Referenz aufgezeichnet."; navigation.append(unavailable);
    }
    const missingTargets = Object.entries(event.causal_targets || {}).filter(([, target]) => target.persisted_target_exists === false);
    if (missingTargets.length) {
      const missing = document.createElement("p"); missing.className = "memory-participation-notice";
      missing.textContent = `Persistiertes Navigationsziel fehlt: ${missingTargets.map(([name, target]) => `${name}=${target.id}`).join(", ")}.`;
      navigation.append(missing);
    }
    const technical = document.createElement("details"); const summary = document.createElement("summary");
    summary.textContent = "Technischer Ereignisbeleg";
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify(event, null, 2);
    technical.append(summary, pre); inspector.append(technical);
  }

  function navigateRuntimeTimeline(field, value) {
    const controls = {
      trace_id: elements.memoryTimelineTrace, planner_round_id: elements.memoryTimelinePlannerRound,
      llm_call_id: elements.memoryTimelineLlmCall, attempt_id: elements.memoryTimelineAttempt,
      operation_id: elements.memoryTimelineOperation, plan_id: elements.memoryTimelinePlan,
      action_id: elements.memoryTimelineAction,
    };
    elements.memoryTimelineSource.value = "runtime";
    for (const control of Object.values(controls)) control.value = "";
    if (controls[field]) controls[field].value = value;
    setMemoryExplorerSubview("timeline", { load: false });
    loadMemoryTimeline(false).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
  }

  function selectMemoryTimelineEvent(index, options) {
    options = options || {};
    if (!memoryTimelineEvents.length) { memoryTimelineIndex = -1; elements.memoryTimelinePosition.textContent = "Kein Ereignis gewählt"; return; }
    memoryTimelineIndex = Math.max(0, Math.min(index, memoryTimelineEvents.length - 1));
    const selected = memoryTimelineEvents[memoryTimelineIndex];
    elements.memoryTimelinePosition.textContent = `${memoryTimelineIndex + 1} / ${memoryTimelineEvents.length} · ${selected.timestamp}`;
    for (const [position, card] of [...elements.memoryTimelineList.children].entries()) {
      card.classList.toggle("active", position === memoryTimelineIndex);
      card.setAttribute("aria-current", position === memoryTimelineIndex ? "true" : "false");
    }
    renderMemoryEventInspector(selected);
    if (selected.event_source === "runtime") {
      const activityEvents = filteredMemoryCloudActivityEvents();
      const activityIndex = activityEvents.findIndex((event) => event.event_id === selected.event_id);
      if (activityIndex >= 0) memoryCloudActivityIndex = activityIndex;
      memoryCloudRenderer?.resumeActivity();
      memoryCloudRenderer?.animateActivityEvent(selected);
      focusMemoryCloudActivityTarget(selected);
      renderMemoryCloudActivityStatus();
    }
    if (options.scroll !== false) elements.memoryTimelineList.children[memoryTimelineIndex]?.scrollIntoView({ block: "nearest" });
  }

  function renderMemoryTimeline(selectedId = memoryTimelineEvents[memoryTimelineIndex]?.event_id) {
    elements.memoryTimelineList.replaceChildren();
    for (const [index, event] of memoryTimelineEvents.entries()) {
      const card = document.createElement("button"); card.type = "button";
      card.className = `memory-timeline-event fidelity-${event.fidelity} source-${event.event_source || "historical"}`;
      const time = document.createElement("time"); time.dateTime = event.timestamp; time.textContent = event.timestamp;
      const title = document.createElement("strong"); title.textContent = MEMORY_EVENT_LABELS[event.event_kind] || event.event_kind;
      const badge = document.createElement("span"); badge.className = "memory-fidelity";
      badge.textContent = event.event_source === "runtime" ? `RUNTIME · ${event.proof_level || "direkt"}` : `HISTORISCH · ${MEMORY_FIDELITY_LABELS[event.fidelity] || event.fidelity}`;
      const source = document.createElement("small"); source.textContent = `${MEMORY_CATEGORY_LABELS[event.category] || event.category} · ${event.source_table} · ${event.source_id}${event.recorded_at && event.recorded_at !== event.timestamp ? ` · persistiert ${event.recorded_at}` : ""}${event.corroboration ? " · technisch korrespondierende Claim-Erstellung" : ""}`;
      const detail = document.createElement("p"); detail.textContent = memoryEventDescription(event);
      card.append(time, title, badge, source, detail);
      card.addEventListener("click", () => { pauseMemoryTimeline(); selectMemoryTimelineEvent(index); });
      elements.memoryTimelineList.append(card);
    }
    memoryTimelineIndex = selectedId ? memoryTimelineEvents.findIndex((event) => event.event_id === selectedId) : -1;
    if (memoryTimelineIndex >= 0) selectMemoryTimelineEvent(memoryTimelineIndex, { scroll: false });
    else elements.memoryTimelinePosition.textContent = memoryTimelineEvents.length
      ? `${memoryTimelineEvents.length} persistente Ereignisse geladen` : "Keine Ereignisse im gewählten Fenster";
  }

  function markMemoryCorroboration(events) {
    for (const event of events) delete event.corroboration;
    const historical = new Map(events.filter((event) => event.event_source === "historical" && event.event_kind === "claim_created" && event.claim_ids?.length)
      .map((event) => [event.claim_ids[0], event]));
    for (const event of events) {
      if (event.event_source !== "runtime" || event.event_kind !== "claim_lifecycle_changed" || event.details?.change_kind !== "created") continue;
      const projected = historical.get(event.claim_ids?.[0]);
      if (!projected) continue;
      event.corroboration = { event_id: projected.event_id, basis: "same_persisted_claim_id_and_explicit_created_transition" };
      projected.corroboration = { event_id: event.event_id, basis: "same_persisted_claim_id_and_explicit_created_transition", secondary_projection: true };
    }
  }

  function pauseMemoryTimeline() {
    if (memoryTimelineTimer) window.clearInterval(memoryTimelineTimer);
    memoryTimelineTimer = null;
    elements.memoryTimelinePlay.setAttribute("aria-pressed", "false");
    elements.memoryTimelinePlay.textContent = "START";
  }

  function playMemoryTimeline() {
    if (memoryTimelineTimer) { pauseMemoryTimeline(); return; }
    if (!memoryTimelineEvents.length) return;
    if (memoryTimelineIndex < 0 || memoryTimelineIndex >= memoryTimelineEvents.length - 1) selectMemoryTimelineEvent(0);
    elements.memoryTimelinePlay.setAttribute("aria-pressed", "true");
    elements.memoryTimelinePlay.textContent = "PAUSE";
    memoryTimelineTimer = window.setInterval(() => {
      if (memoryTimelineIndex >= memoryTimelineEvents.length - 1) { pauseMemoryTimeline(); return; }
      selectMemoryTimelineEvent(memoryTimelineIndex + 1);
    }, Number(elements.memoryTimelineSpeed.value) || 1000);
  }

  function memoryTimelineParameters(source, cursor) {
    if (cursor === undefined) { cursor = source || ""; source = "historical"; }
    const params = new URLSearchParams({ limit: "30" });
    const common = [
      ["from", elements.memoryTimelineFrom.value], ["to", elements.memoryTimelineTo.value],
      ["claim_id", elements.memoryTimelineClaim.value.trim()], ["turn_id", elements.memoryTimelineTurn.value.trim()],
      ["consumer", elements.memoryTimelineConsumer.value], ["category", elements.memoryTimelineCategory.value],
      ["cursor", cursor],
    ];
    const sourceFilters = source === "historical" ? [
      ["event_kind", elements.memoryTimelineKind.value], ["fidelity", elements.memoryTimelineFidelity.value],
      ["scope", elements.memoryTimelineScope.value.trim()], ["compiler_stage", elements.memoryTimelineStage.value],
    ] : [
      ["proof_level", elements.memoryTimelineProof.value], ["event_status", elements.memoryTimelineStatus.value],
      ["trace_id", elements.memoryTimelineTrace.value.trim()], ["planner_round_id", elements.memoryTimelinePlannerRound.value.trim()],
      ["llm_call_id", elements.memoryTimelineLlmCall.value.trim()], ["attempt_id", elements.memoryTimelineAttempt.value.trim()],
      ["operation_id", elements.memoryTimelineOperation.value.trim()], ["plan_id", elements.memoryTimelinePlan.value.trim()],
      ["action_id", elements.memoryTimelineAction.value.trim()], ["sort", "desc"],
    ];
    for (const [key, value] of [...common, ...sourceFilters]) if (value) params.set(key, value);
    return params;
  }

  async function loadMemoryTimeline(append = false) {
    pauseMemoryTimeline();
    const selectedId = memoryTimelineEvents[memoryTimelineIndex]?.event_id;
    elements.memoryExplorerStatus.textContent = append ? "Ältere Ereignisse werden geladen …" : "Persistente Memory-Ereignisse werden gelesen …";
    if (!append) {
      memoryTimelineEvents = []; memoryTimelineIndex = -1;
      memoryTimelineCursor = { historical: null, runtime: null };
      memoryTimelineHasMore = { historical: false, runtime: false };
    }
    const requestedSource = elements.memoryTimelineSource.value;
    const category = elements.memoryTimelineCategory.value;
    const sources = requestedSource === "all" ? ["historical", "runtime"] : [requestedSource];
    const pages = [];
    for (const source of sources) {
      if (append && !memoryTimelineHasMore[source]) continue;
      if (source === "historical" && category && !new Set(["retrieval", "memory_changes", "relations"]).has(category)) continue;
      const cursor = append ? memoryTimelineCursor[source] : "";
      const page = source === "historical"
        ? await memoryExplorerRead(`events?${memoryTimelineParameters(cursor)}`)
        : await memoryExplorerRead(`runtime-events?${memoryTimelineParameters(source, cursor)}`);
      pages.push({ source, page });
      memoryTimelineCursor[source] = page.page?.next_cursor || null;
      memoryTimelineHasMore[source] = Boolean(page.page?.has_more);
    }
    const known = new Set(memoryTimelineEvents.map((event) => event.event_id));
    for (const { source, page } of pages) for (const event of page.items || []) {
      event.event_source ||= source; if (!known.has(event.event_id)) { known.add(event.event_id); memoryTimelineEvents.push(event); }
    }
    memoryTimelineEvents.sort((left, right) => left.timestamp.localeCompare(right.timestamp)
      || String(left.event_source).localeCompare(String(right.event_source)) || left.event_id.localeCompare(right.event_id));
    markMemoryCorroboration(memoryTimelineEvents);
    elements.memoryTimelineMore.hidden = !sources.some((source) => memoryTimelineHasMore[source]);
    renderMemoryTimeline(selectedId);
    elements.memoryExplorerStatus.textContent = `${memoryTimelineEvents.length} persistierte Ereignisse geladen. Historische Projektionen und Runtime-Belege bleiben gekennzeichnet.`;
    const timelineTurn = memoryCloudTurnId(elements.memoryTimelineTurn.value);
    if (!append && timelineTurn && sources.includes("runtime")) {
      await loadMemoryCloudTurnActivity(timelineTurn);
    }
  }

  function setMemoryExplorerSubview(view, options) {
    options = options || {};
    if (!new Set(["cloud", "timeline"]).has(view)) view = "cloud";
    if (view !== "timeline") pauseMemoryTimeline();
    memoryExplorerSubview = view;
    const timeline = view === "timeline";
    const cloud = view === "cloud";
    elements.memoryCloudView.setAttribute("aria-pressed", String(cloud));
    elements.memoryTimelineView.setAttribute("aria-pressed", String(timeline));
    elements.memoryExplorerForm.hidden = timeline;
    elements.memoryExplorerSearch.disabled = timeline;
    elements.memoryExplorerSearch.placeholder = "Optionaler Suchbegriff";
    elements.memoryExplorerResults.hidden = timeline;
    elements.memoryExplorerMore.hidden = timeline || !memoryClaimsCursor;
    elements.memoryTimelineForm.hidden = !timeline;
    elements.memoryTimelineWorkspace.hidden = brainwatchMode !== "memory" || !timeline;
    elements.memoryCloudWorkspace.hidden = brainwatchMode !== "memory" || !cloud;
    memoryCloudRenderer?.setVisible(brainwatchMode === "memory" && cloud && brainwatchOpen);
    syncMemoryCloudLive();
    if (brainwatchMode === "memory") {
      elements.brainwatchCanvas.hidden = true;
      elements.brainwatchGraphToolbar.hidden = true;
      elements.brainwatchEmpty.hidden = true;
      elements.brainwatchGroups.hidden = true;
      elements.brainwatchMore.hidden = true;
    }
    if (timeline && options.load !== false && !memoryTimelineEvents.length) {
      loadMemoryTimeline(false).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
    } else if (cloud) {
      if (options.load !== false && !elements.memoryExplorerResults.childElementCount) {
        loadMemoryClaims(false).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
      }
      if (options.load !== false && !memoryCloudNodes.size) {
        loadMemoryStructure(false).catch((error) => { setMemoryStructureStatus(error.message); });
      }
      ensureMemoryCloud()?.requestRender();
    }
  }

  async function turnMemoryRead(turnId, cursor = "") {
    const params = new URLSearchParams({ limit: "20" }); if (cursor) params.set("cursor", cursor);
    const response = await fetchWithTimeout(`/api/brainwatch/turns/${encodeURIComponent(turnId)}/memory?${params}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Memory-Beteiligung");
    if (!response.ok) throw new Error(data.error || "Memory-Beteiligung konnte nicht gelesen werden.");
    return data;
  }

  async function loadTurnMemoryParticipation(nodeId, section, status) {
    const turnId = String(nodeId).replace(/^turn:/, "");
    const page = await turnMemoryRead(turnId);
    status.remove();
    appendMemoryParticipationPage(section, page, "turn-to-claim", (cursor) => turnMemoryRead(turnId, cursor));
  }

  async function turnRuntimeRead(turnId, cursor = "") {
    const params = new URLSearchParams({ limit: "50", sort: "asc" }); if (cursor) params.set("cursor", cursor);
    const response = await fetchWithTimeout(`/api/brainwatch/turns/${encodeURIComponent(turnId)}/runtime-events?${params}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Memory-Runtime");
    if (!response.ok) throw new Error(data.error || "Memory-Runtime konnte nicht gelesen werden.");
    return data;
  }

  function appendTurnRuntimePage(parent, page, loadMore) {
    const groups = new Map();
    for (const event of page.items || []) {
      const key = event.planner_round_id || "ohne Tool-Runde";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(event);
    }
    for (const [plannerRound, events] of groups) {
      const group = document.createElement("section"); group.className = "memory-runtime-group";
      const title = document.createElement("h4"); title.textContent = `Tool-Runde · ${plannerRound}`; group.append(title);
      for (const event of events) {
        const card = runtimeEventCard(event);
        appendMemoryFields(card, [
          ["LLM-Call", event.llm_call_id], ["Attempt", event.attempt_id],
          ["Operation", event.operation_id], ["Plan", event.plan_id],
          ["Action", event.action_id], ["Action-Position", event.action_index],
        ]);
        for (const claimId of event.claim_ids || []) {
          const openClaim = document.createElement("button"); openClaim.type = "button"; openClaim.className = "memory-link eve-button eve-button--ghost";
          openClaim.textContent = `${claimId} ÖFFNEN`; openClaim.addEventListener("click", () => navigateBrainwatchClaim(claimId)); card.append(openClaim);
        }
        group.append(card);
      }
      parent.append(group);
    }
    if (!(page.items || []).length && !parent.querySelector(".memory-runtime-event")) {
      const empty = document.createElement("p"); empty.textContent = "Für diesen Turn sind keine Runtime-Ereignisse persistiert."; parent.append(empty);
    }
    if (page.page?.has_more) {
      const more = document.createElement("button"); more.type = "button"; more.className = "eve-button"; more.textContent = "WEITERE RUNTIME-EREIGNISSE";
      more.addEventListener("click", async () => {
        more.disabled = true;
        try { const next = await loadMore(page.page.next_cursor); more.remove(); appendTurnRuntimePage(parent, next, loadMore); }
        catch (error) { more.disabled = false; more.textContent = error.message; }
      }); parent.append(more);
    }
  }

  async function loadTurnRuntime(nodeId, section, status) {
    const turnId = String(nodeId).replace(/^turn:/, "");
    const page = await turnRuntimeRead(turnId); status.remove();
    appendTurnRuntimePage(section, page, (cursor) => turnRuntimeRead(turnId, cursor));
  }

  function renderMemoryClaims(page, append) {
    if (!append) elements.memoryExplorerResults.replaceChildren();
    for (const claim of page.items || []) {
      const button = document.createElement("button"); button.type = "button"; button.className = "brainwatch-result memory-result eve-surface";
      const mark = document.createElement("span"); mark.className = `brainwatch-type-mark claim-${claim.claim_kind}`; mark.textContent = MEMORY_CLAIM_MARKS[claim.claim_kind] || "CLM";
      const copy = document.createElement("span"); const title = document.createElement("strong"); title.textContent = claim.display_text || claim.claim_id;
      const meta = document.createElement("small"); meta.textContent = `${claim.scope} · ${claim.lifecycle} · ${claim.verification_policy}`;
      copy.append(title, meta); button.append(mark, copy);
      button.addEventListener("click", () => focusMemoryClaim(claim.id, { anchor: true }).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; }));
      elements.memoryExplorerResults.append(button);
    }
    memoryClaimsCursor = page.page?.next_cursor || null;
    elements.memoryExplorerMore.hidden = !page.page?.has_more;
    const mode = page.search_mode === "bounded_like_fallback" ? " · begrenzter Suchfallback" : "";
    elements.memoryExplorerStatus.textContent = `${page.items?.length || 0} Claim(s) geladen${mode}.`;
    if (!append && !(page.items || []).length) elements.memoryExplorerStatus.textContent = "Keine passenden Memory-V2-Claims vorhanden.";
  }

  async function loadMemoryClaims(append = false) {
    const params = new URLSearchParams({ limit: "20" });
    const filters = {
      q: elements.memoryExplorerSearch.value.trim(), scope: elements.memoryExplorerScope.value.trim(),
      claim_kind: elements.memoryExplorerKind.value, lifecycle: elements.memoryExplorerLifecycle.value,
    };
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    if (append && memoryClaimsCursor) params.set("cursor", memoryClaimsCursor);
    elements.memoryExplorerStatus.textContent = append ? "Weitere Claims werden geladen …" : "Memory V2 wird gelesen …";
    renderMemoryClaims(await memoryExplorerRead(`claims?${params}`), append);
  }

  async function focusMemoryClaim(nodeId, options) {
    options = options || {};
    const { cursor = "", anchor = false } = options;
    const claimId = String(nodeId).replace(/^claim:/, "");
    const fullClaimId = `claim:${claimId}`;
    pinMemoryCloudSelection("claim", fullClaimId);
    if (anchor) brainwatchGraph.anchors.add(fullClaimId);
    elements.memoryExplorerStatus.textContent = "Claim, Evidence und Relations werden gelesen …";
    const relationParams = new URLSearchParams({ limit: "30" }); if (cursor) relationParams.set("cursor", cursor);
    const [detail, evidence, relations, turns, runtime] = await Promise.all([
      memoryExplorerRead(`claims/${encodeURIComponent(claimId)}`),
      memoryExplorerRead(`claims/${encodeURIComponent(claimId)}/evidence?limit=20`),
      memoryExplorerRead(`claims/${encodeURIComponent(claimId)}/relations?${relationParams}`),
      memoryExplorerRead(`claims/${encodeURIComponent(claimId)}/turns?limit=20`),
      memoryExplorerRead(`claims/${encodeURIComponent(claimId)}/runtime-events?limit=30&sort=asc`),
    ]);
    const graph = memoryRelationGraphPayload(detail.claim, relations);
    const staged = stageBrainwatchNeighbors(graph, detail.claim.id, cursor ? 1 : 0);
    if (!cursor || memoryRelationCache.claimId !== detail.claim.id) {
      memoryRelationCache = { claimId: detail.claim.id, items: [...relations.items] };
    } else {
      const known = new Set(memoryRelationCache.items.map((item) => item.id));
      memoryRelationCache.items.push(...relations.items.filter((item) => !known.has(item.id)));
    }
    const visibleRelations = { ...relations, items: memoryRelationCache.items };
    detail.runtime = runtime;
    brainwatchGraph.setFocus(detail.claim.id); renderMemoryClaimInspector(detail, evidence, visibleRelations, turns);
    brainwatchPage = relations.page?.has_more ? { kind: "memory", nodeId: detail.claim.id, cursor: relations.page.next_cursor } : null;
    elements.brainwatchMore.hidden = !brainwatchPage;
    elements.brainwatchMore.textContent = brainwatchPage ? "+ WEITERE RELATIONS" : "";
    elements.memoryExplorerStatus.textContent = staged.grouped
      ? `${staged.count} gespeicherte Relations nach Richtung verfügbar.`
      : `${staged.count} gespeicherte Relations geladen.`;
    updateBrainwatchControls();
  }

  async function searchBrainwatch(event) {
    event.preventDefault();
    const query = elements.brainwatchSearch.value.trim();
    if (!query) return;
    elements.brainwatchStatus.textContent = "EVE durchsucht ihre Informationswelt …";
    const params = new URLSearchParams({ q: query, limit: "30" });
    const response = await fetchWithTimeout(`/api/brainwatch/search?${params}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Brainwatch-Suche");
    if (!response.ok) throw new Error(data.error || "Brainwatch-Suche fehlgeschlagen.");
    renderBrainwatchResults(data);
  }

  const brainwatchCountFormat = new Intl.NumberFormat("de-DE");
  const brainwatchPercentFormat = new Intl.NumberFormat("de-DE", { style: "percent", maximumFractionDigits: 1 });

  async function showConversationLearningClaims(item, selectedClaims = null) {
    const claims = selectedClaims || item.claims || [];
    const claimIds = [...new Set(claims.map((claim) => `claim:${String(claim.id || claim.claim_id || "").replace(/^claim:/, "")}`).filter((id) => id !== "claim:"))];
    if (!claimIds.length) throw new Error("Dieser Lern-Turn hat keine verknüpften Claims.");
    memoryCloudLearningHighlight = {
      turnId: String(item.turn_id || ""),
      claimIds,
      evidenceCount: claims.reduce((amount, claim) => amount + (claim.evidence?.length || 0), 0),
    };
    memoryCloudPinnedSelection = null;
    setBrainwatchMode("memory", { load: false });
    setMemoryExplorerSubview("cloud", { load: false });
    elements.memoryExplorerSearch.value = "";
    elements.memoryExplorerScope.value = "";
    elements.memoryExplorerKind.value = "";
    elements.memoryExplorerLifecycle.value = "";
    elements.memoryCloudRelationType.value = "";
    await loadMemoryStructure(false);
    const visible = claimIds.filter((id) => memoryCloudNodes.has(id));
    if (!visible.length) throw new Error("Die verknüpften Claims sind in der aktuellen Memory-Struktur nicht mehr vorhanden.");
    restoreMemoryCloudLearningHighlight({ focus: true });
    setMemoryStructureStatus(`${visible.length} Claim${visible.length === 1 ? "" : "s"} aus dem Lern-Turn sind orange hervorgehoben.`);
  }

  function brainwatchStatisticCard(value, label, note = "", tone = "", onActivate = null) {
    const card = document.createElement(onActivate ? "button" : "article");
    if (onActivate) card.type = "button";
    card.className = `brainwatch-statistic-card${tone ? ` is-${tone}` : ""}`;
    if (typeof value !== "number") card.classList.add("is-textual");
    if (onActivate) {
      card.classList.add("is-interactive");
      card.title = `${label} ansehen`;
      card.addEventListener("click", () => onActivate(card));
    }
    const amount = document.createElement("strong"); amount.textContent = typeof value === "number" ? brainwatchCountFormat.format(value) : String(value ?? "–");
    const title = document.createElement("span"); title.textContent = label;
    card.append(amount, title);
    if (note) { const detail = document.createElement("small"); detail.textContent = note; card.append(detail); }
    return card;
  }

  function brainwatchStatisticSection(title, description = "") {
    const section = document.createElement("section"); section.className = "brainwatch-statistics-section";
    const heading = document.createElement("h3"); heading.textContent = title; section.append(heading);
    if (description) { const note = document.createElement("p"); note.textContent = description; section.append(note); }
    return section;
  }

  function appendBrainwatchStatisticGrid(section, cards) {
    const grid = document.createElement("div"); grid.className = "brainwatch-statistics-grid";
    for (const card of cards) grid.append(brainwatchStatisticCard(...card));
    section.append(grid);
  }

  const conversationLearningDecisionLabels = Object.freeze({
    create_active: "Aktiven Claim angelegt", create_candidate: "Claim-Kandidat angelegt",
    append_supporting_evidence: "Bestätigende Evidenz ergänzt",
    append_contradicting_evidence: "Widersprechende Evidenz ergänzt",
    create_competing_claim: "Konkurrierenden Claim angelegt",
    supersede_claim: "Claim abgelöst", refine_claim: "Claim verfeinert",
    no_persist: "Kein dauerhafter Inhalt",
    shadow_error: "Lernversuch ohne Abschluss", undetermined: "Vorschlag noch nicht ausreichend belegt",
  });

  function learningHelpButton(help) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "config-help-trigger"; button.textContent = "i";
    button.title = `${help.title}: ${help.text.join(" ")}`;
    button.setAttribute("aria-label", `Erklärung: ${help.title}`);
    button.setAttribute("aria-controls", "configHelpPopover");
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", event => {
      event.preventDefault(); event.stopPropagation();
      openConfigHelp(button, {help, hide_facts: true});
    });
    return button;
  }

  function conversationLearningJobCard(item) {
    const statusHelp = window.EveLearningHelp.status(item.status);
    const card = document.createElement("article"); card.className = `conversation-learning-job is-${item.status}`;
    const head = document.createElement("header");
    const heading = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = item.conversation_title || `Turn ${String(item.turn_id).slice(0, 12)}`;
    const timestamp = document.createElement("time");
    const dateValue = item.completed_at || item.updated_at || item.accepted_at;
    timestamp.textContent = dateValue ? new Date(dateValue).toLocaleString("de-DE") : "";
    heading.append(title, timestamp);
    const badge = document.createElement("span"); badge.className = "conversation-learning-job-status";
    badge.textContent = ({reviewed: "GEPRÜFT", applied: "ÜBERNOMMEN", failed: "OHNE ABSCHLUSS",
      pending: "WARTEND", running: "IN VERARBEITUNG", no_persist: "BEWUSST NICHT GESPEICHERT"})[item.status] || item.status;
    badge.title = statusHelp.text.join(" ");
    head.append(heading, badge, learningHelpButton(statusHelp)); card.append(head);

    const source = document.createElement("blockquote"); source.textContent = item.user_content || "Der Quelltext ist nicht mehr vorhanden."; card.append(source);
    const decision = document.createElement("div"); decision.className = "conversation-learning-decision";
    const decisionTitle = document.createElement("strong");
    decisionTitle.textContent = conversationLearningDecisionLabels[item.decision_type] || item.decision_type || (item.error_class ? "Übernahme nicht abgeschlossen" : "Noch nicht ausgewertet");
    decision.append(decisionTitle);
    if (item.rationale) { const rationale = document.createElement("span"); rationale.textContent = item.rationale; decision.append(rationale); }
    if (item.error_class) {
      const reason = item.latest_attempt?.proposal?.details?.response_evidence?.reason;
      const help = window.EveLearningHelp.error(item.error_class, reason);
      const error = document.createElement("span"); error.className = "is-error learning-error-description";
      const label = document.createElement("span"); label.textContent = help.title; label.title = help.text.join(" ");
      const code = document.createElement("code"); code.textContent = item.error_class; code.title = "Technischer Diagnosecode für die Fehlersuche";
      error.append(label, learningHelpButton(help), code); decision.append(error);
    }
    card.append(decision);
    if (item.status === "failed" || item.status === "reviewed") {
      if (item.latest_attempt) {
        const attempt = document.createElement("details");
        const summary = document.createElement("summary"); summary.textContent = "Fehler und ursprünglicher Lernvorschlag";
        const data = document.createElement("pre"); data.textContent = JSON.stringify(item.latest_attempt, null, 2);
        attempt.append(summary, data); card.append(attempt);
      }
      const actions = document.createElement("div"); actions.className = "conversation-learning-job-actions";
      const note = document.createElement("textarea"); note.rows = 2;
      note.placeholder = "Prüfnotiz (optional)"; note.setAttribute("aria-label", "Prüfnotiz");
      note.value = item.review_note || ""; note.readOnly = item.status === "reviewed";
      const review = document.createElement("button"); review.type = "button"; review.className = "eve-button eve-button--ghost";
      review.textContent = item.status === "reviewed" ? "WIEDER ÖFFNEN" : "ALS GEPRÜFT ABSCHLIESSEN";
      const reviewHelp = window.EveLearningHelp.review(item.status === "reviewed");
      review.title = reviewHelp.text.join(" ");
      review.addEventListener("click", async () => {
        review.disabled = true;
        try {
          const response = await fetchWithTimeout("/api/brainwatch/conversation-learning", {
            method: "POST", headers: { ...auth, "Content-Type": "application/json" },
            body: JSON.stringify({ action: item.status === "reviewed" ? "reopen_review" : "review", turn_id: item.turn_id, note: note.value }),
          });
          const result = await readJsonResponse(response, "Lernfehler prüfen");
          if (!response.ok) throw new Error(result.error || "Prüfstatus konnte nicht gespeichert werden.");
          await loadBrainwatchStatistics();
          elements.brainwatchStatisticsStatus.textContent = item.status === "reviewed"
            ? "Lernfehler wieder geöffnet. Er kann erneut eingereiht werden."
            : "Lernfehler geprüft und abgeschlossen. Er wird nicht erneut eingereiht.";
        } catch (error) { review.disabled = false; review.textContent = error.message; }
      });
      if (item.reviewed_at) {
        const reviewed = document.createElement("small");
        reviewed.textContent = `Geprüft am ${new Date(item.reviewed_at).toLocaleString("de-DE")}`;
        actions.append(reviewed);
      }
      actions.append(note, review, learningHelpButton(reviewHelp)); card.append(actions);
    }

    const claims = item.claims || [];
    if (claims.length) {
      const actions = document.createElement("div"); actions.className = "conversation-learning-job-actions";
      const showAll = document.createElement("button"); showAll.type = "button"; showAll.className = "eve-button eve-button--secondary";
      showAll.textContent = `${claims.length} CLAIM${claims.length === 1 ? "" : "S"} IN 3D ZEIGEN`;
      showAll.addEventListener("click", () => showConversationLearningClaims(item).catch((error) => { showAll.textContent = error.message; }));
      actions.append(showAll); card.append(actions);
      const claimList = document.createElement("div"); claimList.className = "conversation-learning-claims";
      for (const claim of claims) {
        const claimCard = document.createElement("article");
        const claimHead = document.createElement("header");
        const claimTitle = document.createElement("strong"); claimTitle.textContent = claim.display_text || claim.id;
        const open = document.createElement("button"); open.type = "button"; open.className = "eve-button eve-button--ghost"; open.textContent = "CLAIM IN 3D";
        open.addEventListener("click", () => showConversationLearningClaims(item, [claim]).catch((error) => { open.textContent = error.message; }));
        claimHead.append(claimTitle, open); claimCard.append(claimHead);
        const meta = document.createElement("small"); meta.textContent = `${claim.claim_kind} · ${claim.scope} · ${claim.lifecycle} · ${claim.verification_policy}`; claimCard.append(meta);
        for (const evidence of claim.evidence || []) {
          const proof = document.createElement("p"); proof.className = "conversation-learning-evidence";
          proof.textContent = `${evidence.stance === "contradicts" ? "Widerspricht" : "Belegt"} · ${evidence.evidence_type}${evidence.excerpt ? ` · ${evidence.excerpt}` : ""}`;
          claimCard.append(proof);
        }
        const technical = document.createElement("details");
        const summary = document.createElement("summary"); summary.textContent = "Persistierte Claim-Daten";
        const payload = document.createElement("pre"); payload.textContent = JSON.stringify({
          id: claim.id, canonical_key: claim.canonical_key, slot_key: claim.slot_key, payload: claim.payload,
        }, null, 2);
        technical.append(summary, payload); claimCard.append(technical); claimList.append(claimCard);
      }
      card.append(claimList);
      if ((item.relations || []).length) {
        const relationList = document.createElement("div"); relationList.className = "conversation-learning-relations";
        for (const relation of item.relations) {
          const line = document.createElement("p");
          line.textContent = `${relation.from_display_text || relation.from_claim_id} → ${relation.relation_type} → ${relation.to_display_text || relation.to_claim_id}`;
          relationList.append(line);
        }
        card.append(relationList);
      }
    } else {
      const empty = document.createElement("p"); empty.className = "conversation-learning-no-claims";
      empty.textContent = item.status === "no_persist"
        ? "Die Lernentscheidung hat bewusst keinen Claim und keine Evidenz angelegt."
        : item.status === "reviewed" ? "Dieser Lernfehler wurde geprüft und abgeschlossen. Es wird kein Wissen daraus übernommen."
        : item.status === "failed" ? "Dieser Lernversuch wurde nicht erfolgreich abgeschlossen. Das Quellmaterial bleibt für eine erneute Verarbeitung erhalten." : "Dieser Turn wartet noch auf seine Lernentscheidung.";
      card.append(empty);
    }
    if (item.assistant_content) {
      const assistant = document.createElement("details");
      const assistantSummary = document.createElement("summary"); assistantSummary.textContent = "EVEs damalige Antwort";
      const assistantText = document.createElement("p"); assistantText.textContent = item.assistant_content;
      assistant.append(assistantSummary, assistantText); card.append(assistant);
    }
    return card;
  }

  async function loadConversationLearningResults(status, label, host, trigger, offset = 0) {
    if (!offset) {
      host.replaceChildren(); host.hidden = false;
      const loading = document.createElement("p"); loading.textContent = `${label} werden gelesen …`; host.append(loading);
      host.closest(".brainwatch-statistics-section")?.querySelectorAll(".brainwatch-statistic-card.is-interactive").forEach((card) => card.classList.toggle("is-active", card === trigger));
    }
    const params = new URLSearchParams({ view: "jobs", status, limit: "40", offset: String(offset) });
    const response = await fetchWithTimeout(`/api/brainwatch/conversation-learning?${params}`, { cache: "no-store", headers: auth });
    const page = await readJsonResponse(response, "Lernergebnisse");
    if (!response.ok) throw new Error(page.error || "Lernergebnisse konnten nicht gelesen werden.");
    let list = host.querySelector(".conversation-learning-job-list");
    if (!offset) {
      host.replaceChildren();
      const head = document.createElement("header");
      const title = document.createElement("h4"); title.textContent = label;
      const count = document.createElement("span"); count.textContent = `${brainwatchCountFormat.format(page.total || 0)} Ergebnis${page.total === 1 ? "" : "se"}`;
      const close = document.createElement("button"); close.type = "button"; close.className = "eve-button eve-button--ghost"; close.textContent = "SCHLIESSEN";
      close.addEventListener("click", () => { host.hidden = true; host.replaceChildren(); trigger?.classList.remove("is-active"); });
      head.append(title, count, close); host.append(head);
      list = document.createElement("div"); list.className = "conversation-learning-job-list"; host.append(list);
    }
    for (const item of page.items || []) list.append(conversationLearningJobCard(item));
    host.querySelector(".conversation-learning-more")?.remove();
    if (!(page.items || []).length && !offset) {
      const empty = document.createElement("p"); empty.textContent = "Für diesen Zustand gibt es keine persistierten Lern-Turns."; list.append(empty);
    }
    if (page.page?.has_more) {
      const more = document.createElement("button"); more.type = "button"; more.className = "conversation-learning-more eve-button"; more.textContent = "WEITERE ERGEBNISSE";
      more.addEventListener("click", () => { more.disabled = true; loadConversationLearningResults(status, label, host, trigger, page.page.next_offset).catch((error) => { more.disabled = false; more.textContent = error.message; }); });
      host.append(more);
    }
  }

  function renderBrainwatchStatistics(data) {
    const memory = data.memory || {}, home = data.home_assistant || {}, tools = data.tools || {}, activity = data.activity || {};
    const content = elements.brainwatchStatisticsContent; content.replaceChildren();
    const learning = data.conversation_learning;
    if (learning) {
      const labels = {
        waiting: "Wartet auf Leerlauf", running: "Lernt", paused: "Pausiert",
        completed: "Aktuell", failed: "Technischer Fehler", disabled: "Deaktiviert",
      };
      const section = brainwatchStatisticSection(
        "Lernen aus Gesprächen",
        "EVE wertet offene Turns gebündelt im Leerlauf aus. Neue Benutzeraktivität pausiert laufende Inferenz; unvollständige Ergebnisse gelangen nicht ins Memory.",
      );
      const results = document.createElement("section"); results.className = "conversation-learning-results"; results.hidden = true;
      const inspect = (status, label) => (trigger) => {
        loadConversationLearningResults(status, label, results, trigger).catch((error) => {
          results.hidden = false; results.replaceChildren(); const message = document.createElement("p"); message.textContent = error.message; results.append(message);
        });
      };
      const learningCards = [
        [learning.status === "completed" && (learning.failed ?? 0) > 0
          ? "Abgeschlossen mit Fehlern" : (labels[learning.status] || learning.status), "Status"],
        [learning.pending ?? 0, "Offene Turns", "Klicken, um die wartenden Turns zu sehen", "", inspect("pending", "Offene Lern-Turns")],
        [learning.running ?? 0, "Gerade in Arbeit", "Klicken, um die laufenden Turns zu sehen", "", inspect("running", "Laufende Lern-Turns")],
        [learning.learned ?? 0, "Mit persistierter Evidenz",
          `${learning.evidence_records ?? 0} Evidenz-Einträge · ${learning.evidenced_claims ?? 0} Claims`, "success",
          inspect("evidenced", "Turns mit persistierter Evidenz")],
        [learning.discarded ?? 0, "Ohne dauerhaften Inhalt", "Klicken, um die Lernentscheidungen zu sehen", "rejected",
          inspect("no_persist", "Turns ohne dauerhaften Inhalt")],
        [learning.failed ?? 0, "Ohne Abschluss", learning.last_error || "Letzten Lernversuch prüfen", "failed",
          inspect("failed", "Lernversuche ohne Abschluss")],
        [learning.reviewed ?? 0, "Geprüft und abgeschlossen", "Keine erneute Lernauswertung", "",
          inspect("reviewed", "Geprüfte Lernfehler")],
      ];
      if ((learning.applied_without_evidence ?? 0) > 0) {
        learningCards.push([
          learning.applied_without_evidence, "Inkonsistente Lernläufe",
          "Als angewandt markiert, aber ohne persistierte Evidenz", "warning",
          inspect("inconsistent", "Inkonsistente Lern-Turns"),
        ]);
      }
      appendBrainwatchStatisticGrid(section, learningCards);
      const detail = document.createElement("p");
      detail.className = "conversation-learning-detail";
      detail.textContent = `${learning.batch_size} Turns pro Paket · Start nach ${learning.idle_delay_seconds} Sekunden Leerlauf`;
      const controls = document.createElement("div");
      controls.className = "conversation-learning-controls";
      const control = (label, action, disabled = false) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "eve-button eve-button--ghost";
        button.textContent = label;
        button.disabled = disabled;
        button.addEventListener("click", async () => {
          controls.querySelectorAll("button").forEach((item) => { item.disabled = true; });
          elements.brainwatchStatisticsStatus.textContent = `${label} …`;
          try {
            const response = await fetchWithTimeout("/api/brainwatch/conversation-learning", {
              method: "POST",
              headers: { ...auth, "Content-Type": "application/json" },
              body: JSON.stringify({ action }),
            });
            const result = await readJsonResponse(response, "Gesprächslernen");
            if (!response.ok) throw new Error(result.error || "Gesprächslernen konnte nicht gesteuert werden.");
            await loadBrainwatchStatistics();
          } catch (error) {
            elements.brainwatchStatisticsStatus.textContent = error.message;
            controls.querySelectorAll("button").forEach((item) => { item.disabled = false; });
          }
        });
        return button;
      };
      controls.append(
        control("JETZT LERNEN", "run_now", !learning.enabled || !(learning.pending ?? 0)),
        control("FEHLER WIEDERHOLEN", "retry_failed", !learning.enabled || !(learning.failed ?? 0)),
        control("PAUSIEREN", "pause", !learning.enabled || learning.pause_requested),
        control("FORTSETZEN", "resume", !learning.enabled || !learning.pause_requested),
      );
      section.append(detail, controls, results);
      content.append(section);
    }
    const overview = brainwatchStatisticSection("Überblick", "Vollständiger persistierter Bestand, unabhängig vom aktuell sichtbaren Ausschnitt.");
    appendBrainwatchStatisticGrid(overview, [
      [memory.claims, "Claims / Neuronen", `${memory.lifecycle?.active ?? 0} aktiv`],
      [memory.relations, "Relations / Kanten", `${memory.relation_types?.refines ?? 0} Verfeinerungen`],
      [home.active_entities, "Aktive HA-Entitäten", `${home.domains ?? 0} Domains · ${home.areas ?? 0} Bereiche`],
      [home.relations, "HA-Verbindungen", `${home.language_profiles ?? 0} Sprachprofile`],
      [tools.total, "Tool-Aufrufe", `${tools.by_tool?.length ?? 0} Tools`],
      [tools.success_rate == null ? "–" : brainwatchPercentFormat.format(tools.success_rate), "Tool-Erfolgsquote", "completed / alle Aufrufe", "success"],
    ]);
    content.append(overview);

    const memorySection = brainwatchStatisticSection("Memory", "Lifecycle, Herkunftsbelege und Lernentscheidungen.");
    appendBrainwatchStatisticGrid(memorySection, [
      [memory.lifecycle?.active ?? 0, "Aktive Claims"],
      [memory.lifecycle?.candidate ?? 0, "Kandidaten"],
      [memory.lifecycle?.retired ?? 0, "Abgelöst"],
      [memory.lifecycle?.invalid ?? 0, "Invalidiert"],
      [memory.observations ?? 0, "Beobachtungen"],
      [memory.evidence ?? 0, "Evidence-Einträge"],
      [memory.learning_decisions ?? 0, "Lernentscheidungen"],
      [memory.claims_last_24h ?? 0, "Neue Claims / 24 h"],
    ]);
    content.append(memorySection);

    const homeSection = brainwatchStatisticSection("Home Assistant", "Nur vom verbundenen Provider inventarisierte, persistierte Entitäten.");
    appendBrainwatchStatisticGrid(homeSection, [
      [home.active_entities ?? 0, "Aktiv gelernt"],
      [home.retired_entities ?? 0, "Nicht mehr geführt"],
      [home.unavailable_entities ?? 0, "Bei Inventur nicht erreichbar"],
      [home.domains ?? 0, "Domains"],
      [home.areas ?? 0, "Bereiche"],
      [home.language_profiles ?? 0, "Deterministische Sprachprofile"],
    ]);
    content.append(homeSection);

    const toolSection = brainwatchStatisticSection("Tool-Aufrufe", "Statuswerte bleiben getrennt: Ablehnung und unklarer Ausgang sind keine technischen Fehler.");
    appendBrainwatchStatisticGrid(toolSection, [
      [tools.successful ?? 0, "Erfolgreich", "completed / success", "success"],
      [tools.failed ?? 0, "Fehlerhaft", "error / failed", "failed"],
      [tools.rejected ?? 0, "Abgelehnt", "vor oder während der Ausführung", "rejected"],
      [tools.uncertain ?? 0, "Ausgang unklar", "outcome_uncertain", "uncertain"],
      [tools.other ?? 0, "Andere Statuswerte"],
    ]);
    const table = document.createElement("table"); table.className = "brainwatch-statistics-table";
    const head = document.createElement("thead"); const headRow = document.createElement("tr");
    for (const label of ["Tool", "Gesamt", "Erfolg", "Fehler", "Abgelehnt", "Unklar"]) { const cell = document.createElement("th"); cell.textContent = label; headRow.append(cell); }
    head.append(headRow); table.append(head);
    const body = document.createElement("tbody");
    for (const item of tools.by_tool || []) {
      const row = document.createElement("tr");
      for (const value of [item.tool, item.total, item.successful, item.failed, item.rejected, item.uncertain]) {
        const cell = document.createElement("td"); cell.textContent = typeof value === "number" ? brainwatchCountFormat.format(value) : String(value ?? "–"); row.append(cell);
      }
      body.append(row);
    }
    table.append(body); toolSection.append(table); content.append(toolSection);

    const runtimeSection = brainwatchStatisticSection("Belegte Aktivität", "Runtime-Zähler bezeichnen aufgezeichnete technische Ereignisse, keine geschätzte Nutzung.");
    appendBrainwatchStatisticGrid(runtimeSection, [
      [activity.turns ?? 0, "Turns"],
      [activity.conversations ?? 0, "Unterhaltungen"],
      [activity.runtime_events ?? 0, "Memory-Runtime-Ereignisse"],
      [activity.claims_with_runtime_events ?? 0, "Claims mit Runtime-Beleg"],
      [activity.relations_with_runtime_events ?? 0, "Relations mit Runtime-Beleg"],
    ]);
    content.append(runtimeSection);

    const facts = brainwatchStatisticSection("Exciting Fun Facts™", "Kuriose Spitzenwerte, weiterhin ausschließlich aus persistierten Datensätzen.");
    const list = document.createElement("div"); list.className = "brainwatch-fun-facts";
    const connected = data.fun_facts?.most_connected_claim;
    const runtime = data.fun_facts?.most_runtime_active_claim;
    const largest = home.largest_domain;
    const factTexts = [
      connected ? `Am stärksten vernetzt: „${connected.display_text}“ mit ${brainwatchCountFormat.format(connected.relations)} Relations.` : "Noch kein vernetzter Claim vorhanden.",
      largest ? `Größte Home-Assistant-Domain: ${largest.name} mit ${brainwatchCountFormat.format(largest.entities)} Entitäten.` : "Noch keine Home-Assistant-Domain inventarisiert.",
      data.fun_facts?.busiest_tool ? `Meistaufgerufenes Tool: ${data.fun_facts.busiest_tool}.` : "Noch keine Tool-Aufrufe persistiert.",
      runtime ? `Meiste aufgezeichnete Runtime-Aktivität: „${runtime.display_text}“ mit ${brainwatchCountFormat.format(runtime.events)} Ereignissen.` : "Noch kein Claim mit persistierter Runtime-Aktivität.",
      `${brainwatchCountFormat.format(memory.claims_last_24h ?? 0)} Claims kamen in den letzten 24 Stunden hinzu.`,
    ];
    for (const text of factTexts) { const item = document.createElement("article"); item.textContent = text; list.append(item); }
    facts.append(list); content.append(facts);
  }

  function renderBrainwatchStatisticsInspector() {
    elements.brainwatchInspector.replaceChildren();
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = "STATISTIK";
    const title = document.createElement("h2"); title.textContent = "Was wird gezählt?";
    const note = document.createElement("p"); note.textContent = "Jeder Zähler liest persistierte Datenbankzeilen. Sichtbare 3D-Punkte, Animationen oder UI-Zustände sind keine Datenquelle.";
    const details = document.createElement("dl");
    for (const [key, value] of [
      ["Neuron", "ein persistierter Memory-V2-Claim"],
      ["Kante", "eine persistierte Memory-V2-Relation"],
      ["HA-Entität", "aktive inventarisierte Provider-Bindung"],
      ["Tool-Erfolg", "Status completed oder success"],
      ["Tool-Fehler", "Status error oder failed"],
    ]) { const dt = document.createElement("dt"); dt.textContent = key; const dd = document.createElement("dd"); dd.textContent = value; details.append(dt, dd); }
    elements.brainwatchInspector.append(eyebrow, title, note, details);
  }

  async function loadBrainwatchStatistics() {
    elements.brainwatchStatisticsRefresh.disabled = true;
    elements.brainwatchStatisticsStatus.textContent = "Persistente Zähler werden gelesen …";
    try {
      const [statisticsResponse, learningResponse] = await Promise.all([
        fetchWithTimeout("/api/brainwatch/statistics", { cache: "no-store", headers: auth }),
        fetchWithTimeout("/api/brainwatch/conversation-learning", { cache: "no-store", headers: auth }),
      ]);
      const data = await readJsonResponse(statisticsResponse, "Brainwatch-Statistik");
      if (!statisticsResponse.ok) throw new Error(data.error || "Statistik konnte nicht gelesen werden.");
      const learning = await readJsonResponse(learningResponse, "Gesprächslernen");
      if (!learningResponse.ok) throw new Error(learning.error || "Gesprächslernen konnte nicht gelesen werden.");
      data.conversation_learning = learning;
      renderBrainwatchStatistics(data);
      elements.brainwatchStatisticsStatus.textContent = "Aktueller persistenter Stand geladen.";
      return data;
    } finally {
      elements.brainwatchStatisticsRefresh.disabled = false;
    }
  }

  let brainwatchEventsOffset = 0;
  let brainwatchEventsLoading = false;
  function showBrainwatchEventsError(error) {
    elements.brainwatchEventsStatus.textContent = error.message;
  }
  async function loadBrainwatchEvents(more) {
    if (brainwatchEventsLoading) return;
    brainwatchEventsLoading = true;
    elements.brainwatchEventsRefresh.disabled = elements.brainwatchEventsMore.disabled = true;
    elements.brainwatchEventsStatus.textContent = "Ereignisse werden gelesen …";
    try {
      const offset = more ? brainwatchEventsOffset : 0;
      const response = await fetchWithTimeout(`/api/brainwatch/assist-events?offset=${offset}&limit=50`, {cache: "no-store", headers: auth});
      const data = await readJsonResponse(response, "Ereignis-Inbox");
      if (!response.ok) throw new Error(data.error || "Ereignisse konnten nicht gelesen werden.");
      if (!more) elements.brainwatchEventsContent.replaceChildren();
      for (const group of data.groups) {
        const item = document.createElement("details"); item.className = "eve-panel";
        const title = document.createElement("summary");
        title.textContent = `${group.event_type} · ${group.count}×`;
        const times = document.createElement("p");
        times.textContent = `Erster Eingang: ${group.first_received_at} · Letzter Eingang: ${group.last_received_at}`;
        const payload = document.createElement("pre"); payload.style.whiteSpace = "pre-wrap"; payload.style.overflowWrap = "anywhere";
        payload.textContent = JSON.stringify({group_id: group.group_id, through_sequence: group.through_sequence, data: group.data}, null, 2);
        item.append(title, times, payload); elements.brainwatchEventsContent.append(item);
      }
      brainwatchEventsOffset = data.next_offset;
      elements.brainwatchEventsMore.hidden = data.next_offset === null;
      elements.brainwatchEventsStatus.textContent = `${data.pending_count} offene Eingänge in ${data.pending_groups} Gruppen · ${data.total_count} insgesamt gespeichert`;
    } finally {
      brainwatchEventsLoading = false;
      elements.brainwatchEventsRefresh.disabled = elements.brainwatchEventsMore.disabled = false;
    }
  }

  function setBrainwatchMode(mode, options) {
    options = options || {};
    const load = options.load !== false;
    if (!new Set(["information", "memory", "semantic", "statistics", "events"]).has(mode)) return;
    if (mode === brainwatchMode) { applyBrainwatchLayout(); return; }
    storeBrainwatchViewState();
    brainwatchMode = mode;
    renderBrainwatchPath();
    window.localStorage.setItem("eve.brainwatchMode", mode);
    const memory = mode === "memory";
    const semantic = mode === "semantic";
    const statistics = mode === "statistics";
    const events = mode === "events";
    elements.brainwatchEventsMode.setAttribute("aria-pressed", String(events));
    elements.brainwatchEventsNavigation.hidden = !events;
    elements.brainwatchEventsWorkspace.hidden = !events;
    elements.brainwatchInfoMode.setAttribute("aria-pressed", String(mode === "information"));
    elements.brainwatchMemoryMode.setAttribute("aria-pressed", String(memory));
    elements.brainwatchSemanticMode.setAttribute("aria-pressed", String(semantic));
    elements.brainwatchStatisticsMode.setAttribute("aria-pressed", String(statistics));
    elements.brainwatchInfoNavigation.hidden = mode !== "information";
    elements.memoryExplorerNavigation.hidden = !memory;
    elements.semanticNavigation.hidden = !semantic;
    elements.brainwatchStatisticsNavigation.hidden = !statistics;
    elements.semanticWorkspace.hidden = !semantic;
    elements.brainwatchStatisticsWorkspace.hidden = !statistics;
    elements.memoryTimelineWorkspace.hidden = !memory || memoryExplorerSubview !== "timeline";
    elements.memoryCloudWorkspace.hidden = !memory || memoryExplorerSubview !== "cloud";
    elements.brainwatchCanvas.hidden = memory || semantic || statistics || events;
    elements.brainwatchGraphToolbar.hidden = memory || semantic || statistics || events;
    memoryCloudRenderer?.setVisible(memory && memoryExplorerSubview === "cloud" && brainwatchOpen);
    syncMemoryCloudLive();
    if (!memory) pauseMemoryTimeline();
    if (events) {
      elements.brainwatchEmpty.hidden = true;
      elements.brainwatchGroups.hidden = true;
      elements.brainwatchMore.hidden = true;
      elements.brainwatchInspector.replaceChildren();
      const note = document.createElement("p");
      note.textContent = "Offen bedeutet noch nicht quittiert. Eine Quittierung durch EVE bestätigt nur die Kenntnisnahme, keine Reaktion. Rohereignisse bleiben gespeichert.";
      elements.brainwatchInspector.append(note);
    } else if (statistics) {
      elements.brainwatchEmpty.hidden = true;
      elements.brainwatchGroups.hidden = true;
      elements.brainwatchMore.hidden = true;
      renderBrainwatchStatisticsInspector();
    } else if (semantic) {
      elements.brainwatchEmpty.hidden = true;
      elements.brainwatchGroups.hidden = true;
      elements.brainwatchMore.hidden = true;
      renderSemanticModeInspector();
    } else {
      const restored = restoreBrainwatchViewState(mode);
      elements.brainwatchEmpty.textContent = memory
        ? "Wähle links einen realen Memory-V2-Claim. Gespeicherte Relations erscheinen als Pfeile."
        : "Suche links nach einem Thema und öffne einen Knoten.";
      const selectedNode = brainwatchGraph.nodes.get(brainwatchGraph.selected || brainwatchGraph.focus)?.data;
      const selectedEdge = brainwatchGraph.edges.get(brainwatchGraph.selected)?.data;
      if (!restored?.inspectorNodes?.length && selectedEdge) mode === "memory" ? renderMemoryRelationInspector(selectedEdge) : renderBrainwatchInspector({kind: "edge", value: selectedEdge});
      else if (!restored?.inspectorNodes?.length && selectedNode) renderBrainwatchInspector({kind: "node", value: selectedNode});
      else if (!restored?.inspectorNodes?.length) {
        elements.brainwatchInspector.replaceChildren();
        const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = memory ? "MEMORY EXPLORER" : "INSPECTOR";
        const title = document.createElement("h2"); title.textContent = memory ? "Noch kein Claim gewählt" : "Noch kein Knoten gewählt";
        const note = document.createElement("p"); note.textContent = memory
          ? "Alle angezeigten Claims und Pfeile besitzen persistente Memory-V2-Identitäten."
          : "Jeder sichtbare Pfeil zeigt eine gespeicherte, erklärbare Beziehung.";
        elements.brainwatchInspector.append(eyebrow, title, note);
      }
    }
    applyBrainwatchLayout();
    if (!brainwatchOpen) return;
    if (memory) {
      setMemoryExplorerSubview(memoryExplorerSubview, { load: false });
      if (load) {
        if (memoryExplorerSubview === "timeline") loadMemoryTimeline(false).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
        else {
          loadMemoryClaims(false).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
          loadMemoryStructure(false).catch((error) => { setMemoryStructureStatus(error.message); });
        }
        window.requestAnimationFrame(() => (memoryExplorerSubview === "timeline" ? elements.memoryTimelineKind : elements.memoryExplorerSearch).focus());
      }
    } else if (semantic) {
      loadSemanticLearning().catch((error) => { semanticSummary.textContent = error.message; });
      window.requestAnimationFrame(() => semanticSearch.focus());
    } else if (events) {
      if (load) loadBrainwatchEvents(false).catch(showBrainwatchEventsError);
      window.requestAnimationFrame(() => elements.brainwatchEventsRefresh.focus());
    } else if (statistics) {
      if (load) loadBrainwatchStatistics().catch((error) => { elements.brainwatchStatisticsStatus.textContent = error.message; });
      window.requestAnimationFrame(() => elements.brainwatchStatisticsRefresh.focus());
    } else {
      window.requestAnimationFrame(() => elements.brainwatchSearch.focus());
    }
  }

  function setBrainwatchOpen(open) {
    brainwatchOpen = Boolean(open);
    window.localStorage.setItem("eve.brainwatchOpen", String(brainwatchOpen));
    setSystemMenuOpen(false);
    elements.brainwatchView.hidden = !brainwatchOpen;
    if (!brainwatchOpen) { pauseMemoryTimeline(); disposeMemoryCloud(); closeConfigHelp(); }
    document.body.classList.toggle("brainwatch-open", brainwatchOpen);
    syncAvatarCloudVisibility();
    if (brainwatchOpen) {
      if (nerdMode) setNerdMode(false);
      setConfigOpen(false);
      toggleConversationPanel(false);
      applyBrainwatchLayout({persist: false});
      if (brainwatchMode === "memory" && memoryExplorerSubview === "timeline") loadMemoryTimeline(false).catch(error => { elements.memoryExplorerStatus.textContent = error.message; });
      else if (brainwatchMode === "memory") {
        loadMemoryClaims(false).catch(error => { elements.memoryExplorerStatus.textContent = error.message; });
        loadMemoryStructure(false).catch(error => { setMemoryStructureStatus(error.message); });
      }
      else if (brainwatchMode === "semantic") loadSemanticLearning().catch(error => { semanticSummary.textContent = error.message; });
      else if (brainwatchMode === "events") loadBrainwatchEvents(false).catch(showBrainwatchEventsError);
      else if (brainwatchMode === "statistics") loadBrainwatchStatistics().catch(error => { elements.brainwatchStatisticsStatus.textContent = error.message; });
      window.requestAnimationFrame(() => {
        brainwatchGraph.resize();
        if (brainwatchMode === "memory") (memoryExplorerSubview === "timeline" ? elements.memoryTimelineKind : elements.memoryExplorerSearch).focus();
        else if (brainwatchMode === "semantic") semanticSearch.focus();
        else if (brainwatchMode === "events") elements.brainwatchEventsRefresh.focus();
        else if (brainwatchMode === "statistics") elements.brainwatchStatisticsRefresh.focus();
        else elements.brainwatchSearch.focus();
      });
    } else scrollChatToLatest();
  }

  const semanticStateLabels = {candidate: "Kandidat", active: "Aktiv", invalid: "Invalidiert", retired: "Abgelöst"};
  const semanticConfirmationLabels = {confirmed: "Explizite Nutzerbestätigung", corroborated: "Automatische Evidenzbestätigung", operationally_grounded: "Exakte Wiederholung nach verifizierter Ausführung", unconfirmed: "Unbestätigt", contradicted: "Nutzerwiderspruch"};
  const storedSemanticReviewFilter = window.localStorage.getItem("eve.semanticReviewFilter");
  let semanticReviewFilter = new Set(["pending", "reviewed", "positive", "negative", "all"]).has(storedSemanticReviewFilter)
    ? storedSemanticReviewFilter : "pending";
  const semanticPanel = document.createElement("section");
  semanticPanel.className = "semantic-panel";
  const semanticHeading = document.createElement("header"); semanticHeading.className = "semantic-workspace-head";
  const semanticEyebrow = document.createElement("span"); semanticEyebrow.className = "eyebrow"; semanticEyebrow.textContent = "EVES GELERNTES SPRACHVERSTÄNDNIS";
  const semanticTitle = document.createElement("h2"); semanticTitle.textContent = "Semantisches Lernen";
  const semanticIntro = document.createElement("p"); semanticIntro.textContent = "Hier siehst du, welche Formulierungen EVE mit welchen Handlungen verbindet. Du kannst aktuelle Zuordnungen prüfen, falsche Bedeutungen korrigieren und einzelne Lernerfahrungen zurückweisen.";
  semanticHeading.append(semanticEyebrow, semanticTitle, semanticIntro);
  const semanticGuide = document.createElement("nav"); semanticGuide.className = "semantic-guide"; semanticGuide.setAttribute("aria-label", "Möglichkeiten im semantischen Lernen");
  const semanticMetrics = document.createElement("div"); semanticMetrics.className = "semantic-metrics";
  const semanticCoverage = document.createElement("details"); semanticCoverage.className = "semantic-coverage";
  const semanticCoverageTitle = document.createElement("summary"); semanticCoverageTitle.textContent = "Technische Details und vollständiger Bestand"; semanticCoverage.append(semanticCoverageTitle);
  const semanticSummary = document.createElement("p"); semanticSummary.className = "brainwatch-status semantic-navigation-status"; semanticSummary.textContent = "Semantikdaten werden beim Öffnen geladen.";
  const semanticForm = document.createElement("form");
  const semanticSearchLabel = document.createElement("label"); semanticSearchLabel.textContent = "Gelernte Formulierungen durchsuchen";
  const semanticSearch = document.createElement("input");
  semanticSearch.className = "eve-input"; semanticSearch.type = "search"; semanticSearch.maxLength = 300;
  semanticSearch.placeholder = "z. B. Rollo, Wohnzimmer oder ausschalten"; semanticSearch.setAttribute("aria-label", "Gelernte Formulierungen durchsuchen");
  const semanticFilter = document.createElement("select");
  semanticFilter.className = "eve-input"; semanticFilter.setAttribute("aria-label", "Semantischer Status");
  for (const [value, label] of Object.entries({"": "Alle Zustände", ...semanticStateLabels})) {
    const option = document.createElement("option"); option.value = value; option.textContent = label; semanticFilter.append(option);
  }
  const semanticLinkFilter = document.createElement("select");
  semanticLinkFilter.className = "eve-input"; semanticLinkFilter.setAttribute("aria-label", "Verknüpfungsstatus zur Handlung");
  for (const [value, label] of [["", "Alle Verknüpfungen"], ["usable", "Mit Handlung verknüpft"],
    ["conflict", "Widersprüchliche Verknüpfung"], ["insufficient_evidence", "Noch nicht ausreichend belegt"],
    ["invalid", "Ungültige Verknüpfung"]]) {
    const option = document.createElement("option"); option.value = value; option.textContent = label; semanticLinkFilter.append(option);
  }
  const semanticSubmit = document.createElement("button"); semanticSubmit.className = "eve-button eve-button--primary"; semanticSubmit.textContent = "ANZEIGEN";
  const semanticRows = document.createElement("div");
  semanticRows.className = "semantic-experiences";
  semanticRows.id = "semanticExperiences";
  const semanticMore = document.createElement("button"); semanticMore.type = "button"; semanticMore.className = "eve-button"; semanticMore.textContent = "WEITERE ERFAHRUNGEN"; semanticMore.hidden = true;
  semanticForm.append(semanticSearchLabel, semanticSearch, labeledControl("Status der Lernerfahrung", semanticFilter),
    labeledControl("Verknüpfung zur Handlung", semanticLinkFilter), semanticSubmit);
  const semanticNavigationTitle = document.createElement("span"); semanticNavigationTitle.className = "eyebrow"; semanticNavigationTitle.textContent = "GELERNTES DURCHSUCHEN";
  elements.semanticNavigation.append(semanticNavigationTitle, semanticForm, semanticSummary);
  let semanticCursor = null;
  const semanticDynamic = document.createElement("section");
  semanticDynamic.className = "semantic-dynamic";
  semanticDynamic.id = "semanticReview";
  const semanticComposition = document.createElement("section");
  semanticComposition.className = "semantic-dynamic semantic-advanced";
  const semanticActions = document.createElement("div");
  semanticActions.className = "semantic-actions";
  semanticActions.id = "semanticActions";
  const semanticExperienceHeading = document.createElement("header"); semanticExperienceHeading.className = "semantic-section-heading";
  semanticExperienceHeading.tabIndex = -1;
  const semanticExperienceTitle = document.createElement("h3"); semanticExperienceTitle.textContent = "Einzelne Lernerfahrungen";
  const semanticExperienceNote = document.createElement("p"); semanticExperienceNote.textContent = "Hier stehen konkrete Sätze, aus denen EVE gelernt hat. Öffne einen Eintrag, wenn du seine Herkunft prüfen oder ihn ablehnen möchtest.";
  semanticExperienceHeading.append(semanticExperienceTitle, semanticExperienceNote);
  semanticPanel.append(semanticHeading, semanticGuide, semanticMetrics, semanticDynamic, semanticActions,
    semanticExperienceHeading, semanticRows, semanticMore, semanticComposition, semanticCoverage);
  elements.semanticWorkspace.append(semanticPanel);
  let semanticActionCursor = null;

  function semanticGuideCard(title, description, action, target) {
    const card = document.createElement("button"); card.type = "button"; card.className = "semantic-guide-card";
    const heading = document.createElement("strong"); heading.textContent = title;
    const note = document.createElement("span"); note.textContent = description;
    const label = document.createElement("small"); label.textContent = action;
    card.append(heading, note, label);
    card.addEventListener("click", () => {
      target.scrollIntoView({behavior: presentationMotion ? "smooth" : "auto", block: "start"});
      target.focus?.({preventScroll: true});
    });
    return card;
  }
  semanticGuide.append(
    semanticGuideCard("1 · Zuordnungen prüfen", "Hat EVE eine neue Formulierung der richtigen bekannten Handlung zugeordnet?", "RICHTIG ODER FALSCH BEWERTEN", semanticDynamic),
    semanticGuideCard("2 · Gelerntes ansehen", "Welche unterschiedlichen Sätze führen inzwischen zur gleichen Handlung?", "HANDLUNGSGRUPPEN ÖFFNEN", semanticActions),
    semanticGuideCard("3 · Fehler korrigieren", "Markiere eine Zuordnung als falsch oder lehne eine einzelne Lernerfahrung ab.", "KORREKTURMÖGLICHKEITEN ANZEIGEN", semanticRows),
  );

  function renderSemanticModeInspector(stock = null) {
    elements.brainwatchInspector.replaceChildren();
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = "SEMANTISCHES LERNEN";
    const heading = document.createElement("h2"); heading.textContent = "Was kann ich hier tun?";
    const note = document.createElement("p"); note.textContent = "Prüfe, ob EVE deine Worte richtig verstanden hat. Eine Bestätigung stärkt die Zuordnung. Eine Falschmarkierung speichert eine Gegenregel, damit EVE denselben Fehler nicht wiederholt.";
    elements.brainwatchInspector.append(eyebrow, heading, note);
    if (stock) appendMemoryFields(elements.brainwatchInspector, [
      ["Bekannte Handlungen", stock.action_representations], ["Gelernte Formulierungen", stock.linked_formulations],
      ["Noch ungeprüft", stock.candidates], ["Widersprüche", stock.link_conflicts],
    ]);
    const warning = document.createElement("p"); warning.className = "semantic-write-note";
    warning.textContent = "Gelb markierte Schaltflächen verändern EVEs Memory. Sie lösen keine Geräteaktion aus und lassen sich – soweit angezeigt – wieder aufheben.";
    elements.brainwatchInspector.append(warning);
  }

  function renderSemanticMetrics(summary) {
    const c = summary.stock;
    semanticMetrics.replaceChildren();
    const values = [
      ["Bekannte Handlungen", c.action_representations, "Mehrere Sätze können dieselbe Handlung meinen", "", "actions"],
      ["Gelernte Formulierungen", c.linked_formulations, "Mit einer Handlung verknüpfte Sätze", "", "formulations"],
      ["Noch zu prüfen", c.candidates, "Noch nicht freigegebene Lernerfahrungen", "attention", "candidates"],
      ["Bestätigt", (c.automatic_active || 0) + (c.explicit_active || 0), "Automatisch oder ausdrücklich aktiviert", "success", "active"],
      ["Widersprüche", c.link_conflicts, "Mehrdeutige oder gegensätzliche Handlungsverknüpfungen", c.link_conflicts ? "warning" : "success", "conflicts"],
      ["Zurückgewiesen", c.invalid, "Als ungültig markierte Erfahrungen", "", "invalid"],
    ];
    for (const [label, value, explanation, tone, action] of values) {
      const metric = document.createElement("button"); metric.type = "button"; metric.classList.add("is-actionable");
      metric.title = `${label} anzeigen`;
      const number = document.createElement("strong"); const text = document.createElement("span");
      if (tone) metric.classList.add(`is-${tone}`);
      number.textContent = String(value || 0); text.textContent = label; const hint = document.createElement("small"); hint.textContent = `${explanation} · zum Anzeigen klicken`;
      metric.append(number, text, hint); semanticMetrics.append(metric);
      metric.addEventListener("click", () => {
        if (action === "actions") {
          semanticActions.scrollIntoView({behavior: presentationMotion ? "smooth" : "auto", block: "start"});
          semanticActions.focus({preventScroll: true}); semanticSummary.textContent = `${c.action_representations || 0} bekannte Handlungsgruppe(n).`;
          return;
        }
        const filters = {
          formulations: ["", "usable", `${c.linked_formulations || 0} mit Handlungen verknüpfte Formulierung(en)`],
          candidates: ["candidate", "", `${c.candidates || 0} noch nicht freigegebene Lernerfahrung(en)`],
          active: ["active", "", `${(c.automatic_active || 0) + (c.explicit_active || 0)} bestätigte Lernerfahrung(en)`],
          conflicts: ["", "conflict", `${c.link_conflicts || 0} widersprüchliche Handlungsverknüpfung(en)`],
          invalid: ["invalid", "", `${c.invalid || 0} zurückgewiesene Lernerfahrung(en)`],
        };
        const [status, linkStatus, message] = filters[action];
        semanticSearch.value = ""; semanticFilter.value = status; semanticLinkFilter.value = linkStatus;
        loadSemanticLearning().then(() => {
          semanticSummary.textContent = `${message} werden angezeigt.`;
          semanticExperienceHeading.scrollIntoView({behavior: presentationMotion ? "smooth" : "auto", block: "start"});
        }).catch((error) => { semanticSummary.textContent = error.message; });
      });
    }
    semanticCoverage.replaceChildren(semanticCoverageTitle);
    semanticJson(semanticCoverage, "Bestandskennzahlen", c);
    semanticJson(semanticCoverage, "Historische Telemetrie und bekannte Grenzen", summary.historical_telemetry);
    if (brainwatchMode === "semantic") renderSemanticModeInspector(c);
  }
  async function semanticRead(path) {
    const response = await fetchWithTimeout(`/api/brainwatch/${path}`, {cache: "no-store", headers: auth});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || "Semantisches Lernen konnte nicht gelesen werden"); return data;
  }
  function semanticJson(parent, label, value) {
    const heading = document.createElement("strong"); heading.textContent = label;
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify(value, null, 2); parent.append(heading, pre);
  }
  async function semanticWrite(path, payload) {
    const response = await fetchWithTimeout(`/api/brainwatch/${path}`, {
      method: "POST", headers: {...auth, "Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await readJsonResponse(response, "Dynamische Semantik");
    if (!response.ok) throw new Error(data.error || "Semantik-Korrektur fehlgeschlagen");
    return data;
  }
  function labeledControl(label, control) {
    const wrapper = document.createElement("label"); const text = document.createElement("span");
    text.textContent = label; wrapper.append(text, control); return wrapper;
  }
  function semanticBadge(text, tone = "") {
    const badge = document.createElement("span"); badge.className = `semantic-badge${tone ? ` is-${tone}` : ""}`; badge.textContent = text; return badge;
  }
  function semanticFact(label, value) {
    const fact = document.createElement("div"); const term = document.createElement("dt"); const detail = document.createElement("dd");
    term.textContent = label; detail.textContent = value == null || value === "" ? "Nicht aufgezeichnet" : String(value); fact.append(term, detail); return fact;
  }
  async function loadDynamicSemantics() {
    const data = await semanticRead("semantic-similarity?limit=100");
    semanticDynamic.replaceChildren();
    semanticDynamic.tabIndex = -1;
    const header = document.createElement("header"); header.className = "semantic-section-heading";
    const heading = document.createElement("h3"); heading.textContent = "Aktuelle Zuordnungen prüfen";
    const note = document.createElement("p");
    note.textContent = "EVE hat ähnliche Formulierungen einer bereits bekannten Handlung zugeordnet. Dieser Bereich ist von den noch nicht freigegebenen Lernerfahrungen getrennt.";
    header.append(heading, note); semanticDynamic.append(header);

    const allRecognitions = [...(data.recognitions || [])];
    const pendingCount = allRecognitions.filter((item) => !item.user_decision).length;
    const reviewedCount = allRecognitions.length - pendingCount;
    const reviewControls = document.createElement("div"); reviewControls.className = "semantic-review-controls";
    const reviewFilter = document.createElement("select"); reviewFilter.className = "eve-input"; reviewFilter.setAttribute("aria-label", "Bewertungsstatus der Zuordnungen");
    for (const [value, label] of [
      ["pending", `Nur unbewertete (${pendingCount})`], ["reviewed", `Nur bewertete (${reviewedCount})`],
      ["positive", "Als korrekt bestätigt"], ["negative", "Als falsch markiert"], ["all", `Alle Zuordnungen (${allRecognitions.length})`],
    ]) { const option = document.createElement("option"); option.value = value; option.textContent = label; option.selected = semanticReviewFilter === value; reviewFilter.append(option); }
    reviewFilter.addEventListener("change", () => {
      semanticReviewFilter = reviewFilter.value; window.localStorage.setItem("eve.semanticReviewFilter", semanticReviewFilter);
      loadDynamicSemantics().catch((error) => { semanticSummary.textContent = error.message; });
    });
    const reviewCount = document.createElement("span"); reviewCount.textContent = `${pendingCount} unbewertet · ${reviewedCount} bereits bewertet`;
    reviewControls.append(labeledControl("Welche Zuordnungen anzeigen?", reviewFilter), reviewCount); semanticDynamic.append(reviewControls);

    const recognitions = document.createElement("div"); recognitions.className = "semantic-review-list";
    const visibleRecognitions = allRecognitions.filter((item) => semanticReviewFilter === "all"
      || semanticReviewFilter === "pending" && !item.user_decision
      || semanticReviewFilter === "reviewed" && Boolean(item.user_decision)
      || item.user_decision?.polarity === semanticReviewFilter);
    const orderedRecognitions = visibleRecognitions.sort((left, right) => Number(Boolean(left.user_decision)) - Number(Boolean(right.user_decision)));
    for (const item of orderedRecognitions) {
      const card = document.createElement("article"); card.className = "semantic-review-card";
      if (item.user_decision) card.classList.add("is-reviewed");
      const comparison = document.createElement("div"); comparison.className = "semantic-review-comparison";
      const input = document.createElement("div"); const inputLabel = document.createElement("small"); inputLabel.textContent = "NEUE FORMULIERUNG";
      const inputText = document.createElement("strong"); inputText.textContent = item.user_formulation ? `„${item.user_formulation}“` : "Formulierung nicht aufgezeichnet"; input.append(inputLabel, inputText);
      const arrow = document.createElement("span"); arrow.className = "semantic-review-arrow"; arrow.textContent = "→"; arrow.setAttribute("aria-label", "wurde zugeordnet zu");
      const learned = document.createElement("div"); const learnedLabel = document.createElement("small"); learnedLabel.textContent = "BEKANNTE BEDEUTUNG";
      const learnedText = document.createElement("strong"); learnedText.textContent = item.learned_formulation || "Nicht verfügbar"; learned.append(learnedLabel, learnedText);
      comparison.append(input, arrow, learned); card.append(comparison);
      const meta = document.createElement("p"); meta.className = "semantic-review-meta";
      meta.textContent = `Handlung: ${item.action_representation_id || "nicht aufgezeichnet"} · formaler Worttreffer: ${Number(item.similarity || 0).toFixed(3)} bei Schwelle ${item.threshold ?? "–"}`;
      card.append(meta);
      if (item.user_decision) {
        const verdict = document.createElement("p"); verdict.className = `semantic-review-verdict is-${item.user_decision.polarity}`;
        verdict.textContent = item.user_decision.polarity === "positive"
          ? "✓ Von dir als korrekte Zuordnung bestätigt"
          : "× Von dir als falsche Zuordnung markiert";
        card.append(verdict);
      }
      if (item.user_formulation) {
        const actions = document.createElement("div"); actions.className = "semantic-review-actions";
        for (const [value, label, className] of [["positive", "ZUORDNUNG KORREKT", "is-correct"], ["negative", "ZUORDNUNG FALSCH", "is-wrong"]]) {
          const selected = item.user_decision?.polarity === value;
          const button = document.createElement("button"); button.type = "button"; button.className = `eve-button semantic-write-action ${className}${selected ? " is-selected" : ""}`;
          button.textContent = selected ? (value === "positive" ? "✓ ALS KORREKT BESTÄTIGT" : "× ALS FALSCH MARKIERT")
            : item.user_decision ? `BEWERTUNG ÄNDERN: ${value === "positive" ? "KORREKT" : "FALSCH"}` : label;
          button.disabled = selected;
          button.addEventListener("click", async () => {
            button.disabled = true;
            try {
              await semanticWrite("semantic-similarity/recognitions", {input_formulation: item.user_formulation, learned_claim_id: item.claim_id, polarity: value, basis: "Explizite Brainwatch-Bewertung."});
              await loadDynamicSemantics();
              semanticSummary.textContent = value === "positive" ? "Zuordnung wurde bestätigt." : "Zuordnung wurde als falsch gespeichert.";
            } catch (error) { semanticSummary.textContent = error.message; button.disabled = false; }
          });
          actions.append(button);
        }
        if (item.user_decision?.relation_id) {
          const undo = document.createElement("button"); undo.type = "button"; undo.className = "eve-button eve-button--ghost semantic-undo-action"; undo.textContent = "BEWERTUNG AUFHEBEN";
          undo.addEventListener("click", async () => {
            undo.disabled = true;
            try {
              await semanticWrite(`semantic-similarity/relations/${encodeURIComponent(item.user_decision.relation_id)}/undo`, {confirmed: true});
              await loadDynamicSemantics(); semanticSummary.textContent = "Bewertung wurde aufgehoben.";
            } catch (error) { semanticSummary.textContent = error.message; undo.disabled = false; }
          });
          actions.append(undo);
        }
        card.append(actions);
      }
      const details = document.createElement("details"); details.className = "semantic-technical-details";
      const detailsTitle = document.createElement("summary"); detailsTitle.textContent = "Warum wurde das zugeordnet?"; details.append(detailsTitle);
      semanticJson(details, "Verglichene Wortbestandteile", item.pairs || []);
      semanticJson(details, "Berücksichtigte gelernte Beziehungen", item.relevant_relations || []);
      semanticJson(details, "Herkunft", {source_ref: item.source_ref, source_turn_id: item.source_turn_id, source_message_id: item.source_message_id, result_status: item.result_status});
      card.append(details); recognitions.append(card);
    }
    if (!recognitions.childElementCount) {
      const empty = document.createElement("p"); empty.className = "semantic-empty-state";
      empty.textContent = semanticReviewFilter === "pending"
        ? "Aktuell wartet keine dynamische Zuordnung auf deine Prüfung. Bereits bewertete Treffer kannst du über den Filter einblenden."
        : "Für diesen Bewertungsfilter sind keine Zuordnungen vorhanden.";
      recognitions.append(empty);
    }
    semanticDynamic.append(recognitions);

    const correction = document.createElement("details"); correction.className = "semantic-task-details";
    const correctionTitle = document.createElement("summary"); correctionTitle.textContent = "Bedeutung manuell korrigieren";
    const correctionNote = document.createElement("p"); correctionNote.textContent = "Nutze dies, wenn EVE zwei Begriffe oder Formulierungen dauerhaft gleich oder verschieden behandeln soll. Diese Korrektur wird in EVEs Memory gespeichert.";
    const correctionForm = document.createElement("form"); correctionForm.className = "semantic-dynamic-controls semantic-correction-form";
    const left = document.createElement("input"); left.className = "eve-input"; left.required = true; left.placeholder = "z. B. Elena";
    const right = document.createElement("input"); right.className = "eve-input"; right.required = true; right.placeholder = "z. B. Sam";
    const polarity = document.createElement("select"); polarity.className = "eve-input";
    for (const [value, label] of [["negative", "bedeuten etwas Verschiedenes"], ["positive", "bedeuten dasselbe"]]) { const option = document.createElement("option"); option.value = value; option.textContent = label; polarity.append(option); }
    const representation = document.createElement("input"); representation.className = "eve-input"; representation.placeholder = "Handlungs-ID (nur falls bekannt)";
    const apply = document.createElement("button"); apply.className = "eve-button semantic-write-action"; apply.textContent = "BEZIEHUNG KORRIGIEREN";
    correctionForm.append(labeledControl("Erster Begriff oder Satz", left), labeledControl("Zweiter Begriff oder Satz", right), labeledControl("Gewünschte Beziehung", polarity), labeledControl("Optionale technische Bindung", representation), apply);
    correctionForm.addEventListener("submit", async event => {
      event.preventDefault(); apply.disabled = true;
      try {
        await semanticWrite("semantic-similarity/relations", {left: left.value, right: right.value,
          polarity: polarity.value, representation_id: representation.value, basis: "Explizite Brainwatch-Korrektur."});
        correctionForm.reset();
        await loadDynamicSemantics(); semanticSummary.textContent = "Die Bedeutungsregel wurde in EVEs Memory gespeichert.";
      } catch (error) { semanticSummary.textContent = error.message; apply.disabled = false; }
    });
    correction.append(correctionTitle, correctionNote, correctionForm); semanticDynamic.append(correction);

    const relations = document.createElement("details"); relations.className = "semantic-task-details";
    const relationTitle = document.createElement("summary"); relationTitle.textContent = `Gespeicherte Korrekturen (${(data.relations || []).length} geladen)`; relations.append(relationTitle);
    for (const item of data.relations || []) {
      const row = document.createElement("div"); row.className = "semantic-dynamic-row";
      const text = document.createElement("span");
      const relationLabel = item.polarity === "positive" ? "gleichbedeutend" : item.polarity === "negative" ? "verschieden" : item.polarity;
      text.textContent = `${item.display_text || item.input_formulation || item.id} · ${relationLabel} · ${semanticStateLabels[item.lifecycle] || item.lifecycle}`; row.append(text);
      if (item.lifecycle === "active") {
        const undo = document.createElement("button"); undo.type = "button"; undo.className = "eve-button eve-button--ghost semantic-write-action"; undo.textContent = "KORREKTUR AUFHEBEN";
        undo.addEventListener("click", async () => { undo.disabled = true; try { await semanticWrite(`semantic-similarity/relations/${encodeURIComponent(item.id)}/undo`, {confirmed: true}); await loadDynamicSemantics(); semanticSummary.textContent = "Korrektur wurde aufgehoben."; } catch (error) { semanticSummary.textContent = error.message; undo.disabled = false; } }); row.append(undo);
      }
      const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "Herkunft anzeigen"; details.append(summary); semanticJson(details, "Evidenz", item.evidence || []); row.append(details); relations.append(row);
    }
    if (!(data.relations || []).length) { const empty = document.createElement("p"); empty.className = "semantic-empty-state"; empty.textContent = "Noch keine manuellen Bedeutungsregeln gespeichert."; relations.append(empty); }
    semanticDynamic.append(relations);

    const settings = document.createElement("details"); settings.className = "semantic-task-details semantic-settings";
    const settingsTitle = document.createElement("summary"); settingsTitle.textContent = "Erweiterte Erkennungseinstellungen";
    const settingsNote = document.createElement("p"); settingsNote.textContent = "Diese Werte steuern den formalen Vergleich bereits gelernter Formulierungen. Die Schwelle ist keine semantische Wahrscheinlichkeit.";
    const config = document.createElement("form"); config.className = "semantic-dynamic-controls";
    const enabled = document.createElement("input"); enabled.type = "checkbox"; enabled.checked = Boolean(data.settings.enabled);
    const mode = document.createElement("select"); mode.className = "eve-input";
    for (const [value, label] of [["active", "Aktiv verwenden"], ["shadow", "Nur beobachten"]]) { const option = document.createElement("option"); option.value = value; option.textContent = label; option.selected = data.settings.mode === value; mode.append(option); }
    const threshold = document.createElement("input"); threshold.className = "eve-input"; threshold.type = "number"; threshold.min = "0.5"; threshold.max = "1"; threshold.step = "0.01"; threshold.value = data.settings.threshold;
    const save = document.createElement("button"); save.className = "eve-button semantic-write-action"; save.textContent = "EINSTELLUNG SPEICHERN";
    const state = document.createElement("span"); state.className = "semantic-config-version"; state.textContent = `Version ${data.settings.version} · ${data.settings.policy}`;
    config.append(labeledControl("Erkennung eingeschaltet", enabled), labeledControl("Betriebsart", mode), labeledControl("Formale Trefferschwelle", threshold), save, state);
    config.addEventListener("submit", async event => {
      event.preventDefault(); save.disabled = true;
      try {
        const response = await fetchWithTimeout("/api/config", {method: "PATCH", headers: {...auth, "Content-Type": "application/json"}, body: JSON.stringify({values: {
          "semantic_similarity.enabled": enabled.checked,
          "semantic_similarity.mode": mode.value,
          "semantic_similarity.threshold": Number(threshold.value),
        }})});
        const result = await readJsonResponse(response, "Konfiguration"); if (!response.ok) throw new Error(result.error || "Speichern fehlgeschlagen");
        await loadDynamicSemantics(); semanticSummary.textContent = "Erkennungseinstellungen wurden aktualisiert.";
      } catch (error) { state.textContent = error.message; save.disabled = false; }
    });
    settings.append(settingsTitle, settingsNote, config); semanticDynamic.append(settings);
  }
  async function loadDifferentialComposition() {
    const data = await semanticRead("semantic-composition?limit=30");
    semanticComposition.replaceChildren();
    const heading = document.createElement("h3"); heading.textContent = "Technische Lernlogik";
    const status = document.createElement("p");
    status.textContent = `Erweiterte Diagnose der kompositionellen Lernregeln · Modus ${data.settings.mode} · Version ${data.settings.version} · ${data.counts.released || 0} freigegeben · ${data.counts.candidate || 0} Kandidaten · ${(data.counts.blocked || 0) + (data.counts.truncated || 0)} blockiert`;
    semanticComposition.append(heading, status);
    const hypotheses = document.createElement("details");
    const hypothesisTitle = document.createElement("summary"); hypothesisTitle.textContent = "Hypothesen, Kontraste, Provenienz und Abhängigkeiten";
    hypotheses.append(hypothesisTitle); semanticJson(hypotheses, "Versionierte Relationen", data.hypotheses || []);
    const evaluations = document.createElement("details");
    const evaluationTitle = document.createElement("summary"); evaluationTitle.textContent = "Letzte kompositionelle Auswertungen";
    evaluations.append(evaluationTitle); semanticJson(evaluations, "Candidates, Fallbacks und fehlende Evidenz", data.evaluations || []);
    const language = document.createElement("details");
    const languageTitle = document.createElement("summary"); languageTitle.textContent = "Explizit gelernte Sprachbeziehungen";
    language.append(languageTitle);
    semanticJson(language, "Allgemeine Äquivalenzen, Ressourcenaliase, Kontext, Evidenz, Versionen und Korrekturen", data.language_relations || []);
    semanticComposition.append(language, hypotheses, evaluations);
  }
  async function loadSemanticLearning(append = false) {
    const params = new URLSearchParams({q: semanticSearch.value, status: semanticFilter.value,
      action_link_status: semanticLinkFilter.value, limit: "20", cursor: String(append ? semanticCursor || 0 : 0)});
    const [summary, page] = await Promise.all([semanticRead("semantic-summary"), semanticRead(`semantic-links?${params}`)]);
    if (!append) await Promise.all([loadSemanticActions(), loadDynamicSemantics(), loadDifferentialComposition()]);
    const c = summary.stock;
    if (!append) renderSemanticMetrics(summary);
    semanticSummary.textContent = `${page.items.length} Erfahrung(en) geladen · ${c.action_representations || 0} gemeinsame Handlungen · ${c.link_conflicts || 0} Konflikte.`;
    if (!append) {
      semanticRows.replaceChildren();
      const trends = document.createElement("details"); trends.className = "semantic-technical-details"; const title = document.createElement("summary"); title.textContent = "Tageswerte der Lernereignisse";
      trends.append(title);
      const table = document.createElement("table");
      const eventLabels = {llm_interpretation: "Neue Erfahrungen", automatic_release: "Automatische Freigaben", reuse_result: "Wiederverwendungsversuche (einschließlich Fehler)", user_correction: "Widerspruchsevidenzen"};
      const head = document.createElement("tr"); for (const label of ["Datum (UTC)", "Gemessenes Ereignis", "Anzahl"]) { const cell = document.createElement("th"); cell.textContent = label; head.append(cell); } table.append(head);
      for (const item of summary.daily_evidence) { const row = document.createElement("tr"); for (const value of [item.day, eventLabels[item.evidence_type] || item.evidence_type, item.count]) { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); } table.append(row); }
      trends.append(table); semanticCoverage.append(trends);
    }
    for (const item of page.items) {
      const row = document.createElement("details"); row.className = "semantic-experience-card"; const title = document.createElement("summary");
      const utterance = document.createElement("strong"); utterance.className = "semantic-experience-utterance"; utterance.textContent = `„${item.utterance}“`;
      const badges = document.createElement("span"); badges.className = "semantic-experience-badges";
      badges.append(semanticBadge(semanticStateLabels[item.lifecycle] || item.lifecycle || "Unbekannt", item.lifecycle), semanticBadge(semanticConfirmationLabels[item.confirmation] || item.confirmation || "Nicht bestätigt"));
      title.append(utterance, badges);
      const info = document.createElement("dl"); info.className = "semantic-experience-facts";
      const targets = (item.plan?.actions || []).map(action => action.entity_id).filter(Boolean).join(", ");
      info.append(
        semanticFact("Provider", item.provider?.provider || "Unbekannt"),
        semanticFact("Ziel", targets || "Kein konkretes Ziel gespeichert"),
        semanticFact("Erwartete Wirkung", item.plan?.effect || "Nicht aufgezeichnet"),
        semanticFact("Wiederverwendungen", item.uses || 0),
        semanticFact("Fehler", item.failures || 0),
        semanticFact("Letzter Erfolg", item.last_success || "Noch keiner"),
      );
      if (item.invalidation_reason || item.technical_status) {
        const notice = document.createElement("p"); notice.className = "semantic-experience-notice"; notice.textContent = item.invalidation_reason || item.technical_status; info.append(notice);
      }
      const body = document.createElement("div"); let loaded = false;
      row.append(title, info, body);
      row.addEventListener("toggle", async () => {
        if (!row.open || loaded) return;
        try {
          const data = await semanticRead(`semantic-links/${encodeURIComponent(item.id)}`); loaded = true;
          semanticJson(body, "Claim, Provider, Ressourcen, Aktion, Kontext, Interpretation und Policy", data.item);
          semanticJson(body, "Letzter Fehler / Invalidierung", item.last_failure || item.invalidation_reason || "Kein Fehler erfasst");
          const versions = document.createElement("div"); body.append(versions);
          semanticJson(versions, "Versionsbeziehungen", data.relations);
          const versionMore = document.createElement("button"); versionMore.type = "button"; versionMore.className = "eve-button"; versionMore.textContent = "WEITERE VERSIONSBEZIEHUNGEN";
          let versionCursor = data.next_relation_cursor; versionMore.hidden = versionCursor == null;
          versionMore.addEventListener("click", async () => { try { const page = await semanticRead(`semantic-links/${encodeURIComponent(item.id)}?relation_cursor=${versionCursor}&limit=1`); semanticJson(versions, "Versionsbeziehungen", page.relations); versionCursor = page.next_relation_cursor; versionMore.hidden = versionCursor == null; } catch (error) { semanticSummary.textContent = error.message; } }); body.append(versionMore);
          const evidence = document.createElement("div"); body.append(evidence);
          const addEvidence = page => semanticJson(evidence, "Technische / semantische Evidenzen und Nutzerentscheidungen", page.evidence);
          addEvidence(data);
          const more = document.createElement("button"); more.type = "button"; more.className = "eve-button"; more.textContent = "WEITERE EVIDENZEN"; let cursor = data.next_cursor; more.hidden = cursor == null;
          more.addEventListener("click", async () => { try { const page = await semanticRead(`semantic-links/${encodeURIComponent(item.id)}?cursor=${cursor}`); addEvidence(page); cursor = page.next_cursor; more.hidden = cursor == null; } catch (error) { semanticSummary.textContent = error.message; } }); body.append(more);
          const reject = document.createElement("button"); reject.type = "button"; reject.className = "eve-button semantic-write-action"; reject.textContent = "ERFAHRUNG ABLEHNEN"; reject.disabled = item.lifecycle === "invalid";
          reject.addEventListener("click", async () => {
            if (!window.confirm(`Claim ${item.id} ablehnen? ${data.rejection_policy} Es werden keine Geräteaktionen ausgeführt.`)) return;
            reject.disabled = true;
            try {
              const response = await fetchWithTimeout(`/api/brainwatch/semantic-links/${encodeURIComponent(item.id)}/reject`, {method: "POST", headers: {...auth, "Content-Type": "application/json"}, body: JSON.stringify({claim_id: item.id, confirmed: true})});
              const result = await response.json(); if (!response.ok) throw new Error(result.error); await loadSemanticLearning();
            } catch (error) { reject.disabled = false; semanticSummary.textContent = error.message; }
          }); body.append(reject);
        } catch (error) { semanticSummary.textContent = error.message; }
      }); semanticRows.append(row);
    }
    if (!append && !page.items.length) {
      const empty = document.createElement("p"); empty.className = "semantic-empty-state";
      empty.textContent = semanticSearch.value || semanticFilter.value
        ? "Für diese Suche wurden keine Lernerfahrungen gefunden."
        : "EVE hat noch keine einzelnen semantischen Lernerfahrungen gespeichert.";
      semanticRows.append(empty);
    }
    semanticCursor = page.next_cursor; semanticMore.hidden = semanticCursor == null;
  }
  semanticForm.addEventListener("submit", async event => {
    event.preventDefault();
    semanticSubmit.disabled = true;
    semanticSummary.textContent = "Gelernte Formulierungen werden durchsucht …";
    try {
      await loadSemanticLearning();
      semanticSummary.textContent += " Die Treffer werden im Hauptbereich angezeigt.";
      semanticExperienceHeading.scrollIntoView({behavior: presentationMotion ? "smooth" : "auto", block: "start"});
      semanticExperienceHeading.focus({preventScroll: true});
    } catch (error) {
      semanticSummary.textContent = error.message;
    } finally {
      semanticSubmit.disabled = false;
    }
  });
  semanticMore.addEventListener("click", () => loadSemanticLearning(true).catch(error => {semanticSummary.textContent = error.message;}));

  async function loadSemanticActions(append = false) {
    const page = await semanticRead(`semantic-actions?limit=20&cursor=${append ? semanticActionCursor || 0 : 0}`);
    if (!append) {
      semanticActions.replaceChildren();
      semanticActions.tabIndex = -1;
      const header = document.createElement("header"); header.className = "semantic-section-heading";
      const heading = document.createElement("h3"); heading.textContent = "Was EVE bereits als gleiche Handlung versteht";
      const note = document.createElement("p"); note.textContent = "Eine Gruppe bündelt verschiedene Formulierungen mit derselben technischen Bedeutung. Öffne sie, um die zugehörigen Sätze und Bedingungen zu sehen. Die Gruppenzugehörigkeit allein gibt noch keine Ausführung frei.";
      header.append(heading, note); semanticActions.append(header);
    }
    semanticActions.querySelector(".semantic-actions-more")?.remove();
    for (const group of page.items) {
      const row = document.createElement("details"); row.className = "semantic-action-card"; const title = document.createElement("summary");
      const meaning = document.createElement("strong"); meaning.textContent = group.representation.meaning || group.id;
      const badges = document.createElement("span"); badges.className = "semantic-experience-badges";
      badges.append(semanticBadge(`${group.formulations} Formulierungen`), semanticBadge(`${group.directly_usable} direkt nutzbar`, "active"));
      if (group.invalid_memberships) badges.append(semanticBadge(`${group.invalid_memberships} zurückgewiesen`, "invalid"));
      title.append(meaning, badges);
      const body = document.createElement("div"); row.append(title, body); let loaded = false;
      row.addEventListener("toggle", async () => {
        if (!row.open || loaded) return;
        try {
          const data = await semanticRead(`semantic-actions/${encodeURIComponent(group.id)}`); loaded = true;
          const hint = document.createElement("p"); hint.textContent = data.replay_policy; body.append(hint);
          semanticJson(body, "Handlung, technische Bindung und verbindliche Bedingungen", data.item);
          const members = document.createElement("div"); body.append(members);
          const addMembers = list => {
            for (const member of list) {
              const detail = document.createElement("details"); const label = document.createElement("summary");
              label.textContent = `${member.utterance} · ${semanticStateLabels[member.lifecycle]} · Verknüpfung: ${member.action_link_status} · ${semanticConfirmationLabels[member.confirmation] || member.confirmation} · ${member.uses || 0} Wiederverwendungen`;
              detail.append(label); let opened = false;
              detail.addEventListener("toggle", async () => {
                if (!detail.open || opened) return;
                try {
                  const experience = await semanticRead(`semantic-links/${encodeURIComponent(member.id)}`); opened = true;
                  semanticJson(detail, "Konkrete Erfahrung und Kontextbedingungen", experience.item);
                  semanticJson(detail, "Versionsbeziehungen", experience.relations);
                  const evidence = document.createElement("div"); detail.append(evidence);
                  semanticJson(evidence, "Semantische / technische Evidenzen", experience.evidence);
                  const more = document.createElement("button"); more.type = "button"; more.className = "eve-button"; more.textContent = "WEITERE EVIDENZEN";
                  let cursor = experience.next_cursor; more.hidden = cursor == null;
                  more.addEventListener("click", async () => { try { const page = await semanticRead(`semantic-links/${encodeURIComponent(member.id)}?cursor=${cursor}`); semanticJson(evidence, "Weitere Evidenzen", page.evidence); cursor = page.next_cursor; more.hidden = cursor == null; } catch (error) { semanticSummary.textContent = error.message; } }); detail.append(more);
                } catch (error) { semanticSummary.textContent = error.message; }
              }); members.append(detail);
            }
          };
          addMembers(data.members);
          const memberMore = document.createElement("button"); memberMore.type = "button"; memberMore.className = "eve-button"; memberMore.textContent = "WEITERE FORMULIERUNGEN";
          let memberCursor = data.next_cursor; memberMore.hidden = memberCursor == null;
          memberMore.addEventListener("click", async () => { try { const page = await semanticRead(`semantic-actions/${encodeURIComponent(group.id)}?cursor=${memberCursor}`); addMembers(page.members); memberCursor = page.next_cursor; memberMore.hidden = memberCursor == null; } catch (error) { semanticSummary.textContent = error.message; } }); body.append(memberMore);
          const evidence = document.createElement("div"); body.append(evidence); semanticJson(evidence, "Verknüpfungsevidenz, Konflikte und Invalidierungen", data.evidence);
          const evidenceMore = document.createElement("button"); evidenceMore.type = "button"; evidenceMore.className = "eve-button"; evidenceMore.textContent = "WEITERE VERKNÜPFUNGSEVIDENZEN";
          let evidenceCursor = data.next_evidence_cursor; evidenceMore.hidden = evidenceCursor == null;
          evidenceMore.addEventListener("click", async () => { try { const page = await semanticRead(`semantic-actions/${encodeURIComponent(group.id)}?evidence_cursor=${evidenceCursor}`); semanticJson(evidence, "Weitere Verknüpfungsevidenzen", page.evidence); evidenceCursor = page.next_evidence_cursor; evidenceMore.hidden = evidenceCursor == null; } catch (error) { semanticSummary.textContent = error.message; } }); body.append(evidenceMore);
        } catch (error) { semanticSummary.textContent = error.message; }
      }); semanticActions.append(row);
    }
    semanticActionCursor = page.next_cursor;
    if (!append && !(page.items || []).length) { const empty = document.createElement("p"); empty.className = "semantic-empty-state"; empty.textContent = "Noch keine gemeinsamen Handlungsgruppen gespeichert."; semanticActions.append(empty); }
    if (semanticActionCursor != null) { const more = document.createElement("button"); more.type = "button"; more.className = "eve-button semantic-actions-more"; more.textContent = "WEITERE GEMEINSAME HANDLUNGEN"; more.addEventListener("click", () => loadSemanticActions(true).catch(error => {semanticSummary.textContent = error.message;})); semanticActions.append(more); }
  }

  function renderSemanticLearning(turn, openDetails) {
    const value = turn.semantic_learning;
    if (!value) return null;
    const panel = document.createElement("details"); panel.className = "nerd-section"; panel.dataset.nerdKey = `${turn.id}:semantic-learning`; panel.open = openDetails.has(panel.dataset.nerdKey);
    const title = document.createElement("summary"); title.textContent = `Semantisches Lernen · ${value.route} · ${value.learning.join(" / ")}`; panel.append(title);
    for (const [key, label] of Object.entries({formulation: "Konkrete Formulierung", action_representation_id: "Gemeinsame Handlung", evidence_kind: "Evidenzart", membership_status: "Verknüpfungsstatus", invalidations: "Invalidierungen / Korrekturen"})) appendNerdField(panel, label, value[key]);
    for (const [key, label] of Object.entries({semantic_reuse: "Wiederverwendungsart", threshold: "Angewendete Schwelle", similarity: "Formaler Ähnlichkeitswert", config_version: "Konfigurationsversion", checked_count: "Geprüfte Lernkandidaten", candidate_count: "Passende Kandidaten", negative_relation_present: "Negative Relation vorhanden", ambiguity_conflict: "Mehrdeutigkeitskonflikt", direct_execution: "Direkte Ausführung"})) appendNerdField(panel, label, value[key]);
    if (value.composition) semanticJson(panel, "Differenzielle Komposition · Evidenz, Konflikte, Modellkosten und Freigabe", value.composition);
    appendNerdField(panel, "Gemessene umgangene Planner-Einstiege", value.planner_entrypoints_avoided ?? "Nicht nachgewiesen");
    if (value.linking) appendNerdField(panel, "Verknüpfungen · neu / zugeordnet / unzureichend / Konflikte", `${value.linking.created} / ${value.linking.linked} / ${value.linking.insufficient} / ${value.linking.conflicts}`);
    appendNerdField(panel, "Lookup-Treffer / tatsächlich plannerfrei", `${value.lookup_hit ? "ja" : "nein"} / ${value.planner_free_execution ? "ja" : "nein"}`);
    for (const [key, label] of Object.entries({planner_calls: "Alle Planner-Aufrufe", execution_planner_calls: "Turn- und Home-Assistant-Planner", llm_calls: "Alle LLM-Aufrufe", prompt_tokens: "Prompt-Tokens", completion_tokens: "Completion-Tokens", duration_ms: "Turn-Laufzeit (ms)"})) appendNerdField(panel, label, value[key] ?? "Nicht gemessen");
    appendNerdField(panel, "Dialogverarbeitung", (value.dialog_statuses || []).join(" / "));
    semanticJson(panel, "Dialogentscheidung, Feedback-Referenz und verworfene Entscheidungen", value.dialog_decisions || []);
    semanticJson(panel, "Claim-ID, Kontext, Freigabe, Providerprüfung und Ergebnis", value.events);
    semanticJson(panel, "Gemessene LLM-Aufrufe und Latenzen", value.measured_calls); return panel;
  }

  const metric = (value, suffix = "") => value === null || value === undefined ? "–" : `${value}${suffix}`;

  function appendNerdField(parent, label, value) {
    if (value === null || value === undefined || value === "") return null;
    const row = document.createElement("div");
    row.className = "nerd-field";
    const key = document.createElement("span");
    key.textContent = label;
    const content = document.createElement("strong");
    content.textContent = metric(value);
    row.append(key, content);
    parent.append(row);
    return row;
  }

  const nerdModuleLabels = {
    planner: "Historischer Planner", native_tool: "Qwen Toolwahl", minimal: "Technische Entscheidung", home_assistant: "Home Assistant", web: "Web", vision: "Vision",
    memory: "Memory", retrieval: "Retrieval", knowledge_flow: "Knowledge Flow",
    presentation: "Presentation", stt: "STT", tts: "TTS", llm: "Modelle",
  };

  function nerdLabel(value) {
    const key = String(value || "system").toLowerCase();
    return nerdModuleLabels[key] || String(value || "System").replaceAll("_", " ");
  }

  function measuredTimeline(turn) {
    const measured = [];
    for (const step of turn.steps || []) {
      const start = Number(step.start_ms);
      const end = Number(step.end_ms);
      const duration = Number(step.duration_ms ?? (end - start));
      if (![start, end, duration].every(Number.isFinite) || duration < 0) continue;
      measured.push({
        label: `${nerdLabel(step.component)} › ${step.operation}`,
        status: step.status || "neutral", start, end, duration, component: step.component,
      });
    }
    for (const call of turn.llm_calls || []) {
      const start = Number(call.start_ms);
      const end = Number(call.end_ms);
      const duration = Number(call.duration_ms ?? (end - start));
      if (![start, end, duration].every(Number.isFinite) || duration < 0) continue;
      measured.push({
        label: `${typeof call.role === "string" && call.role.trim() ? call.role.trim() : "LLM-Aufruf"} › ${call.model || "Modell"}`,
        status: call.status || "neutral", start, end, duration, component: "llm",
      });
    }
    return measured.sort((a, b) => a.start - b.start || b.duration - a.duration);
  }

  function renderTurnTimeline(turn) {
    const section = document.createElement("section");
    section.className = "nerd-section nerd-runtime";
    const heading = document.createElement("div");
    heading.className = "nerd-section-head";
    const title = document.createElement("h2");
    title.textContent = "Turn Timeline";
    const hint = document.createElement("span");
    hint.textContent = "Position und Breite entsprechen der gemessenen Laufzeit";
    heading.append(title, hint);
    section.append(heading);
    const items = measuredTimeline(turn);
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "nerd-empty";
      empty.textContent = "Noch keine abgeschlossenen Zeitmessungen.";
      section.append(empty);
      return section;
    }
    const extent = Math.max(Number(turn.duration_ms) || 0, ...items.map((item) => item.end), 1);
    const longest = Math.max(...items.map((item) => item.duration), 1);
    const timeline = document.createElement("div");
    timeline.className = "nerd-timeline";
    for (const item of items) {
      const row = document.createElement("div");
      row.className = `nerd-timeline-row ${item.status}`;
      const label = document.createElement("div");
      label.className = "nerd-timeline-label";
      const name = document.createElement("strong");
      name.textContent = item.label;
      const duration = document.createElement("span");
      duration.textContent = `${Math.round(item.duration)} ms`;
      label.append(name, duration);
      const track = document.createElement("div");
      track.className = "nerd-timeline-track";
      const bar = document.createElement("span");
      bar.className = `nerd-timeline-bar${item.duration >= longest * .72 ? " hotspot" : ""}`;
      bar.style.left = `${Math.max(0, Math.min(100, item.start / extent * 100))}%`;
      bar.style.width = `${Math.max(.45, Math.min(100, item.duration / extent * 100))}%`;
      track.append(bar);
      row.append(label, track);
      timeline.append(row);
    }
    section.append(timeline);
    return section;
  }

  function renderSystemModules(turn, openDetails) {
    const groups = new Map();
    for (const step of turn.steps || []) {
      const key = String(step.component || "system").toLowerCase();
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(step);
    }
    if ((turn.llm_calls || []).length) groups.set("llm", turn.llm_calls);
    if (turn.knowledge_flow?.stages?.length) groups.set("knowledge_flow", turn.knowledge_flow.stages);
    if (!groups.size) return null;
    const section = document.createElement("section");
    section.className = "nerd-section nerd-modules-wrap";
    const heading = document.createElement("div");
    heading.className = "nerd-section-head";
    const title = document.createElement("h2");
    title.textContent = "System Modules";
    heading.append(title);
    const modules = document.createElement("div");
    modules.className = "nerd-modules";
    for (const [key, entries] of groups) {
      const module = document.createElement("details");
      module.className = "nerd-module";
      module.dataset.nerdKey = `${turn.id}:module:${key}`;
      module.open = openDetails.has(module.dataset.nerdKey);
      const summary = document.createElement("summary");
      const name = document.createElement("strong");
      name.textContent = nerdLabel(key);
      const meta = document.createElement("span");
      const durations = entries.map((entry) => Number(entry.duration_ms)).filter(Number.isFinite);
      meta.textContent = durations.length ? `${entries.length} · max ${Math.round(Math.max(...durations))} ms` : `${entries.length} aktiv`;
      summary.append(name, meta);
      const grid = document.createElement("div");
      grid.className = "nerd-module-detail";
      for (const entry of entries) {
        const row = document.createElement("div");
        const operation = document.createElement("strong");
        operation.textContent = entry.operation || entry.role || entry.label || entry.kind || "Messung";
        const value = document.createElement("span");
        value.textContent = [entry.model, entry.status, entry.duration_ms == null ? null : `${Math.round(entry.duration_ms)} ms`].filter(Boolean).join(" · ");
        row.append(operation, value);
        grid.append(row);
      }
      module.append(summary, grid);
      modules.append(module);
    }
    section.append(heading, modules);
    return section;
  }

  function renderKnowledgeFlow(turn, openDetails) {
    const stages = turn.knowledge_flow?.stages;
    if (!Array.isArray(stages) || !stages.length) return null;
    const wrapper = document.createElement("section");
    wrapper.className = "knowledge-flow-wrap";
    wrapper.setAttribute("aria-label", "Wissensfluss");
    const flow = document.createElement("div");
    flow.className = "knowledge-flow";
    const symbols = { user: "●", vision: "◉", web: "◎", tools: "◇", eve: "✦", answer: "✓" };
    for (const [index, stage] of stages.entries()) {
      if (index) {
        const arrow = document.createElement("span");
        arrow.className = "knowledge-arrow";
        arrow.textContent = "→";
        arrow.setAttribute("aria-hidden", "true");
        flow.append(arrow);
      }
      const node = document.createElement("div");
      node.className = `knowledge-node ${stage.status || "neutral"}`;
      const heading = document.createElement("strong");
      heading.textContent = `${symbols[stage.kind] || "◇"} ${stage.label || stage.kind || "Station"}`;
      const summary = document.createElement("span");
      summary.textContent = stage.summary || "beteiligt";
      node.append(heading, summary);
      flow.append(node);
    }
    wrapper.append(flow);

    const detail = document.createElement("details");
    detail.className = "knowledge-flow-details";
    detail.dataset.nerdKey = `${turn.id}:knowledge-flow`;
    detail.open = openDetails.has(detail.dataset.nerdKey);
    const detailSummary = document.createElement("summary");
    detailSummary.textContent = "Wissensfluss-Details";
    const grid = document.createElement("div");
    grid.className = "nerd-grid";
    for (const stage of stages) {
      for (const [key, value] of Object.entries(stage.details || {})) {
        const rendered = Array.isArray(value) ? value.join(", ") : value;
        if (rendered === "" || rendered === null || rendered === undefined) continue;
        appendNerdField(grid, `${stage.label || stage.kind} · ${key}`, rendered);
      }
    }
    detail.append(detailSummary, grid);
    if (grid.childElementCount) wrapper.append(detail);
    return wrapper;
  }

  function tokenRatePresentation(call) {
    if (call?.tokens_per_second_basis === "whole_request_fallback") {
      return {
        hudLabel: "Output / Request",
        detailLabel: "Outputrate (Gesamtrequest)",
        description: "Completion-Tokens geteilt durch die vollständige Requestdauer einschließlich Prompt-Verarbeitung.",
      };
    }
    if (call?.tokens_per_second_basis === "visible_generation_fallback") {
      return {
        hudLabel: "Sichtbare Ausgabe",
        detailLabel: "Outputrate (sichtbare Ausgabe)",
        description: "Completion-Tokens geteilt durch die Zeit vom ersten sichtbaren Token bis zum Streamende.",
      };
    }
    if (call?.tokens_per_second_basis === "server_reported") {
      return {
        hudLabel: "Provider-Rate",
        detailLabel: "Provider-gemeldete Rate",
        description: "Vom Modellprovider gemeldete Tok/s; die genaue Messbasis bestimmt der Provider.",
      };
    }
    return {
      hudLabel: "Outputrate",
      detailLabel: "Outputrate",
      description: "Messbasis in dieser älteren Telemetrie nicht gespeichert.",
    };
  }

  function renderNerdTurns(data) {
    const openDetails = new Set(
      [...elements.nerdTurns.querySelectorAll("details[open][data-nerd-key]")]
        .map((item) => item.dataset.nerdKey)
    );
    const rawScrollPositions = new Map(
      [...elements.nerdTurns.querySelectorAll("details[data-nerd-key] > pre")]
        .map((pre) => {
          const key = pre.parentElement?.dataset.nerdKey;
          const distanceFromBottom = pre.scrollHeight - pre.clientHeight - pre.scrollTop;
          return [key, {
            top: pre.scrollTop,
            left: pre.scrollLeft,
            pinnedToBottom: distanceFromBottom <= 2,
          }];
        })
        .filter(([key]) => key)
    );
    const previousScrollTop = elements.nerdTurns.scrollTop;
    elements.nerdTurns.replaceChildren();
    for (const turn of data.turns || []) {
      const card = document.createElement("article");
      card.className = "nerd-turn";
      const head = document.createElement("header");
      head.className = "nerd-turn-head";
      const identity = document.createElement("div");
      identity.className = "nerd-turn-identity";
      const eyebrow = document.createElement("span");
      eyebrow.textContent = "TURN HUD";
      const title = document.createElement("strong");
      title.textContent = turn.summary?.backend_turn_id || turn.id || "Aktueller Turn";
      const rateCall = turn.llm_calls?.find((call) => call.tokens_per_second != null);
      const rate = rateCall?.tokens_per_second;
      const ratePresentation = tokenRatePresentation(rateCall);
      const status = document.createElement("span");
      const finalTurnState = turn.summary?.final_turn_state;
      const displayedStatus = finalTurnState || turn.status;
      const statusTone = finalTurnState === "operational_resolved"
        ? "success"
        : finalTurnState === "operational_unresolved"
          ? "warning"
          : ["planning_failed", "execution_failed"].includes(finalTurnState)
            ? "error"
            : turn.status;
      status.className = `nerd-status ${statusTone}`;
      status.textContent = displayedStatus;
      identity.append(eyebrow, title);
      head.append(identity, status);
      const hud = document.createElement("div");
      hud.className = "nerd-hud";
      const addHudMetric = (label, value, unit = "", emphasis = false, description = "") => {
        if (value === null || value === undefined || value === "") return;
        const item = document.createElement("div");
        item.className = `nerd-hud-metric${emphasis ? " primary" : ""}`;
        if (description) item.title = description;
        const metricValue = document.createElement("strong");
        metricValue.textContent = `${value}${unit}`;
        const metricLabel = document.createElement("span");
        metricLabel.textContent = label;
        item.append(metricValue, metricLabel);
        hud.append(item);
      };
      addHudMetric("Gesamtdauer", turn.duration_ms == null ? null : (turn.duration_ms / 1000).toFixed(2), " s", true);
      addHudMetric("Hauptpfad", turn.route);
      addHudMetric("Confidence", turn.confidence);
      addHudMetric("Modell", turn.model);
      const promptTokens = turn.summary?.usage?.prompt_tokens;
      const outputTokens = turn.summary?.usage?.completion_tokens;
      addHudMetric("Prompt → Output", promptTokens == null && outputTokens == null ? null : `${promptTokens ?? "?"} → ${outputTokens ?? "?"}`);
      addHudMetric(ratePresentation.hudLabel, rate, " tok/s", false, ratePresentation.description);
      card.append(head, hud, renderTurnTimeline(turn));
      const semantics = renderSemanticLearning(turn, openDetails);
      if (semantics) card.append(semantics);

      const modules = renderSystemModules(turn, openDetails);
      if (modules) card.append(modules);

      const knowledgeFlow = renderKnowledgeFlow(turn, openDetails);
      if (knowledgeFlow) {
        const knowledgeSection = document.createElement("section");
        knowledgeSection.className = "nerd-section nerd-knowledge";
        const knowledgeHead = document.createElement("div");
        knowledgeHead.className = "nerd-section-head";
        const knowledgeTitle = document.createElement("h2");
        knowledgeTitle.textContent = "Knowledge Flow";
        const knowledgeHint = document.createElement("span");
        knowledgeHint.textContent = "Woher die verwendeten Informationen kamen";
        knowledgeHead.append(knowledgeTitle, knowledgeHint);
        knowledgeSection.append(knowledgeHead, knowledgeFlow);
        card.append(knowledgeSection);
      }

      const details = document.createElement("details");
      details.className = "nerd-deep";
      details.dataset.nerdKey = `${turn.id}:technical`;
      details.open = openDetails.has(details.dataset.nerdKey);
      const summary = document.createElement("summary");
      summary.textContent = "Deep Telemetry";
      const grid = document.createElement("div");
      grid.className = "nerd-grid";
      const minimalDecisions = (turn.steps || []).filter(
        (step) => step.component === "minimal" && step.operation === "decision" && step.details,
      );
      const initialDecision = minimalDecisions[0]?.details;
      const finalDecision = minimalDecisions.at(-1)?.details;
      const calls = turn.llm_calls || [];
      appendNerdField(grid, "LLM-Requests gestartet", calls.length);
      appendNerdField(grid, "LLM-Requests erfolgreich", calls.filter((c) => (c.status || "success") === "success").length);
      appendNerdField(grid, "LLM-Requests fehlgeschlagen", calls.filter((c) => c.status && !["success", "running", "cancelled"].includes(c.status)).length);
      appendNerdField(grid, "LLM-Requests abgebrochen", calls.filter((c) => c.status === "cancelled").length);
      appendNerdField(grid, "Gemeldete Prompt-Tokens", turn.summary?.usage_reported?.prompt_tokens);
      appendNerdField(grid, "Gemeldete Completion-Tokens", turn.summary?.usage_reported?.completion_tokens);
      appendNerdField(grid, "Modell", turn.model);
      appendNerdField(grid, "Turn-ID", turn.summary?.backend_turn_id || turn.id);
      appendNerdField(grid, "Backend-Status", turn.summary?.backend_status || turn.status);
      appendNerdField(grid, "Entscheidungsweg", minimalDecisions.length ? "EVE Minimal" : null);
      appendNerdField(grid, "Erste Entscheidung", initialDecision?.decision);
      appendNerdField(grid, "Letzte Entscheidung", finalDecision?.decision);
      appendNerdField(grid, "Capability", finalDecision?.capability || initialDecision?.capability);
      appendNerdField(grid, "Operation", finalDecision?.operation || initialDecision?.operation);
      appendNerdField(grid, "Wirkung", finalDecision?.effect || initialDecision?.effect);
      appendNerdField(grid, "Semantische Entscheidungen", minimalDecisions.length || null);
      appendNerdField(grid, "Quantisierung", turn.quantization);
      appendNerdField(grid, "Prompt-Tokens", turn.summary?.usage?.prompt_tokens);
      appendNerdField(grid, "Output-Tokens", turn.summary?.usage?.completion_tokens);
      appendNerdField(grid, "Erster Text-Chunk", turn.summary?.first_text_chunk_ms == null ? null : `${turn.summary.first_text_chunk_ms} ms`);
      appendNerdField(grid, "Answer Commit", turn.summary?.answer_committed_at == null ? null : `${turn.summary.answer_committed_at} ms`);
      appendNerdField(grid, "Textstream fertig", turn.summary?.text_stream_end_ms == null ? null : `${turn.summary.text_stream_end_ms} ms`);
      appendNerdField(grid, "Antwort fertig", turn.summary?.answer_ready_ms == null ? null : `${turn.summary.answer_ready_ms} ms`);
      appendNerdField(grid, "Text gesendet", turn.summary?.text_sent_ms == null ? null : `${turn.summary.text_sent_ms} ms`);
      appendNerdField(grid, "Presentation Start", turn.summary?.presentation_start_ms == null ? null : `${turn.summary.presentation_start_ms} ms`);
      appendNerdField(grid, "Presentation fertig", turn.summary?.presentation_ready_ms == null ? null : `${turn.summary.presentation_ready_ms} ms`);
      appendNerdField(grid, "TTS Start", turn.summary?.tts_start_ms == null ? null : `${turn.summary.tts_start_ms} ms`);
      appendNerdField(grid, "Erstes sprechbares Segment", turn.summary?.tts_first_segment_ms == null ? null : `${turn.summary.tts_first_segment_ms} ms`);
      appendNerdField(grid, "TTS-Segmente", turn.summary?.tts_segment_count);
      appendNerdField(grid, "Erstes Audiosegment", turn.summary?.first_audio_ready_ms == null ? null : `${turn.summary.first_audio_ready_ms} ms`);
      appendNerdField(grid, "Audio fertig", turn.summary?.audio_ready_ms == null ? null : `${turn.summary.audio_ready_ms} ms`);
      appendNerdField(grid, "P/T-Überlappung", turn.summary?.postprocess_overlap_ms == null ? null : `${turn.summary.postprocess_overlap_ms} ms`);
      appendNerdField(grid, "Turn vollständig", turn.summary?.full_turn_completion_ms == null ? null : `${turn.summary.full_turn_completion_ms} ms`);
      appendNerdField(grid, "Gesamtdauer", turn.duration_ms == null ? null : `${turn.duration_ms} ms`);
      details.append(summary, grid);
      for (const [callIndex, call] of (turn.llm_calls || []).entries()) {
        const callRatePresentation = tokenRatePresentation(call);
        const llm = document.createElement("details");
        llm.dataset.nerdKey = `${turn.id}:llm:${callIndex}`;
        llm.open = openDetails.has(llm.dataset.nerdKey);
        const llmSummary = document.createElement("summary");
        const llmRole = typeof call.role === "string" && call.role.trim() ? call.role.trim() : "LLM-Aufruf";
        llmSummary.textContent = `${llmRole} · ${call.status || "success"} · ${call.model} · ${metric(call.duration_ms, " ms")}`;
        const llmGrid = document.createElement("div");
        llmGrid.className = "nerd-grid";
        appendNerdField(llmGrid, "Request-ID", call.request_id);
        appendNerdField(llmGrid, "Status", call.status || "success");
        appendNerdField(llmGrid, "Fehlerkategorie", call.error_category);
        appendNerdField(llmGrid, "Prompt-Tokens", call.prompt_tokens ?? "Nicht gemeldet");
        appendNerdField(llmGrid, "Completion-Tokens", call.completion_tokens ?? "Nicht gemeldet");
        appendNerdField(llmGrid, "TTFT", call.ttft_ms == null ? null : `${call.ttft_ms} ms`);
        appendNerdField(llmGrid, "Generierungsdauer", call.generation_ms == null ? null : `${call.generation_ms} ms`);
        appendNerdField(llmGrid, "Streaming", call.streaming == null ? null : (call.streaming ? "ja" : "nein"));
        appendNerdField(llmGrid, "Context", call.context_size);
        appendNerdField(llmGrid, "Context genutzt", call.context_used);
        appendNerdField(llmGrid, "Prompt Eval", call.prompt_tokens_per_second == null ? null : `${call.prompt_tokens_per_second} tok/s`);
        appendNerdField(llmGrid, callRatePresentation.detailLabel, call.tokens_per_second == null ? null : `${call.tokens_per_second} tok/s`);
        appendNerdField(llmGrid, "Tok/s-Messbasis", call.tokens_per_second == null ? null : callRatePresentation.description);
        llm.append(llmSummary, llmGrid);
        details.append(llm);
      }
      const raw = document.createElement("details");
      raw.dataset.nerdKey = `${turn.id}:raw`;
      raw.open = openDetails.has(raw.dataset.nerdKey);
      const rawSummary = document.createElement("summary");
      rawSummary.textContent = "Redigierte Rohdaten (JSON)";
      const pre = document.createElement("pre");
      pre.textContent = formatDiagnosticJson(turn);
      raw.append(rawSummary, createDiagnosticCopyControl(turn), pre);
      details.append(raw);
      card.append(details);
      elements.nerdTurns.append(card);
    }
    if (!(data.turns || []).length) elements.nerdTurns.textContent = "Noch keine Turn-Telemetrie vorhanden.";
    elements.nerdTurns.scrollTop = previousScrollTop;
    for (const pre of elements.nerdTurns.querySelectorAll("details[data-nerd-key] > pre")) {
      const position = rawScrollPositions.get(pre.parentElement?.dataset.nerdKey);
      if (!position) continue;
      pre.scrollTop = position.pinnedToBottom
        ? Math.max(0, pre.scrollHeight - pre.clientHeight)
        : position.top;
      pre.scrollLeft = position.left;
    }
  }

  async function loadNerdTelemetry() {
    if (!nerdMode || elements.nerdView.hidden) return;
    const suffix = activeConversationId ? `?conversation_id=${encodeURIComponent(activeConversationId)}` : "";
    const response = await fetchWithTimeout(`/api/telemetry${suffix}`, { cache: "no-store", headers: auth });
    const data = await readJsonResponse(response, "Telemetrie");
    if (!response.ok) throw new Error(data.error || "Telemetrie konnte nicht geladen werden.");
    renderNerdTurns(data);
  }

  function setNerdMode(enabled) {
    nerdMode = Boolean(enabled);
    if (nerdMode && brainwatchOpen) setBrainwatchOpen(false);
    window.localStorage.setItem("eve.nerdMode", String(nerdMode));
    elements.nerdModeToggle.setAttribute("aria-pressed", String(nerdMode));
    elements.nerdModeState.textContent = nerdMode ? "AN" : "AUS";
    elements.nerdView.hidden = !nerdMode;
    document.body.classList.toggle("nerd-open", nerdMode);
    syncAvatarCloudVisibility();
    setSystemMenuOpen(false);
    if (nerdMode) {
      elements.presentationView.hidden = true;
      document.body.classList.remove("presentation-open");
      setConfigOpen(false);
      loadNerdTelemetry().catch((error) => { elements.nerdTurns.textContent = error.message; });
      window.clearInterval(nerdTimer);
      nerdTimer = window.setInterval(() => loadNerdTelemetry().catch(() => {}), 2000);
    } else {
      window.clearInterval(nerdTimer);
      presentationRevision = -1;
    }
  }

  function setPresentationMotion(enabled) {
    presentationMotion = Boolean(enabled);
    window.localStorage.setItem("eve.presentationMotion", String(presentationMotion));
    elements.presentationMotionToggle.setAttribute("aria-pressed", String(presentationMotion));
    elements.presentationMotionState.textContent = presentationMotion ? "AN" : "AUS";
    document.body.classList.toggle("motion-off", !presentationMotion);
  }

  elements.shareToggle.addEventListener("click", () => {
    if (chatOpen) {
      setChatOpen(false);
      return;
    }
    openCurrentChat().catch((error) => setDetail(error.message));
  });
  elements.composerScrim.addEventListener("click", () => closeComposer({ hide: true }));
  elements.messageText.addEventListener("input", () => {
    resizeMessageInput();
    updateComposerActivity();
  });
  elements.dropzone.addEventListener("click", () => elements.imageInput.click());
  elements.dropzone.addEventListener("keydown", (event) => {
    if (event.code === "Enter" || event.code === "Space") {
      event.preventDefault();
      elements.imageInput.click();
    }
  });
  elements.imageInput.addEventListener("change", () => {
    addImages(elements.imageInput.files).catch((error) => setDetail(error.message));
    elements.imageInput.value = "";
  });
  for (const eventName of ["dragenter", "dragover"]) {
    elements.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      elements.dropzone.classList.add("drag");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    elements.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      elements.dropzone.classList.remove("drag");
    });
  }
  elements.dropzone.addEventListener("drop", (event) => {
    addImages(event.dataTransfer.files).catch((error) => setDetail(error.message));
  });
  window.addEventListener("paste", (event) => {
    const images = [...event.clipboardData.items]
      .filter((item) => SAFE_IMAGE_TYPES.has(item.type))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (images.length) {
      openComposer();
      addImages(images).catch((error) => setDetail(error.message));
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.imageViewer.hidden) closeImageViewer();
    else if (event.key === "Escape" && !elements.configHelpPopover.hidden) closeConfigHelp();
    else if (event.key === "Escape" && systemMenuOpen) setSystemMenuOpen(false);
    else if (event.key === "Escape" && brainwatchOpen) setBrainwatchOpen(false);
    else if (event.key === "Escape" && nerdMode) setNerdMode(false);
    else if (event.key === "Escape" && configOpen) setConfigOpen(false);
    else if (event.key === "Escape" && elements.taskEditor.open) closeTaskEditor();
    else if (event.key === "Escape" && chatOpen) closeComposer({ hide: true });
  });

  elements.conversationToggle.addEventListener("click", () => toggleConversationPanel());
  elements.systemMenuToggle.addEventListener("click", () => setSystemMenuOpen(!systemMenuOpen));
  elements.openConfig.addEventListener("click", () => setConfigOpen(true));
  elements.openBrainwatch.addEventListener("click", () => setBrainwatchOpen(true));
  elements.brainwatchClose.addEventListener("click", () => setBrainwatchOpen(false));
  elements.brainwatchInfoMode.addEventListener("click", () => setBrainwatchMode("information"));
  elements.brainwatchMemoryMode.addEventListener("click", () => setBrainwatchMode("memory"));
  elements.brainwatchSemanticMode.addEventListener("click", () => setBrainwatchMode("semantic"));
  elements.brainwatchEventsMode.addEventListener("click", () => setBrainwatchMode("events"));
  elements.brainwatchEventsRefresh.addEventListener("click", () => loadBrainwatchEvents(false).catch(showBrainwatchEventsError));
  elements.brainwatchEventsMore.addEventListener("click", () => loadBrainwatchEvents(true).catch(showBrainwatchEventsError));
  elements.brainwatchStatisticsMode.addEventListener("click", () => setBrainwatchMode("statistics"));
  elements.brainwatchStatisticsRefresh.addEventListener("click", () => {
    loadBrainwatchStatistics().catch((error) => { elements.brainwatchStatisticsStatus.textContent = error.message; });
  });
  elements.brainwatchSearchForm.addEventListener("submit", (event) => searchBrainwatch(event).catch((error) => { elements.brainwatchStatus.textContent = error.message; }));
  elements.memoryExplorerForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadMemoryClaims(false).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
    loadMemoryStructure(false).catch((error) => { setMemoryStructureStatus(error.message); });
  });
  elements.memoryExplorerMore.addEventListener("click", () => {
    if (memoryClaimsCursor) loadMemoryClaims(true).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
  });
  elements.memoryCloudView.addEventListener("click", () => setMemoryExplorerSubview("cloud"));
  elements.memoryTimelineView.addEventListener("click", () => setMemoryExplorerSubview("timeline"));
  elements.memoryCloudReset.addEventListener("click", () => ensureMemoryCloud()?.resetCamera());
  for (const [button, mode] of [[elements.memoryCloudVR, "immersive-vr"], [elements.memoryCloudAR, "immersive-ar"]]) {
    button.addEventListener("click", () => {
      ensureMemoryCloud()?.xrController?.start(mode).catch(error => { elements.memoryCloudXRStatus.textContent = error.message; });
    });
  }
  elements.memoryCloudXREnd.addEventListener("click", () => {
    memoryCloudRenderer?.xrController?.end().catch(error => { elements.memoryCloudXRStatus.textContent = error.message; });
  });
  elements.memoryCloudFocus.addEventListener("click", focusMemoryCloudClaim);
  elements.memoryCloudWorking.addEventListener("change", () => {
    updateWorkingMemoryCloud();
    syncWorkingMemoryCloud();
  });
  elements.memoryCloudWorkingFocus.addEventListener("click", () => {
    const node = memoryWorkingLayer?.snapshot?.nodes?.find(item => item.work_status === "running")
      || memoryWorkingLayer?.snapshot?.nodes?.[0];
    if (!elements.memoryCloudWorking.checked || !node) {
      elements.memoryCloudWorkingStatus.textContent = "Kein temporärer Lernarbeitsstand eingeblendet.";
      return;
    }
    memoryCloudRenderer?.focusClaim(node.id);
    renderWorkingMemoryInspector(node);
  });
  elements.memoryCloudOverview.addEventListener("click", () => {
    memoryCloudAnchor = null;
    ensureMemoryCloud()?.resetCamera();
  });
  elements.memoryCloudRelationType.addEventListener("change", () => loadMemoryStructure(false, "").catch((error) => { setMemoryStructureStatus(error.message); }));
  elements.memoryCloudIntensity.addEventListener("change", () => ensureMemoryCloud()?.setIntensity(elements.memoryCloudIntensity.value));
  elements.memoryCloudQuality.addEventListener("change", () => ensureMemoryCloud()?.setQuality(elements.memoryCloudQuality.value));
  elements.memoryCloudLearningClear.addEventListener("click", clearMemoryCloudLearningHighlight);
  elements.memoryCloudMore.addEventListener("click", () => {
    loadMemoryCloud(false).catch((error) => { setMemoryStructureStatus(error.message); });
  });
  elements.memoryCloudActivityLoad.addEventListener("click", () => {
    loadMemoryCloudTurnActivity().catch((error) => renderMemoryCloudActivityStatus(error.message));
  });
  elements.memoryCloudTurn.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    loadMemoryCloudTurnActivity().catch((error) => renderMemoryCloudActivityStatus(error.message));
  });
  elements.memoryCloudActivityCategory.addEventListener("change", () => {
    pauseMemoryCloudActivity(); memoryCloudActivityIndex = -1;
    ensureMemoryCloud()?.setActivityFilter(elements.memoryCloudActivityCategory.value);
    renderMemoryCloudActivityStatus();
  });
  elements.memoryCloudActivityPrevious.addEventListener("click", () => { pauseMemoryCloudActivity(false); selectMemoryCloudActivityEvent(memoryCloudActivityIndex - 1); });
  elements.memoryCloudActivityPlay.addEventListener("click", playMemoryCloudActivity);
  elements.memoryCloudActivityNext.addEventListener("click", () => { pauseMemoryCloudActivity(false); selectMemoryCloudActivityEvent(memoryCloudActivityIndex + 1); });
  elements.memoryCloudActivityClear.addEventListener("click", clearMemoryCloudActivity);
  elements.memoryCloudActivitySpeed.addEventListener("change", () => { if (memoryCloudActivityTimer) { pauseMemoryCloudActivity(); playMemoryCloudActivity(); } });
  elements.memoryCloudLive.addEventListener("change", async () => {
    if (!elements.memoryCloudLive.checked) { stopMemoryCloudLive(); renderMemoryCloudActivityStatus(); return; }
    const turnId = memoryCloudTurnId();
    if (!turnId) { elements.memoryCloudLive.checked = false; renderMemoryCloudActivityStatus("Für LIVE zuerst eine Turn-ID angeben."); return; }
    try {
      if (turnId !== memoryCloudActivityTurn) await loadMemoryCloudTurnActivity(turnId);
      else await startMemoryCloudLive();
    } catch (error) {
      elements.memoryCloudLive.checked = false; stopMemoryCloudLive();
      renderMemoryCloudActivityStatus(`Live-Nachlauf gestoppt: ${error.message}`);
    }
  });
  elements.memoryTimelineForm.addEventListener("submit", (event) => {
    event.preventDefault(); loadMemoryTimeline(false).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
  });
  elements.memoryTimelineMore.addEventListener("click", () => {
    if (Object.values(memoryTimelineHasMore).some(Boolean)) loadMemoryTimeline(true).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
  });
  elements.memoryTimelineSource.addEventListener("change", () => {
    const runtimeOnly = elements.memoryTimelineSource.value === "runtime";
    elements.memoryTimelineKind.disabled = runtimeOnly;
    elements.memoryTimelineFidelity.disabled = runtimeOnly;
    elements.memoryTimelineProof.disabled = elements.memoryTimelineSource.value === "historical";
  });
  elements.memoryTimelineFirst.addEventListener("click", () => { pauseMemoryTimeline(); selectMemoryTimelineEvent(0); });
  elements.memoryTimelinePrevious.addEventListener("click", () => { pauseMemoryTimeline(); selectMemoryTimelineEvent(memoryTimelineIndex - 1); });
  elements.memoryTimelinePlay.addEventListener("click", () => playMemoryTimeline());
  elements.memoryTimelineNext.addEventListener("click", () => { pauseMemoryTimeline(); selectMemoryTimelineEvent(memoryTimelineIndex + 1); });
  elements.memoryTimelineSpeed.addEventListener("change", () => { if (memoryTimelineTimer) { pauseMemoryTimeline(); playMemoryTimeline(); } });
  elements.brainwatchZoomIn.addEventListener("click", () => brainwatchGraph.zoom(1.2));
  elements.brainwatchZoomOut.addEventListener("click", () => brainwatchGraph.zoom(.8));
  elements.brainwatchCenter.addEventListener("click", () => brainwatchGraph.center());
  elements.brainwatchContextView.addEventListener("click", () => {
    brainwatchGraph.setViewMode("context"); updateBrainwatchControls();
    elements.brainwatchStatus.textContent = "Auswahl mit zwei Beziehungsebenen angezeigt.";
  });
  elements.brainwatchFlowView.addEventListener("click", () => {
    brainwatchGraph.setViewMode("flow"); updateBrainwatchControls();
    elements.brainwatchStatus.textContent = "Persistierter Ablauf aus Herkunft, Retrieval und Folgen hervorgehoben.";
  });
  elements.brainwatchOverviewView.addEventListener("click", () => {
    brainwatchGraph.setViewMode("overview"); updateBrainwatchControls();
    elements.brainwatchStatus.textContent = "Gesamter bisher geladener Explorationsraum angezeigt.";
  });
  elements.brainwatchToggleBranch.addEventListener("click", () => {
    const focused = brainwatchGraph.focus;
    if (!focused) return;
    if (brainwatchGraph.isExpanded(focused)) {
      brainwatchGraph.collapse(focused);
      brainwatchPendingGroups.delete(focused); renderBrainwatchGroups(focused);
      brainwatchPage = null; elements.brainwatchMore.hidden = true;
      const status = brainwatchMode === "memory" ? elements.memoryExplorerStatus : elements.brainwatchStatus;
      status.textContent = brainwatchMode === "memory" ? "Memory-Relations eingeklappt." : "Informationsast eingeklappt.";
      updateBrainwatchControls();
    } else {
      if (brainwatchMode === "memory") {
        focusMemoryClaim(focused).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
      } else {
        focusBrainwatchNode(focused).catch((error) => { elements.brainwatchStatus.textContent = error.message; });
      }
    }
  });
  elements.brainwatchSearchCollapse.addEventListener("click", () => {
    toggleBrainwatchColumn("navigation");
  });
  elements.brainwatchInspectorCollapse.addEventListener("click", () => toggleBrainwatchColumn("inspector"));
  elements.brainwatchLayoutReset.addEventListener("click", () => resetBrainwatchLayout());
  attachBrainwatchResize(elements.brainwatchNavigationResize, "navigation");
  attachBrainwatchResize(elements.brainwatchInspectorResize, "inspector");
  window.addEventListener("resize", () => applyBrainwatchLayout({persist: false}));
  applyBrainwatchLayout({persist: false});
  elements.brainwatchReset.addEventListener("click", () => {
    brainwatchGraph.clear(); brainwatchPendingGroups.clear(); renderBrainwatchGroups(null);
    brainwatchFocusHistory = []; renderBrainwatchPath();
    memoryRelationCache = { claimId: null, items: [] };
    brainwatchPage = null; elements.brainwatchMore.hidden = true;
    elements.brainwatchInspector.replaceChildren();
    const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow"; eyebrow.textContent = brainwatchMode === "memory" ? "MEMORY EXPLORER" : "INSPECTOR";
    const title = document.createElement("h2"); title.textContent = brainwatchMode === "memory" ? "Noch kein Claim gewählt" : "Noch kein Knoten gewählt";
    elements.brainwatchInspector.append(eyebrow, title);
    updateBrainwatchControls();
  });
  elements.brainwatchMore.addEventListener("click", () => {
    if (!brainwatchPage) return;
    if (brainwatchPage.kind === "memory") {
      focusMemoryClaim(brainwatchPage.nodeId, { cursor: brainwatchPage.cursor }).catch((error) => { elements.memoryExplorerStatus.textContent = error.message; });
    } else {
      focusBrainwatchNode(brainwatchPage.nodeId, { cursor: brainwatchPage.cursor }).catch((error) => { elements.brainwatchStatus.textContent = error.message; });
    }
  });
  elements.nerdModeToggle.addEventListener("click", () => setNerdMode(!nerdMode));
  elements.avatarModeToggle.addEventListener("click", () => setAvatarMode(avatarMode === "brainwatch" ? "logo" : "brainwatch"));
  elements.presentationMotionToggle.addEventListener("click", () => setPresentationMotion(!presentationMotion));
  elements.configHelpClose.addEventListener("click", closeConfigHelp);
  elements.configSections.addEventListener("scroll", closeConfigHelp, { passive: true });
  window.addEventListener("resize", positionConfigHelp);
  elements.presentationClose.addEventListener("click", async () => {
    const response = await fetchWithTimeout("/api/presentation", { method: "DELETE", headers: auth });
    if (response.ok) renderPresentation(await readJsonResponse(response, "Präsentation"));
  });
  elements.imageViewerClose.addEventListener("click", closeImageViewer);
  document.addEventListener("pointerdown", (event) => {
    if (!elements.configHelpPopover.hidden
        && !elements.configHelpPopover.contains(event.target)
        && !event.target.closest(".config-help-trigger")) {
      closeConfigHelp();
    }
    if (systemMenuOpen && !elements.systemMenu.contains(event.target) && !elements.systemMenuToggle.contains(event.target)) {
      setSystemMenuOpen(false);
    }
  });
  elements.configClose.addEventListener("click", () => setConfigOpen(false));
  const markConfigDirty = () => {
    elements.configSave.disabled = false;
    elements.configStatus.textContent = "Ungespeicherte Änderungen.";
  };
  elements.configForm.addEventListener("input", markConfigDirty);
  elements.configForm.addEventListener("change", markConfigDirty);
  elements.configForm.addEventListener("submit", saveConfig);
  elements.nerdModeToggle.setAttribute("aria-pressed", String(nerdMode));
  elements.nerdModeState.textContent = nerdMode ? "AN" : "AUS";
  setPresentationMotion(presentationMotion);
  if (nerdMode) setNerdMode(true);
  elements.conversationScrim.addEventListener("click", () => toggleConversationPanel(false));
  elements.taskViewToggle.addEventListener("click", () => toggleTaskView());
  elements.scheduleViewToggle.addEventListener("click", () => toggleScheduleView());
  elements.newWorkList.addEventListener("click", () => {
    const opening = elements.newWorkListForm.hidden;
    elements.newWorkListForm.hidden = !opening;
    elements.newWorkList.setAttribute("aria-expanded", String(opening));
    if (opening) { elements.newWorkListName.focus(); window.requestAnimationFrame(sizeWorkDescriptions); }
  });
  elements.newWorkListForm.querySelector('[data-action="cancel-list"]').addEventListener("click", () => {
    elements.newWorkListForm.reset();
    elements.newWorkListForm.hidden = true;
    elements.newWorkList.setAttribute("aria-expanded", "false");
  });
  elements.newWorkListForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (workMutationBusy) return;
    try {
      workMutationBusy = true;
      setWorkTaskError();
      const data = await workTaskRequest("/api/work-lists", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({
          name: elements.newWorkListName.value.trim(),
          description: elements.newWorkListDescription.value.trim() || null,
        }),
      }, "Arbeitsliste anlegen");
      if (data.list?.id) {
        openWorkLists.add(data.list.id);
        persistWorkDisclosures("eve.openWorkLists", openWorkLists);
      }
      elements.newWorkListForm.reset();
      elements.newWorkListForm.hidden = true;
      elements.newWorkList.setAttribute("aria-expanded", "false");
      await loadWorkTasks();
    } catch (error) {
      setWorkTaskError(error.message);
    } finally {
      workMutationBusy = false;
    }
  });
  elements.taskScheduleType.addEventListener("change", updateTaskEditorFields);
  elements.taskEditorClose.addEventListener("click", closeTaskEditor);
  elements.taskEditorCancel.addEventListener("click", closeTaskEditor);
  elements.taskEditor.addEventListener("click", (event) => {
    if (event.target === elements.taskEditor) closeTaskEditor();
  });
  elements.taskEditorForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!editingTaskId) return;
    elements.taskEditorError.textContent = "";
    try {
      const timing = taskSchedulePayload();
      await updateTask(editingTaskId, {
        request: elements.taskMessage.value.trim(),
        status: elements.taskActive.checked ? "active" : "paused",
        schedule_type: timing.type,
        schedule: timing.schedule,
      });
      closeTaskEditor();
    } catch (error) {
      elements.taskEditorError.textContent = error.message;
    }
  });
  elements.exportConversation.addEventListener("click", exportConversationPng);
  elements.newConversation.addEventListener("click", () => {
    createConversation().catch((error) => setDetail(error.message));
  });
  elements.renameConversation.addEventListener("click", async () => {
    if (!activeConversationId) return;
    const current = conversations.find((item) => item.id === activeConversationId)?.title || "";
    const title = window.prompt("Neuer Titel der Unterhaltung:", current);
    if (title === null || title.trim() === current) return;
    try {
      const response = await fetchWithTimeout(`/api/conversations/${encodeURIComponent(activeConversationId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ title: title.trim() }),
      });
      const data = await readJsonResponse(response, "Umbenennen");
      if (!response.ok) throw new Error(data.error || "Titel konnte nicht geändert werden.");
      await loadConversations(activeConversationId);
    } catch (error) {
      setDetail(error.message);
    }
  });
  elements.deleteConversation.addEventListener("click", async () => {
    if (!activeConversationId || !window.confirm("Diese Unterhaltung wirklich löschen?")) return;
    try {
      const response = await fetchWithTimeout(`/api/conversations/${encodeURIComponent(activeConversationId)}`, {
        method: "DELETE", headers: auth,
      });
      const data = await readJsonResponse(response, "Löschen");
      if (!response.ok) throw new Error(data.error || "Unterhaltung konnte nicht gelöscht werden.");
      activeConversationId = data.active_id || null;
      await loadConversations(activeConversationId);
    } catch (error) {
      setDetail(error.message);
    }
  });

  function takeComposerMessage() {
    const text = elements.messageText.value.trim();
    if (!text && !attachedImages.length) return null;
    const message = {
      text,
      submittedText: elements.messageText.value,
      images: [...attachedImages],
    };
    elements.messageText.value = "";
    attachedImages = [];
    resizeMessageInput();
    renderPreviews();
    updateComposerActivity();
    return message;
  }

  async function submitMessage(queuedMessage = null) {
    if (!llmReady) {
      setDetail("Das lokale Sprachmodell ist nicht erreichbar.");
      return;
    }
    const message = queuedMessage || takeComposerMessage();
    if (!message) {
      setDetail("Bitte Text oder einen Screenshot ablegen.");
      return;
    }
    if (requestBusy || window.localStorage.getItem("eve.activeBackendTurn")) {
      if (!requestBusy) scheduleBackendReconnect(0);
      queuedMessages.push(message);
      renderMessageQueue();
      updateComposerActivity();
      return;
    }
    const { text, submittedText, images: submittedImages } = message;
    requestBusy = true;
    updatePTT();
    setReply("");
    renderArtifacts([]);
    renderSources([]);
    setDetail("EVE nimmt das auf …");
    showState("thinking");
    unlockAudio().catch(() => {});
    const optimisticMessage = appendChatMessage({ role: "user", content: text || `[${submittedImages.length} Screenshot(s)]`, created_at: new Date().toISOString() });
    let streamingMessage = null;
    const reasoning = liveReasoningState();
    let streamedText = "";
    let streamPaint = 0;
    let backendAccepted = false;
    const paintStream = (final = false) => {
      if (!streamingMessage) return;
      if (streamPaint) window.clearTimeout(streamPaint);
      streamPaint = 0;
      const content = streamingMessage.querySelector(".message-content");
      renderAssistantMarkdown(content, streamedText);
      setReply(streamedText);
      elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    };
    const queueStreamPaint = () => {
      if (!streamPaint) streamPaint = window.setTimeout(() => paintStream(false), 50);
    };
    let messageAccepted = false;
    let turnCancelled = false;
    try {
      const request = fetchWithTimeout("/api/message/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({
          text,
          images: submittedImages.map((item) => item.data),
          conversation_id: activeConversationId,
          resume_conversation: explicitConversationResume,
          ...(message.retryContext ? { retry_context: message.retryContext } : {}),
        }),
      }, 210000);
      const response = await request;
      if (!response.ok) {
        const data = await readJsonResponse(response, "EVE-Antwort");
        throw new Error(data.error || "Unbekannter Fehler");
      }
      if (!response.body) throw new Error("Der Browser unterstützt keinen Antwortstream.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let data = null;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = done ? "" : lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "accepted" && event.turn_id) {
            backendAccepted = true;
            cancelledAudioTurns.delete(event.turn_id);
            window.localStorage.setItem("eve.activeBackendTurn", event.turn_id);
            latestVisibleTurnId = event.turn_id;
            activeBackendTurnId = event.turn_id;
            startAvatarCloudActivity(event.turn_id).catch(() => {});
            backendTurnCancellable = Boolean(event.cancellable);
            updateComposerActivity();
            if (event.conversation_id && event.conversation_id !== activeConversationId) {
              activeConversationId = event.conversation_id;
              await loadConversations(activeConversationId);
            }
            scheduleConversationRollover(null, true);
            optimisticMessage.dataset.backendTurnId = event.turn_id;
          } else if (event.type === "input") {
            ensureBackendUserMessage(event.turn_id, event.content);
          } else if (event.type === "status") {
            backendTurnCancellable = Boolean(event.cancellable && !event.cancel_requested);
            updateComposerActivity();
            setDetail(backendTurnStatusLabel(event.status));
          } else if (event.type === "reasoning_delta") {
            appendLiveReasoning(reasoning, event.content);
          } else if (["preview_delta", "delta"].includes(event.type) && typeof event.content === "string") {
            finishLiveReasoning(reasoning);
            if (!streamingMessage) {
              streamingMessage = appendChatMessage({ role: "assistant", content: "", created_at: new Date().toISOString() });
              streamingMessage.classList.add("streaming");
              attachReasoningLink(reasoning, streamingMessage);
            }
            streamedText += event.content;
            queueStreamPaint();
          } else if (event.type === "preview_reset") {
            if (streamPaint) window.clearTimeout(streamPaint);
            streamPaint = 0;
            streamedText = "";
            streamingMessage?.remove();
            streamingMessage = null;
            setReply("");
          } else if (event.type === "preview_commit") {
            streamingMessage?.classList.remove("preview");
          } else if (event.type === "audio" && event.audio_wav_base64) {
            queueReply(decodeAudio(event.audio_wav_base64), event.turn_id).catch((error) => {
              audioError("Textantwort bleibt sichtbar; Audio konnte nicht abgespielt werden", error);
            });
          } else if (event.type === "complete") {
            finishLiveReasoning(reasoning);
            data = event.result;
            finishAvatarCloudActivity(event.turn_id || data?.turn_id || activeBackendTurnId, true);
            window.localStorage.removeItem("eve.activeBackendTurn");
          } else if (event.type === "cancelled") {
            finishLiveReasoning(reasoning, "cancelled");
            turnCancelled = true;
            finishAvatarCloudActivity(event.turn_id || activeBackendTurnId, false);
            cancelTurnAudio(event.turn_id);
            backendTurnCancellable = false;
            streamingMessage?.classList.add("cancelled");
            setDetail("Backend-Turn abgebrochen · cancelled");
          } else if (event.type === "error") {
            finishLiveReasoning(reasoning, "failed");
            throw streamFailure(event);
          }
        }
        if (done) break;
      }
      if (turnCancelled) {
        window.localStorage.removeItem("eve.activeBackendTurn");
        paintStream(true);
        messageAccepted = true;
        showState("idle");
        return;
      }
      if (!data) throw new Error("Der Antwortstream endete ohne Abschluss.");
      if (streamedText && streamedText !== data.answer) {
        throw new Error("Der Abschluss stimmt nicht mit dem veröffentlichten Antwortstream überein.");
      }
      if (!streamedText) streamedText = data.answer || "";
      paintStream(true);
      messageAccepted = true;
      latestVisibleTurnId = data.turn_id || latestVisibleTurnId;
      setReply(streamedText);
      renderArtifacts(data.artifacts);
      renderSources(data.sources);
      activeConversationId = data.conversation_id || activeConversationId;
      await loadConversations(activeConversationId);
      showState("idle");
      followTurnCompletion(data).catch((error) => {
        audioError("Textantwort bleibt sichtbar; Nachbearbeitung fehlgeschlagen", error);
      });
    } catch (error) {
      finishLiveReasoning(reasoning, "failed");
      finishAvatarCloudActivity(activeBackendTurnId, false);
      if (!error.backendTerminal && backendAccepted) {
        if (streamPaint) window.clearTimeout(streamPaint);
        streamingMessage?.remove();
        if (reconnectInterruptedTurn(error, activeBackendTurnId)) return;
      }
      window.localStorage.removeItem("eve.activeBackendTurn");
      if (streamPaint) window.clearTimeout(streamPaint);
      const hasPublishedAnswer = Boolean(streamedText);
      if (hasPublishedAnswer) {
        paintStream(true);
        streamingMessage?.classList.add("failed");
        messageAccepted = true;
      } else {
        streamingMessage?.remove();
      }
      if (!messageAccepted && backendAccepted) {
        optimisticMessage.classList.add("failed");
        optimisticMessage.title = "Die Nachricht wurde angenommen, der Turn aber nicht abgeschlossen.";
      } else if (!messageAccepted) {
        optimisticMessage.remove();
        elements.chatEmpty.hidden = elements.chatMessages.childElementCount > 0;
        const newDraft = elements.messageText.value;
        elements.messageText.value = newDraft
          ? `${submittedText.replace(/\s+$/, "")}\n${newDraft}`
          : submittedText;
        attachedImages = submittedImages;
        resizeMessageInput();
        renderPreviews();
      }
      showState("error");
      if (await recoverStoredAnswer(activeBackendTurnId)) messageAccepted = true;
      showTurnFailure(error, activeBackendTurnId, submittedText, submittedImages);
      setDetail(`Fehler: ${error.name === "AbortError" ? "Zeitüberschreitung" : error.message}`);
    } finally {
      activeBackendTurnId = null;
      backendTurnCancellable = false;
      elements.turnCancel.textContent = "Abbrechen";
      requestBusy = false;
      updateComposerActivity();
      elements.sendMessage.disabled = !llmReady;
      updatePTT();
      flushNotifications();
      if (messageAccepted && queuedMessages.length) {
        const nextMessage = queuedMessages.shift();
        renderMessageQueue();
        window.setTimeout(() => submitMessage(nextMessage), 0);
      }
    }
  }

  elements.sendMessage.addEventListener("click", () => submitMessage());

  let backendReconnectTimer = 0;
  let backendReconnectDelay = 1000;

  function scheduleBackendReconnect(delay = backendReconnectDelay) {
    window.clearTimeout(backendReconnectTimer);
    backendReconnectTimer = window.setTimeout(() => {
      backendReconnectTimer = 0;
      resumeBackendTurn().catch((error) => setDetail(error.message));
    }, delay);
  }

  function reconnectInterruptedTurn(error, turnId) {
    if (!turnId || error.backendTerminal) return false;
    window.localStorage.setItem("eve.activeBackendTurn", turnId);
    setDetail("Verbindung unterbrochen · EVE arbeitet im Backend weiter. Wiederverbinden …");
    showState("thinking");
    scheduleBackendReconnect();
    backendReconnectDelay = Math.min(15000, backendReconnectDelay * 2);
    return true;
  }

  async function resumeBackendTurn() {
    const turnId = window.localStorage.getItem("eve.activeBackendTurn");
    if (!turnId || requestBusy) return;
    requestBusy = true;
    updatePTT();
    showState("thinking");
    setDetail("Laufender Backend-Turn wird wieder verbunden …");
    let node = null;
    const reasoning = liveReasoningState();
    let answer = "";
    let answerPaint = 0;
    const paintResumedAnswer = () => {
      answerPaint = 0;
      if (node) renderAssistantMarkdown(node.querySelector(".message-content"), answer);
      setReply(answer);
    };
    let turnCancelled = false;
    try {
      const response = await fetchWithTimeout(`/api/message/stream/${encodeURIComponent(turnId)}`, {
        cache: "no-store", headers: auth,
      }, 210000);
      if (!response.ok || !response.body) {
        const error = new Error(`Backend-Turn konnte nicht verbunden werden (HTTP ${response.status}).`);
        error.backendTerminal = response.status === 404 || response.status === 410;
        throw error;
      }
      // Replays contain the entire answer. Replace any previous partial render.
      if (activeConversationId) await selectConversation(activeConversationId, false, true);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let result = null;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = done ? "" : lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "accepted") {
            activeBackendTurnId = turnId;
            latestVisibleTurnId = turnId;
            backendTurnCancellable = Boolean(event.cancellable);
            backendReconnectDelay = 1000;
            updateComposerActivity();
            startAvatarCloudActivity(turnId).catch(() => {});
            if (event.conversation_id && event.conversation_id !== activeConversationId) {
              activeConversationId = event.conversation_id;
              await loadConversations(activeConversationId);
            }
          } else if (["preview_delta", "delta"].includes(event.type) && typeof event.content === "string") {
            finishLiveReasoning(reasoning);
            answer += event.content;
            if (!node) {
              node = appendChatMessage({ role: "assistant", content: "", created_at: new Date().toISOString() });
              node.classList.add("streaming");
              attachReasoningLink(reasoning, node);
            }
            if (!answerPaint) answerPaint = window.setTimeout(paintResumedAnswer, 50);
          } else if (event.type === "preview_reset") {
            if (answerPaint) window.clearTimeout(answerPaint);
            answerPaint = 0;
            answer = "";
            node?.remove();
            node = null;
            setReply("");
          } else if (event.type === "preview_commit") {
            node?.classList.remove("preview");
          } else if (event.type === "audio" && event.audio_wav_base64) {
            queueReply(decodeAudio(event.audio_wav_base64), event.turn_id).catch((error) => {
              audioError("Textantwort bleibt sichtbar; Audio konnte nicht abgespielt werden", error);
            });
          } else if (event.type === "input") {
            ensureBackendUserMessage(turnId, event.content);
          } else if (event.type === "transcript") {
            ensureBackendUserMessage(turnId, event.content);
            setDetail(`DU // ${event.content}`);
          } else if (event.type === "status") {
            activeBackendTurnId = turnId;
            backendTurnCancellable = Boolean(event.cancellable && !event.cancel_requested);
            updateComposerActivity();
            setDetail(`Backend-Turn ${turnId.slice(0, 8)} … ${event.status}`);
          } else if (event.type === "reasoning_delta") {
            appendLiveReasoning(reasoning, event.content);
          } else if (event.type === "complete") {
            finishLiveReasoning(reasoning);
            result = event.result;
            finishAvatarCloudActivity(event.turn_id || result?.turn_id || turnId, true);
          } else if (event.type === "cancelled") {
            finishLiveReasoning(reasoning, "cancelled");
            turnCancelled = true;
            finishAvatarCloudActivity(event.turn_id || turnId, false);
            cancelTurnAudio(event.turn_id || turnId);
            node?.classList.add("cancelled");
            setDetail("Backend-Turn abgebrochen · cancelled");
          } else if (event.type === "error") {
            finishLiveReasoning(reasoning, "failed");
            throw streamFailure(event);
          }
        }
        if (done) break;
      }
      if (answerPaint) window.clearTimeout(answerPaint);
      paintResumedAnswer();
      if (turnCancelled) {
        window.localStorage.removeItem("eve.activeBackendTurn");
        showState("idle");
        return;
      }
      if (!result) throw new Error("Backend-Turn endete ohne Ergebnis.");
      if (answer && answer !== result.answer) {
        throw new Error("Der Abschluss stimmt nicht mit dem veröffentlichten Antwortstream überein.");
      }
      if (!answer) answer = result.answer || "";
      window.localStorage.removeItem("eve.activeBackendTurn");
      activeConversationId = result.conversation_id || activeConversationId;
      latestVisibleTurnId = result.turn_id || turnId;
      await loadConversations(activeConversationId);
      setReply(answer);
      renderArtifacts(result.artifacts);
      renderSources(result.sources);
      showState("idle");
      followTurnCompletion(result).catch(() => {});
      if (queuedMessages.length) {
        const nextMessage = queuedMessages.shift();
        renderMessageQueue();
        window.setTimeout(() => submitMessage(nextMessage), 0);
      }
    } catch (error) {
      finishLiveReasoning(reasoning, "failed");
      finishAvatarCloudActivity(turnId, false);
      if (answerPaint) window.clearTimeout(answerPaint);
      if (answer) {
        paintResumedAnswer();
        node?.classList.add("failed");
      } else {
        node?.remove();
      }
      if (reconnectInterruptedTurn(error, turnId)) {
        node?.remove();
        return;
      }
      window.localStorage.removeItem("eve.activeBackendTurn");
      await recoverStoredAnswer(turnId);
      showTurnFailure(error, turnId);
      setDetail(`Backend-Turn: ${error.message}`);
      showState("error");

    } finally {
      activeBackendTurnId = null;
      backendTurnCancellable = false;
      elements.turnCancel.textContent = "Abbrechen";
      requestBusy = false;
      updatePTT();
      updateComposerActivity();
    }
  }
  elements.messageQueue.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-queue-index]");
    if (!button) return;
    const index = Number(button.dataset.queueIndex);
    if (!Number.isInteger(index) || index < 0 || index >= queuedMessages.length) return;
    queuedMessages.splice(index, 1);
    renderMessageQueue();
    updateComposerActivity();
  });
  elements.messageText.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !mobileChatQuery.matches) {
      event.preventDefault();
      submitMessage();
    }
  });

  function attachHorizontalResize(handle, readStart, applyDelta, allowCoarsePointer = false) {
    handle.addEventListener("pointerdown", (event) => {
      if ((!finePointerQuery.matches && !allowCoarsePointer) || event.button !== 0) return;
      event.preventDefault();
      const startX = event.clientX;
      const startValue = readStart();
      handle.setPointerCapture(event.pointerId);
      const move = (moveEvent) => applyDelta(startValue, moveEvent.clientX - startX);
      const stop = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
  }

  const MIN_HISTORY_PANEL_WIDTH = 280;
  const MIN_ACTIVE_CHAT_WIDTH = 560;
  const persistentLayoutWidth = (element, storageKey, cssProperty, fallback) => {
    const rendered = element.getBoundingClientRect().width;
    if (rendered > 0) return rendered;
    const stored = Number(window.localStorage.getItem(storageKey));
    if (Number.isFinite(stored) && stored > 0) return stored;
    const configured = Number.parseFloat(
      window.getComputedStyle(document.documentElement).getPropertyValue(cssProperty),
    );
    return Number.isFinite(configured) && configured > 0 ? configured : fallback;
  };
  const historyWidth = () => persistentLayoutWidth(
    elements.conversationPanel, "eve.historyPanelWidth", "--history-panel-width",
    MIN_HISTORY_PANEL_WIDTH,
  );
  const activeChatWidth = () => persistentLayoutWidth(
    elements.chatWorkspace, "eve.activeChatWidth", "--active-chat-width",
    MIN_ACTIVE_CHAT_WIDTH,
  );
  const desktopChatWidth = () => historyWidth() + activeChatWidth() + 12;
  const syncCoreLayout = () => {
    window.cancelAnimationFrame(coreLayoutFrame);
    coreLayoutFrame = window.requestAnimationFrame(() => canvasEngine.syncCoreBounds(520));
  };
  const applyDesktopChatWidths = (total, history) => {
    const available = Math.max(
      MIN_HISTORY_PANEL_WIDTH + 12 + MIN_ACTIVE_CHAT_WIDTH,
      window.innerWidth - 32,
    );
    history = Math.min(
      available - 12 - MIN_ACTIVE_CHAT_WIDTH,
      Math.max(MIN_HISTORY_PANEL_WIDTH, history),
    );
    const requestedMain = total - history - 12;
    const main = Math.min(
      available - history - 12,
      Math.max(MIN_ACTIVE_CHAT_WIDTH, requestedMain),
    );
    total = history + 12 + main;
    const visibleTotal = sidebarOpen ? total : main;
    const freeWidth = Math.max(320, window.innerWidth - visibleTotal - 32);
    const presenceScale = Math.min(.86, Math.max(.48, freeWidth / 760));
    document.body.classList.toggle("chat-stacked-dock", freeWidth < 620);
    elements.conversationPanel.style.width = `${history}px`;
    elements.conversationPanel.style.right = `${16 + main + 12}px`;
    elements.chatWorkspace.style.width = `${main}px`;
    document.documentElement.style.setProperty("--chat-total-width", `${total}px`);
    document.documentElement.style.setProperty("--history-panel-width", `${history}px`);
    document.documentElement.style.setProperty("--active-chat-width", `${main}px`);
    document.documentElement.style.setProperty("--presence-shift", `${-(visibleTotal + 32) / 2}px`);
    document.documentElement.style.setProperty("--presence-scale", String(presenceScale));
    document.documentElement.style.setProperty("--left-free-width", `${freeWidth}px`);
    document.documentElement.style.setProperty("--left-free-center", `${16 + freeWidth / 2}px`);
    window.localStorage.setItem("eve.historyPanelWidth", String(Math.round(history)));
    window.localStorage.setItem("eve.activeChatWidth", String(Math.round(main)));
    syncCoreLayout();
  };
  const setHistoryPanelWidth = (start, delta) => {
    const main = activeChatWidth();
    const width = Math.min(window.innerWidth - 32 - main - 12, Math.max(MIN_HISTORY_PANEL_WIDTH, start - delta));
    applyDesktopChatWidths(width + 12 + main, width);
    elements.workspaceResize.setAttribute("aria-valuenow", String(Math.round(width)));
  };
  const setActiveChatWidth = (start, delta) => {
    const history = historyWidth();
    const width = Math.min(window.innerWidth - 32 - history - 12, Math.max(MIN_ACTIVE_CHAT_WIDTH, start - delta));
    applyDesktopChatWidths(history + 12 + width, history);
    elements.panelResize.setAttribute("aria-valuenow", String(Math.round(width)));
  };

  attachHorizontalResize(elements.workspaceResize, historyWidth, setHistoryPanelWidth);
  attachHorizontalResize(elements.panelResize, activeChatWidth, setActiveChatWidth);
  elements.workspaceResize.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setHistoryPanelWidth(historyWidth(), event.key === "ArrowRight" ? 24 : -24);
  });
  elements.panelResize.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setActiveChatWidth(activeChatWidth(), event.key === "ArrowRight" ? 24 : -24);
  });
  const defaultConfigWidth = () => Math.min(window.innerWidth - 28, Math.max(760, Math.min(1800, window.innerWidth * .68)));
  const configWidth = () => {
    const rendered = elements.configView.getBoundingClientRect().width;
    if (rendered > 0) return rendered;
    const stored = Number(window.localStorage.getItem("eve.configWidth"));
    return Number.isFinite(stored) && stored > 0 ? stored : defaultConfigWidth();
  };
  const applyConfigWidth = (width) => {
    if (window.innerWidth < 900) return;
    const bounded = Math.min(window.innerWidth - 28, Math.max(460, width));
    document.documentElement.style.setProperty("--config-width", `${bounded}px`);
    elements.configResize.setAttribute("aria-valuenow", String(Math.round(bounded)));
    elements.configResize.setAttribute("aria-valuemax", String(Math.round(window.innerWidth - 28)));
    window.localStorage.setItem("eve.configWidth", String(Math.round(bounded)));
  };
  const savedConfigWidth = Number(window.localStorage.getItem("eve.configWidth"));
  if (window.innerWidth >= 900 && Number.isFinite(savedConfigWidth)) applyConfigWidth(savedConfigWidth);
  attachHorizontalResize(elements.configResize, configWidth, (start, delta) => applyConfigWidth(start + delta), true);
  elements.configResize.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    applyConfigWidth(configWidth() + (event.key === "ArrowRight" ? 24 : -24));
  });
  if (window.innerWidth >= 900) {
    const savedHistory = Number(window.localStorage.getItem("eve.historyPanelWidth"));
    const savedMain = Number(window.localStorage.getItem("eve.activeChatWidth"));
    const history = Number.isFinite(savedHistory) && savedHistory >= MIN_HISTORY_PANEL_WIDTH ? savedHistory : Math.max(MIN_HISTORY_PANEL_WIDTH, historyWidth());
    const main = Number.isFinite(savedMain) && savedMain >= MIN_ACTIVE_CHAT_WIDTH ? savedMain : Math.max(MIN_ACTIVE_CHAT_WIDTH, activeChatWidth());
    const boundedHistory = Math.max(MIN_HISTORY_PANEL_WIDTH, Math.min(window.innerWidth - 32 - MIN_ACTIVE_CHAT_WIDTH - 12, history));
    const boundedMain = Math.min(window.innerWidth - 32 - boundedHistory - 12, main);
    applyDesktopChatWidths(boundedHistory + 12 + boundedMain, boundedHistory);
  }
  window.addEventListener("resize", () => {
    if (window.innerWidth >= 900) {
      applyConfigWidth(configWidth());
      const total = Math.min(window.innerWidth - 32, desktopChatWidth());
      const history = Math.max(MIN_HISTORY_PANEL_WIDTH, Math.min(total - 12 - MIN_ACTIVE_CHAT_WIDTH, historyWidth()));
      applyDesktopChatWidths(total, history);
      return;
    }
    document.body.classList.remove("chat-stacked-dock");
    elements.conversationPanel.style.removeProperty("width");
    elements.conversationPanel.style.removeProperty("right");
    elements.chatWorkspace.style.removeProperty("width");
    document.documentElement.style.removeProperty("--config-width");
  });

  function stopTracks() {
    window.clearTimeout(recordingTimer);
    recordingTimer = null;
    try { micSource?.disconnect(); } catch (_) { /* already disconnected */ }
    micSource = null;
    micAnalyser = null;
    for (const track of stream?.getTracks() || []) track.stop();
    stream = null;
  }

  async function startPTT(event) {
    event.preventDefault();
    if (elements.ptt.disabled || requestBusy || captureBusy || audioQueued > 0 || playingAudio || recorder?.state === "recording") return;
    pressActive = true;
    elements.ptt.classList.add("pressed");
    elements.pttText.textContent = "MIKROFON WIRD AKTIVIERT …";
    captureBusy = true;
    updatePTT();
    try {
      await unlockAudio();
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!pressActive) {
        stopTracks();
        setDetail("Aufnahme abgebrochen.");
        showState("idle");
        return;
      }
      if (audioQueued > 0 || playingAudio) {
        pressActive = false;
        elements.ptt.classList.remove("pressed");
        elements.pttText.textContent = "GEDRÜCKT HALTEN ZUM SPRECHEN";
        releaseActivePointerCapture();
        stopTracks();
        setDetail("EVE spricht gerade noch.");
        return;
      }
      if (audioCtx) {
        micSource = audioCtx.createMediaStreamSource(stream);
        micAnalyser = audioCtx.createAnalyser();
        micAnalyser.fftSize = 256;
        micAnalyser.smoothingTimeConstant = .65;
        micSource.connect(micAnalyser);
      }
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.addEventListener("dataavailable", (chunkEvent) => {
        if (chunkEvent.data.size) chunks.push(chunkEvent.data);
      });
      recorder.start();
      recordingTimer = window.setTimeout(() => finishPTT(new Event("timeout")), 45000);
      elements.ptt.classList.add("recording");
      elements.ptt.setAttribute("aria-label", "Loslassen, um die Aufnahme an EVE zu senden");
      elements.pttText.textContent = "LOSLASSEN ZUM SENDEN";
      setDetail("EVE hört zu …");
      showState("listening");
    } catch (error) {
      pressActive = false;
      elements.ptt.classList.remove("pressed");
      releaseActivePointerCapture();
      stopTracks();
      showState("error");
      setDetail(`Mikrofon- oder Audiozugriff fehlgeschlagen: ${error.message}`);
    } finally {
      captureBusy = false;
      updatePTT();
    }
  }

  async function stopPTT(event) {
    event.preventDefault?.();
    pressActive = false;
    elements.ptt.classList.remove("pressed");
    if (stopRecordingPromise) return stopRecordingPromise;
    if (!recorder || recorder.state !== "recording") {
      elements.pttText.textContent = "GEDRÜCKT HALTEN ZUM SPRECHEN";
      updatePTT();
      return;
    }
    stopRecordingPromise = (async () => {
      window.clearTimeout(recordingTimer);
      elements.ptt.classList.remove("recording");
      elements.ptt.setAttribute("aria-label", "Gedrückt halten, um mit EVE zu sprechen");
      elements.pttText.textContent = "GEDRÜCKT HALTEN ZUM SPRECHEN";
      requestBusy = true;
      updatePTT();
      setReply("");
      renderArtifacts([]);
      renderSources([]);
      setDetail("EVE verarbeitet …");
      showState("thinking");
      const activeRecorder = recorder;
      const reasoning = liveReasoningState();
      try {
        const stopped = new Promise((resolve) => activeRecorder.addEventListener("stop", resolve, { once: true }));
        activeRecorder.stop();
        await stopped;
        stopTracks();
        const blob = new Blob(chunks, { type: activeRecorder.mimeType || "audio/webm" });
        if (!blob.size) throw new Error("Die Aufnahme war leer.");
        const resumeSuffix = explicitConversationResume ? "&resume_conversation=true" : "";
        const turnUrl = activeConversationId
          ? `/api/turn/stream?conversation_id=${encodeURIComponent(activeConversationId)}${resumeSuffix}`
          : "/api/turn/stream";
        const response = await fetchWithTimeout(turnUrl, {
          method: "POST",
          headers: { "Content-Type": blob.type, ...auth },
          body: blob,
        }, 210000);
        if (!response.ok) {
          const error = await readJsonResponse(response, "EVE-Sprachantwort");
          throw new Error(error.error || "Unbekannter Fehler");
        }
        if (!response.body) throw new Error("Der Browser unterstützt keinen Antwortstream.");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let data = null;
        let turnId = null;
        let answer = "";
        let assistantNode = null;
        let turnCancelled = false;
        let answerPaint = 0;
        const paintVoiceAnswer = () => {
          answerPaint = 0;
          if (assistantNode) {
            renderAssistantMarkdown(assistantNode.querySelector(".message-content"), answer);
          }
          setReply(answer);
        };
        while (true) {
          const { value, done } = await reader.read();
          buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
          const lines = buffer.split("\n");
          buffer = done ? "" : lines.pop();
          for (const line of lines) {
            if (!line.trim()) continue;
            const streamEvent = JSON.parse(line);
            if (streamEvent.type === "accepted") {
              turnId = streamEvent.turn_id;
              cancelledAudioTurns.delete(turnId);
              latestVisibleTurnId = turnId;
              window.localStorage.setItem("eve.activeBackendTurn", turnId);
              activeBackendTurnId = turnId;
              backendTurnCancellable = Boolean(streamEvent.cancellable);
              updateComposerActivity();
              if (streamEvent.conversation_id && streamEvent.conversation_id !== activeConversationId) {
                activeConversationId = streamEvent.conversation_id;
                await loadConversations(activeConversationId);
              }
              scheduleConversationRollover(null, true);
            } else if (streamEvent.type === "transcript") {
              ensureBackendUserMessage(turnId, streamEvent.content);
              setDetail(`DU // ${streamEvent.content}`);
            } else if (streamEvent.type === "status") {
              backendTurnCancellable = Boolean(streamEvent.cancellable && !streamEvent.cancel_requested);
              updateComposerActivity();
              if (streamEvent.status === "running") showState("thinking");
            } else if (streamEvent.type === "reasoning_delta") {
              appendLiveReasoning(reasoning, streamEvent.content);
            } else if (["preview_delta", "delta"].includes(streamEvent.type)) {
              finishLiveReasoning(reasoning);
              answer += streamEvent.content || "";
              if (!assistantNode) {
                assistantNode = appendChatMessage({ role: "assistant", content: "", created_at: new Date().toISOString() });
                assistantNode.classList.add("streaming");
                attachReasoningLink(reasoning, assistantNode);
              }
              if (!answerPaint) answerPaint = window.setTimeout(paintVoiceAnswer, 50);
            } else if (streamEvent.type === "preview_reset") {
              if (answerPaint) window.clearTimeout(answerPaint);
              answerPaint = 0;
              answer = "";
              assistantNode?.remove();
              assistantNode = null;
              setReply("");
            } else if (streamEvent.type === "preview_commit") {
              assistantNode?.classList.remove("preview");
            } else if (streamEvent.type === "audio" && streamEvent.audio_wav_base64) {
              queueReply(decodeAudio(streamEvent.audio_wav_base64), streamEvent.turn_id).catch((error) => {
                audioError("Textantwort bleibt sichtbar; Audio konnte nicht abgespielt werden", error);
              });
            } else if (streamEvent.type === "complete") {
              finishLiveReasoning(reasoning);
              data = streamEvent.result;
              window.localStorage.removeItem("eve.activeBackendTurn");
            } else if (streamEvent.type === "cancelled") {
              finishLiveReasoning(reasoning, "cancelled");
              turnCancelled = true;
              cancelTurnAudio(streamEvent.turn_id || turnId);
              backendTurnCancellable = false;
              assistantNode?.classList.add("cancelled");
              setDetail("Backend-Turn abgebrochen · cancelled");
            } else if (streamEvent.type === "error") {
              finishLiveReasoning(reasoning, "failed");
              throw streamFailure(streamEvent);
            }
          }
          if (done) break;
        }
        if (answerPaint) window.clearTimeout(answerPaint);
        paintVoiceAnswer();
        if (turnCancelled) {
          showState("idle");
          return;
        }
        if (!data) throw new Error("Der Sprach-Turn endete ohne Abschluss.");
        if (answer && answer !== data.answer) {
          throw new Error("Der Abschluss stimmt nicht mit dem veröffentlichten Antwortstream überein.");
        }
        if (!answer) answer = data.answer || "";
        latestVisibleTurnId = data.turn_id || latestVisibleTurnId;
        setDetail(`DU // ${data.transcript}`);
        setReply(answer);
        renderArtifacts(data.artifacts);
        renderSources(data.sources);
        activeConversationId = data.conversation_id || activeConversationId;
        await loadConversations(activeConversationId);
        showState("idle");
        followTurnCompletion(data).catch((error) => {
          audioError("Textantwort bleibt sichtbar; Nachbearbeitung fehlgeschlagen", error);
        });
      } catch (error) {
        finishLiveReasoning(reasoning, "failed");
        if (reconnectInterruptedTurn(error, activeBackendTurnId)) return;
        window.localStorage.removeItem("eve.activeBackendTurn");
        showState("error");
        await recoverStoredAnswer(activeBackendTurnId);
        showTurnFailure(error, activeBackendTurnId);
        setDetail(`Fehler: ${error.name === "AbortError" ? "Zeitüberschreitung" : error.message}`);
      } finally {
        activeBackendTurnId = null;
        backendTurnCancellable = false;
        elements.turnCancel.textContent = "Abbrechen";
        stopTracks();
        recorder = null;
        requestBusy = false;
        stopRecordingPromise = null;
        updatePTT();
        flushNotifications();
      }
    })();
    return stopRecordingPromise;
  }

  function releaseActivePointerCapture() {
    const pointerId = activePointerId;
    activePointerId = null;
    if (pointerId === null) return;
    try {
      if (elements.ptt.hasPointerCapture(pointerId)) elements.ptt.releasePointerCapture(pointerId);
    } catch (_) { /* capture may already have been released by the browser */ }
  }

  function finishPTT(event) {
    if (Number.isInteger(event.pointerId)) {
      if (activePointerId === null || event.pointerId !== activePointerId) return;
    }
    releaseActivePointerCapture();
    stopPTT(event);
  }

  elements.ptt.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
    if (activePointerId !== null) return;
    activePointerId = event.pointerId;
    try { elements.ptt.setPointerCapture(event.pointerId); } catch (_) { /* browser owns capture */ }
    startPTT(event);
  });
  elements.voiceMute.addEventListener("click", toggleVoiceMute);
  elements.ptt.addEventListener("pointerup", finishPTT);
  elements.ptt.addEventListener("pointercancel", finishPTT);
  // These are a fallback for engines that reject capture; with successful
  // capture the element handler clears activePointerId before bubbling here.
  window.addEventListener("pointerup", finishPTT);
  window.addEventListener("pointercancel", finishPTT);
  elements.ptt.addEventListener("lostpointercapture", (event) => {
    if (event.pointerId !== activePointerId) return;
    activePointerId = null;
    stopPTT(event);
  });
  elements.ptt.addEventListener("keydown", (event) => {
    if ((event.code === "Space" || event.code === "Enter") && !event.repeat) startPTT(event);
  });
  elements.ptt.addEventListener("keyup", (event) => {
    if (event.code === "Space" || event.code === "Enter") finishPTT(event);
  });

  function updateComposerViewport() {
    const height = window.visualViewport?.height || window.innerHeight;
    document.documentElement.style.setProperty("--visual-height", `${height}px`);
    resizeMessageInput();
  }

  window.visualViewport?.addEventListener("resize", updateComposerViewport);
  updateComposerViewport();

  let pointerX = 0;
  let pointerY = 0;
  window.addEventListener("pointermove", (event) => {
    if (!finePointerQuery.matches || reducedMotionQuery.matches) return;
    pointerX = event.clientX / window.innerWidth - .5;
    pointerY = event.clientY / window.innerHeight - .5;
    elements.mark.style.setProperty("--tilt-y", `${(pointerX * 3).toFixed(2)}deg`);
    elements.mark.style.setProperty("--tilt-x", `${(-pointerY * 3).toFixed(2)}deg`);
    elements.mark.style.setProperty("--drift-x", `${(pointerX * 8).toFixed(2)}px`);
    elements.mark.style.setProperty("--drift-y", `${(pointerY * 8).toFixed(2)}px`);
  }, { passive: true });
  document.documentElement.addEventListener("mouseleave", () => {
    pointerX = 0;
    pointerY = 0;
    for (const property of ["--tilt-x", "--tilt-y", "--drift-x", "--drift-y"]) {
      elements.mark.style.removeProperty(property);
    }
  });

  class LivingSignalCanvas {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d", { alpha: true });
      this.width = 1;
      this.height = 1;
      this.dpr = 1;
      this.core = { x: 0, y: 0, width: 1, height: 1 };
      this.nodes = [];
      this.edges = [];
      this.coreNodes = [];
      this.coreEdges = [];
      this.pulses = [];
      this.spawnCursor = 0;
      this.lastSpawn = 0;
      this.lastFrame = 0;
      this.frameInterval = 16.7;
      this.slowFrameScore = 0;
      this.transitionPulse = 0;
      this.animationFrame = 0;
      this.running = false;
      this.signalLevel = 0;
      this.voiceVisualLevel = 0;
      this.lastVoiceSignal = 0;
      this.lastSpeechRipple = 0;
      this.speechRipples = [];
      this.bandLevels = new Float32Array(56);
      this.frequencyData = null;
      this.timeData = null;
      this.resizeBucket = "";
      this.coreSyncUntil = 0;
      this.resize = this.resize.bind(this);
      this.frame = this.frame.bind(this);
      this.resize();
    }

    random(seed) {
      let value = seed >>> 0;
      return () => {
        value += 0x6D2B79F5;
        let output = value;
        output = Math.imul(output ^ (output >>> 15), output | 1);
        output ^= output + Math.imul(output ^ (output >>> 7), output | 61);
        return ((output ^ (output >>> 14)) >>> 0) / 4294967296;
      };
    }

    resize() {
      this.width = Math.max(1, window.innerWidth);
      this.height = Math.max(1, window.innerHeight);
      this.dpr = Math.min(window.devicePixelRatio || 1, 1.75);
      this.canvas.width = Math.round(this.width * this.dpr);
      this.canvas.height = Math.round(this.height * this.dpr);
      this.canvas.style.width = `${this.width}px`;
      this.canvas.style.height = `${this.height}px`;
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      this.updateCoreBounds();
      const bucket = `${Math.round(this.width / 80)}:${Math.round(this.height / 80)}`;
      if (bucket !== this.resizeBucket) {
        this.resizeBucket = bucket;
        this.buildAmbientGraph();
        this.buildCoreGraph();
      }
      this.requestDraw();
    }

    updateCoreBounds() {
      const rect = elements.coreScene.getBoundingClientRect();
      this.core = { x: rect.left, y: rect.top, width: rect.width, height: rect.height };
    }

    syncCoreBounds(duration = 520) {
      // Several layout updates can occur during one drawer transition. A
      // shorter follow-up sync must never truncate the window established by
      // the original movement, otherwise the canvas field stops before the
      // DOM-hosted logo reaches its final position.
      this.coreSyncUntil = Math.max(this.coreSyncUntil, performance.now() + duration);
      this.updateCoreBounds();
      this.requestDraw();
    }

    buildAmbientGraph() {
      const random = this.random((Math.round(this.width / 80) * 73856093) ^ (Math.round(this.height / 80) * 19349663));
      const count = Math.max(48, Math.min(150, Math.round((this.width * this.height) / 17000)));
      const minimum = Math.max(36, Math.min(this.width, this.height) * .047);
      this.nodes = [];
      let attempts = 0;
      while (this.nodes.length < count && attempts < count * 28) {
        attempts += 1;
        const candidate = {
          x: random() * this.width,
          y: random() * this.height,
          depth: random(),
          radius: .55 + random() * 1.35,
          phase: random() * Math.PI * 2,
        };
        const coreX = this.core.x + this.core.width / 2;
        const coreY = this.core.y + this.core.height / 2;
        const inQuietCore = Math.abs(candidate.x - coreX) < this.core.width * .62
          && Math.abs(candidate.y - coreY) < this.core.height * .62;
        if (inQuietCore && random() < .76) continue;
        if (this.nodes.some((node) => Math.hypot(node.x - candidate.x, node.y - candidate.y) < minimum * (.55 + candidate.depth * .45))) continue;
        this.nodes.push(candidate);
      }
      this.edges = [];
      this.nodes.forEach((node, index) => {
        const nearest = this.nodes
          .map((other, otherIndex) => ({ otherIndex, distance: Math.hypot(node.x - other.x, node.y - other.y) }))
          .filter((item) => item.otherIndex !== index)
          .sort((a, b) => a.distance - b.distance)
          .slice(0, node.depth > .66 ? 2 : 1);
        for (const item of nearest) {
          if (index < item.otherIndex && item.distance < Math.min(this.width, this.height) * .27) {
            this.edges.push({ a: index, b: item.otherIndex, phase: random() });
          }
        }
      });
    }

    buildCoreGraph() {
      const random = this.random(0xE7E2026);
      const count = window.innerWidth < 700 ? 54 : 92;
      this.coreNodes = [];
      let attempts = 0;
      while (this.coreNodes.length < count && attempts < count * 30) {
        attempts += 1;
        const x = random() * 2 - 1;
        const y = random() * 2 - 1;
        const organic = (x * x) / .98 + (y * y) / .82;
        if (organic > 1 || (Math.abs(x) < .09 && y < -.54)) continue;
        if (this.coreNodes.some((node) => Math.hypot(node.x - x, node.y - y) < .09)) continue;
        this.coreNodes.push({ x, y, phase: random() * Math.PI * 2, soma: random() < .18 });
      }
      this.coreEdges = [];
      this.coreNodes.forEach((node, index) => {
        const nearest = this.coreNodes
          .map((other, otherIndex) => ({ otherIndex, distance: Math.hypot(node.x - other.x, node.y - other.y) }))
          .filter((item) => item.otherIndex !== index)
          .sort((a, b) => a.distance - b.distance)
          .slice(0, node.soma ? 4 : 3);
        for (const item of nearest) {
          if (index < item.otherIndex && item.distance < .34) {
            this.coreEdges.push({ a: index, b: item.otherIndex, phase: random() });
          }
        }
      });
    }

    corePoint(node) {
      return {
        x: this.core.x + this.core.width * (.5 + node.x * .64),
        y: this.core.y + this.core.height * (.5 + node.y * .62),
      };
    }

    stateKind() {
      if (currentState.startsWith("tool:")) return "tool";
      if (currentState.startsWith("memory:")) return "memory";
      return currentState;
    }

    palette() {
      switch (this.stateKind()) {
        case "listening": return ["#5fffd0", "#35e8ff"];
        case "thinking": return ["#9d63ff", "#f052ff"];
        case "speaking": return ["#e9fdff", "#35e8ff"];
        case "tool": return ["#5fffd0", "#9d63ff"];
        case "memory": return ["#ffd36b", "#ff9f68"];
        case "error": return ["#ff466a", "#ffb86a"];
        case "offline": return ["#54727f", "#344b59"];
        default: return ["#35e8ff", "#9d63ff"];
      }
    }

    analyser() {
      if (currentState === "listening" && micAnalyser) return micAnalyser;
      if (currentState === "speaking" && playingAudio && outputAnalyser) return outputAnalyser;
      return null;
    }

    updateAudioSignal() {
      const analyser = this.analyser();
      let target = 0;
      if (analyser) {
        if (!this.frequencyData || this.frequencyData.length !== analyser.frequencyBinCount) {
          this.frequencyData = new Uint8Array(analyser.frequencyBinCount);
          this.timeData = new Uint8Array(analyser.fftSize);
        }
        analyser.getByteFrequencyData(this.frequencyData);
        analyser.getByteTimeDomainData(this.timeData);
        let energy = 0;
        for (const sample of this.timeData) {
          const normalized = (sample - 128) / 128;
          energy += normalized * normalized;
        }
        target = Math.min(1, Math.sqrt(energy / this.timeData.length) * 4.2);
        for (let index = 0; index < this.bandLevels.length; index += 1) {
          const position = index / (this.bandLevels.length - 1);
          const mirrored = position <= .5 ? position * 2 : (1 - position) * 2;
          const bin = Math.min(this.frequencyData.length - 1, Math.floor(2 + Math.pow(mirrored, 1.7) * (this.frequencyData.length - 7)));
          const value = Math.min(1, this.frequencyData[bin] / 190);
          const rate = value > this.bandLevels[index] ? .46 : .13;
          this.bandLevels[index] += (value - this.bandLevels[index]) * rate;
        }
      } else {
        for (let index = 0; index < this.bandLevels.length; index += 1) this.bandLevels[index] *= .86;
      }
      const rate = target > this.signalLevel ? .38 : .075;
      this.signalLevel += (target - this.signalLevel) * rate;
      const voiceTarget = this.stateKind() === "speaking" ? this.signalLevel : 0;
      const voiceRate = voiceTarget > this.voiceVisualLevel ? .1 : .045;
      this.voiceVisualLevel += (voiceTarget - this.voiceVisualLevel) * voiceRate;
      const now = performance.now();
      const signalRise = this.signalLevel - this.lastVoiceSignal;
      if (this.stateKind() === "speaking" && this.signalLevel > .075 && signalRise > .018 && now - this.lastSpeechRipple > 320) {
        this.speechRipples.push({ startedAt: now, strength: Math.min(1, .38 + this.signalLevel * 1.7) });
        this.lastSpeechRipple = now;
      }
      this.lastVoiceSignal = this.stateKind() === "speaking" ? this.signalLevel : 0;
      if (this.stateKind() !== "speaking") this.speechRipples.length = 0;
      document.documentElement.style.setProperty("--signal", this.signalLevel.toFixed(3));
      document.documentElement.style.setProperty("--voice-level", Math.min(1, this.voiceVisualLevel * 2.2).toFixed(3));
      for (let index = 0; index < spectrumBars.length; index += 1) {
        const level = this.bandLevels[index];
        spectrumBars[index].style.setProperty("--level", level.toFixed(3));
        spectrumBars[index].style.setProperty("--bar", `${(4 + level * 23).toFixed(1)}px`);
      }
    }

    intensity() {
      switch (this.stateKind()) {
        case "thinking": return 1;
        case "tool": return .92;
        case "speaking": return .5 + this.voiceVisualLevel * .18;
        case "listening": return .58 + this.signalLevel * .35;
        case "memory": return .68;
        case "error": return .38;
        case "offline": return .04;
        default: return .13;
      }
    }

    spawnPulse(time) {
      const kind = this.stateKind();
      const cadence = {
        idle: 4300,
        listening: 420,
        thinking: 72,
        speaking: 260,
        tool: 145,
        memory: 310,
        error: 900,
        offline: 12000,
      }[kind] || 1200;
      if (time - this.lastSpawn < cadence || !this.coreEdges.length) return;
      this.lastSpawn = time;
      const count = kind === "thinking" ? 4 : kind === "tool" ? 2 : 1;
      for (let index = 0; index < count; index += 1) {
        const edgeIndex = (this.spawnCursor * 17 + index * 23) % this.coreEdges.length;
        this.spawnCursor += 1;
        this.pulses.push({
          edgeIndex,
          progress: kind === "listening" ? 1 : 0,
          direction: kind === "listening" ? -1 : 1,
          speed: .006 + ((edgeIndex % 7) / 7) * .005 + (kind === "thinking" ? .01 : 0),
          life: 1,
        });
      }
      if (this.pulses.length > 90) this.pulses.splice(0, this.pulses.length - 90);
    }

    drawAmbient(time, first, second) {
      const ctx = this.ctx;
      const kind = this.stateKind();
      const active = !["idle", "offline"].includes(kind);
      const toolActive = kind === "tool";
      for (const edge of this.edges) {
        const a = this.nodes[edge.a];
        const b = this.nodes[edge.b];
        const depth = (a.depth + b.depth) * .5;
        const parallaxX = pointerX * (3 + depth * 8);
        const parallaxY = pointerY * (3 + depth * 8);
        ctx.globalAlpha = kind === "offline" ? .008 : toolActive ? .05 + depth * .07 : .014 + depth * .025 + (active ? .014 : 0);
        ctx.strokeStyle = first;
        ctx.lineWidth = .45 + depth * .25;
        ctx.beginPath();
        ctx.moveTo(a.x + parallaxX, a.y + parallaxY);
        ctx.lineTo(b.x + parallaxX, b.y + parallaxY);
        ctx.stroke();
      }
      for (const node of this.nodes) {
        const parallaxX = pointerX * (3 + node.depth * 8);
        const parallaxY = pointerY * (3 + node.depth * 8);
        const pulse = reducedMotionQuery.matches ? .4 : Math.sin(time * .00055 + node.phase) * .5 + .5;
        ctx.globalAlpha = kind === "offline" ? .02 : toolActive ? .14 + node.depth * .2 + pulse * .12 : .055 + node.depth * .1 + pulse * .025;
        ctx.fillStyle = node.depth > .55 ? second : first;
        ctx.beginPath();
        ctx.arc(node.x + parallaxX, node.y + parallaxY, node.radius + node.depth * .7, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    drawToolField(time, first, second) {
      if (this.stateKind() !== "tool" || !this.edges.length) return;
      const ctx = this.ctx;
      const originX = this.core.x + this.core.width * .5;
      const originY = this.core.y + this.core.height * .5;
      const maximumReach = Math.hypot(this.width, this.height);
      const waveRadius = reducedMotionQuery.matches ? maximumReach * .58 : (time * .00016 % 1) * maximumReach;
      const waveWidth = Math.max(90, Math.min(this.width, this.height) * .16);

      for (let echo = 0; echo < 3; echo += 1) {
        const echoRadius = reducedMotionQuery.matches
          ? maximumReach * (.25 + echo * .22)
          : ((time * .00013 + echo / 3) % 1) * maximumReach;
        ctx.globalAlpha = .12 * (1 - echo * .18);
        ctx.strokeStyle = echo % 2 ? second : first;
        ctx.lineWidth = .7;
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.arc(originX, originY, echoRadius, 0, Math.PI * 2);
        ctx.stroke();
      }

      const routeCount = Math.min(10, this.nodes.length);
      for (let route = 0; route < routeCount; route += 1) {
        const node = this.nodes[Math.floor(route * this.nodes.length / routeCount)];
        const bendX = (originX + node.x) * .5 + Math.sin(route * 2.17) * this.width * .055;
        const bendY = (originY + node.y) * .5 + Math.cos(route * 1.73) * this.height * .065;
        ctx.globalAlpha = .1 + (route % 4) * .025;
        ctx.strokeStyle = route % 3 ? first : second;
        ctx.lineWidth = .65;
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.moveTo(originX, originY);
        ctx.quadraticCurveTo(bendX, bendY, node.x, node.y);
        ctx.stroke();

        if (!reducedMotionQuery.matches) {
          const head = (time * (.00038 + (route % 4) * .000045) + route / routeCount) % 1;
          for (let trail = 0; trail < 3; trail += 1) {
            const rawProgress = head - trail * .045;
            if (rawProgress < 0) continue;
            const progress = .16 + rawProgress * .84;
            const inverse = 1 - progress;
            const packetX = inverse * inverse * originX + 2 * inverse * progress * bendX + progress * progress * node.x;
            const packetY = inverse * inverse * originY + 2 * inverse * progress * bendY + progress * progress * node.y;
            ctx.globalAlpha = .82 - trail * .25;
            ctx.fillStyle = trail === 0 ? "#ffffff" : route % 3 ? first : second;
            ctx.shadowColor = route % 3 ? first : second;
            ctx.shadowBlur = 19 - trail * 4;
            ctx.beginPath();
            ctx.arc(packetX, packetY, 2.15 - trail * .42, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }

      this.edges.forEach((edge, index) => {
        const a = this.nodes[edge.a];
        const b = this.nodes[edge.b];
        const midX = (a.x + b.x) * .5;
        const midY = (a.y + b.y) * .5;
        const distance = Math.hypot(midX - originX, midY - originY);
        const wave = Math.max(0, 1 - Math.abs(distance - waveRadius) / waveWidth);
        if (wave > 0) {
          ctx.globalAlpha = wave * .34;
          ctx.strokeStyle = index % 3 ? first : second;
          ctx.lineWidth = .7 + wave * 1.15;
          ctx.shadowBlur = 0;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }

        if (wave > .18) {
          const node = this.nodes[wave > .55 ? edge.b : edge.a];
          ctx.globalAlpha = .22 + wave * .65;
          ctx.fillStyle = wave > .62 ? "#ffffff" : second;
          ctx.shadowColor = first;
          ctx.shadowBlur = 8 + wave * 18;
          ctx.beginPath();
          ctx.arc(node.x, node.y, 1.2 + wave * 2.1, 0, Math.PI * 2);
          ctx.fill();
        }

        if (reducedMotionQuery.matches || index % 3 !== 0) return;
        const progress = (time * (.00022 + (index % 5) * .000018) + edge.phase) % 1;
        const x = a.x + (b.x - a.x) * progress;
        const y = a.y + (b.y - a.y) * progress;
        const envelope = Math.sin(progress * Math.PI);
        ctx.globalAlpha = .3 + envelope * .58;
        ctx.fillStyle = index % 2 ? first : second;
        ctx.shadowColor = ctx.fillStyle;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(x, y, 1.1 + envelope * 1.25, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.shadowBlur = 0;
    }

    drawCoreNetwork(time, first, second) {
      const ctx = this.ctx;
      const kind = this.stateKind();
      const power = this.intensity();
      for (const edge of this.coreEdges) {
        const a = this.corePoint(this.coreNodes[edge.a]);
        const b = this.corePoint(this.coreNodes[edge.b]);
        const waveSpeed = kind === "thinking" ? .0062 : .0038;
        const wave = reducedMotionQuery.matches ? .2 : Math.max(0, Math.sin(time * waveSpeed + edge.phase * 17));
        const thoughtBoost = kind === "thinking" ? wave * .28 : kind === "tool" ? wave * .18 : 0;
        ctx.globalAlpha = .018 + power * .05 + thoughtBoost;
        ctx.strokeStyle = wave > .88 ? second : first;
        ctx.lineWidth = wave > .88 ? (kind === "thinking" ? 1.35 : 1.05) : .55;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      for (const node of this.coreNodes) {
        const point = this.corePoint(node);
        const firing = reducedMotionQuery.matches ? .22 : Math.max(0, Math.sin(time * (node.soma ? .0048 : .0028) + node.phase));
        ctx.globalAlpha = .025 + power * (node.soma ? .22 : .1) + firing * (kind === "thinking" ? .34 : .08);
        ctx.fillStyle = firing > .88 ? "#ffffff" : second;
        ctx.shadowColor = first;
        ctx.shadowBlur = node.soma && firing > .72 ? (kind === "thinking" ? 20 : 14) : 0;
        ctx.beginPath();
        ctx.arc(point.x, point.y, (node.soma ? 2.2 : .9) + firing * 1.1, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;
    }

    drawPulses(delta, first, second) {
      const ctx = this.ctx;
      const next = [];
      for (const pulse of this.pulses) {
        pulse.progress += pulse.speed * delta * pulse.direction;
        pulse.life -= .00045 * delta;
        if (pulse.progress < 0 || pulse.progress > 1 || pulse.life <= 0) continue;
        const edge = this.coreEdges[pulse.edgeIndex];
        if (!edge) continue;
        const a = this.corePoint(this.coreNodes[edge.a]);
        const b = this.corePoint(this.coreNodes[edge.b]);
        const x = a.x + (b.x - a.x) * pulse.progress;
        const y = a.y + (b.y - a.y) * pulse.progress;
        ctx.globalAlpha = Math.min(1, pulse.life) * .9;
        ctx.fillStyle = second;
        ctx.shadowColor = first;
        ctx.shadowBlur = 13;
        ctx.beginPath();
        ctx.arc(x, y, 1.35 + this.intensity() * 1.35, 0, Math.PI * 2);
        ctx.fill();
        next.push(pulse);
      }
      ctx.shadowBlur = 0;
      this.pulses = next;
    }

    drawListening(time, first) {
      if (this.stateKind() !== "listening") return;
      const ctx = this.ctx;
      const cx = this.core.x + this.core.width * .5;
      const cy = this.core.y + this.core.height * .5;
      const radius = Math.max(this.core.width, this.core.height) * .68;
      for (let index = 0; index < 12; index += 1) {
        const phase = (time * .00023 * (1 + this.signalLevel) + index / 12) % 1;
        const angle = index * 2.39996;
        const distance = radius * (1 - phase * .76);
        const x = cx + Math.cos(angle) * distance;
        const y = cy + Math.sin(angle) * distance * .83;
        ctx.globalAlpha = .08 + phase * .52;
        ctx.fillStyle = first;
        ctx.shadowColor = first;
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(x, y, 1 + phase * 1.5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;
    }

    drawFutureConstruct(time, first, second) {
      if (!futureVisual) return;
      const ctx = this.ctx;
      const kind = this.stateKind();
      const cx = this.core.x + this.core.width * .5;
      const cy = this.core.y + this.core.height * .49;
      const rx = this.core.width * .72;
      const ry = this.core.height * .65;
      const active = !["idle", "offline"].includes(kind);
      const thinking = kind === "thinking" || kind === "tool";
      const motion = reducedMotionQuery.matches ? 0 : time;

      // Two counter-phased signal strands make the surrounding field feel
      // biological without turning the logo itself into a wobbly blob.
      for (const side of [-1, 1]) {
        const anchorX = cx + side * this.core.width * .59;
        ctx.beginPath();
        for (let step = 0; step <= 30; step += 1) {
          const phase = step / 30;
          const y = cy - ry * .72 + phase * ry * 1.44;
          const amplitude = this.core.width * (.035 + (thinking ? .018 : 0));
          const x = anchorX + Math.sin(phase * Math.PI * 5 + motion * .00125 + side) * amplitude;
          if (step === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.globalAlpha = kind === "offline" ? .025 : active ? .18 : .075;
        ctx.strokeStyle = side < 0 ? second : first;
        ctx.lineWidth = .7;
        ctx.shadowColor = side < 0 ? second : first;
        ctx.shadowBlur = thinking ? 12 : 5;
        ctx.stroke();
      }

      // Perspective arcs suggest a volumetric neural chamber rather than a
      // flat ring. Gaps keep the construct technical and non-decorative.
      for (let layer = 0; layer < 4; layer += 1) {
        const phase = motion * (.00012 + layer * .000025) * (layer % 2 ? -1 : 1);
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(phase + layer * .43);
        ctx.scale(1, .38 + layer * .055);
        ctx.beginPath();
        ctx.arc(0, 0, rx * (.72 + layer * .095), -.18 * Math.PI, .64 * Math.PI);
        ctx.globalAlpha = kind === "offline" ? .018 : .045 + this.intensity() * .055;
        ctx.strokeStyle = layer % 2 ? second : first;
        ctx.lineWidth = .65 + (thinking ? .35 : 0);
        ctx.stroke();
        ctx.restore();
      }

      if (thinking) {
        const burstCount = reducedMotionQuery.matches ? 5 : 14;
        for (let index = 0; index < burstCount; index += 1) {
          const angle = index * 2.39996 + motion * .00031;
          const oscillation = .76 + Math.sin(motion * .0024 + index * 1.7) * .11;
          const x = cx + Math.cos(angle) * rx * oscillation;
          const y = cy + Math.sin(angle) * ry * oscillation;
          const inwardX = cx + Math.cos(angle) * this.core.width * .36;
          const inwardY = cy + Math.sin(angle) * this.core.height * .34;
          ctx.globalAlpha = .08 + (index % 3) * .035;
          ctx.strokeStyle = index % 2 ? second : first;
          ctx.lineWidth = .55;
          ctx.beginPath();
          ctx.moveTo(inwardX, inwardY);
          ctx.quadraticCurveTo((x + inwardX) / 2 + Math.sin(angle * 3) * 20, (y + inwardY) / 2, x, y);
          ctx.stroke();
          ctx.globalAlpha = .36 + (index % 4) * .09;
          ctx.fillStyle = index % 2 ? second : "#ffffff";
          ctx.shadowColor = first;
          ctx.shadowBlur = 12;
          ctx.beginPath();
          ctx.arc(x, y, 1.1 + (index % 3) * .45, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.shadowBlur = 0;
    }

    drawFutureThoughtTraffic(time, first, second) {
      if (!futureVisual || !["thinking", "tool"].includes(this.stateKind()) || !this.coreEdges.length) return;
      const ctx = this.ctx;
      const packetCount = Math.min(this.coreEdges.length, reducedMotionQuery.matches ? 7 : 34);
      const epoch = Math.floor(time / 920);
      for (let index = 0; index < packetCount; index += 1) {
        const edgeIndex = (index * 19 + epoch * 7) % this.coreEdges.length;
        const edge = this.coreEdges[edgeIndex];
        const fromNode = this.coreNodes[(index + epoch) % 2 ? edge.a : edge.b];
        const toNode = fromNode === this.coreNodes[edge.a] ? this.coreNodes[edge.b] : this.coreNodes[edge.a];
        const from = this.corePoint(fromNode);
        const to = this.corePoint(toNode);
        const speed = .00062 + (index % 7) * .000055;
        const progress = (time * speed + edge.phase + index * .113) % 1;
        const packetColor = index % 3 === 0 ? "#ffffff" : index % 2 ? second : first;

        // The complete carrier flashes briefly before the packet traverses it,
        // making source and destination visibly related instead of producing
        // unrelated decorative sparkles.
        const carrier = ctx.createLinearGradient(from.x, from.y, to.x, to.y);
        carrier.addColorStop(0, "transparent");
        carrier.addColorStop(Math.max(0, progress - .16), "transparent");
        carrier.addColorStop(progress, packetColor);
        carrier.addColorStop(Math.min(1, progress + .08), "transparent");
        ctx.globalAlpha = .2 + (index % 4) * .045;
        ctx.strokeStyle = carrier;
        ctx.lineWidth = index % 5 === 0 ? 1.7 : .9;
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();

        for (let tail = 5; tail >= 0; tail -= 1) {
          const position = Math.max(0, progress - tail * .027);
          const x = from.x + (to.x - from.x) * position;
          const y = from.y + (to.y - from.y) * position;
          const strength = 1 - tail / 6;
          ctx.globalAlpha = strength * (.22 + this.intensity() * .62);
          ctx.fillStyle = packetColor;
          ctx.shadowColor = index % 2 ? second : first;
          ctx.shadowBlur = 5 + strength * 17;
          ctx.beginPath();
          ctx.arc(x, y, .55 + strength * 1.65, 0, Math.PI * 2);
          ctx.fill();
        }

        if (progress > .88) {
          const arrival = Math.sin((progress - .88) / .12 * Math.PI);
          ctx.globalAlpha = arrival * .8;
          ctx.strokeStyle = packetColor;
          ctx.lineWidth = 1;
          ctx.shadowColor = packetColor;
          ctx.shadowBlur = 16;
          ctx.beginPath();
          ctx.arc(to.x, to.y, 3 + arrival * 8, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
      ctx.shadowBlur = 0;
    }

    drawFutureSpeech(time, first, second) {
      if (!futureVisual || this.stateKind() !== "speaking") return;
      const ctx = this.ctx;
      const origins = [
        { x: .72, y: .275, band: 6 },
        { x: .69, y: .505, band: 22 },
        { x: .72, y: .735, band: 39 },
      ];
      const maximumReach = Math.min(this.width * .28, this.core.width * .82);
      origins.forEach((origin, originIndex) => {
        const startX = this.core.x + this.core.width * origin.x;
        const startY = this.core.y + this.core.height * origin.y;
        const localLevel = Math.max(this.signalLevel, this.bandLevels[origin.band] || 0);
        const reach = maximumReach * (.7 + localLevel * .3);
        const segments = 44;
        ctx.beginPath();
        for (let segment = 0; segment <= segments; segment += 1) {
          const phase = segment / segments;
          const envelope = Math.sin(phase * Math.PI);
          const bandIndex = Math.min(this.bandLevels.length - 1, origin.band + Math.floor(phase * 12));
          const band = Math.max(localLevel * .45, this.bandLevels[bandIndex] || 0);
          const carrier = Math.sin(time * .012 - phase * 25 + originIndex * 2.1);
          const detail = Math.sin(time * .021 - phase * 47 + originIndex) * .35;
          const x = startX + phase * reach;
          const y = startY + (carrier + detail) * envelope * (3 + band * 17);
          if (segment === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        const gradient = ctx.createLinearGradient(startX, startY, startX + reach, startY);
        gradient.addColorStop(0, second);
        gradient.addColorStop(.28, "#ffffff");
        gradient.addColorStop(.72, first);
        gradient.addColorStop(1, "transparent");
        ctx.globalAlpha = .25 + localLevel * .7;
        ctx.strokeStyle = gradient;
        ctx.lineWidth = 1.15 + localLevel * 2.3;
        ctx.shadowColor = first;
        ctx.shadowBlur = 8 + localLevel * 19;
        ctx.stroke();

        const packetPhase = (time * (.00048 + originIndex * .000035) + originIndex * .31) % 1;
        const packetX = startX + reach * packetPhase;
        const packetY = startY + Math.sin(time * .012 - packetPhase * 25 + originIndex * 2.1)
          * Math.sin(packetPhase * Math.PI) * (3 + localLevel * 17);
        ctx.globalAlpha = .5 + localLevel * .5;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(packetX, packetY, 1.4 + localLevel * 2.2, 0, Math.PI * 2);
        ctx.fill();
      });

      const waveOriginX = this.core.x + this.core.width * .72;
      const waveOriginY = this.core.y + this.core.height * .505;
      for (let wave = 0; wave < 4; wave += 1) {
        const phase = (time * .00042 + wave / 4) % 1;
        ctx.globalAlpha = (1 - phase) * (.08 + this.signalLevel * .28);
        ctx.strokeStyle = wave % 2 ? second : first;
        ctx.lineWidth = .6 + this.signalLevel * 1.1;
        ctx.beginPath();
        ctx.ellipse(waveOriginX, waveOriginY, 10 + phase * maximumReach, 18 + phase * this.core.height * .34, 0, -.46 * Math.PI, .46 * Math.PI);
        ctx.stroke();
      }
      ctx.shadowBlur = 0;
    }

    drawSpeakingPresence(time, first, second) {
      if (this.stateKind() !== "speaking") return;
      const ctx = this.ctx;
      const centerX = this.core.x + this.core.width * .5;
      const centerY = this.core.y + this.core.height * .5;
      const level = this.voiceVisualLevel;
      const breath = reducedMotionQuery.matches ? .5 : Math.sin(time * .00125) * .5 + .5;
      const radiusX = this.core.width * (.69 + breath * .008 + level * .018);
      const radiusY = this.core.height * (.72 + breath * .008 + level * .018);
      ctx.globalAlpha = .055 + level * .12;
      ctx.strokeStyle = level > .35 ? first : second;
      ctx.lineWidth = .55 + level * .55;
      ctx.shadowColor = first;
      ctx.shadowBlur = level > .4 ? 5 : 0;
      ctx.beginPath();
      ctx.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
      ctx.stroke();

      const activeRipples = [];
      for (const ripple of this.speechRipples) {
        const progress = (time - ripple.startedAt) / 1050;
        if (progress < 0 || progress >= 1) continue;
        const envelope = Math.sin(progress * Math.PI);
        const rippleX = this.core.width * (.58 + progress * .38);
        const rippleY = this.core.height * (.61 + progress * .32);
        ctx.globalAlpha = envelope * ripple.strength * .3;
        ctx.strokeStyle = progress < .42 ? "#ffffff" : progress < .72 ? first : second;
        ctx.lineWidth = 1.05 - progress * .45;
        ctx.shadowColor = first;
        ctx.shadowBlur = envelope * ripple.strength * 9;
        ctx.beginPath();
        ctx.ellipse(centerX, centerY, rippleX, rippleY, 0, 0, Math.PI * 2);
        ctx.stroke();
        activeRipples.push(ripple);
      }
      this.speechRipples = activeRipples;
      ctx.shadowBlur = 0;
    }

    drawTransition(first, second) {
      if (this.transitionPulse <= .002) return;
      const ctx = this.ctx;
      const progress = 1 - this.transitionPulse;
      const cx = this.core.x + this.core.width * .43;
      const cy = this.core.y + this.core.height * .48;
      const radius = 12 + progress * this.core.width * .72;
      ctx.globalAlpha = this.transitionPulse * .52;
      ctx.strokeStyle = progress < .35 ? "#ffffff" : second;
      ctx.shadowColor = first;
      ctx.shadowBlur = 22;
      ctx.lineWidth = 1.1 + this.transitionPulse * 1.4;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
      this.transitionPulse *= .87;
    }

    requestDraw() {
      if (!this.running && !document.hidden) {
        this.running = true;
        this.animationFrame = requestAnimationFrame(this.frame);
      }
    }

    stop() {
      this.running = false;
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = 0;
    }

    frame(time) {
      if (!this.running) return;
      const baseInterval = {
        idle: 50,
        offline: 250,
        thinking: 22.2,
        listening: 33.3,
        speaking: 33.3,
        tool: 33.3,
        memory: 40,
        error: 50,
      }[this.stateKind()] || 33.3;
      this.frameInterval = reducedMotionQuery.matches
        ? 250
        : this.slowFrameScore > 45 ? Math.max(33.3, baseInterval) : baseInterval;
      const elapsed = time - this.lastFrame;
      if (elapsed < this.frameInterval) {
        this.animationFrame = requestAnimationFrame(this.frame);
        return;
      }
      const delta = Math.min(50, this.lastFrame ? elapsed : 16.7);
      this.lastFrame = time;
      if (delta > 27) this.slowFrameScore += 1;
      else this.slowFrameScore = Math.max(0, this.slowFrameScore - .08);

      if (time <= this.coreSyncUntil) this.updateCoreBounds();

      this.updateAudioSignal();
      this.spawnPulse(time);
      const [first, second] = this.palette();
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.width, this.height);
      this.drawAmbient(time, first, second);
      this.drawToolField(time, first, second);
      this.drawCoreNetwork(time, first, second);
      this.drawPulses(delta, first, second);
      this.drawListening(time, first);
      this.drawSpeakingPresence(time, first, second);
      this.drawTransition(first, second);
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
      this.animationFrame = requestAnimationFrame(this.frame);
    }
  }

  const canvasEngine = new LivingSignalCanvas(elements.canvas);
  canvasEngine.requestDraw();

  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      canvasEngine.resize();
      updateComposerViewport();
    }, 90);
  });
  reducedMotionQuery.addEventListener?.("change", () => {
    canvasEngine.frameInterval = reducedMotionQuery.matches ? 250 : 16.7;
    canvasEngine.requestDraw();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (recorder?.state === "recording") stopPTT(new Event("hidden"));
      canvasEngine.stop();
      if (!memoryCloudRenderer?.xrSession) { memoryCloudRenderer?.setVisible(false); stopMemoryCloudLive(); memoryWorkingLayer?.stop(); }
      avatarCloudRenderer?.setVisible(false);
    } else {
      canvasEngine.lastFrame = 0;
      canvasEngine.requestDraw();
      tick();
      if (window.localStorage.getItem("eve.activeBackendTurn")) scheduleBackendReconnect(0);
      else if (!requestBusy) loadConversations(activeConversationId).catch(() => {});
      refreshWorkTasksIfVisible();
      memoryCloudRenderer?.setVisible(brainwatchOpen && brainwatchMode === "memory" && memoryExplorerSubview === "cloud");
      syncAvatarCloudVisibility();
      syncMemoryCloudLive();
    }
  });
  window.addEventListener("online", () => scheduleBackendReconnect(0));
  window.addEventListener("pageshow", () => scheduleBackendReconnect(0));
  window.addEventListener("pagehide", () => {
    disposeMemoryCloud();
    disposeAvatarMemoryCloud();
  });

  updatePTT();
  updateVoiceMute();
  setChatOpen(chatOpen);
  if (restoreBrainwatchMode !== "information") setBrainwatchMode(restoreBrainwatchMode, {load: false});
  if (restoreBrainwatchOpen) setBrainwatchOpen(true);
  setPanelView(panelView).catch((error) => setDetail(error.message));
  setAvatarMode(avatarMode, false);
  loadConversations()
    .then(() => synchronizeConversationLifecycle())
    .then(() => resumeBackendTurn())
    .catch((error) => setDetail(error.message));
  window.setInterval(refreshWorkTasksIfVisible, 2000);
  stateLoop();
  presentationLoop();
  checkNotifications();
})();
