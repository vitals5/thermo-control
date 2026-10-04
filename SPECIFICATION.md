# Thermo Control 2.0 – Regelung und Panel

## Architektur und Kompatibilität

- Domain `thermo_control`, Integrationsart `hub`, ein Config Entry. Der Config Flow bietet ausschließlich den leeren Bestätigungsdialog. Sämtliche Parameter werden im lokalen Seitenleisten-Panel verwaltet.
- Physische Climate-Entitäten gehören genau einem Raum. Ein Raum besitzt eine virtuelle Climate-Entität; eine optionale Gruppe bündelt mehrere Räume in einer weiteren Climate-Entität. Etage/Zone ist eine frei wählbare Anzeigezuordnung.
- Bestehende Räume bleiben im Typ `radiator`: die Geräte regeln selbst proportional, Thermo Control synchronisiert Modus und Sollwert. FBH/PWM muss pro Raum ausdrücklich gewählt werden.
- Externer Temperatursensor optional. Ohne ihn wird das Mittel gültiger Thermostatmessungen verwendet; automatische Offset-Kalibrierung ist deaktiviert.
- Alle absoluten Regeltemperaturen und Master-Differenzen werden intern in Celsius geführt. Climate-Darstellung und Serviceaufrufe berücksichtigen die HA-/Geräteeinheiten.
- Steuerung, Speicher und Services sind asynchron. Zustandslistener verwenden ausschließlich `async_track_state_change_event`. Eine minütliche Abgleichroutine bedient PWM, Wiederholungen und Trendaufnahme; Listener und laufende Aufgaben werden beim Entladen entfernt.

## Vorausschauende FBH-Regelung

Dies ist ein Trendmodell mit PI/TPI, kein selbstlernendes physikalisches Gebäudemodell. Der Raumeditor, die Gruppe und die globalen Einstellungen erlauben die Anpassung an die tatsächliche Anlage.

| Parameter | Standard | Bereich |
| --- | --- | --- |
| Gleitendes Trendfenster | 45 Minuten | 30–60 Minuten |
| Trägheitsfaktor | 1 | 0–2 |
| Maximale Vorlaufzeit | 180 Minuten | 0–240 Minuten |
| PWM-Zyklus | 45 Minuten | 30–60 Minuten |
| Mindestlaufzeit der Raumventile | 300 Sekunden | 60–1800 Sekunden |
| Mindestruhezeit der Raumventile | 300 Sekunden | 60–1800 Sekunden |
| Proportionalband | 2 °C | 0,5–5 °C |
| Integrationszeit | 6 Stunden | 1–24 Stunden |
| Globale FBH-Hysterese | 0,2 °C | 0,1–2 °C |

Mindestlauf- und Ruhezeit müssen zusammen in den Zyklus passen. Parameterreihenfolge: Raumparameter → globale Parameter, wenn im Raum gewählt → vollständige Gruppenparameter, wenn die Gruppe eine eigene Regelung hat. Gruppen überschreiben nur FBH-Regelparameter, keine Raumfühler, Fenster oder Hardwarezuordnungen.

1. Höchstens eine Raumtemperatur pro Minute wird in einem begrenzten Ringpuffer aufgenommen. Für die lineare Regression müssen Messungen mindestens zehn Minuten abdecken. Ein fehlender Messwert oder eine Aufnahmeunterbrechung über zehn Minuten verwirft den Trend. Messungen außerhalb des gewählten Zeitfensters werden entfernt.
2. Die Steigung der Regression ergibt `dT/dt` in °C/h, begrenzt auf ±3 °C/h. Solange der Trend noch nicht belastbar ist, bleibt er unbekannt und der Regler verwendet die aktuelle Raumtemperatur.
3. `Horizont = min(maximale Vorlaufzeit, 120 Minuten × Trägheitsfaktor)`.
4. `Prognose = Raumtemperatur + max(0, dT/dt) × Horizont`. Eine negative Steigung wird angezeigt, aber nicht als zusätzlich vorweggenommener Wärmeverlust angerechnet.
5. Bei steigender Temperatur über 0,02 °C/h und `Prognose >= Sollwert − Hysterese/2` greift Pre-Shutoff: rechnerischer Bedarf 0 %. Damit kann die Heizung vor Erreichen des Sollwerts pausieren.
6. Sonst ergibt der Prognosefehler mit Proportionalband und einem begrenzten Integralanteil einen Bedarf von 0–100 %. Der Integralanteil wird bei Sättigung nur zur Entsättigung weitergeführt, bei Sperren zurückgesetzt und über Neustarts gespeichert. Ausfallzeiten werden nicht integriert.
7. Zu Zyklusbeginn wird der berechnete Anteil für den Zyklus festgelegt. Beispiel: 50 % bei 45 Minuten bedeutet rund 22,5 Minuten Heizen und 22,5 Minuten Pause. Der Abgleich erfolgt minütlich. Zu kurze Heizpulse werden ausgelassen; zu kurze Restpausen ergeben einen vollen Heizzyklus. Neue Sollwerte beginnen einen neuen Zyklus unter Beibehaltung der Mindestzeiten.
8. Pre-Shutoff und eine reale Temperatur oberhalb `Sollwert + Hysterese` beenden den Heizanteil unter Beachtung der Mindestlaufzeit. Ein bewusstes Ausschalten, Fenstersperre, Messwertausfall oder fehlende Luxtronik-Freigabe senkt den physischen Sollwert sofort auf Frostschutz ab. Die Mindestruhezeit verhindert anschließend einen sofortigen Neustart.
9. PWM wechselt im physischen Climate-Modus `heat` zwischen effektivem Raum-Sollwert und konfiguriertem Frostschutz-Sollwert (Standard 5 °C). Ein physisches `off` wird nicht gesendet; so bleibt die Geräteanzeige aktiv. Die virtuelle Climate-Entität behält ihren Raum-Sollwert. Unterhalb des Frostschutz-Sollwerts kann der Geräteschutz weiterhin Wärme anfordern. Prozentwerte sind zeitlicher Bedarf, keine Zusage einer proportionalen physischen Ventilöffnung.

Trendmessungen, Integralanteil, letzter Schaltzeitpunkt und angeforderter Ventilzustand werden gespeichert. Ein Neustart beginnt einen neuen Zyklus, erhält aber die Mindestzeiten. Schaltzeitpunkte werden vor Gerätebefehlen gespeichert; ein Speicherfehler verhindert den neuen Befehl. Gerätedienste besitzen Timeout, Fehleranzeige und begrenzte Wiederholungen. Fensterkontakte und ausstehende Fensterverzögerungen bleiben Teil der bestehenden Verriegelung.

## Geräte-Auto und externe Regelung

- Externe Regelung benötigt einen temperaturregelnden `heat`-Modus. Der frühere Geräteparameter `regulated_mode: auto` wird beim externen Ansteuern nicht mehr verwendet. Auto wird über den normalen Climate-Modus gewählt.
- Ein bewusster Raum-/Gruppen-Moduswechsel darf den physischen Modus einmalig ändern. Im Auto-Betrieb gibt es keine zyklischen Modus-, Sollwert-, Preset-, Number- oder MQTT-Kalibrierungsbefehle, auch nicht bei Fensteröffnung, Messwertverlust, Master-Verschiebung oder fehlender Luxtronik-Freigabe.
- Physisches `auto` wird unabhängig vom gespeicherten Raumwunsch respektiert. Bei mehreren Geräten steuert ein gemischter Raum nur die Geräte außerhalb von Auto. Ein Gerät ohne `heat`-Unterstützung wird nicht extern geregelt. Die Auswahl der virtuellen HVAC-Modi berücksichtigt alle Raumgeräte.
- Sind alle verfügbaren Geräte in Auto, meldet der Raum `auto` und den Mittelwert der gemeldeten Gerätesollwerte. Der bisherige manuelle Basis-Sollwert bleibt erhalten. Auto-Stepper und Presets sind gesperrt; diese Dienste weisen Änderungen ohne expliziten Wechsel auf Heat/Off zurück.
- Gruppen prüfen den Modus aller Räume vor Sollwert-/Presetänderungen und vermeiden so teilweise geänderte Gruppen. Gruppenmodus Auto ist nur bei gemeinsamer Unterstützung verfügbar. Der Wechsel auf Heizen/Frostschutz ist eine bewusste Übernahme der externen Steuerung.
- Auto-Heizaktivität zählt als beobachteter Wärmebedarf, ohne daraus PWM-Schaltungen abzuleiten. Geräte-Fensterschutz und Frostschutz bleiben im Auto-Betrieb Aufgabe der Geräte.
- Beim Wechsel von/zu Auto wird der Befehls-Cache verworfen, damit der manuelle Sollwert anschließend sofort wieder übertragen werden kann. Kalibrierungs-Mindestintervalle bleiben erhalten.

## Sollwerte, Gruppen und tatsächlicher Heizstatus

- `effektiver Sollwert = Basis-Sollwert + Master-Verschiebung`, begrenzt auf die Hardwaregrenzen des Raums. Der Basis-Sollwert bleibt erhalten. Eco/Normal/Komfort/Party im Überblick setzen die Verschiebung auf −2/0/+1/+2 °C. Diese Schnellaktionen sind unabhängig vom individuellen Raum-Preset.
- Ein normaler `climate.set_temperature`-Aufruf setzt den effektiven Sollwert; die aktuelle Master-Verschiebung wird für den gespeicherten Basiswert herausgerechnet. Deshalb addieren sich wiederholte Master-Aktionen nicht.
- Gruppen-Sollwert und HVAC-/Preset-Dienste werden an alle enthaltenen Räume übertragen. Eine Gruppentemperatur wird vorab gegen die gemeinsamen Hardwaregrenzen geprüft. Räume behalten ihre eigenen Sensoren und Fensterpausen. Die Gruppe zeigt mittlere Ist-/Solltemperaturen und kennzeichnet unterschiedliche Sollwerte.
- Raum-`hvac_action` wird aus den verfügbaren physischen Thermostaten aggregiert: mindestens ein `heating` → heating, sonst mindestens ein `idle` → idle, sonst eine Off-Rückmeldung → off. Bei eingeschaltetem Raum ohne verwertbare Rückmeldung bleibt die Aktion unbekannt. Ein Ausschaltwunsch überdeckt eine noch gemeldete physische Heizaktivität nicht.
- Gruppen melden heating, sobald mindestens ein Mitgliedsraum heating meldet. Wärmebedarf und tatsächliche Heizaktion sind getrennt; Nachlauf und verzögerte Zigbee-Bestätigungen sind sichtbar.
- Die mittlere gemeldete Ventilposition bleibt ein eigener Messwert. Fehlende Positionssensoren verhindern weder Regelung noch `hvac_action`-Anzeige.

## Alpha Innotec WWC 100 H/X / Luxtronik

Thermo Control verwendet die bereits von einer HACS-Luxtronik-Integration veröffentlichten HA-Entitäten. Es öffnet keine zweite Verbindung zur Wärmepumpe und setzt keine modellabhängigen Luxtronik-Register voraus. Tatsächliche Entitätsnamen hängen von Integration, Firmware und Installation ab; alle Zuordnungen sind im Tab Einstellungen durchsuchbar.

| Zuordnung | Erlaubte Entität | Bedeutung |
| --- | --- | --- |
| Vorlauf Ist | Temperatur-`sensor` | Tatsächlich gemeldete Vorlauftemperatur |
| Vorlauf Soll | Temperatur-`sensor` | Vom Controller veröffentlichter Zielwert; separat angezeigt |
| Heizungs-Betriebsmodus | `sensor`, `select` oder `climate` | Rohzustand des Heizkreises; Automatik-Aliase explizit einstellbar |
| Verdichterstatus | `binary_sensor` | on/off = aktiv/inaktiv; unknown/unavailable bleiben unbekannt |

Automatik-Aliase standardmäßig `automatic`, `automatik`, `automatisch`, `auto`; Vergleich ohne Groß-/Kleinschreibung. Bei einer Climate-Entität zählt deren HA-Zustand. Ein anderes Modusformat muss entsprechend zugeordnet werden. Heizkreis-Betriebsmodus und generelle Status-/Warmwasseranzeige sind unterschiedliche Entitäten und werden nicht automatisch gleichgesetzt.

Die optionale Freigabe ist standardmäßig deaktiviert. Sie benötigt Vorlauf-Ist und Heizungs-Betriebsmodus. Mit aktivierter Freigabe sind Raumventile nur freigegeben, wenn:

- der konfigurierte Modus ein Automatik-Alias ist;
- der Vorlauf bekannt und mindestens so warm wie der konfigurierte Grenzwert ist (Standard 25 °C);
- der Vorlauf mindestens `Raumtemperatur + Wärmeabstand` erreicht (Standard 2 °C).

Ein ausgewählter, ausgefallener Sensor führt zu gesperrter Freigabe. Der Verdichter muss für warme Restwärme nicht gerade laufen. Die Ziel-Vorlauftemperatur wird zur Diagnose angezeigt; sie wird nicht mit der Isttemperatur gleichgesetzt. Auf Warmwasserbereitung oder Verdichterregister wird nicht geschrieben.

Systembedarf wird ausschließlich aus Räumen berechnet, damit Gruppen nicht doppelt zählen. Das Haus-Bedarfssignal ist der höchste Raumanteil, der mittlere Raumanteil steht zusätzlich als Attribut bereit. Alle Räume ohne Bedarf → 0 %.

- **Thermo Control Wärmebedarf:** ungefilterter Hausbedarf, auch bei fehlender Vorlaufwärme sichtbar.
- **Thermo Control Freigegebener Wärmebedarf:** höchster Anteil eines aktuell freigegebenen Raums.
- Attribute: Vorlauf Ist/Soll, Modus, Automatik erkannt, Verdichterstatus, Anzahl bedürftiger/heizender Räume, `heat_requested` und mittlerer Bedarf.

Diese Sensoren ermöglichen die Kopplung mit bestehenden Automationen. Thermo Control stellt keine direkte Verdichteranforderung, verändert keine Heizkurve und kontrolliert keine Mindestdurchflussmenge. Die konfigurierten Mindestlauf-/Ruhezeiten betreffen die Raumventile; der Verdichterschutz bleibt beim Luxtronik-Controller. Ein externer Startpfad darf den ungefilterten Bedarf nutzen, während die Raumfreigabe auf tatsächliche Vorlaufwärme wartet.

## Panel-Tabs

1. **Übersicht:** Luxtronik-Statusleiste, Master-Verschiebung, Gruppensteuerung, Raumkarten mit Etage, große Temperatur-Stepper, Heizmodus und Presets. Isttemperatur, Fenster, Ventilposition, Bedarf, Trend, Prognose und Pre-Shutoff sind direkt sichtbar. Das Raumraster hat auf Desktop und Mobilgeräten zwei Spalten mit 8 px Abstand. Raum- und Gruppen-Stepper zeigen `− / Sollwert / +` als volle Pill-Leiste mit mindestens 44 × 44 px großen Tasten. Die Sollwerte werden in 0,5-°C-Schritten im Bereich 5–30 °C verstellt; engere Hardwaregrenzen bleiben wirksam. Die Anzeige reagiert sofort. Pro Climate-Entität wird `climate.set_temperature` erst 400 ms nach der letzten Eingabe gesendet. Zwischenzeitliche HA-Rückmeldungen und neue Snapshots überschreiben die Vorschau nicht; überlappende Aufrufe werden je Entität geordnet. Bei Service-Fehlern oder fehlender Bestätigung nach 10 Sekunden wird wieder der HA-Sollwert angezeigt. Verlassen des Panels, Entfernen eines Raums oder Ausfall seiner Entität oder Wechsel in Auto verwirft noch nicht gesendete Änderungen.
2. **Verläufe & Analyse:** Raum-/Gruppen-Auswahl; 6h, 24h, 48h, 7 Tage; Ist-/Sollkurven, binäre Heizphasen und optional Vorlaufkurve. Lokales SVG-Diagramm mit Messwertvorschau, ohne CDN, Chart-Bibliothek oder zusätzliche HACS-Karte. Die authentifizierte HA-History-API liefert Recorder-Daten einschließlich Attributänderungen. Fehlende Historie wird angezeigt. Ausfallphasen unterbrechen Kurven und Heiz-Timeline. Gruppen-Ist-/Sollwerte stammen aus ihrer virtuellen Climate-Entität.
3. **Thermostate & Gruppen:** Selektor-Matrix zur Gruppenzuordnung; Raumeditor für Multi-Thermostat-Kopplung, Etage, Heizungsart, Sensor und Kontakte. Gruppen können eigene vollständige FBH-Parameter bekommen. Eine noch zugewiesene Gruppe kann nicht gelöscht werden.
4. **Einstellungen:** Luxtronik-Entitätszuordnung und Automatik-Aliase, Wärmefreigabe und Vorlaufgrenzen, globale FBH- und Kalibrierungsparameter, Mindestlauf-/Ruhezeiten.

Tabs sind per Tastatur erreichbar, mobile Ansichten sind geprüft. Entitätsfelder behalten Texteingabe, Live-Suche und Zustandsvorschau. Telemetrie aktualisiert laufende Felder ohne Fokusverlust. Das Panel und alle schreibenden WebSocket-Kommandos sind auf HA-Administratoren beschränkt.

## Persistenz und API

Bestehender Storage `.storage/thermo_control.rooms` erhält zusätzlich `settings`; vorhandene Daten ohne dieses Feld erhalten kompatible Defaults. Raum-IDs und bestehende Climate-Zuordnungen bleiben erhalten. Gruppen erhalten eigene stabile Unique IDs `group_<id>`. Raum- und Systemeinstellungen werden vor Laufzeitänderungen gespeichert und gegen eine gemeinsame Revision geprüft. Ein veralteter Editor erhält eine Konfliktmeldung, statt aktuelle Änderungen zu überschreiben.

WebSocket-Kommandos: `thermo_control/rooms`, `subscribe`, `save_room`, `delete_room`, `save_settings`, `master_offset`. Raum-/System-Dokumente werden serverseitig geprüft (endliche Zahlen, Parametergrenzen, Entitätsdomains, Temperatureinheiten, doppelte Zuweisungen, Gruppenzugehörigkeit).

Service: `thermo_control.set_master_offset`, Daten `{offset: -2}`; Benutzeraufrufe benötigen Admin-Rechte, Automationen ohne Benutzerkontext sind zulässig. Room-/Group-Climates verwenden die standardmäßigen Climate-Dienste. Physische Geräte bleiben beim Löschen eines Raums bestehen.

## Validierung und praktische Grenzen

Automatisierte Tests verwenden reale HA-Zustände, Timer, Config Entries, Entity Registry, Climate-/Sensor-Plattformen und authentifizierte WebSockets. Zeitreihentests prüfen Trend, Pre-Shutoff, Integralsättigung, lange PWM-Zyklen, Mindestzeiten und Neustarts. Playwright prüft die vier Tabs, Live-Suche, Gruppenzuordnung, Expertenspeicherung, Historienkurven und mobile Layouts.

Ein physischer Test an der WWC 100 H/X und ihren Heizkreisen ist in der Entwicklungsumgebung nicht möglich. Trendprognose und Standardwerte müssen deshalb an der realen Anlage anhand der aufgezeichneten Verläufe beurteilt und angepasst werden. Die sieben Tage Diagrammfenster setzen entsprechende Recorder-Aufbewahrung und eingeschlossene Entitäten voraus.

Primärquellen: [Home Assistant History-API](https://github.com/home-assistant/core/blob/dev/homeassistant/components/history/websocket_api.py), [HA Climate-Modell](https://developers.home-assistant.io/docs/core/entity/climate/), [Luxtronik HACS](https://github.com/BenPru/luxtronik), [Bouni Luxtronik](https://github.com/Bouni/luxtronik).
