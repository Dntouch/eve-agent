# EVE Visual System V1

## Idee

EVE ist das High-Tech-Interface eines lokalen persönlichen KI-Systems: dunkel,
präzise, räumlich und lebendig. Cyan/Türkis ist die primäre Identität. Licht ist
kein Schmuck: Licht bedeutet Aktivität, Glow bedeutet Relevanz, Helligkeit
bedeutet Fokus und Dunkelheit schafft Informationsraum.

Brainwatch zeigt diese Sprache in hoher Intensität. Chat und Presentation bleiben
ruhiger, Nerd Mode technisch und mittelintensiv, Config bewusst funktional und
niedrigintensiv. Gemeinsame Sprache bedeutet nicht überall gleich viel Neon.

## Tokens

Die zentrale Definition liegt im ersten `:root` von `web/styles.css`.

- `--eve-bg-*` beschreibt den tiefen Grundraum.
- `--eve-surface*` definiert normale, erhöhte und solide Flächen.
- `--eve-border-*` trennt passive und aktive Konturen.
- `--eve-text-*` bildet primären, sekundären und gedimmten Text ab.
- `--eve-accent`, `--eve-success`, `--eve-warning`, `--eve-error` und
  `--eve-unavailable` sind semantische Farben.
- `--eve-glow-*` reicht von keinem Glow über subtil und aktiv bis Focus und
  intensiv.
- `--eve-space-*`, `--eve-radius-*`, `--eve-font-*`, `--eve-text-*` und
  `--eve-motion-*` definieren den kleinen gemeinsamen Maßstab.

Die bisherigen Variablen bleiben als Kompatibilitätsaliase erhalten. Bestehende
Ansichten ändern deshalb weder Struktur noch Funktion und können schrittweise
migriert werden.

## Glow-Hierarchie

| Zustand | Bedeutung | Darstellung |
| --- | --- | --- |
| Normal | verfügbar, nicht hervorgehoben | kein oder kaum Glow |
| Hover | mögliche Interaktion | subtiler Lichtsaum |
| Aktiv/selected | aktuell aktiv | Cyan-Kontur und aktiver Glow |
| Focus | höchste momentane Relevanz | klarer Halo, erhöhte Helligkeit |
| Success | erfolgreich | kontrollierter grüner Akzent |
| Warning | Aufmerksamkeit nötig | warmer funktionaler Akzent |
| Error | fehlgeschlagen | klarer roter Akzent |
| Unavailable | nicht verfügbar | gedimmt und gestrichelte Kontur |

Status darf nicht ausschließlich durch Farbe vermittelt werden. Text, Kontur,
Form oder Statuspunkt ergänzen die Farbe.

## Intensität nach Oberfläche

- **High – Brainwatch:** räumlicher Informationsraum, Focus-Halo, sichtbare
  Informationspfade.
- **Medium – Nerd Mode:** technische Messwerte und aktive Zustände, weniger
  räumliche Tiefe.
- **Low/Medium – Chat:** ruhig und für lange Inhalte lesbar; Licht nur für Status,
  Fokus und Interaktion.
- **Low – Config:** funktional, wenig Glow, klare Controls.
- **Adaptiv – Presentation:** Inhalt dominiert, EVE-Chrome bleibt zurückhaltend.

Die Hilfsklassen `eve-intensity-low`, `eve-intensity-medium` und
`eve-intensity-high` stellen dafür `--eve-view-glow` bereit.

## Typografie

`--eve-font-ui` ist für Titel, Beschreibungen, Chat, Labels und normale Inhalte.
`--eve-font-tech` bleibt IDs, Modellnamen, Messwerten, Code und Rohdiagnose
vorbehalten. Technische Anmutung entsteht durch Präzision, nicht durch flächigen
Monospace-Einsatz.

## Flächen und Controls

Gemeinsame Bausteine:

- `eve-surface`, `eve-surface--raised`, `eve-panel`
- `eve-toolbar`, `eve-inspector-section`, `eve-glow-focus`
- `eve-button` mit `--primary`, `--secondary`, `--ghost`
- `eve-icon-button`
- `eve-input`, `eve-select`
- `eve-badge`, `eve-status`
- `eve-tech` für ausdrücklich technische Inhalte

Neue Ansichten sollen zuerst diese Basis verwenden und nur fachlich notwendige
Erweiterungen ergänzen. Karten-in-Karten-Verschachtelung vermeiden. Passive
Controls bleiben ruhig; Cyan und Glow markieren Aktivität oder Fokus.

## Motion

Animation erklärt Veränderung. `--eve-motion-fast` gilt für Hover und unmittelbare
Interaktion, `--eve-motion-normal` für Panels und Controls, `--eve-motion-focus`
für bewusst sichtbare Fokuswechsel. Keine zufällige oder permanente Bewegung.
Die globale `prefers-reduced-motion`-Regel bleibt verbindlich.

## Regeln für neue Ansichten

1. Intensität festlegen, bevor Effekte ergänzt werden.
2. Semantische Tokens statt neuer Einzel-Farbwerte bevorzugen.
3. Glow nur für Aktivität, Relevanz oder Status verwenden.
4. UI-Schrift für Inhalte, Monospace nur für technische Daten.
5. Controls aus den gemeinsamen Varianten aufbauen.
6. Funktionale Zustände zusätzlich zu Farbe durch Form, Text oder Kontur zeigen.
7. Bewegung muss eine Zustandsänderung erklären und Reduced Motion respektieren.
8. Keine Matrix-, Partikel- oder dekorativen Sci-Fi-Effekte.
