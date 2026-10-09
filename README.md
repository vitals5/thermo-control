# Thermo Control

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/thermo_control/brand/dark_logo@2x.png">
  <img src="custom_components/thermo_control/brand/logo@2x.png" alt="Thermo Control" width="330">
</picture>

Asynchrone Home-Assistant-Integration für die zentrale Raumregelung mit Heizkörper- oder Wandthermostaten und einem optionalen externen Temperatursensor. Domain: `thermo_control`, Version: `2.2.0`.

Neu in **2.2.0**: Täglicher Ventil-Wartungszyklus für Wandthermostate/TRVs, auch bei virtuell ausgeschalteter Heizung. Unter **Einstellungen → Tägliche Ventilwartung** aktivieren (zunächst deaktiviert), Uhrzeit und Dauer wählen. Standard: 12:00 Uhr in der HA-Zeitzone, je 180 Sekunden am minimalen und maximalen Gerätesollwert, anschließend normale Regelung. Räume kommen nacheinander dran; im Raumeditor lassen sich einzelne Räume ausschließen. Für träge Stellantriebe muss die Dauer zur tatsächlichen Stellzeit passen. Sollwerte, Presets und Zeitpläne bleiben erhalten; Geräte-Auto wird ausgelassen, offene Fenster und Ausfälle unterbrechen den Zyklus. Die Wartung erzeugt keinen zusätzlichen Haus-Wärmebedarf.

Seit **2.1.5**: Heizmodus, Preset, Sollwert und manueller Rückkehrwert werden unabhängig von der Verfügbarkeit des Raums in Home Assistants zusätzlichen Wiederherstellungsdaten gespeichert. Ein Sensor- oder Thermostatausfall vor Neustart/Neuladen setzt **Heizen / Auto · Zeitplan** dadurch nicht mehr auf **Aus / Manuell** zurück. Bereits verlorene Einstellungen müssen einmal neu gesetzt werden.

Seit **2.1.4**: Die orange Sollwertkurve zeichnet getrennte waagerechte Abschnitte ohne senkrechte Verbindungsstriche. Zwischenwerte ohne Zeitdauer erzeugen weder Ausschläge noch eine unnötig große Temperaturskala. Echte kurze und lange Sollwertphasen bleiben erhalten; Tooltip und Recorder-Daten bleiben unverändert.

Seit **2.1.3**: Das Thermo-Control-Icon öffnet die Seitenleiste. Dashboard-Links auf `/thermo-control?back=1` blenden daneben einen Zurück-Button ein; er führt zum vorherigen HA-Bildschirm oder bei direkt geöffneten Links zur HA-Startansicht. Die Karte **Heizung** steht ausschließlich in der Übersicht. Der Button **Raum hinzufügen** steht im Tab **Thermostate & Gruppen**.

Seit **2.1.2**: Gruppen-Karten im Übersicht-Tab sind 84 px hoch. Die Kopfzeile zeigt Gruppenname, Raumanzahl, orange Heizflamme und mittlere Ist-Temperatur. Modus, Preset und Sollwert-Stepper liegen darunter in einer einzigen 38-px-Aktionszeile. Sichtbare Feldbeschriftungen entfallen; zugängliche Namen, manuelle Sollwerteingabe und 400-ms-Debouncing bleiben erhalten.

Seit **2.1.1**: Kompakte mobile Analyseansicht mit Raum-Pill und 6h-/24h-/48h-Segmenten, aktuellen Werten in der Legende und einem mindestens 320 px hohen Graphen. Die Raumskala zoomt auf Ist/Soll ±0,5 °C; Vorlauf erhält eine eigene rechte Achse. Heizphasen erscheinen als orange Hintergrundbänder. Ein Touch-Tooltip zeigt Zeit, Ist/Soll, Heizstatus und die gemeldete Ventilöffnung. Daten werden bei Auswahl und minütlich geladen; Hintergrundinformationen stehen hinter dem Fragezeichen.

Seit **2.1.0**: Wochenzeitpläne pro Raum und Gruppe, visueller Editor im Tab **Zeitpläne**, temporäre manuelle Overrides und vorausschauendes FBH-Vorheizen. **Auto · Zeitplan** steuert Thermo Control in `heat`; **Auto · Gerätezeitplan** bleibt der separate Betriebsmodus des Thermostats.

Seit **2.0.4**: Gruppen verwenden wie einzelne Räume eine gemeinsame Heizmodus- und Preset-Auswahl. Die Master-Sollwertverschiebung hat ausschließlich einen Regler; Schnellwahlbuttons entfallen.

Seit **2.0.3**: Heizpausen senken den Gerätesollwert auf Frostschutz ab und erhalten `heat` sowie die Temperaturanzeige. Auto folgt dem geräteeigenen Zeitplan und pausiert die externe Regelung; das Panel kennzeichnet und schützt diesen Betrieb.

Seit **2.0.2**: Raum- und Gruppen-Stepper mit 0,5-°C-Schritten, sofortiger Sollwertvorschau und 400-ms-Debouncing. Das zweispaltige Raumraster und die volle Pill-Leiste mit mindestens 44 × 44 px großen Tasten funktionieren auch auf schmalen Displays.

Neu in 2.0: vorausschauende FBH-Regelung mit PI/TPI und langen PWM-Zyklen, virtuelle Gruppen-Climates, globale Master-Sollwertverschiebung und Luxtronik-Wärmefreigabe. Das lokale Panel bietet **Übersicht**, **Verläufe & Analyse**, **Zeitpläne**, **Thermostate & Gruppen** und **Einstellungen**. Die vollständige Regelungs-, Hardware- und API-Spezifikation steht in [SPECIFICATION.md](SPECIFICATION.md).

Bestehende Räume bleiben bei ihrer bisherigen Thermostatregelung. Für Fußbodenheizung im Raumeditor **Heizungstyp → Fußbodenheizung** wählen. Globale FBH-Parameter und Luxtronik-Zuordnungen werden im Tab **Einstellungen** eingerichtet; eigene Raum- und Gruppenparameter sind optional. Gruppen erhalten Climate-Entitäten; Raumventile melden den tatsächlichen `hvac_action` ihrer Geräte.

Die Luxtronik-Anbindung veröffentlicht **Wärmebedarf** und **Freigegebener Wärmebedarf** als Sensoren. Die optionale Freigabe erlaubt Raumventile nur im konfigurierten Automatikmodus und mit ausreichend warmem Vorlauf. Verdichter- und Warmwassersteuerung bleiben beim Luxtronik-Controller. Die Mindestlauf-/Ruhezeiten gelten für Raumventile. Für Diagramme müssen **History/Recorder** die Raum-/Gruppen-Climates und den Vorlaufsensor aufzeichnen; das Panel nutzt deren Historie ohne externe Bibliotheken.

Die eigenen Brand-Grafiken liegen unter `custom_components/thermo_control/brand/`: Icon (256/512 px) und Logo (655×256 / 1310×512 px), jeweils als transparente PNGs für helle und dunkle Oberflächen. Home Assistant lädt sie lokal für die Integrationsübersicht. SVG-Quellen stehen in `assets/brand/`; `node scripts/build-brands.cjs` erzeugt mit installiertem Playwright/Chromium und FreeSans die PNGs erneut. [HA-Brands-Dokumentation](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/).

[Releases mit Installationspaket und Prüfsummen](https://github.com/vitals5/thermo-control/releases). `python scripts/build-release.py --tag v2.2.0` baut die Pakete lokal. Ein Versions-Tag startet auf GitHub zunächst die bestehenden Prüfungen und veröffentlicht anschließend das Release.

## Installation und Seitenleisten-Panel

Voraussetzung: Home Assistant Core **2026.9 oder neuer**, registrierte Climate-Entitäten der Heizkörper- oder Wandthermostate. Ein externer Raumtemperatursensor ist optional. Für MQTT-Kalibrierung muss die MQTT-Integration bereits eingerichtet sein.

1. Den Ordner `custom_components/thermo_control` nach `/config/custom_components/thermo_control` kopieren. Alternativ dieses Repository in HACS als benutzerdefiniertes Repository vom Typ **Integration** hinzufügen und installieren.
2. Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Thermo Control** suchen und den leeren Bestätigungsdialog abschließen. Es werden keine Einstellungen abgefragt.
4. In der linken Seitenleiste **Thermo Control** (`/thermo_control`) öffnen. Das Panel ist für HA-Administratoren sichtbar. Der zusätzliche Pfad `/thermo-control` öffnet dasselbe Panel ohne zweiten Seitenleisteneintrag.

5. Im Tab **Thermostate & Gruppen** den Button **Raum hinzufügen** wählen. Raumname und Thermostate auswählen; externer Raumtemperatursensor und Fensterkontakte sind optional. Im gleichen Raumeditor die Verzögerungen, Preset-Sollwerte und Kalibrierungszuordnungen je Thermostat bearbeiten und speichern. Eine eindeutige Number- bzw. Positions-Entität am selben HA-Gerät kann automatisch erkannt werden. Deaktivierte Entitäten zuerst in HA aktivieren.
6. Die neue virtuelle Climate-Entität im Panel einschalten. Neue Räume starten in Pause/Frostschutz; bestehende Räume stellen nach Neustarts ihren gewünschten Zustand wieder her.

Ein Dashboard-Button kann das Panel mit Zurück-Pfeil öffnen:

```yaml
tap_action:
  action: navigate
  navigation_path: /thermo-control?back=1
```

Ohne `back=1` bleibt der Zurück-Pfeil verborgen. Das Brand-Icon links ist auf Desktop und Smartphone der Seitenleistenbutton. Der Rücksprung nutzt die HA-interne Historie; ein direkter Aufruf ohne vorherigen HA-Bildschirm führt zur Startansicht. Räume werden unter **Thermostate & Gruppen** hinzugefügt; die Ersteinrichtung bleibt zusätzlich im Leerzustand erreichbar.

**Der Config Flow legt ausschließlich die Integration an.** Es gibt keine Einstellungsfelder und keinen Options Flow. Alle Raum- und Geräteparameter werden ausschließlich im Seitenleisten-Panel verwaltet. YAML und eine eigene `panel_custom`-Konfiguration sind nicht erforderlich. Ein bereits vorhandener leerer `thermo_control:`-Eintrag aus Version 1.1 wird aus Kompatibilitätsgründen importiert und kann danach aus YAML entfernt werden. Es wird nur eine Integration angelegt.

Thermo Control ist als `hub` eingestuft und erscheint nach dem Hinzufügen unter **Einstellungen → Geräte & Dienste → Integrationen**, auch ohne angelegte Räume. Bis Version 1.2.0 führte die Einstufung als `helper` dazu, dass HA den Eintrag im Bereich **Helfer** anzeigte. Nach einem Update auf 1.2.1 und einem Neustart von Home Assistant erscheint der vorhandene Eintrag in der Integrationsübersicht. Anschließend die Browserseite neu laden; ein Löschen oder erneutes Anlegen ist nicht erforderlich.

Alle Entitätsfelder bieten Texteingabe mit Live-Suche nach Anzeigename oder Entitäts-ID. Die Treffer zeigen Name, ID und den aktuellen Messwert bzw. Zustand. Thermostat-Treffer zeigen ihre gemessene Temperatur. Ausgewählte Entitäten behalten eine live aktualisierte Vorschau. Für mehrere Thermostate oder Kontakte einzeln nach weiteren Entitäten suchen und hinzufügen; über das Kreuz lassen sie sich entfernen. Auch die Gerätefelder für Kalibrierung, Ventilposition und interne Temperatur sind durchsuchbar. Temperatursensorfelder bieten nur Entitäten mit einer Temperatureinheit an. Pfeiltasten und Enter wählen Treffer aus; Escape schließt die Vorschlagsliste. Vollständig eingegebene, vorhandene Entitäts-IDs werden beim Speichern übernommen. Unvollständige oder unbekannte Eingaben müssen ausgewählt oder gelöscht werden.

Ohne externen Raumtemperatursensor verwendet die Zone `current_temperature` ihrer Thermostate. Bei mehreren Geräten wird der Mittelwert gültiger, verfügbarer Messungen verwendet, nach Umrechnung nach Celsius. Fehlende oder ungültige Messungen werden ausgelassen. Ohne gültige Messung wird der Raum als nicht verfügbar markiert und Off/Frostschutz gesendet; nach Rückkehr einer Messung gilt wieder der gewünschte Heizmodus. Die Übersicht zeigt, ob die Temperatur vom externen Sensor oder den Thermostaten stammt.

**Ohne externen Sensor erfolgt keine automatische Offset-Kalibrierung.** Bestehende Hardware-Offsets bleiben erhalten; Number- und MQTT-Kalibrierungsbefehle werden nicht gesendet. Damit können Wandthermostate mit passender eigener Messung unverändert genutzt werden. Ist ein externer Sensor ausgewählt, bleibt dieser die verbindliche Referenz; ein Ausfall führt nicht zu einem stillen Wechsel auf interne Messungen.

Die Panel-Übersicht zeigt aktuelle Raumtemperatur, Sollwert, Heizstatus, Ventilöffnung und Fensterstatus. Heizung und Presets sind direkt steuerbar. **Konfigurieren** öffnet den Raumeditor; **Raum löschen** entfernt den Raum und seine virtuelle Climate-Entität nach Bestätigung. Physische Thermostate bleiben bestehen und behalten ihren letzten Hardwarezustand. Für ein Abschalten vor dem Entfernen im Panel zuerst **Aus** wählen.

Beim Entladen der Integration werden Panel, Climate-/Sensor-Entitäten, Timer und Listener entfernt. Die Raumkonfigurationen bleiben für ein erneutes Laden erhalten.

Raum-, Gruppen- und Systemeinstellungen werden in HA-Storage unter `.storage/thermo_control.rooms` gespeichert. Kalibrierungszeitstempel bleiben je Raum separat gespeichert. Stabile Raum-IDs erhalten die Climate-Entitätszuordnung beim Bearbeiten. Parallele Bearbeitungen werden mit einer Revisionsprüfung erkannt. Schreibfehler verändern eine bereits laufende Raumkonfiguration nicht.

Vorhandene Config-Entry-Räume aus Version 1.0 werden einmalig mit ihren IDs und Einstellungen in den Panel-Speicher übernommen. Es wird dabei kein Flow aufgerufen. Bei mehreren alten Einträgen lädt einer das gemeinsame Panel; mindestens ein Eintrag muss aktiviert bleiben. Im Panel gelöschte Räume werden aus alten Einträgen nicht erneut importiert.

Leere optionale Zuordnungen entfernen eine explizite Auswahl; anschließend ist automatische Geräteerkennung wieder möglich. Ein leerer Kalibrierungspfad ohne passende Number-Entität deaktiviert die Offset-Schreibvorgänge. Der Raumeditor erlaubt auch die Bearbeitung vorübergehend nicht verfügbarer Sensoren mit bekannter Temperatureinheit.

## Hardware und Fähigkeiten

Die Integration verwendet HA-Entitäten und setzt keine Tuya-Datenpunktnummern voraus. Die Gerätebezeichnung muss trotzdem geprüft werden: Die aktuelle Zigbee2MQTT-Dokumentation führt `TP-WGZBA` als **SONOFF-Thermostatpanel**. Moes TV01-ZB ist eine Variante des Tuya `TV02-Zigbee`.

| Gerät / Firmware | Kalibrierung laut Zigbee2MQTT | Hinweise |
| --- | --- | --- |
| Tuya TV02-Zigbee / Moes TV01-ZB | −5 … +5 °C, Schritt 0,1 °C | HVAC `heat`/`off`; Presets `auto`, `manual`, `holiday` |
| SONOFF TP-WGZBA | −10 … +10 °C, Schritt 0,2 °C | HVAC `heat`, `auto`, `off`; kein zugesicherter Ventilpositionswert |
| Andere Tuya-TRV-Firmware | geräteabhängig | Grenzen und regelnden HVAC-Modus prüfen |

Die Number-Entität liefert die maßgebliche Schrittweite und Hardwaregrenzen. Zusätzlich begrenzen die UI-Einstellungen den erlaubten Bereich, standardmäßig auf −9 … +9 °C. Für den vollständigen SONOFF-Bereich diese Grenzen auf −10/+10 setzen. Externe Regelung setzt einen temperaturregelnden `heat`-Modus voraus. TV01/TV02 verwenden dabei `manual`, sofern verfügbar. Der HVAC-Modus `auto` gehört dem geräteeigenen Zeitplan; Thermo Control überlagert ihn nicht mit einer externen Regelung.

Quellen: [TV02-Zigbee](https://www.zigbee2mqtt.io/devices/TV02-Zigbee.html), [TP-WGZBA](https://www.zigbee2mqtt.io/devices/TP-WGZBA.html). Die Integration wurde gegen HA Core getestet; ein physischer Gerätetest ist in dieser Umgebung nicht möglich.

## Kalibrierung

Für eine unkalibrierte interne Temperatur gilt:

```text
delta = Raumtemperatur − interne Rohmessung
neuer Offset = delta
```

Enthält die gemeldete interne Temperatur bereits den bestehenden Offset, gilt stattdessen:

```text
neuer Offset = bestehender Offset + Raumtemperatur − interne gemeldete Temperatur
```

Diese zweite Variante ist standardmäßig aktiviert. Sie verhindert, dass ein erfolgreich korrigierter Messwert beim nächsten Durchlauf wieder zum Offset 0 führt. Die Option **Interne Temperatur enthält den Kalibrierungsoffset bereits** pro Gerät passend zur Firmware einstellen. Ein separater interner Sensor ist optional zuordenbar.

Schreibvorgänge erfolgen nur, wenn **beide** Bedingungen erfüllt sind: Mindestintervall seit dem letzten Versuch abgelaufen **und** Änderung mindestens so groß wie die konfigurierte Schwelle. Standard: 600 Sekunden / 0,5 °C, Mindestintervall im UI: 300 Sekunden. Auch fehlgeschlagene Schreibversuche sind begrenzt. Zeitstempel werden vor dem Senden persistent gespeichert und über Neustarts hinweg berücksichtigt. Werte werden an Hardwaregrenzen und Schrittweite angepasst.

Bevorzugt wird `number.set_value`. Als Alternative kann pro Gerät ein vollständiges Topic eingetragen werden:

```text
zigbee2mqtt/wohnzimmer_links/set/local_temperature_calibration
```

Dabei darf keine Number-Entität gleichzeitig ausgewählt sein. MQTT muss bereits eingerichtet sein. Nachrichten enthalten den numerischen Offset, QoS 0 und **retain: false**. Für die erste MQTT-Kalibrierung muss der aktive Offset im Climate-Attribut `local_temperature_calibration` vorhanden sein. Später steht der zuletzt erfolgreich gesendete Wert als persistenter Fallback zur Verfügung. Ein unbekannter Ausgangsoffset wird niemals als 0 angenommen.

Bei fehlender Raum-/TRV-Temperatur, ungültigem Number-Zustand oder offenen Kontakten wird nicht kalibriert. Alle absoluten Temperaturmessungen werden intern nach Celsius umgerechnet; Offsetwerte bleiben Temperaturdifferenzen in Celsius.

## Fenster und Türen

Beliebig viele `binary_sensor`-Kontakte oder HA-Binary-Sensor-Gruppen sind möglich. `on` bedeutet offen, `off` geschlossen. Bei mindestens einem offenen Kontakt startet die Abschaltverzögerung. Erst wenn alle Kontakte geschlossen sind, startet die Wiederanlaufverzögerung. Eine erneute Zustandsänderung bricht die jeweils laufende Verzögerung ab; wiederholte identische Meldungen verlängern sie nicht.

Ein fehlender, `unknown` oder `unavailable` Kontakt zählt als offen. Nach Ablauf der Abschaltverzögerung wird der konfigurierbare Frostschutz-Sollwert (standardmäßig 5 °C) gesendet, begrenzt durch die Temperaturgrenzen des Geräts. Physische Thermostate bleiben in `heat`, damit ihre Temperaturanzeige aktiv bleibt.

Der gewünschte Modus, Sollwert und Preset bleiben erhalten. Änderungen während der Fensterpause gelten nach dem Schließen; ein bewusstes Ausschalten wird nicht durch die Wiederherstellung überschrieben. Bei Ausfall des Raumtemperatursensors wird die Zone als nicht verfügbar markiert und extern gesteuerte Thermostate erhalten ebenfalls den Frostschutz-Sollwert. Nach Rückkehr des Sensors wird der gewünschte Zustand wieder angewendet.

Die lokale Fenstererkennung und die Kindersicherung der Geräte werden nicht umgeschaltet. Vorhandene Climate-Attribute werden im Gerätestatus angezeigt; eigene Geräteschutzfunktionen bleiben wirksam.

## Koordination und Presets

Im Modus **Heizen** ist die virtuelle Raum-Entität die führende Stelle für Sollwert und HVAC-Modus. Gruppen übertragen gemeinsame Vorgaben an ihre Räume. Abweichende physische Einstellungen werden wieder synchronisiert. Geräte-Presets werden, soweit unterstützt, auf `manual` gesetzt, damit lokale Zeitpläne die Raumvorgabe nicht ersetzen. Die Raum-Presets verwenden einheitliche, konfigurierbare Sollwerte statt uneinheitlicher Firmware-Presets:

| Preset | Standard |
| --- | --- |
| `none` | 20 °C; nach einem Preset Rückkehr zum letzten manuellen Sollwert |
| `eco` | 17 °C |
| `comfort` | 21 °C |
| `boost` | 25 °C |
| `away` | 15 °C |

Bei Heizkörpern bleibt die native TRV-Regelung aktiv; die Hysterese schätzt den Wärmebedarf. Der tatsächliche `hvac_action`-Status stammt aus den physischen Geräten. FBH-Räume verwenden dagegen die vorausschauende PI/TPI-Regelung aus der Spezifikation. `boost` ist ein erhöhtes Raumziel und bleibt bis zum nächsten Presetwechsel aktiv.

**Heizpausen erhalten die Geräteanzeige:** Die virtuelle Einstellung **Pause / Frostschutz** (`off`), eine Fensterpause und ein FBH-PWM-Ruheanteil senken ausschließlich den physischen Sollwert ab. Der Hardware-Modus bleibt `heat`. Raum-Sollwert und Preset bleiben gespeichert; beim Weiterheizen wird der effektive Raum-Sollwert wieder gesendet. Die Geräte regeln weiterhin selbst anhand ihres jeweils empfangenen Sollwerts. Der Frostschutz ist kein garantierter vollständiger Ventilschluss: Unterhalb seiner Temperaturgrenze kann das Gerät heizen.

**Auto verwendet den Gerätezeitplan:** Auto im Panel sendet einmalig `climate.set_hvac_mode: auto`, sofern alle Raumthermostate dies unterstützen. Danach erfolgen keine automatischen Sollwert-, Modus-, Preset- oder Kalibrierungsbefehle. Auch ein am Gerät aktivierter Auto-Modus wird respektiert. Das Panel zeigt den gemeldeten Gerätesollwert (bei mehreren Auto-Thermostaten dessen Mittelwert) und sperrt Sollwert-Stepper sowie Raum-Presets. Fensterkontakte und Luxtronik-Freigabe werden weiter angezeigt, steuern Auto-Geräte jedoch nicht; hier gelten deren eigene Schutzfunktionen. Die Master-Verschiebung wirkt nur auf extern gesteuerte Geräte. Ein bewusster Wechsel auf **Heizen** oder **Pause / Frostschutz** übernimmt die externe Steuerung wieder. Ein Wechsel am Thermostat von Auto zu Heat erlaubt ebenfalls die externe Regelung.

In einem gemischten Raum bleiben einzelne Auto-Thermostate unangetastet; die übrigen Geräte folgen dem Raumziel. Enthält eine Gruppe Auto-Räume, sind gemeinsame Sollwert- und Presetänderungen gesperrt, bis alle Räume bewusst auf Heizen gestellt werden. Die tatsächliche Heizaktion wird in allen Modi aus `hvac_action` übernommen. Bei Auto zählt eine gemeldete Heizaktion als beobachteter Wärmebedarf.

`valve_position` zeigt den Mittelwert aller verfügbaren Positionswerte (Climate-Attribut `position` oder zugeordnete Sensoren). Fehlende Werte werden ausgelassen; ohne Positionswerte ist das Attribut `null`. Zusätzliche Attribute: `native_auto`, `auto_devices`, `temperature_source` (`external_sensor` / `thermostats`), `desired_hvac_mode`, `target_temperature_celsius`, `manual_temperature`, `window_open`, `window_pending`, `thermostats`, `temperature_sensor`, `device_status`.

Ein fehlendes TRV blockiert die übrigen Geräte nicht. Wiederholungen nicht bestätigter Steuerbefehle erfolgen höchstens einmal pro Minute. Jeder Serviceaufruf hat ein Timeout von zehn Sekunden. Sensor- und Geräteereignisse werden gebündelt; jede Minute wird außerdem auf ausstehende Wiederholungen und Kalibrierungen geprüft. Die State-Listener verwenden ausschließlich `async_track_state_change_event`; Listener, Timer und laufende Aufgaben werden beim Entladen entfernt.

## Wochenzeitpläne und Automatik

1. Im Tab **Zeitpläne** einen Raum oder eine Gruppe auswählen. Eigene Raumpläne haben Vorrang vor Gruppenplänen, auch wenn der Raumplan deaktiviert ist.
2. Eine Vorlage (**Standard FBH**, **Homeoffice**, **Abwesend**) wählen oder eigene Blöcke anlegen. **Mo–Fr**, **Sa–So** und Einzeltage auswählen; Blockänderungen gelten für alle ausgewählten Tage. Die Zeitachse zeigt den ersten ausgewählten Tag.
3. Einen farbigen Zeitblock antippen und Start, Ende und Sollwert bearbeiten. Sollwerte verwenden 0,5-°C-Schritte bei 5–30 °C. **Block übernehmen** verändert den Entwurf; **Zeitplan speichern** schreibt ihn nach Home Assistant. Nachtblöcke dürfen über Mitternacht reichen. `24:00` ist als Ende erlaubt; überschneidende Blöcke, einschließlich der Nachtanteile des Vortags, werden abgewiesen.
4. **Automatikmodus aktiv** einschalten und speichern. Das aktiviert für die betroffenen Räume Heizen und das Preset `schedule`. Der Heizmodus muss temperaturregelndes `heat` unterstützen. Falls ein Thermostat in Geräte-Auto war, ist diese Aktivierung eine bewusste Übernahme in Heat; ein später am Gerät aktiviertes Auto wird weiterhin respektiert.
5. In der Raumkachel schaltet das Kalendersymbol zwischen Zeitplan und Manuell um. Ohne vorhandenen Plan führt es direkt zum Editor. Bei Zeitplan-Automatik bleiben die Sollwert-Stepper bedienbar: eine Änderung erzeugt einen **Override bis zum nächsten tatsächlichen Temperaturwechsel**, optional für die eingestellte Stundenzahl (0–48 h). Ein durchgehend konstanter Plan ohne Schaltpunkt begrenzt einen solchen Override auf 24 Stunden. Danach gilt automatisch wieder der Plan. Kacheln zeigen **Auto (bis …)**, **Override (bis …)** und **Vorheizen**.
6. Ein gespeicherter Plan lässt sich über **Plan auf andere Räume übertragen** als Woche oder einzelner Tag auf Räume, Gruppen oder weitere Wochentage kopieren. Neue Wochenkopien sind zunächst deaktiviert; Tageskopien erhalten den Aktivierungszustand ihres Zielplans. Ungespeicherte Entwürfe zuerst speichern.

Zeitlücken verwenden den konfigurierten Fallback-Sollwert (Standard 18 °C). Die HA-Zeitzone bestimmt die Schaltzeiten. In der fehlenden Stunde der Sommerzeit werden Grenzen auf die erste existierende Minute verschoben; in der doppelt auftretenden Winterzeit wird die erste Ausführung verwendet. Gleich temperierte angrenzende Blöcke bilden keinen zusätzlichen Override-Schaltpunkt.

**FBH-Vorheizen** benötigt die Option im Zeitplan und den Heizungstyp Fußbodenheizung. `Vorlaufzeit = (nächster höherer Sollwert + Master-Verschiebung − Raumtemperatur) / Aufheizkoeffizient`, begrenzt durch die maximale Vorheizzeit des Plans und die maximale Vorlaufzeit des Raums. Beispiel: Bei 20 °C Raumtemperatur, 21,5 °C Ziel um 06:00 und 1 °C/h beginnt das Vorheizen um 04:30. Ein begonnener Abschnitt bleibt bis zum geplanten Zeitpunkt bestehen und wird für Neustarts gespeichert. Ein manueller Override ersetzt ihn. Fensterpausen, Messwertausfälle, Luxtronik-Freigabe und Mindestzeiten bleiben wirksam.

Zeitpläne und Overrides werden unter `.storage/thermo_control_schedules` gespeichert. Normale Presets (Manuell, Eco, Komfort, Boost, Abwesend) pausieren den Zeitplan des betreffenden Raums; `schedule` aktiviert ihn erneut. Bei eigenen Raumplänen wird auch deren Aktivierung angepasst; bei geerbten Gruppenplänen bleibt die Pause auf den einzelnen Raum begrenzt. Ein virtueller Heizmodus Off pausiert die Ausführung; zurück auf Heizen wird ein aktivierter Plan wieder ausgeführt. Geräte-Auto erhält keine automatischen Steuer- oder Kalibrierungsbefehle. FBH-Aufheizkoeffizienten sind einstellbare Anlagenparameter; eine automatische Lernfunktion ist nicht enthalten.

## Servicebeispiele

Räume und Gruppen verwenden die normalen Home-Assistant-Climate-Services. Zusätzlich setzt `thermo_control.set_master_offset` die globale Sollwertverschiebung mit `{offset: -2}`. Sie ist reversibel und wird gespeichert.

```yaml
action: climate.set_temperature
target:
  entity_id: climate.wohnzimmer
data:
  temperature: 21
  hvac_mode: heat
```

```yaml
action: climate.set_preset_mode
target:
  entity_id: climate.wohnzimmer
data:
  preset_mode: eco
```

## Entwicklung und Prüfung

```bash
uv venv --python 3.14
uv pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest --cov-fail-under=90
```

Die Tests verwenden echtes HA Core mit passenden `pytest-homeassistant-custom-component`-Fixtures, HA-State-Machine, Event-Helpern, Raumverwaltung, authentifizierten Panel-WebSockets und Service-Registry. GitHub Actions prüft stabile Version 2026.9.4, Beta 2026.10.0b0 und die Integrationsmetadaten mit Hassfest. Externe Serviceantworten und Gerätebestätigungen werden simuliert.

Die Frontend-Prüfungen verwenden Chromium und simulierte HA-Antworten:

```bash
npm ci
npx playwright install --with-deps chromium
npm run test:panel
```

Sie prüfen Anlegen, Bearbeiten, Löschen, Live-Anzeige, Entitätssuche mit Messwertvorschau, Mehrfachauswahl, Tastaturbedienung, optionale Sensoren, Heizbefehle, fehlgeschlagenes Speichern, mobile Darstellung und Subscription-Cleanup. Das Panel lädt ausschließlich lokale Dateien und benötigt kein CDN.
