# Thermo Control

Asynchrone Home-Assistant-Integration für die zentrale Raumregelung mit einem externen Temperatursensor und einem oder mehreren Heizkörperthermostaten. Domain: `thermo_control`, Version: `1.0.0`.

## Installation

Voraussetzung: Home Assistant Core **2026.9 oder neuer**, bereits eingerichtete TRV-Climate-Entitäten, ein Raumtemperatursensor mit Temperatureinheit und optional Zigbee2MQTT/MQTT.

1. Den Ordner `custom_components/thermo_control` nach `/config/custom_components/thermo_control` kopieren und Home Assistant neu starten. Alternativ dieses Repository in HACS als benutzerdefiniertes Repository vom Typ **Integration** hinzufügen und installieren.
2. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen → Thermo Control** einen Raum anlegen.
3. Raumname, physische Thermostate und Raumtemperatursensor auswählen. Ein Thermostat darf nur einem Thermo-Control-Raum zugeordnet sein.
4. Optional die erweiterten Einstellungen öffnen: Kontakte, Verzögerungen, Kalibrierung und Preset-Sollwerte.
5. Je TRV die Kalibrierungs-Number-Entität und optional den Ventilpositionssensor auswählen. Eine eindeutige passende Entität am selben HA-Gerät wird automatisch erkannt. Deaktivierte Entitäten zuerst in HA aktivieren.
6. Die neue Climate-Entität mit `climate.turn_on` einschalten. Ein neuer Raum startet ausgeschaltet; nach Neustarts wird der letzte gewünschte Zustand wiederhergestellt.

Die Optionen der Integration erlauben die Bearbeitung aller Zuordnungen und Sollwerte. Änderungen laden den Raum neu. Leere optionale Zuordnungen entfernen eine explizite Auswahl; anschließend ist automatische Geräteerkennung wieder möglich. Ein leerer Kalibrierungspfad ohne passende Number-Entität deaktiviert die Offset-Schreibvorgänge.

## Hardware und Fähigkeiten

Die Integration verwendet HA-Entitäten und setzt keine Tuya-Datenpunktnummern voraus. Die Gerätebezeichnung muss trotzdem geprüft werden: Die aktuelle Zigbee2MQTT-Dokumentation führt `TP-WGZBA` als **SONOFF-Thermostatpanel**. Moes TV01-ZB ist eine Variante des Tuya `TV02-Zigbee`.

| Gerät / Firmware | Kalibrierung laut Zigbee2MQTT | Hinweise |
| --- | --- | --- |
| Tuya TV02-Zigbee / Moes TV01-ZB | −5 … +5 °C, Schritt 0,1 °C | HVAC `heat`/`off`; Presets `auto`, `manual`, `holiday` |
| SONOFF TP-WGZBA | −10 … +10 °C, Schritt 0,2 °C | HVAC `heat`, `auto`, `off`; kein zugesicherter Ventilpositionswert |
| Andere Tuya-TRV-Firmware | geräteabhängig | Grenzen und regelnden HVAC-Modus prüfen |

Die Number-Entität liefert die maßgebliche Schrittweite und Hardwaregrenzen. Zusätzlich begrenzen die UI-Einstellungen den erlaubten Bereich, standardmäßig auf −9 … +9 °C. Für den vollständigen SONOFF-Bereich diese Grenzen auf −10/+10 setzen. Bei Firmware, deren `heat`-Modus das Ventil dauerhaft öffnet, den tatsächlich regelnden Modus `auto` auswählen. TV01/TV02 verwenden `heat` mit `manual`, sofern verfügbar.

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

Ein fehlender, `unknown` oder `unavailable` Kontakt zählt als offen. Nach Ablauf der Abschaltverzögerung wird `off` an die TRVs geschickt. Unterstützt die Firmware keinen Off-Modus, wird der konfigurierbare Frostschutz-Sollwert verwendet, begrenzt durch die Temperaturgrenzen des Geräts.

Der gewünschte Modus, Sollwert und Preset bleiben erhalten. Änderungen während der Fensterpause gelten nach dem Schließen; ein bewusstes Ausschalten wird nicht durch die Wiederherstellung überschrieben. Bei Ausfall des Raumtemperatursensors wird die Zone als nicht verfügbar markiert und die TRVs erhalten ebenfalls Off/Frostschutz. Nach Rückkehr des Sensors wird der gewünschte Zustand wieder angewendet.

Die lokale Fenstererkennung und die Kindersicherung der Geräte werden nicht umgeschaltet. Vorhandene Climate-Attribute werden im Gerätestatus angezeigt; eigene Geräteschutzfunktionen bleiben wirksam.

## Koordination und Presets

Die virtuelle Entität ist die führende Stelle für Sollwert und HVAC-Modus. Abweichende physische Einstellungen werden wieder synchronisiert. Geräte-Presets werden, soweit unterstützt, auf `manual` gesetzt, damit lokale Zeitpläne die Raumvorgabe nicht ersetzen. Die Raum-Presets verwenden einheitliche, konfigurierbare Sollwerte statt uneinheitlicher Firmware-Presets:

| Preset | Standard |
| --- | --- |
| `none` | 20 °C; nach einem Preset Rückkehr zum letzten manuellen Sollwert |
| `eco` | 17 °C |
| `comfort` | 21 °C |
| `boost` | 25 °C |
| `away` | 15 °C |

Die native TRV-Regelung bleibt aktiv. Die konfigurierte Hysterese bestimmt den geschätzten `hvac_action`-Status (`heating`/`idle`) aus der externen Raumtemperatur; sie erzeugt keine zusätzlichen Heat/Off-Schaltzyklen. `boost` ist ein erhöhtes Raumziel und bleibt bis zum nächsten Presetwechsel aktiv.

`valve_position` zeigt den Mittelwert aller verfügbaren Positionswerte (Climate-Attribut `position` oder zugeordnete Sensoren). Fehlende Werte werden ausgelassen; ohne Positionswerte ist das Attribut `null`. Zusätzliche Attribute: `desired_hvac_mode`, `target_temperature_celsius`, `manual_temperature`, `window_open`, `window_pending`, `thermostats`, `temperature_sensor`, `device_status`.

Ein fehlendes TRV blockiert die übrigen Geräte nicht. Wiederholungen nicht bestätigter Steuerbefehle erfolgen höchstens einmal pro Minute. Jeder Serviceaufruf hat ein Timeout von zehn Sekunden. Sensor- und Geräteereignisse werden gebündelt; jede Minute wird außerdem auf ausstehende Wiederholungen und Kalibrierungen geprüft. Die State-Listener verwenden ausschließlich `async_track_state_change_event`; Listener, Timer und laufende Aufgaben werden beim Entladen entfernt.

## Servicebeispiele

Es werden die normalen Home-Assistant-Climate-Services verwendet; `services.yaml` enthält deshalb eine leere Zuordnung.

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

Die Tests verwenden echtes HA Core mit passenden `pytest-homeassistant-custom-component`-Fixtures, HA-State-Machine, Event-Helpern, Config-/Options-Flow und Service-Registry. GitHub Actions prüft stabile Version 2026.9.4, Beta 2026.10.0b0 und die Integrationsmetadaten mit Hassfest. Externe Serviceantworten und Gerätebestätigungen werden simuliert.
