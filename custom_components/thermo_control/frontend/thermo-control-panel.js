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

/** Searchable entity selection with keyboard support and live state previews. */
class ThermoControlEntityPicker extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._values = [];
    this._query = "";
    this._active = -1;
    this._opened = false;
    this._options = {};
    this._results = [];
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;min-width:0;font:inherit;color:inherit}*{box-sizing:border-box}
        label{display:block;margin-bottom:7px;font-size:12px;font-weight:550}.search{position:relative}
        input,button{font:inherit;color:inherit}input{width:100%;min-height:42px;padding:10px;border:1px solid var(--divider-color,#d4ded5);border-radius:8px;background:var(--card-background-color,#fff)}
        input:focus-visible,button:focus-visible{outline:3px solid var(--primary-color,#548269);outline-offset:2px}input:disabled,button:disabled{opacity:.55}
        .results{margin-top:4px;max-height:240px;overflow:auto;border:1px solid var(--divider-color,#d4ded5);border-radius:9px;background:var(--card-background-color,#fff);box-shadow:0 6px 20px #0002}
        .option{display:block;width:100%;text-align:left;padding:10px 12px;border:0;border-bottom:1px solid var(--divider-color,#e2e8e2);background:transparent;cursor:pointer}.option:last-child{border-bottom:0}.option:hover,.option.active{background:var(--secondary-background-color,#eef3ef)}
        .name{font-size:12px;font-weight:600;overflow-wrap:anywhere}.id,.preview,.hint{font-size:11px;font-weight:400;color:var(--secondary-text-color,#69786e);overflow-wrap:anywhere;line-height:1.5}.preview{color:var(--primary-text-color,#23312d)}.empty{padding:12px;font-size:12px}
        .selections{display:grid;gap:6px;margin-top:7px}.selection{display:flex;gap:8px;align-items:center;padding:9px 10px;border:1px solid var(--divider-color,#dce4dd);border-radius:8px;background:var(--secondary-background-color,#f0f5f1)}.selection>div{flex:1;min-width:0}.remove{flex:none;border:0;border-radius:6px;background:transparent;padding:4px 7px;min-height:30px;cursor:pointer}
        .hint{margin-top:5px}[hidden]{display:none!important}
      </style>
      <label for="search"></label><div class="search"><input id="search" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="results" autocomplete="off" spellcheck="false"><div id="results" class="results" role="listbox" hidden></div></div><div class="selections"></div><div class="hint" role="status"></div>
    `;
    this._input = this.shadowRoot.querySelector("input");
    this._list = this.shadowRoot.querySelector(".results");
    this._selections = this.shadowRoot.querySelector(".selections");
    this._hint = this.shadowRoot.querySelector(".hint");
    this._input.addEventListener("input", () => {
      this._query = this._input.value;
      if (!this._options.multiple && !this._query.trim() && this._values.length) {
        this.value = "";
        this.dispatchEvent(new Event("change", { bubbles: true }));
      }
      this._active = -1;
      this._input.setCustomValidity("");
      this._opened = true;
      this._renderResults();
    });
    this._input.addEventListener("change", (event) => event.stopPropagation());
    this._input.addEventListener("focus", () => { if (!this._disabled) { this._opened = true; this._renderResults(); } });
    this._input.addEventListener("keydown", (event) => this._keyDown(event));
    this.shadowRoot.addEventListener("focusout", () => queueMicrotask(() => {
      if (!this.shadowRoot.activeElement) this.close();
    }));
  }

  configure(options) {
    this.close();
    this._options = options;
    this.setAttribute("name", options.name);
    this.shadowRoot.querySelector("label").textContent = options.label;
    this._input.placeholder = options.placeholder || "Name oder Entitäts-ID eingeben …";
    this._list.setAttribute("aria-label", `${options.label}: Suchergebnisse`);
    this._list.setAttribute("aria-multiselectable", String(Boolean(options.multiple)));
    this.value = options.values;
  }

  set hass(value) { this._hass = value; this._refresh(); }
  get value() { return this._options.multiple ? [...this._values] : this._values[0] || ""; }
  set value(value) {
    this._values = [...new Set((Array.isArray(value) ? value : [value]).filter(Boolean))];
    this._query = "";
    this._input.value = this._options.multiple ? "" : this._values[0] || "";
    this._input.setCustomValidity("");
    this._refresh();
  }
  set disabled(value) {
    this._disabled = Boolean(value);
    for (const field of this.shadowRoot.querySelectorAll("input,button")) field.disabled = this._disabled;
    if (this._disabled) this.close();
  }
  set excluded(values) { this._options.excluded = new Set(values); this._renderResults(); }

  _name(id) { return this._hass?.states?.[id]?.attributes?.friendly_name || id; }

  _preview(id) {
    const state = this._hass?.states?.[id];
    if (!state || ["unknown", "unavailable"].includes(state.state)) return "Nicht verfügbar";
    const attributes = state.attributes || {};
    if (id.startsWith("climate.")) {
      const temperature = attributes.current_temperature;
      const mode = { heat: "Heizen", auto: "Automatisch", off: "Aus", cool: "Kühlen" }[state.state] || state.state;
      const unit = attributes.temperature_unit || this._hass?.config?.unit_system?.temperature || "°C";
      return Number.isFinite(temperature) ? `${temperature.toLocaleString("de-DE")} ${unit} · ${mode}` : mode;
    }
    if (id.startsWith("binary_sensor.")) return state.state === "on" ? "Offen" : state.state === "off" ? "Geschlossen" : state.state;
    return `${state.state}${attributes.unit_of_measurement ? ` ${attributes.unit_of_measurement}` : ""}`;
  }

  _candidates() {
    const { domain, temperatureOnly, excluded } = this._options;
    return Object.keys(this._hass?.states || {}).filter((id) => {
      if (!id.startsWith(`${domain}.`) || excluded?.has(id)) return false;
      return !temperatureOnly || ["°C", "°F", "K"].includes(this._hass.states[id].attributes?.unit_of_measurement);
    });
  }

  _refresh() {
    // Update existing selections in place so HA state updates preserve focus.
    const existing = new Map([...this._selections.children].map((node) => [node.dataset.entityId, node]));
    for (const id of this._values) {
      let node = existing.get(id);
      if (!node) {
        node = create("div", undefined, "selection"); node.dataset.entityId = id;
        const text = create("div"); text.append(create("div", "", "name"), create("div", id, "id"), create("div", "", "preview"));
        const remove = create("button", "✕", "remove"); remove.type = "button";
        remove.onclick = () => {
          this.value = this._values.filter((value) => value !== id);
          this._input.focus();
          this.dispatchEvent(new Event("change", { bubbles: true }));
        };
        node.append(text, remove); this._selections.append(node);
      }
      node.querySelector(".name").textContent = this._name(id);
      node.querySelector(".preview").textContent = this._preview(id);
      const remove = node.querySelector("button");
      remove.setAttribute("aria-label", `${this._name(id)} entfernen`); remove.disabled = Boolean(this._disabled);
      existing.delete(id);
    }
    for (const node of existing.values()) node.remove();
    this._hint.textContent = this._values.length ? (this._options.multiple ? `${this._values.length} ausgewählt` : "") : this._options.emptyLabel || "Keine Auswahl";
    this._renderResults();
  }

  _renderResults() {
    this._list.hidden = !this._opened;
    this._input.setAttribute("aria-expanded", String(this._opened));
    if (!this._opened) return;
    const fold = (value) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("de");
    const tokens = fold(this._query.trim()).split(/\s+/).filter(Boolean);
    const matching = this._candidates().filter((id) => (!this._options.multiple || !this._values.includes(id)) && tokens.every((token) => fold(`${this._name(id)} ${id}`).includes(token)));
    matching.sort((a, b) => Number(b === this._query.trim()) - Number(a === this._query.trim()) || this._name(a).localeCompare(this._name(b), "de") || a.localeCompare(b));
    const activeId = this._results[this._active];
    this._results = matching.slice(0, 40);
    this._active = activeId ? this._results.indexOf(activeId) : -1;
    this._list.replaceChildren();
    this._results.forEach((id, index) => {
      const option = create("button", undefined, "option"); option.type = "button"; option.tabIndex = -1; option.id = `option-${index}`; option.setAttribute("role", "option"); option.setAttribute("aria-selected", String(this._values.includes(id))); option.disabled = Boolean(this._disabled);
      option.append(create("div", this._name(id), "name"), create("div", id, "id"), create("div", this._preview(id), "preview"));
      option.onmousedown = (event) => event.preventDefault();
      option.onclick = () => this._choose(id);
      this._list.append(option);
    });
    if (!matching.length) this._list.append(create("div", "Keine passenden Entitäten gefunden.", "empty"));
    else if (matching.length > this._results.length) this._list.append(create("div", `${matching.length} Treffer – Suche eingrenzen.`, "empty"));
    this._highlight();
  }

  _highlight() {
    for (const [index, option] of [...this._list.querySelectorAll(".option")].entries()) option.classList.toggle("active", index === this._active);
    const selected = this._list.querySelector(".active");
    if (selected) { this._input.setAttribute("aria-activedescendant", selected.id); selected.scrollIntoView({ block: "nearest" }); }
    else this._input.removeAttribute("aria-activedescendant");
  }

  _choose(id) {
    if (this._disabled) return;
    this.value = this._options.multiple ? [...this._values, id] : id;
    this.close();
    this.dispatchEvent(new Event("change", { bubbles: true }));
  }

  _keyDown(event) {
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault(); this._opened = true; this._renderResults();
      if (this._results.length) this._active = (this._active + (event.key === "ArrowDown" ? 1 : this._active < 0 ? 0 : -1) + this._results.length) % this._results.length;
      this._highlight();
    } else if (event.key === "Enter") {
      event.preventDefault();
      const exact = this._candidates().find((id) => id === this._input.value.trim());
      const id = this._results[this._active] || exact || (this._opened ? this._results[0] : null);
      if (id) this._choose(id);
      else this.reportValidity();
    } else if (event.key === "Escape" && this._opened) {
      event.preventDefault(); event.stopPropagation(); this.close();
    }
  }

  commit() {
    const query = this._query.trim();
    if (!query) return;
    const id = this._candidates().find((id) => id === query);
    if (id) this._choose(id);
  }

  reportValidity() {
    const pending = this._query.trim();
    const message = pending ? "Bitte eine Entität aus den Suchergebnissen auswählen oder die Suche leeren." : this._options.required && !this._values.length ? "Bitte mindestens ein Thermostat auswählen." : "";
    this._input.setCustomValidity(message);
    return this._input.reportValidity();
  }

  close() { this._opened = false; this._active = -1; this._input.removeAttribute("aria-activedescendant"); this._list.hidden = true; this._input.setAttribute("aria-expanded", "false"); }
}

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
      this._updatePickers();
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
    this._updatePickers();
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
      <header class="toolbar"><button class="menu" aria-label="Seitenleiste öffnen">☰</button><span class="brand" aria-hidden="true">♨</span><strong>Thermo Control</strong><span class="version">Raumregelung · 1.2.0</span></header>
      <main><section class="intro"><div><div class="eyebrow">Temperaturen im Blick</div><h1>Deine Räume</h1><p>Heizung steuern und jeden Raum passend konfigurieren.</p></div><button class="primary" id="add-room" disabled>+ Raum hinzufügen</button></section>
      <div id="error" class="error" role="alert"></div><section class="grid" id="rooms" aria-label="Räume"></section><div id="empty" class="empty" hidden><div class="empty-symbol" aria-hidden="true">♨</div><h2>Hier beginnt deine Raumregelung</h2><p>Verbinde Thermostate mit deinem ersten Raum. Ein externer Temperatursensor ist optional.</p><button class="primary" id="first-room">Ersten Raum anlegen</button></div><div class="footer"><span class="live"></span><span id="connection">Verbindung wird hergestellt …</span></div></main>
      <dialog id="editor" aria-labelledby="editor-title"><form id="room-form"><div class="dialog-header"><div><h2 id="editor-title">Raum hinzufügen</h2><p>Sensoren, Thermostate und Regelung für diesen Raum.</p></div><button type="button" id="close-editor" aria-label="Schließen">✕</button></div><div class="dialog-body"><div class="error" id="form-error" role="alert"></div><div class="fields">
        <label class="wide">Raumname<input name="name" required maxlength="100" placeholder="z. B. Wohnzimmer"></label>
        <div><thermo-control-entity-picker name="trvs"></thermo-control-entity-picker><p class="help">Nach Namen oder Entitäts-ID suchen und Thermostate einzeln hinzufügen.</p></div>
        <div><thermo-control-entity-picker name="temperature_sensor"></thermo-control-entity-picker><p class="help">Optional. Ohne externen Sensor wird die gemessene Thermostattemperatur verwendet; bei mehreren Geräten der Mittelwert. Keine Offset-Kalibrierung.</p></div>
        <div class="wide"><thermo-control-entity-picker name="window_sensors"></thermo-control-entity-picker><p class="help">Optional. Die Heizung startet erst wieder, wenn alle Kontakte geschlossen sind.</p></div>
      </div><details id="advanced"><summary>Regelung, Verzögerungen und Presets</summary><div class="fields" id="numeric-fields"></div></details><details id="devices" open><summary>Thermostate und Kalibrierung</summary><p class="help" style="margin-top:12px">Die Offset-Kalibrierung ist nur mit externem Raumtemperatursensor aktiv. Number-Entität auswählen oder ein MQTT-Topic verwenden. Leere Felder erlauben die automatische Geräteerkennung.</p><div id="device-fields"></div></details></div><div class="dialog-footer"><button type="button" id="delete-room" class="danger" hidden>Raum löschen</button><span id="saving" class="saving" hidden>Wird gespeichert …</span><button type="button" id="cancel-editor">Abbrechen</button><button class="primary" type="submit" id="save-room">Raum speichern</button></div></form></dialog>
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
    root.addEventListener("pointerdown", (event) => {
      for (const picker of root.querySelectorAll("thermo-control-entity-picker")) if (!event.composedPath().includes(picker)) picker.close();
    });
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
      card.innerHTML = `<div class="card-head"><h2></h2><button class="edit" type="button">Konfigurieren</button></div><div class="status"><span class="dot"></span><span class="status-text"></span></div><div class="measure"><div class="eyebrow">Raumtemperatur</div><span class="temperature">—</span><span class="unit">°C</span><div class="help temperature-source"></div></div><div class="metrics"><div class="metric"><span>Ventilöffnung</span><strong class="position">—</strong></div><div class="metric"><span>Thermostate</span><strong class="trv-count"></strong></div><div class="metric"><span>Fenster</span><strong class="window-status">—</strong></div></div><div class="controls"><label class="target">Solltemperatur<div class="target-row"><input type="number" class="target-input" step="0.5" aria-label="Solltemperatur"><span class="target-unit">°C</span></div></label><label>Heizung<select class="mode" aria-label="Heizung"><option value="off">Aus</option><option value="heat">Heizen</option></select></label><label>Preset<select class="preset" aria-label="Preset"></select></label></div>`;
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
      card.querySelector(".temperature-source").textContent = room.config.temperature_sensor ? "Externer Sensor" : room.config.trvs.length > 1 ? "Mittelwert der Thermostattemperaturen" : "Thermostattemperatur";
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

  _climateExclusions() {
    return this._data.rooms.flatMap((room) => [room.entity_id, ...(room.id === this._editing?.id ? [] : room.config.trvs)]).filter(Boolean);
  }

  _configurePicker(picker, name, label, domain, values, options = {}) {
    picker.configure({ name, label, domain, values, ...options });
    picker.hass = this._hass;
    return picker;
  }

  _updatePickers() {
    for (const picker of this.shadowRoot.querySelectorAll("thermo-control-entity-picker")) {
      if (picker.getAttribute("name") === "trvs") picker.excluded = this._climateExclusions();
      picker.hass = this._hass;
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
    this._configurePicker(root.querySelector('[name="trvs"]'), "trvs", "Thermostate", "climate", this._draft.trvs, { multiple: true, required: true, excluded: new Set(this._climateExclusions()) });
    this._configurePicker(root.querySelector('[name="temperature_sensor"]'), "temperature_sensor", "Externer Raumtemperatursensor (optional)", "sensor", this._draft.temperature_sensor, { temperatureOnly: true, emptyLabel: "Thermostattemperatur verwenden" });
    this._configurePicker(root.querySelector('[name="window_sensors"]'), "window_sensors", "Fenster- und Türkontakte", "binary_sensor", this._draft.window_sensors || [], { multiple: true });
    this._numberFields(root.querySelector("#numeric-fields"), NUMBERS, this._draft);
    this._renderDevices();
    root.querySelector("#delete-room").hidden = !room;
    root.querySelector("#editor").showModal();
    form.elements.name.focus();
  }

  _selectedTrvs() { return this.shadowRoot.querySelector('[name="trvs"]').value; }

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
        const picker = document.createElement("thermo-control-entity-picker");
        this._configurePicker(picker, key, title, domain, device[key] || "", { temperatureOnly: key === "internal_sensor", emptyLabel: "Automatische Erkennung / keine Zuordnung" }); fields.append(picker);
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
      for (const picker of section.querySelectorAll("thermo-control-entity-picker")) if (picker.value) device[picker.getAttribute("name")] = picker.value;
      this._draft.devices[section.dataset.entityId] = device;
    }
  }

  _setBusy(busy) {
    this._busy = busy;
    for (const field of this.shadowRoot.querySelectorAll("dialog input,dialog select,dialog button")) field.disabled = busy;
    for (const picker of this.shadowRoot.querySelectorAll("thermo-control-entity-picker")) picker.disabled = busy;
    this.shadowRoot.querySelector("#saving").hidden = !busy;
  }

  async _save() {
    if (this._busy) return;
    const form = this.shadowRoot.querySelector("#room-form");
    if (!form.reportValidity()) return;
    const root = this.shadowRoot;
    // Commit exact IDs typed into the main fields before TRV changes rebuild device fields.
    for (const name of ["trvs", "temperature_sensor", "window_sensors"]) root.querySelector(`[name="${name}"]`).commit();
    for (const picker of root.querySelectorAll("thermo-control-entity-picker")) {
      picker.commit();
      if (!picker.reportValidity()) return;
    }
    this._readDevices();
    const config = { ...this._draft, name: form.elements.name.value.trim(), trvs: this._selectedTrvs(), temperature_sensor: root.querySelector('[name="temperature_sensor"]').value || null, window_sensors: root.querySelector('[name="window_sensors"]').value };
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

if (!customElements.get("thermo-control-entity-picker")) customElements.define("thermo-control-entity-picker", ThermoControlEntityPicker);
if (!customElements.get("thermo-control-panel")) customElements.define("thermo-control-panel", ThermoControlPanel);
