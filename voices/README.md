# EVE-Stimme

`de_DE-eve-medium.onnx` und die zugehörige `.onnx.json` sind EVEs trainierte
Piper-Stimme. Der Installer nutzt diese Dateien direkt. Die Prüfsummen stehen
in `eve-voice.json`, zusammen mit den verwendeten Sprechparametern.

Das Modell ist etwa 61 MB groß und läuft auf der CPU. Es benötigt weder
Qwen3-TTS noch eine Referenzaufnahme zur Laufzeit.

## Herkunft

EVEs eigener Trainingsdatensatz besteht aus 720 synthetisch erzeugten
Sprachaufnahmen mit der entworfenen EVE-Referenzstimme. Thorsten bezeichnet
hier die Herkunft des vortrainierten Piper-Checkpoints, mit dem das Training
gestartet wurde.

Die Stimme wurde in dieser Reihenfolge erzeugt:

1. **Referenzstimme:** `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, aus einer
   Textbeschreibung einer erwachsenen, deutschsprachigen weiblichen KI-Stimme.
   Ausgewählt wurde `eve-02-klar-futuristisch.wav`.
2. **Trainingsaufnahmen:** `Qwen/Qwen3-TTS-12Hz-0.6B-Base` erzeugte anhand
   dieser Referenz den synthetischen EVE-Sprachdatensatz mit 720 deutschen Sätzen.
3. **Piper-Modell:** Anpassung eines `de_DE-thorsten-medium`-Checkpoints an
   diesen Datensatz, anschließend ONNX-Export als `de_DE-eve-medium`.

Die Herkunft ist im Projekt durch `generate_eve_voice_candidates.py` sowie die
lokalen Trainingsskripte `generate_dataset.py` und `train_piper.sh` belegt.
Die alternative Qwen3-TTS-Anbindung wird zur Wiedergabe dieses Piper-Modells
nicht benötigt.

## Quellen und Lizenzangaben

Stand der Quellenprüfung: 22. Oktober 2026.

| Bestandteil | Angabe des Herausgebers | Quelle |
| --- | --- | --- |
| Qwen3-TTS 1.7B VoiceDesign | Apache-2.0 | [Modellkarte](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign) |
| Qwen3-TTS 0.6B Base | Apache-2.0 | [Modellkarte](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base) |
| Ursprünglicher Datensatz des Piper-Basismodells: Thorsten | CC0 laut Modellkarte (Datensatz) | [Modellkarte für Thorsten medium](https://huggingface.co/rhasspy/piper-voices/blob/main/de/de_DE/thorsten/medium/MODEL_CARD) |

Der Thorsten-Datensatz ist nicht EVEs eigener Trainingsdatensatz. Für EVE wurde
der vortrainierte Checkpoint auf die synthetischen EVE-Aufnahmen angepasst
(`warmstart_ckpt`); diese Herkunft steht auch in `eve-voice.json`.

Die Thorsten-Modellkarte nennt außerdem ein vorheriges Finetuning aus der
englischen Lessac-Stimme. Ihre CC0-Angabe bezieht sich ausdrücklich auf den
Thorsten-Datensatz. Die Angaben oben dokumentieren die Quellen; sie weisen dem
fertigen EVE-Modell keine aus den Quelllizenzen abgeleitete Lizenz zu.
Die MIT-Lizenz des EVE-Anwendungscodes gilt nicht automatisch für Modellgewichte
oder synthetisch erzeugte Aufnahmen.
