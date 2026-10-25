/* Explanations of recorded learning outcomes; never infer an unreported cause. */
(() => {
  "use strict";
  const errors = {
    result_evidence_pointer_not_found: ["Belegstelle nicht gefunden", "EVE hat eine bestimmte Stelle im Werkzeugergebnis als Beleg angegeben. Diese Stelle existiert dort nicht. Deshalb wurde der Lernvorschlag nicht übernommen. Das beweist nicht, dass die damalige Antwort falsch war. Beim erneuten Versuch muss EVE eine vorhandene Belegstelle auswählen."],
    result_evidence_value_mismatch: ["Belegwert stimmt nicht überein", "Die angegebene Belegstelle existiert, enthält aber einen anderen Wert als im Lernvorschlag behauptet. Der Vorschlag wurde deshalb nicht übernommen. EVE muss den tatsächlichen Quellenwert verwenden oder ihren Vorschlag korrigieren."],
    result_evidence_invalid_pointer: ["Ungültiger Quellenpfad", "Der angegebene Datenpfad ist formal ungültig. Die Prüfung konnte damit keine Belegstelle lesen. Das ist ein Fehler beim Verweisen auf die Quelle, noch kein Urteil über die Aussage selbst."],
    result_evidence_missing_pointer: ["Belegstelle fehlt", "EVE hat einen Quellenwert angegeben, aber nicht die genaue Stelle im Werkzeugergebnis. Ohne diese Zuordnung lässt sich der Nachweis nicht prüfen. Der nächste Vorschlag muss den passenden Datenpfad ergänzen."],
    result_evidence_missing_value: ["Belegwert fehlt", "Die Belegstelle ist angegeben, der dort erwartete Quellenwert fehlt jedoch. Dadurch kann die Prüfung Quelle und Behauptung nicht vergleichen. EVE muss den tatsächlich gelesenen Wert mit angeben."],
    result_evidence_requires_tool_source: ["Falsche Quellenart", "Der Vorschlag behandelt eine Nutzernachricht wie ein strukturiertes Werkzeugergebnis. Für diese Quellenart ist der angegebene Beleg nicht zulässig. EVE muss die richtige Quellenart verwenden; die Aussage wurde damit nicht als falsch bewertet."],
    invented_message_reference: ["Nachricht als Beleg nicht verfügbar", "Die angegebene Nachrichten-ID gehört nicht zu den freigegebenen Nachrichten dieses Lern-Turns. Deshalb kann sie diesen Vorschlag nicht belegen. EVE muss einen tatsächlich verfügbaren Quellverweis verwenden."],
    invented_tool_reference: ["Werkzeugquelle nicht verfügbar", "Die angegebene Werkzeug-ID ist in diesem Lern-Turn nicht als Quelle vorhanden. Der Vorschlag kann deshalb nicht anhand dieses Verweises geprüft werden. Das ist kein Beweis, dass die inhaltliche Aussage falsch ist."],
    provider_evidence_not_property_specific: ["Beleg ist zu ungenau", "Der Vorschlag nennt keine ausreichend konkrete Eigenschaft mit zugehörigem Quellenverweis. Eine allgemeine Quelle reicht für diese Übernahme nicht. EVE muss den konkreten Zusammenhang nachweisen."],
    user_instruction_not_grounded_verbatim: ["Nutzeranweisung nicht wörtlich belegt", "Eine dauerhafte Nutzeranweisung soll anhand des Originalwortlauts belegt werden. Der Vorschlag stimmt damit nicht ausreichend überein. Eine umformulierte Vermutung darf nicht als deine ausdrückliche Anweisung gespeichert werden."],
    learning_navigation_stalled: ["Abrufe ohne Fortschritt beendet", "Der Lernversuch hat mehrfach kein neues Material erschlossen, etwa durch wiederholte Abrufe oder erfolglose Datenpfade. Die Verarbeitung wurde begrenzt beendet, damit weitere Einträge drankommen. Das Originalmaterial bleibt für einen erneuten Versuch erhalten."],
    learning_model_round_budget: ["Grenze für Modellrunden erreicht", "Dieser Versuch hat die erlaubte Anzahl an Modellrunden ausgeschöpft, ohne die Lernentscheidung abzuschließen. Der Eintrag wurde zur weiteren Prüfung zurückgestellt. Das Material ist erhalten; die Meldung bewertet nicht die Richtigkeit einer Aussage."],
    learning_tool_call_budget: ["Grenze für Werkzeugaufrufe erreicht", "Dieser Versuch hat die erlaubte Anzahl an Werkzeugaufrufen ausgeschöpft. Er wurde beendet, damit er die Warteschlange nicht dauerhaft blockiert. Der Eintrag kann nach Prüfung erneut eingereiht werden."],
    LearningProgressError: ["Lernversuch ohne ausreichenden Fortschritt", "Eine Grenze für Navigation oder Verarbeitung wurde erreicht. EVE hat diesen Versuch beendet und die Diagnose gespeichert. Das Lernmaterial bleibt erhalten. Die technischen Details nennen die genaue erreichte Grenze."],
    LocalLLMOutputLimitError: ["Modellantwort abgeschnitten", "Das Modell hat sein Ausgabelimit erreicht, bevor eine vollständige Antwort vorlag. Der unvollständige Vorschlag konnte nicht übernommen werden. Das ist eine technische Begrenzung, kein Urteil über die Quelle."],
    LocalLLMContextLimitError: ["Modellkontext reicht nicht aus", "Das Lernmaterial hat den verfügbaren Modellkontext überschritten. Normalerweise wird es über das Kurzzeitgedächtnis portionsweise gelesen. Wenn der Versuch trotzdem hier endet, muss der genaue technische Ablauf geprüft werden."],
    WorkingContextBudgetError: ["Arbeitskontext passt nicht ins Modell", "Auch der vorbereitete Arbeitskontext konnte nicht innerhalb des Modellbudgets bereitgestellt werden. Der Versuch blieb ohne Abschluss. Die Daten sind erhalten; der Einstieg oder die Aufteilung des Materials muss geprüft werden."],
    EmptyModelResponseError: ["Keine verwertbare Modellantwort", "Der Modellaufruf lieferte weder eine nutzbare Antwort noch einen Werkzeugauftrag. Daraus konnte keine Lernentscheidung übernommen werden. Diese Meldung sagt nichts über die Richtigkeit des ursprünglichen Inhalts aus."],
    LearningResponseError: ["Lernantwort nicht auswertbar", "Die Antwort des Modells entsprach nicht dem erwarteten Datenformat oder Lernvertrag. Deshalb konnte sie nicht sicher als Lernentscheidung verarbeitet werden. Das Originalmaterial bleibt für einen erneuten Versuch erhalten."],
    LocalLLMError: ["Modellaufruf nicht erfolgreich", "Der Modellaufruf konnte nicht erfolgreich verarbeitet werden. Diese allgemeine Meldung nennt noch keine gesicherte Ursache. Die technischen Details enthalten die nähere Diagnose; eine inhaltliche Widerlegung ist das nicht."],
    IntegrityError: ["Datenbankänderung zurückgewiesen", "Eine Datenbankregel hat die Änderung dieses Lernversuchs verhindert. Das ist ein technischer Konflikt und kein Urteil über die Aussage. Vor einer Wiederholung sollte die genaue Datenbankdiagnose geprüft werden."],
  };
  const statuses = {
    pending: ["Wartet auf Verarbeitung", "Dieser Eintrag steht in der Lernwarteschlange. Es gibt für diesen Durchlauf noch keine abgeschlossene Lernentscheidung."],
    running: ["Lernversuch läuft", "EVE prüft diesen Eintrag oder überarbeitet einen zurückgewiesenen Vorschlag. Laufende Aktivität allein bedeutet noch keine dauerhafte Übernahme."],
    failed: ["Lernversuch ohne Abschluss", "Der letzte Versuch konnte keine erfolgreich abgeschlossene Lernentscheidung übernehmen. Das Material bleibt erhalten. Prüfe den Fehlergrund; ein erneuter Versuch ist über das erneute Einreihen möglich. Die Meldung bedeutet nicht automatisch, dass die damalige Antwort falsch war."],
    no_persist: ["Bewusst nicht gespeichert", "Die Auswertung ist abgeschlossen und hat keinen dauerhaft zu speichernden Inhalt ergeben. Das ist ein reguläres Lernergebnis, kein technischer Fehler."],
    applied: ["Lernentscheidung übernommen", "Die geprüfte Lernentscheidung wurde gespeichert. Ob daraus ein aktiver Fakt oder zunächst ein unbestätigter Kandidat entstanden ist, zeigen die verknüpften Claims und deren Status."],
    reviewed: ["Als geprüft abgeschlossen", "Der erfolglose Versuch wurde manuell als geprüft markiert. Dadurch wird sein Lernvorschlag nicht als richtig bestätigt und kein Wissen daraus übernommen. Für eine erneute Bearbeitung zuerst wieder öffnen und anschließend erneut einreihen."],
  };
  function help(table, code, fallback) {
    const value = Object.hasOwn(table, code) ? table[code] : fallback;
    return {title: value[0], text: [value[1]]};
  }
  window.EveLearningHelp = {
    error(code, reason) {
      return help(errors, Object.hasOwn(errors, reason) ? reason : code, ["Lernversuch prüfen", "Für diesen Diagnosecode gibt es noch keine genauere Erklärung. Eine Ursache oder ein Urteil über die Richtigkeit lässt sich daraus allein nicht ableiten. Öffne die technischen Details, bevor du den Eintrag erneut verarbeiten lässt."]);
    },
    status(code) { return help(statuses, code, ["Lernstatus", "Dieser Status wurde vom Lernprozess gemeldet. Die technischen Details zeigen den gespeicherten Verarbeitungsstand."]); },
    review(reopen) { return {
      title: reopen ? "Prüfung wieder öffnen" : "Nur Prüfstatus ändern",
      text: [reopen ? "Öffnet den geprüften Eintrag wieder. Ein neuer Lernlauf startet dadurch noch nicht; dafür muss er erneut eingereiht werden."
        : "Schließt die manuelle Prüfung ab und nimmt den Eintrag aus den ungeprüften Lernfehlern. Das bestätigt weder den Lernvorschlag noch die Richtigkeit der damaligen Antwort und speichert keinen Claim."],
    }; },
  };
})();
