/* Local Home Assistant custom panel. No build step or external resources. */
const PRESETS = { none: "Manuell", eco: "Eco", comfort: "Komfort", boost: "Boost", away: "Abwesend" };
const NUMBERS = [
  ["tolerance", "Hysterese für den Heizstatus", "°C", 0.1, 2, 0.1],
  ["calibration_interval", "Mindestintervall der Kalibrierung", "s", 300, 86400, 1],
  ["calibration_threshold", "Mindeständerung des Offsets", "°C", 0.1, 5, 0.1],
  ["window_open_delay", "Verzögerung bis zum Abschalten", "s", 0, 3600, 1],
  ["window_close_delay", "Verzögerung bis zur Wiederherstellung", "s", 0, 3600, 1],
  ["frost_temperature", "Frostschutz-Sollwert", "°C", 5, 15, 0.5],
  ...Object.entries(PRESETS).map(([key, label]) => [`preset_${key}`, `${label}: Sollwert`, "°C", 5, 35, 0.5]),
];
const DEVICE_NUMBERS = [
  ["calibration_min", "Minimaler Offset", "°C", -10, 0, 0.1],
  ["calibration_max", "Maximaler Offset", "°C", 0, 10, 0.1],
  ["calibration_step", "Schrittweite", "°C", 0.1, 1, 0.1],
];
const create = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

class ThermoControlPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = { rooms: [], revision: 0, defaults: {}, device_defaults: {} };
    this._cards = new Map();
    this._connection = null;
    this._generation = 0;
    this._busy = false;
  }

  set hass(value) {
    this._hass = value;
    if (this.isConnected) {
      this._connect();
      this._updateCards();
    }
  }
  get hass() { return this._hass; }
  set narrow(value) { this.toggleAttribute("narrow", Boolean(value)); }
  set panel(value) { this._panel = value; }

  connectedCallback() {
    if (!this.shadowRoot.hasChildNodes()) this._build();
    this._connect();
  }

  disconnectedCallback() {
    this._generation += 1;
    if (this._unsubscribe) this._unsubscribe();
    this._unsubscribe = null;
    this._connection = null;
  }

  async _connect() {
    const connection = this._hass?.connection;
    if (!connection || connection === this._connection) return;
    if (this._unsubscribe) this._unsubscribe();
    this._connection = connection;
    const generation = ++this._generation;
    try {
      const data = await this._hass.callWS({ type: "thermo_control/rooms" });
      if (generation !== this._generation || !this.isConnected) return;
      this._receive(data);
      const unsubscribe = await connection.subscribeMessage(
        (snapshot) => {
          if (generation === this._generation && this.isConnected) this._receive(snapshot);
        }, { type: "thermo_control/subscribe" },
      );
      if (generation !== this._generation || !this.isConnected) unsubscribe();
      else this._unsubscribe = unsubscribe;
    } catch (error) {
      if (generation === this._generation) {
        this._connection = null;
        this._error("Verbindung zu Thermo Control fehlgeschlagen. " + this._message(error));
      }
    }
  }

  _receive(data) {
    this._data = data;
    this._renderCards();
    this.shadowRoot.querySelector("#connection").textContent = "Mit Home Assistant verbunden";
    this.shadowRoot.querySelector("#add-room").disabled = false;
  }

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;height:100%;overflow:auto;color:var(--primary-text-color,#23312d);background:var(--primary-background-color,#f4f6f4);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
        *{box-sizing:border-box}button,input,select{font:inherit}button{cursor:pointer;border:1px solid var(--divider-color,#dce3dd);border-radius:9px;background:var(--card-background-color,#fff);color:inherit;padding:10px 14px;min-height:42px}button:hover{background:var(--secondary-background-color,#eef3ef)}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--primary-color,#548269);outline-offset:2px}button:disabled{opacity:.55;cursor:wait}.primary{background:var(--primary-color,#287757);border-color:transparent;color:var(--text-primary-color,#fff)}.primary:hover{filter:brightness(.94);background:var(--primary-color,#287757)}
        .toolbar{display:flex;gap:14px;align-items:center;padding:18px 28px;border-bottom:1px solid var(--divider-color,#dce3dd);background:var(--card-background-color,#fff);position:sticky;top:0;z-index:2}.brand{width:36px;height:36px;border-radius:11px;background:#e5efe8;color:#287757;display:grid;place-items:center;font-size:23px}.toolbar strong{font-size:18px;font-weight:650}.version{color:var(--secondary-text-color,#718078);font-size:12px;margin-left:auto}.menu{display:none;padding:6px 10px;font-size:24px}
        main{max-width:1280px;margin:auto;padding:36px 32px 48px}.intro{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:28px}.eyebrow{color:var(--secondary-text-color,#64766a);font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}h1{font-size:30px;letter-spacing:-.04em;margin:7px 0 9px;font-weight:650}p{color:var(--secondary-text-color,#69786e);line-height:1.55;margin:0}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}.card{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde5de);border-radius:16px;padding:23px;box-shadow:0 3px 15px #13221c05}.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px}h2{font-size:18px;margin:0;font-weight:650}.edit{font-size:12px;padding:7px 10px;min-height:34px}.status{display:flex;align-items:center;gap:7px;font-size:12px;margin-top:10px;color:var(--secondary-text-color,#6b796f)}.dot{width:7px;height:7px;border-radius:50%;background:#9daa9f}.status.heating .dot{background:#d18043}.status.window .dot{background:#5798b6}.measure{margin:30px 0 24px}.temperature{font-size:48px;letter-spacing:-.06em;font-weight:550;line-height:1.2}.unit{font-size:21px;color:var(--secondary-text-color,#6b796f);margin-left:6px}.metrics{display:flex;justify-content:space-between;border-top:1px solid var(--divider-color,#e2e8e2);border-bottom:1px solid var(--divider-color,#e2e8e2);padding:15px 0;margin-bottom:20px;gap:12px}.metric strong{display:block;font-size:15px;margin-top:5px}.metric span{font-size:11px;color:var(--secondary-text-color,#6b796f)}.controls{display:grid;grid-template-columns:1fr 1fr;gap:12px}.controls .target{grid-column:1/-1}.target-row{display:flex;gap:10px;align-items:center}label{display:flex;flex-direction:column;gap:7px;font-size:12px;font-weight:550}input,select{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#d4ded5);border-radius:8px;padding:10px;color:var(--primary-text-color,#23312d);width:100%;min-height:42px}input[type=checkbox]{width:18px;min-height:18px;accent-color:var(--primary-color,#287757)}select[multiple]{min-height:116px}input[type=number]{font-variant-numeric:tabular-nums}.footer{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--secondary-text-color,#69786e);margin-top:24px}.live{width:6px;height:6px;border-radius:50%;background:#52896b}.empty{padding:65px 24px;text-align:center;border:1px dashed var(--divider-color,#c9d6cd);border-radius:16px;background:var(--card-background-color,#fff)}.empty h2{margin:16px 0 10px}.empty button{margin-top:24px}.empty-symbol{font-size:35px;color:var(--secondary-text-color,#69786e)}
        .error{border:1px solid #d89e91;background:var(--card-background-color,#fff);color:var(--error-color,#ae4933);border-radius:9px;padding:13px 16px;margin-bottom:20px}.error:empty{display:none}dialog{border:1px solid var(--divider-color,#d4ded5);border-radius:16px;background:var(--card-background-color,#fff);color:inherit;padding:0;max-width:850px;width:calc(100% - 32px);max-height:90vh;box-shadow:0 25px 80px #0003}dialog::backdrop{background:#10261b66}.dialog-header{display:flex;justify-content:space-between;align-items:center;padding:23px 26px;border-bottom:1px solid var(--divider-color,#dde5de)}.dialog-header p{font-size:12px;margin-top:6px}.dialog-body{padding:25px 26px;max-height:65vh;overflow:auto}.fields{display:grid;grid-template-columns:1fr 1fr;gap:20px}.wide{grid-column:1/-1}.help{font-size:11px;line-height:1.5;font-weight:400;color:var(--secondary-text-color,#69786e)}details{border:1px solid var(--divider-color,#dce4dd);border-radius:10px;margin-top:24px;padding:16px}summary{cursor:pointer;font-size:14px;font-weight:600}details .fields{margin-top:20px}.device{margin-top:22px}.device h3{font-size:14px;margin:0 0 16px}.checkbox{flex-direction:row;align-items:center;font-size:12px;font-weight:400}.dialog-footer{display:flex;justify-content:flex-end;align-items:center;gap:10px;border-top:1px solid var(--divider-color,#dde5de);padding:16px 26px}.danger{color:var(--error-color,#b4523d);margin-right:auto}.confirm{padding:24px}.confirm p{margin:16px 0 24px}.confirm-actions{display:flex;justify-content:flex-end;gap:10px}.saving{font-size:12px;color:var(--secondary-text-color,#69786e)}[hidden]{display:none!important}
        @media(max-width:650px){main{padding:24px 16px}.toolbar{padding:12px 16px}.menu{display:block}.brand{display:none}.intro{align-items:flex-start}h1{font-size:26px}.intro p{font-size:13px}.intro button{white-space:nowrap;padding:9px 11px;font-size:12px}.grid{grid-template-columns:1fr}.fields{grid-template-columns:1fr}.dialog-body{padding:20px 18px}.dialog-header,.dialog-footer{padding:16px 18px}.wide{grid-column:auto}.version{font-size:11px}}
      </style>
      <header class="toolbar"><button class="menu" aria-label="Seitenleiste öffnen">☰</button><span class="brand" aria-hidden="true">♨</span><strong>Thermo Control</strong><span class="version">Raumregelung · 1.1.0</span></header>
      <main><section class="intro"><div><div class="eyebrow">Temperaturen im Blick</div><h1>Deine Räume</h1><p>Heizung steuern und jeden Raum passend konfigurieren.</p></div><button class="primary" id="add-room" disabled>+ Raum hinzufügen</button></section>
      <div id="error" class="error" role="alert"></div><section class="grid" id="rooms" aria-label="Räume"></section><div id="empty" class="empty" hidden><div class="empty-symbol" aria-hidden="true">♨</div><h2>Hier beginnt deine Raumregelung</h2><p>Verbinde Thermostate und einen Temperatursensor mit deinem ersten Raum.</p><button class="primary" id="first-room">Ersten Raum anlegen</button></div><div class="footer"><span class="live"></span><span id="connection">Verbindung wird hergestellt …</span></div></main>
      <dialog id="editor" aria-labelledby="editor-title"><form id="room-form"><div class="dialog-header"><div><h2 id="editor-title">Raum hinzufügen</h2><p>Sensoren, Thermostate und Regelung für diesen Raum.</p></div><button type="button" id="close-editor" aria-label="Schließen">✕</button></div><div class="dialog-body"><div class="error" id="form-error" role="alert"></div><div class="fields">
        <label class="wide">Raumname<input name="name" required maxlength="100" placeholder="z. B. Wohnzimmer"></label>
        <label>Thermostate<select name="trvs" multiple required aria-label="Thermostate"></select><span class="help">Mehrfachauswahl mit Strg / Cmd. Ein Thermostat gehört zu genau einem Raum.</span></label>
        <label>Raumtemperatursensor<select name="temperature_sensor" required></select><span class="help">Externer Sensor für die tatsächliche Temperatur im Raum.</span></label>
        <label class="wide">Fenster- und Türkontakte<select name="window_sensors" multiple aria-label="Fenster- und Türkontakte"></select><span class="help">Optional. Die Heizung startet erst wieder, wenn alle Kontakte geschlossen sind.</span></label>
      </div><details id="advanced"><summary>Regelung, Verzögerungen und Presets</summary><div class="fields" id="numeric-fields"></div></details><details id="devices" open><summary>Thermostate und Kalibrierung</summary><p class="help" style="margin-top:12px">Number-Entität auswählen oder ein MQTT-Topic verwenden. Leere Felder erlauben die automatische Geräteerkennung.</p><div id="device-fields"></div></details></div><div class="dialog-footer"><button type="button" id="delete-room" class="danger" hidden>Raum löschen</button><span id="saving" class="saving" hidden>Wird gespeichert …</span><button type="button" id="cancel-editor">Abbrechen</button><button class="primary" type="submit" id="save-room">Raum speichern</button></div></form></dialog>
      <dialog id="confirm-delete" aria-labelledby="delete-title"><div class="confirm"><h2 id="delete-title">Raum löschen?</h2><p id="delete-description"></p><div class="error" id="delete-error" role="alert"></div><div class="confirm-actions"><button id="cancel-delete">Abbrechen</button><button class="danger" id="confirm-delete-button">Raum löschen</button></div></div></dialog>
    `;
    const root = this.shadowRoot;
    root.querySelector(".menu").onclick = () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
    root.querySelector("#add-room").onclick = () => this._openEditor();
    root.querySelector("#first-room").onclick = () => this._openEditor();
    root.querySelector("#close-editor").onclick = () => this._closeEditor();
    root.querySelector("#cancel-editor").onclick = () => this._closeEditor();
    root.querySelector("#room-form").onsubmit = (event) => { event.preventDefault(); this._save(); };
    root.querySelector('[name="trvs"]').onchange = () => { this._readDevices(); this._renderDevices(); };
    root.querySelector("#delete-room").onclick = () => this._confirmDelete();
    root.querySelector("#cancel-delete").onclick = () => root.querySelector("#confirm-delete").close();
    root.querySelector("#confirm-delete-button").onclick = () => this._delete();
    root.querySelector("#editor").addEventListener("cancel", (event) => { if (this._busy) event.preventDefault(); });
    root.querySelector("#confirm-delete").addEventListener("cancel", (event) => { if (this._busy) event.preventDefault(); });
  }

  _renderCards() {
    const container = this.shadowRoot.querySelector("#rooms");
    container.replaceChildren();
    this._cards.clear();
    this.shadowRoot.querySelector("#empty").hidden = this._data.rooms.length > 0;
    for (const room of this._data.rooms) {
      const card = create("article", undefined, "card");
      card.innerHTML = `<div class="card-head"><h2></h2><button class="edit" type="button">Konfigurieren</button></div><div class="status"><span class="dot"></span><span class="status-text"></span></div><div class="measure"><div class="eyebrow">Raumtemperatur</div><span class="temperature">—</span><span class="unit">°C</span></div><div class="metrics"><div class="metric"><span>Ventilöffnung</span><strong class="position">—</strong></div><div class="metric"><span>Thermostate</span><strong class="trv-count"></strong></div><div class="metric"><span>Fenster</span><strong class="window-status">—</strong></div></div><div class="controls"><label class="target">Solltemperatur<div class="target-row"><input type="number" class="target-input" step="0.5" aria-label="Solltemperatur"><span class="target-unit">°C</span></div></label><label>Heizung<select class="mode" aria-label="Heizung"><option value="off">Aus</option><option value="heat">Heizen</option></select></label><label>Preset<select class="preset" aria-label="Preset"></select></label></div>`;
      card.querySelector("h2").textContent = room.config.name;
      card.querySelector(".edit").onclick = () => this._openEditor(room);
      card.querySelector(".trv-count").textContent = String(room.config.trvs.length);
      const presets = card.querySelector(".preset");
      for (const [value, label] of Object.entries(PRESETS)) { const option = create("option", label); option.value = value; presets.append(option); }
      card.querySelector(".mode").onchange = (event) => this._service(room, "set_hvac_mode", { hvac_mode: event.target.value });
      presets.onchange = (event) => this._service(room, "set_preset_mode", { preset_mode: event.target.value });
      card.querySelector(".target-input").onchange = (event) => { if (event.target.reportValidity()) this._service(room, "set_temperature", { temperature: Number(event.target.value) }); };
      container.append(card);
      this._cards.set(room.id, card);
    }
    this._updateCards();
  }

  _updateCards() {
    if (!this.shadowRoot.querySelector("#rooms")) return;
    const unit = this._hass?.config?.unit_system?.temperature || "°C";
    for (const room of this._data.rooms) {
      const card = this._cards.get(room.id);
      if (!card) continue;
      const state = this._hass?.states?.[room.entity_id];
      const attributes = state?.attributes || {};
      const available = state && !["unknown", "unavailable"].includes(state.state);
      const current = attributes.current_temperature;
      card.querySelector(".temperature").textContent = Number.isFinite(current) ? current.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "—";
      card.querySelector(".unit").textContent = unit;
      card.querySelector(".target-unit").textContent = unit;
      card.querySelector(".position").textContent = Number.isFinite(attributes.valve_position) ? `${attributes.valve_position} %` : "—";
      card.querySelector(".window-status").textContent = !room.config.window_sensors?.length ? "Keine" : attributes.window_open ? "Offen" : "Geschlossen";
      const status = !available ? "Nicht verfügbar" : attributes.window_open ? "Fensterpause" : attributes.hvac_action === "heating" ? "Heizt" : state.state === "heat" ? "Bereit" : "Ausgeschaltet";
      card.querySelector(".status-text").textContent = status;
      card.querySelector(".status").className = `status ${attributes.window_open ? "window" : attributes.hvac_action === "heating" ? "heating" : ""}`;
      const input = card.querySelector(".target-input");
      if (this.shadowRoot.activeElement !== input) input.value = attributes.temperature ?? "";
      input.min = attributes.min_temp ?? 5; input.max = attributes.max_temp ?? 35;
      const mode = card.querySelector(".mode");
      if (this.shadowRoot.activeElement !== mode) mode.value = attributes.desired_hvac_mode || state?.state || "off";
      const preset = card.querySelector(".preset");
      if (this.shadowRoot.activeElement !== preset) preset.value = attributes.preset_mode || "none";
      for (const field of card.querySelectorAll("input,select")) field.disabled = !available;
    }
  }

  async _service(room, service, data) {
    this._error("");
    try { await this._hass.callService("climate", service, { entity_id: room.entity_id, ...data }); }
    catch (error) { this._error(this._message(error)); }
    this._updateCards();
  }

  _fillSelect(select, domain, values = [], multiple = false) {
    const selected = new Set(Array.isArray(values) ? values : [values]);
    select.replaceChildren();
    if (!multiple) { const option = create("option", "Bitte auswählen …"); option.value = ""; select.append(option); }
    const virtualIds = new Set(this._data.rooms.map((room) => room.entity_id));
    const states = this._hass?.states || {};
    const ids = new Set(Object.keys(states).filter((id) => id.startsWith(`${domain}.`) && !virtualIds.has(id)));
    for (const id of selected) if (id) ids.add(id);
    for (const id of [...ids].sort((a, b) => (states[a]?.attributes?.friendly_name || a).localeCompare(states[b]?.attributes?.friendly_name || b, "de"))) {
      const option = create("option", `${states[id]?.attributes?.friendly_name || id} · ${id}`);
      option.value = id; option.selected = selected.has(id); select.append(option);
    }
  }

  _numberFields(container, definitions, values) {
    container.replaceChildren();
    for (const [name, title, unit, min, max, step] of definitions) {
      const label = create("label", `${title} (${unit})`);
      const input = document.createElement("input");
      Object.assign(input, { type: "number", name, min, max, step, required: true, value: values[name] ?? "" });
      label.append(input); container.append(label);
    }
  }

  _openEditor(room = null) {
    this._editing = room;
    this._editRevision = this._data.revision;
    this._draft = structuredClone(room?.config || { ...this._data.defaults, name: "", trvs: [], temperature_sensor: "", devices: {} });
    const root = this.shadowRoot, form = root.querySelector("#room-form");
    root.querySelector("#form-error").textContent = "";
    root.querySelector("#editor-title").textContent = room ? "Raum konfigurieren" : "Raum hinzufügen";
    form.elements.name.value = this._draft.name;
    this._fillSelect(form.elements.trvs, "climate", this._draft.trvs, true);
    this._fillSelect(form.elements.temperature_sensor, "sensor", this._draft.temperature_sensor);
    this._fillSelect(form.elements.window_sensors, "binary_sensor", this._draft.window_sensors || [], true);
    this._numberFields(root.querySelector("#numeric-fields"), NUMBERS, this._draft);
    this._renderDevices();
    root.querySelector("#delete-room").hidden = !room;
    root.querySelector("#editor").showModal();
    form.elements.name.focus();
  }

  _selectedTrvs() { return [...this.shadowRoot.querySelector('[name="trvs"]').selectedOptions].map((option) => option.value); }

  _renderDevices() {
    const container = this.shadowRoot.querySelector("#device-fields");
    container.replaceChildren();
    for (const entityId of this._selectedTrvs()) {
      const device = { ...this._data.device_defaults, ...this._draft.devices?.[entityId] };
      if (!this._draft.devices?.[entityId]?.regulated_mode) {
        const modes = this._hass.states[entityId]?.attributes.hvac_modes || [];
        if (modes.includes("auto") && !modes.includes("heat")) device.regulated_mode = "auto";
      }
      const section = create("section", undefined, "device"); section.dataset.entityId = entityId;
      section.append(create("h3", this._hass.states[entityId]?.attributes.friendly_name || entityId));
      const fields = create("div", undefined, "fields");
      for (const [key, title, domain] of [["calibration_entity", "Kalibrierungs-Number-Entität", "number"], ["position_entity", "Sensor für die Ventilöffnung", "sensor"], ["internal_sensor", "Interner Temperatursensor (optional)", "sensor"]]) {
        const label = create("label", title), select = document.createElement("select"); select.name = key;
        this._fillSelect(select, domain, device[key] || ""); label.append(select); fields.append(label);
      }
      const modeLabel = create("label", "Regelnder HVAC-Modus"), mode = document.createElement("select"); mode.name = "regulated_mode";
      for (const value of ["heat", "auto"]) { const option = create("option", value); option.value = value; mode.append(option); }
      mode.value = device.regulated_mode; modeLabel.append(mode); fields.append(modeLabel);
      const topicLabel = create("label", "MQTT-Topic (alternativ zur Number-Entität)", "wide"), topic = document.createElement("input"); topic.name = "calibration_topic"; topic.value = device.calibration_topic || ""; topic.placeholder = "zigbee2mqtt/wohnzimmer/set/local_temperature_calibration"; topicLabel.append(topic); fields.append(topicLabel);
      const numeric = create("div", undefined, "fields wide"); this._numberFields(numeric, DEVICE_NUMBERS, device); fields.append(numeric);
      const checkboxLabel = create("label", undefined, "checkbox wide"), checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.name = "temperature_is_calibrated"; checkbox.checked = device.temperature_is_calibrated;
      checkboxLabel.append(checkbox, create("span", "Die interne Temperatur enthält den bestehenden Kalibrierungsoffset bereits.")); fields.append(checkboxLabel);
      section.append(fields); container.append(section);
    }
    if (!container.hasChildNodes()) container.append(create("p", "Wähle oben mindestens ein Thermostat aus.", "help"));
  }

  _readDevices() {
    this._draft.devices ||= {};
    for (const section of this.shadowRoot.querySelectorAll(".device")) {
      const device = {};
      for (const field of section.querySelectorAll("input,select")) {
        if (field.type === "checkbox") device[field.name] = field.checked;
        else if (field.type === "number") device[field.name] = Number(field.value);
        else if (field.value) device[field.name] = field.value;
      }
      this._draft.devices[section.dataset.entityId] = device;
    }
  }

  _setBusy(busy) {
    this._busy = busy;
    for (const field of this.shadowRoot.querySelectorAll("dialog input,dialog select,dialog button")) field.disabled = busy;
    this.shadowRoot.querySelector("#saving").hidden = !busy;
  }

  async _save() {
    if (this._busy) return;
    const form = this.shadowRoot.querySelector("#room-form");
    if (!form.reportValidity()) return;
    this._readDevices();
    const config = { ...this._draft, name: form.elements.name.value.trim(), trvs: this._selectedTrvs(), temperature_sensor: form.elements.temperature_sensor.value, window_sensors: [...form.elements.window_sensors.selectedOptions].map((option) => option.value) };
    config.devices = Object.fromEntries(config.trvs.map((id) => [id, this._draft.devices[id]]));
    for (const [name] of NUMBERS) config[name] = Number(form.elements[name].value);
    const message = { type: "thermo_control/save_room", config, revision: this._editRevision };
    if (this._editing) message.room_id = this._editing.id;
    this._setBusy(true);
    try { await this._hass.callWS(message); this.shadowRoot.querySelector("#editor").close(); }
    catch (error) { this.shadowRoot.querySelector("#form-error").textContent = this._message(error); this.shadowRoot.querySelector(".dialog-body").scrollTop = 0; }
    finally { this._setBusy(false); }
  }

  _closeEditor() { if (!this._busy) this.shadowRoot.querySelector("#editor").close(); }

  _confirmDelete() {
    this.shadowRoot.querySelector("#delete-description").textContent = `„${this._editing.config.name}“ und die virtuelle Climate-Entität werden entfernt. Die physischen Thermostate bleiben erhalten.`;
    this.shadowRoot.querySelector("#delete-error").textContent = "";
    this.shadowRoot.querySelector("#confirm-delete").showModal();
  }

  async _delete() {
    if (this._busy) return;
    this._setBusy(true);
    try {
      await this._hass.callWS({ type: "thermo_control/delete_room", room_id: this._editing.id, revision: this._editRevision });
      this.shadowRoot.querySelector("#confirm-delete").close(); this.shadowRoot.querySelector("#editor").close();
    } catch (error) { this.shadowRoot.querySelector("#delete-error").textContent = this._message(error); }
    finally { this._setBusy(false); }
  }

  _message(error) { return error?.message || "Die Aktion konnte nicht ausgeführt werden. Bitte erneut versuchen."; }
  _error(message) { this.shadowRoot.querySelector("#error").textContent = message; }
}

if (!customElements.get("thermo-control-panel")) customElements.define("thermo-control-panel", ThermoControlPanel);
