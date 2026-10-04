/* Local Home Assistant custom panel. No build step or external resources. */
const PRESETS = { none: "Manuell", eco: "Eco", comfort: "Komfort", boost: "Boost", away: "Abwesend" };
const TARGET_STEP = 0.5;
const TARGET_MIN = 5;
const TARGET_MAX = 30;
const TARGET_DEBOUNCE = 400;
const TARGET_CONFIRM_TIMEOUT = 10000;
const NUMBERS = [
  ["tolerance", "Hysterese", "°C", 0.1, 2, 0.1],
  ["trend_window", "Trend-Zeitfenster", "Min.", 30, 60, 1],
  ["inertia", "Trägheitsfaktor", "Faktor", 0, 2, 0.1],
  ["lookahead", "Maximale Vorlaufzeit", "Min.", 0, 240, 5],
  ["cycle_minutes", "PWM-Zyklus", "Min.", 30, 60, 1],
  ["minimum_on", "Mindestlaufzeit der Ventile", "s", 60, 1800, 30],
  ["minimum_off", "Mindestruhezeit der Ventile", "s", 60, 1800, 30],
  ["proportional_band", "Proportionalband", "°C", 0.5, 5, 0.1],
  ["integral_hours", "Integrationszeit", "h", 1, 24, 0.5],
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
const CONTROL_VALUES = { tolerance: 0.2, trend_window: 45, inertia: 1, lookahead: 180, cycle_minutes: 45, minimum_on: 300, minimum_off: 300, proportional_band: 2, integral_hours: 6 };
const CONTROL_NUMBERS = NUMBERS.filter(([key]) => key in CONTROL_VALUES);
const SYSTEM_VALUES = { master_offset: 0, calibration_interval: 600, control: CONTROL_VALUES, groups: [], heat_pump: { flow_sensor: null, target_sensor: null, mode_entity: null, compressor_entity: null, automatic_states: ["automatic", "automatik", "automatisch", "auto"], interlock: false, minimum_flow: 25, flow_margin: 2 } };
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
      if (!(Array.isArray(domain) ? domain : [domain]).some((item) => id.startsWith(`${item}.`)) || excluded?.has(id)) return false;
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

const SCHEDULE_DAYS = { monday: "Mo", tuesday: "Di", wednesday: "Mi", thursday: "Do", friday: "Fr", saturday: "Sa", sunday: "So" };
const CLIMATE_PRESETS = { ...PRESETS, schedule: "Auto · Zeitplan" };

class ThermoControlScheduleEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._drafts = new Map(); this._days = ["monday"]; this._dirty = false; }
  connectedCallback() { if (!this.shadowRoot.hasChildNodes()) this._build(); if (this._context) this._refresh(); }
  set context(value) { this._context = value; if (this.isConnected) this._refresh(); }
  _owners() { return [...(this._context?.data.rooms || []).map((room) => ({ key: `room:${room.id}`, name: room.config.name })), ...(this._context?.data.settings.groups || []).map((group) => ({ key: `group:${group.id}`, name: `Gruppe: ${group.name}` }))]; }
  _plan(key) { return (this._context.data.schedules || []).find((plan) => (plan.room_id ? `room:${plan.room_id}` : `group:${plan.group_id}`) === key); }
  _refresh() {
    const owners = this._owners(), fingerprint = JSON.stringify(owners), select = this.shadowRoot.querySelector("#owner");
    if (fingerprint !== this._ownersFingerprint) {
      this._ownersFingerprint = fingerprint; select.replaceChildren();
      for (const owner of owners) { const option = create("option", owner.name); option.value = owner.key; select.append(option); }
      if (owners.some((owner) => owner.key === this._owner)) select.value = this._owner;
      else { this._owner = select.value; this._dirty = false; }
    }
    this.shadowRoot.querySelector("#schedule-empty").hidden = Boolean(owners.length);
    this.shadowRoot.querySelector("#schedule-editor").hidden = !owners.length;
    const version = JSON.stringify([this._context.data.schedule_revision, this._owner, this._context.data.schedules]);
    if (version !== this._version && !this._dirty && !this._editing && !this._saving) { this._version = version; this._load(this._owner); }
    this.shadowRoot.querySelector("#zone").textContent = `Zeitzone: ${this._context.data.time_zone || this._context.hass.config?.time_zone || "Home Assistant"}`;
    this.shadowRoot.querySelector("#copy").disabled = this._dirty || !this._plan(this._owner) || this._saving;
  }
  selectOwner(key) { const select = this.shadowRoot.querySelector("#owner"); this._remember(); this._owner = key; select.value = key; this._load(key); }
  _remember() { if (this._owner && this._draft) this._drafts.set(this._owner, { draft: structuredClone(this._draft), revision: this._revision, dirty: this._dirty }); }
  _load(key) {
    if (!key) return;
    const cached = this._drafts.get(key);
    this._draft = cached?.dirty ? structuredClone(cached.draft) : structuredClone(this._plan(key) || { [key.startsWith("room:") ? "room_id" : "group_id"]: key.split(":")[1], enabled: false, weekdays: Object.fromEntries(Object.keys(SCHEDULE_DAYS).map((day) => [day, []])), fallback_temp: 18, override_hours: 0, preheat: false, heating_rate: 0.5, max_preheat_minutes: 180 });
    this._revision = cached?.dirty ? cached.revision : this._context.data.schedule_revision || 0;
    this._dirty = Boolean(cached?.dirty); this._editing = false;
    const form = this.shadowRoot.querySelector("#plan-form");
    for (const key of ["enabled", "fallback_temp", "override_hours", "preheat", "heating_rate", "max_preheat_minutes"]) {
      const field = form.elements[key]; if (field.type === "checkbox") field.checked = Boolean(this._draft[key]); else field.value = this._draft[key];
    }
    const profiles = this.shadowRoot.querySelector("#profile"); profiles.replaceChildren();
    const blank = create("option", "Vorlage wählen"); blank.value = ""; profiles.append(blank);
    for (const [id, profile] of Object.entries(this._context.data.schedule_templates || {})) { const option = create("option", profile.name); option.value = id; profiles.append(option); }
    this.shadowRoot.querySelector("#block-form").hidden = true; this._draw();
  }
  _build() {
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;color:var(--primary-text-color,#23312d)}*{box-sizing:border-box}section{padding:20px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde5de);border-radius:14px}h2{margin:0 0 16px;font-size:20px}p{font-size:13px;line-height:1.5}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}label{display:flex;flex-direction:column;gap:6px;font-size:13px;min-width:0}input,select,button{font:inherit;color:inherit;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#d4ded5);border-radius:8px;min-height:44px;padding:8px;width:100%;min-width:0}button{cursor:pointer;width:auto}button:disabled{opacity:.5;cursor:default}.checkbox{display:flex;flex-direction:row;align-items:center;margin:16px 0}.checkbox input{width:20px;min-height:20px}.days,.actions{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0}.days [aria-pressed=true],.primary{background:var(--primary-color,#287757);color:white}.timeline{position:relative;height:70px;border:1px dashed var(--divider-color,#ddd);border-radius:8px;overflow:hidden;background:var(--secondary-background-color,#eef3ef);margin-top:20px}.timeline button{position:absolute;top:0;height:100%;padding:4px 1px;border-radius:0;overflow:hidden;color:#fff;white-space:nowrap;font-size:12px}.axis{display:flex;justify-content:space-between;font-size:11px;margin-top:6px}.blocks{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin:16px 0}.blocks button{text-align:left;white-space:normal}.help{color:var(--secondary-text-color,#69786e)}[role=alert]{color:var(--error-color,#ae4933);overflow-wrap:anywhere}#block-form{padding:14px;border:1px solid var(--divider-color,#ddd);border-radius:10px;margin:16px 0}dialog{max-width:600px;width:calc(100% - 32px);max-height:85vh;overflow:auto;background:var(--card-background-color,#fff);color:inherit;border:1px solid var(--divider-color,#ddd);border-radius:14px;padding:20px}dialog::backdrop{background:#0006}select[multiple]{min-height:150px}[hidden]{display:none!important}@media(max-width:600px){section{padding:14px}.fields{grid-template-columns:minmax(0,1fr)}.blocks{grid-template-columns:minmax(0,1fr)}}
      </style><section><h2>Wochenzeitpläne</h2><label>Raum oder Gruppe<select id="owner"></select></label><p id="schedule-empty">Lege zuerst einen Raum oder eine Gruppe an.</p><div id="schedule-editor"><p class="help" id="zone"></p><p class="help">Auto · Zeitplan steuert Thermo Control in Heizen. Geräte-Auto verwendet weiterhin den eigenen Thermostatzeitplan. Raumpläne haben Vorrang vor Gruppenplänen.</p><form id="plan-form"><label class="checkbox"><input name="enabled" type="checkbox">Automatikmodus aktiv</label><div class="fields"><label>Vorlage<select id="profile"></select></label><label>Sollwert für Zeitlücken (°C)<input name="fallback_temp" type="number" min="5" max="30" step="0.5" required></label><label>Manueller Override (Stunden; 0 = nächster Schaltpunkt)<input name="override_hours" type="number" min="0" max="48" step="0.5" required></label><label class="checkbox"><input name="preheat" type="checkbox">Vorausschauendes Vorheizen bei FBH</label><label>Aufheizkoeffizient (°C pro Stunde)<input name="heating_rate" type="number" min="0.1" max="5" step="0.1" required></label><label>Maximales Vorheizen (Minuten)<input name="max_preheat_minutes" type="number" min="0" max="360" step="1" required></label></div><p class="help">Vorheizen berücksichtigt Raumtemperatur und die maximale Vorlaufzeit des Raums. Nachtblöcke dürfen über Mitternacht reichen; 24:00 bezeichnet das Tagesende.</p><div class="days" id="days" role="group" aria-label="Tagesauswahl"></div><p class="help" id="day-note"></p><div class="timeline" id="timeline" aria-label="24-Stunden-Zeitachse"></div><div class="axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div><div class="blocks" id="blocks"></div><button type="button" id="add">+ Block hinzufügen</button><div class="actions"><button type="submit" class="primary">Zeitplan speichern</button><button type="button" id="copy">Plan auf andere Räume übertragen</button><button type="button" id="reset">Gespeicherten Plan laden</button></div></form><form id="block-form" hidden><h3 id="block-title">Zeitblock bearbeiten</h3><div class="fields"><label>Startzeit<input name="from" type="time" required></label><label>Endzeit<input name="to" type="text" placeholder="HH:MM oder 24:00" pattern="([01][0-9]|2[0-3]):[0-5][0-9]|24:00" required></label><label>Block-Sollwert (°C)<input name="temp" type="number" min="5" max="30" step="0.5" required></label></div><div class="actions"><button type="submit">Block übernehmen</button><button type="button" id="delete-block">Block löschen</button><button type="button" id="cancel-block">Abbrechen</button></div></form><p id="message" role="alert"></p></div></section><dialog id="copy-dialog"><h2>Zeitplan kopieren</h2><label>Kopierumfang<select id="copy-kind"><option value="week">Gesamte Woche</option><option value="day">Ausgewählter Tag</option></select></label><label>Zielräume und Gruppen<select id="copy-targets" multiple></select></label><label id="copy-days-label" hidden>Zieltage<select id="copy-days" multiple></select></label><p class="help">Neue Wochenkopien sind deaktiviert. Tageskopien erhalten die Aktivierung des Zielplans. Einzelpläne haben Vorrang vor Gruppenplänen.</p><div class="actions"><button id="confirm-copy">Kopieren</button><button id="cancel-copy">Abbrechen</button></div><p id="copy-error" role="alert"></p></dialog>`;
    const root = this.shadowRoot;
    for (const select of root.querySelectorAll("select")) select.setAttribute("aria-label", select.closest("label").firstChild.textContent.trim());
    root.querySelector("#owner").onchange = (event) => this.selectOwner(event.target.value);
    root.querySelector("#plan-form").oninput = (event) => {
      const field = event.target;
      if (!field.name) return;
      this._draft[field.name] = field.type === "checkbox" ? field.checked : Number(field.value);
      this._changed();
    };
    root.querySelector("#plan-form").onsubmit = (event) => { event.preventDefault(); this._save(); };
    root.querySelector("#profile").onchange = (event) => {
      const template = this._context.data.schedule_templates?.[event.target.value]; if (!template) return;
      this._draft.weekdays = structuredClone(template.weekdays); this._changed(); this._draw();
    };
    for (const [title, days] of [["Mo–Fr", Object.keys(SCHEDULE_DAYS).slice(0, 5)], ["Sa–So", Object.keys(SCHEDULE_DAYS).slice(5)], ...Object.entries(SCHEDULE_DAYS).map(([day, title]) => [title, [day]])]) {
      const button = create("button", title); button.type = "button"; button.dataset.days = days.join(","); button.onclick = () => { this._days = days; root.querySelector("#block-form").hidden = true; this._draw(); }; root.querySelector("#days").append(button);
    }
    root.querySelector("#add").onclick = () => this._edit(-1);
    root.querySelector("#block-form").onsubmit = (event) => { event.preventDefault(); this._acceptBlock(); };
    root.querySelector("#cancel-block").onclick = () => { this._editing = false; root.querySelector("#block-form").hidden = true; this._refresh(); };
    root.querySelector("#delete-block").onclick = () => {
      const blocks = structuredClone(this._draft.weekdays[this._days[0]] || []); blocks.splice(this._blockIndex, 1); this._setBlocks(blocks);
    };
    root.querySelector("#reset").onclick = () => { this._drafts.delete(this._owner); this._load(this._owner); this._message(""); };
    root.querySelector("#copy").onclick = () => this._openCopy();
    root.querySelector("#copy-kind").onchange = () => this._copyChoices();
    root.querySelector("#cancel-copy").onclick = () => root.querySelector("#copy-dialog").close();
    root.querySelector("#confirm-copy").onclick = () => this._copy();
  }
  _changed() { this._dirty = true; this._remember(); this.shadowRoot.querySelector("#copy").disabled = true; this._message("Ungespeicherte Änderungen."); }
  _message(text) { this.shadowRoot.querySelector("#message").textContent = text; }
  _minute(value) { const [hour, minute] = value.split(":").map(Number); return hour * 60 + minute; }
  _draw() {
    const root = this.shadowRoot, day = this._days[0], blocks = this._draft.weekdays[day] || [];
    for (const button of root.querySelectorAll("#days button")) button.setAttribute("aria-pressed", String(button.dataset.days === this._days.join(",")));
    root.querySelector("#day-note").textContent = this._days.length > 1 ? `Anzeige ${SCHEDULE_DAYS[day]}; Blockänderungen gelten für ${this._days.map((key) => SCHEDULE_DAYS[key]).join(", ")}.` : SCHEDULE_DAYS[day];
    const timeline = root.querySelector("#timeline"), list = root.querySelector("#blocks"); timeline.replaceChildren(); list.replaceChildren();
    const render = (block, index, sourceDay, start, end, carry = false) => {
      const button = create("button", `${block.temp}°`); button.type = "button";
      button.setAttribute("aria-label", `${carry ? "Nachtblock " : "Zeitblock "}${block.from} bis ${block.to}, ${block.temp} °C`);
      button.title = button.getAttribute("aria-label");
      button.style.left = `${start / 14.4}%`; button.style.width = `${(end - start) / 14.4}%`;
      button.style.background = block.temp < 20 ? "#397bbc" : block.temp < 22 ? "#bf832b" : "#c46536";
      button.onclick = () => { if (carry) this._days = [sourceDay]; this._draw(); this._edit(index); };
      timeline.append(button);
    };
    blocks.forEach((block, index) => {
      const start = this._minute(block.from), end = this._minute(block.to);
      render(block, index, day, start, end < start ? 1440 : end);
      const button = create("button", `${block.from}–${block.to} · ${block.temp.toFixed(1)} °C${end < start ? " · Folgetag" : ""}`); button.type = "button"; button.onclick = () => this._edit(index); list.append(button);
    });
    const names = Object.keys(SCHEDULE_DAYS), previous = names[(names.indexOf(day) + 6) % 7];
    (this._draft.weekdays[previous] || []).forEach((block, index) => { const start = this._minute(block.from), end = this._minute(block.to); if (end < start && end > 0) render(block, index, previous, 0, end, true); });
  }
  _edit(index) {
    this._editing = true;
    this._blockIndex = index; const form = this.shadowRoot.querySelector("#block-form");
    const block = index < 0 ? { from: "08:00", to: "09:00", temp: 21.5 } : this._draft.weekdays[this._days[0]][index];
    for (const key of ["from", "to", "temp"]) form.elements[key].value = block[key];
    form.hidden = false; this.shadowRoot.querySelector("#delete-block").hidden = index < 0; form.elements.from.focus();
  }
  _acceptBlock() {
    const form = this.shadowRoot.querySelector("#block-form"); if (!form.reportValidity()) return;
    const block = { from: form.elements.from.value, to: form.elements.to.value, temp: Number(form.elements.temp.value) };
    if (block.from === block.to) { this._message("Start und Ende müssen unterschiedlich sein."); return; }
    const blocks = structuredClone(this._draft.weekdays[this._days[0]] || []);
    if (this._blockIndex < 0) blocks.push(block); else blocks[this._blockIndex] = block;
    blocks.sort((a, b) => a.from.localeCompare(b.from)); this._setBlocks(blocks);
  }
  _setBlocks(blocks) { this._editing = false; for (const day of this._days) this._draft.weekdays[day] = structuredClone(blocks); this.shadowRoot.querySelector("#block-form").hidden = true; this._changed(); this._draw(); }
  async _save() {
    if (this._saving) return;
    if (!this.shadowRoot.querySelector("#block-form").hidden) { this._message("Den geöffneten Block zuerst übernehmen oder abbrechen."); return; }
    this._saving = true;
    for (const field of this.shadowRoot.querySelectorAll("input,select,button")) field.disabled = true;
    const owner = this._owner, plan = structuredClone(this._draft), revision = this._revision;
    try {
      const result = await this._context.hass.callWS({ type: "thermo_control/save_schedule", schedule: plan, revision });
      this._dirty = false; this._drafts.delete(owner);
      if (result) this.dispatchEvent(new CustomEvent("schedules-updated", { detail: result, bubbles: true, composed: true }));
      this._version = null; this._refresh(); this._message("Zeitplan gespeichert.");
    } catch (error) { this._message(error.message || String(error)); }
    finally { this._saving = false; for (const field of this.shadowRoot.querySelectorAll("input,select,button")) field.disabled = false; this._refresh(); }
  }
  _openCopy() { this._copyChoices(); this.shadowRoot.querySelector("#copy-error").textContent = ""; this.shadowRoot.querySelector("#copy-dialog").showModal(); }
  _copyChoices() {
    const root = this.shadowRoot, day = root.querySelector("#copy-kind").value === "day", targets = root.querySelector("#copy-targets"); targets.replaceChildren();
    for (const owner of this._owners()) { if (!day && owner.key === this._owner) continue; const option = create("option", owner.name); option.value = owner.key; option.selected = day && owner.key === this._owner; targets.append(option); }
    root.querySelector("#copy-days-label").hidden = !day;
    const days = root.querySelector("#copy-days"); days.replaceChildren();
    for (const [id, title] of Object.entries(SCHEDULE_DAYS)) { const option = create("option", title); option.value = id; option.selected = id !== this._days[0]; days.append(option); }
  }
  async _copy() {
    const root = this.shadowRoot, button = root.querySelector("#confirm-copy"); if (button.disabled) return; button.disabled = true;
    const message = { type: "thermo_control/copy_schedule", source: this._owner, targets: [...root.querySelector("#copy-targets").selectedOptions].map((option) => option.value), revision: this._context.data.schedule_revision || 0 };
    if (root.querySelector("#copy-kind").value === "day") Object.assign(message, { source_day: this._days[0], target_days: [...root.querySelector("#copy-days").selectedOptions].map((option) => option.value) });
    try { const result = await this._context.hass.callWS(message); if (result) this.dispatchEvent(new CustomEvent("schedules-updated", { detail: result, bubbles: true, composed: true })); root.querySelector("#copy-dialog").close(); this._message("Zeitplan kopiert. Wochenkopien sind zunächst deaktiviert."); }
    catch (error) { root.querySelector("#copy-error").textContent = error.message || String(error); }
    finally { button.disabled = false; }
  }
}
customElements.define("thermo-control-schedule-editor", ThermoControlScheduleEditor);

class ThermoControlPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = { rooms: [], revision: 0, defaults: {}, device_defaults: {} };
    this._cards = new Map();
    this._targets = new Map();
    this._targetRequests = new Map();
    this._connection = null;
    this._generation = 0;
    this._busy = false;
    this._tab = "overview";
    this._historyGeneration = 0;
  }

  set hass(value) {
    this._hass = value;
    if (this.isConnected) {
      this._connect();
      this._updateCards();
      this._updatePickers();
      this._updateSystem();
    }
  }
  get hass() { return this._hass; }
  set narrow(value) { this.toggleAttribute("narrow", Boolean(value)); }
  set panel(value) { this._panel = value; }

  connectedCallback() {
    if (!this.shadowRoot.hasChildNodes()) this._build();
    this._connect();
    this._historyTimer = setInterval(() => { if (this._tab === "graphs") this._loadHistory(); }, 60000);
  }

  disconnectedCallback() {
    clearInterval(this._historyTimer);
    for (const entityId of this._targets.keys()) this._cancelTarget(entityId);
    this._historyGeneration += 1;
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
    const fingerprint = JSON.stringify([data.revision, data.rooms, data.groups]);
    const changed = this._fingerprint !== fingerprint;
    this._fingerprint = fingerprint;
    this._data = { ...data, settings: data.settings || structuredClone(SYSTEM_VALUES) };
    const entities = new Set([...data.rooms, ...(data.groups || [])].map((item) => item.entity_id));
    for (const entityId of this._targets.keys()) if (!entities.has(entityId)) this._cancelTarget(entityId);
    if (changed) { this._renderCards(); this._renderAssignments(); this._renderGroupCards(); this._graphChoices(); }
    else this._updateCards();
    this._updateSystem();
    this._updateScheduleEditor();
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
      <header class="toolbar"><button class="menu" aria-label="Seitenleiste öffnen">☰</button><span class="brand" aria-hidden="true">♨</span><strong>Thermo Control</strong><span class="version">Raumregelung · 2.1.0</span></header>
      <main><section class="intro"><div><div class="eyebrow">Temperaturen im Blick</div><h1>Deine Räume</h1><p>Heizung steuern und jeden Raum passend konfigurieren.</p></div><button class="primary" id="add-room" disabled>+ Raum hinzufügen</button></section>
      <div id="error" class="error" role="alert"></div><section class="rooms-grid" id="rooms" aria-label="Räume"></section><div id="empty" class="empty" hidden><div class="empty-symbol" aria-hidden="true">♨</div><h2>Hier beginnt deine Raumregelung</h2><p>Verbinde Thermostate mit deinem ersten Raum. Ein externer Temperatursensor ist optional.</p><button class="primary" id="first-room">Ersten Raum anlegen</button></div><div class="footer"><span class="live"></span><span id="connection">Verbindung wird hergestellt …</span></div></main>
      <dialog id="editor" aria-labelledby="editor-title"><form id="room-form"><div class="dialog-header"><div><h2 id="editor-title">Raum hinzufügen</h2><p>Sensoren, Thermostate und Regelung für diesen Raum.</p></div><button type="button" id="close-editor" aria-label="Schließen">✕</button></div><div class="dialog-body"><div class="error" id="form-error" role="alert"></div><div class="fields">
        <label class="wide">Raumname<input name="name" required maxlength="100" placeholder="z. B. Wohnzimmer"></label>
        <label>Etage / Zone<input name="floor" maxlength="100" placeholder="z. B. Erdgeschoss"></label>
        <label>Gruppe<select name="group_id"><option value="">Keine Gruppe</option></select></label>
        <label>Heizungstyp<select name="heating_type"><option value="radiator">Heizkörper / eigene Thermostatregelung</option><option value="floor">Fußbodenheizung · vorausschauend / TPI</option></select></label>
        <label class="checkbox"><input name="use_global_control" type="checkbox"><span>Globale FBH-Parameter verwenden (Gruppenparameter haben Vorrang)</span></label>
        <label class="checkbox wide"><input name="use_global_calibration" type="checkbox"><span>Globales Kalibrierungsintervall verwenden</span></label>
        <div><thermo-control-entity-picker name="trvs"></thermo-control-entity-picker><p class="help">Nach Namen oder Entitäts-ID suchen und Thermostate einzeln hinzufügen.</p></div>
        <div><thermo-control-entity-picker name="temperature_sensor"></thermo-control-entity-picker><p class="help">Optional. Ohne externen Sensor wird die gemessene Thermostattemperatur verwendet; bei mehreren Geräten der Mittelwert. Keine Offset-Kalibrierung.</p></div>
        <div class="wide"><thermo-control-entity-picker name="window_sensors"></thermo-control-entity-picker><p class="help">Optional. Die Heizung startet erst wieder, wenn alle Kontakte geschlossen sind.</p></div>
      </div><details id="advanced"><summary>Regelung, Verzögerungen und Presets</summary><div class="fields" id="numeric-fields"></div></details><details id="devices" open><summary>Thermostate und Kalibrierung</summary><p class="help" style="margin-top:12px">Die Offset-Kalibrierung ist nur mit externem Raumtemperatursensor aktiv. Number-Entität auswählen oder ein MQTT-Topic verwenden. Leere Felder erlauben die automatische Geräteerkennung.</p><div id="device-fields"></div></details></div><div class="dialog-footer"><button type="button" id="delete-room" class="danger" hidden>Raum löschen</button><span id="saving" class="saving" hidden>Wird gespeichert …</span><button type="button" id="cancel-editor">Abbrechen</button><button class="primary" type="submit" id="save-room">Raum speichern</button></div></form></dialog>
      <dialog id="confirm-delete" aria-labelledby="delete-title"><div class="confirm"><h2 id="delete-title">Raum löschen?</h2><p id="delete-description"></p><div class="error" id="delete-error" role="alert"></div><div class="confirm-actions"><button id="cancel-delete">Abbrechen</button><button class="danger" id="confirm-delete-button">Raum löschen</button></div></div></dialog>
    `;
    this._extendUI();
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
    let currentFloor = null;
    const rooms = [...this._data.rooms].sort((a, b) => (a.config.floor || "Ohne Etage").localeCompare(b.config.floor || "Ohne Etage", "de") || a.config.name.localeCompare(b.config.name, "de"));
    for (const room of rooms) {
      const floor = room.config.floor || "Ohne Etage";
      if (floor !== currentFloor) { const heading = create("h2", floor, "rooms-floor"); container.append(heading); currentFloor = floor; }
      const card = create("article", undefined, "room-tile");
      card.innerHTML = `<div class="card-head"><h2></h2><button class="edit" type="button">Konfigurieren</button></div><div class="status"><span class="dot"></span><span class="status-text"></span></div><div class="measure"><div class="eyebrow">Raumtemperatur</div><span class="temperature">—</span><span class="unit">°C</span><div class="help temperature-source"></div></div><div class="metrics"><div class="metric"><span>Ventilöffnung</span><strong class="position">—</strong></div><div class="metric"><span>Thermostate</span><strong class="trv-count"></strong></div><div class="metric"><span>Fenster</span><strong class="window-status">—</strong></div></div>`;
      card.querySelector("h2").textContent = room.config.name;
      card.querySelector(".edit").onclick = () => this._openEditor(room);
      card.querySelector(".trv-count").textContent = String(room.config.trvs.length);
      card.append(this._climateControls(room.entity_id));
      const scheduleRow = create("div", undefined, "schedule-indicator"), scheduleButton = create("button", undefined, "schedule-toggle"), scheduleIcon = document.createElement("ha-icon");
      scheduleButton.type = "button"; scheduleButton.setAttribute("aria-label", `${room.config.name}: Zeitplan umschalten`); scheduleIcon.setAttribute("icon", "mdi:calendar-check"); scheduleButton.append(scheduleIcon);
      scheduleButton.onclick = () => this._toggleSchedule(room); scheduleRow.append(scheduleButton, create("span", "", "schedule-status")); card.append(scheduleRow);
      const edit = card.querySelector(".edit"); edit.textContent = "⚙"; edit.setAttribute("aria-label", "Konfigurieren"); edit.title = `${room.config.name} konfigurieren`;
      const details = create("div", "", "help control-preview"); card.append(details);
      card.append(this._targetStepper(room.entity_id, room.config.name));
      card.dataset.floor = room.config.floor || "Ohne Etage";
      card.querySelector(".card-head").before(create("div", room.config.floor || "Ohne Etage", "eyebrow"));
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
      card.querySelector(".position").textContent = Number.isFinite(attributes.valve_position) ? `${attributes.valve_position} %` : "—";
      card.querySelector(".window-status").textContent = !room.config.window_sensors?.length ? "Keine" : attributes.window_open ? "Offen" : "Geschlossen";
      const status = !available ? "Nicht verfügbar" : attributes.window_open && !this._nativeAuto(state) ? "Fensterpause" : attributes.hvac_action === "heating" ? "🔥 Heizt" : attributes.hvac_action === "idle" ? "Bereit / Leerlauf" : attributes.hvac_action === "off" || state.state === "off" ? "Ausgeschaltet" : "Heizstatus unbekannt";
      card.querySelector(".status-text").textContent = status;
      card.querySelector(".status").className = `status ${attributes.window_open ? "window" : attributes.hvac_action === "heating" ? "heating" : ""}`;
      card.classList.toggle("heating", Boolean(available && attributes.hvac_action === "heating"));
      const nativeAuto = state?.state === "auto" || attributes.native_auto;
      this._updateClimateControls(card, state);
      const scheduleButton = card.querySelector(".schedule-toggle"); scheduleButton.disabled = !available;
      scheduleButton.setAttribute("aria-pressed", String(Boolean(attributes.schedule_active)));
      scheduleButton.title = attributes.schedule_active ? "Zeitplan ausschalten · Manuell" : nativeAuto ? "Thermo-Control-Zeitplan aktivieren · Geräte-Auto verlassen" : "Wochenzeitplan aktivieren";
      let until = "";
      if (attributes.schedule_until) { try { until = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit", timeZone: this._data.time_zone || "UTC" }).format(new Date(attributes.schedule_until)); } catch {} }
      card.querySelector(".schedule-status").textContent = attributes.schedule_active ? `${attributes.schedule_override ? "Override" : "Auto"}${until ? ` (bis ${until})` : ""}${attributes.preheating ? " · Vorheizen" : ""}` : "Manuell";
      this._updateTargetStepper(card, room.entity_id, state);
      const detail = card.querySelector(".control-preview");
      const percent = Number.isFinite(attributes.heat_demand) ? `${attributes.heat_demand.toFixed(0)} % Bedarf` : "";
      const trend = Number.isFinite(attributes.temperature_rate) ? ` · ${attributes.temperature_rate.toFixed(2)} °C/h` : "";
      const prediction = Number.isFinite(attributes.predicted_temperature) ? ` · Prognose ${attributes.predicted_temperature.toFixed(1)} °C` : "";
      detail.textContent = nativeAuto ? "Auto · Gerätezeitplan; externe Regelung pausiert." : (attributes.auto_devices?.length ? `${attributes.auto_devices.length} Thermostat(e) in Auto · ` : "") + percent + trend + prediction + (attributes.pre_shutoff ? " · Vorausschauende Abschaltung" : "") + (attributes.interlock_reason ? " · Wärmepumpen-Freigabe fehlt" : "");
    }
  }

  _updateScheduleEditor() {
    const editor = this.shadowRoot.querySelector("thermo-control-schedule-editor");
    if (editor && this._data) editor.context = { data: this._data, hass: this._hass };
  }

  _toggleSchedule(room) {
    const state = this._hass.states[room.entity_id];
    const configured = (this._data.schedules || []).some((plan) => plan.room_id === room.id || plan.group_id && plan.group_id === room.config.group_id);
    if (!configured) { this._switchTab("schedules"); this.shadowRoot.querySelector("thermo-control-schedule-editor").selectOwner(`room:${room.id}`); return; }
    this._service(room, "set_preset_mode", { preset_mode: state?.attributes.schedule_active ? "none" : "schedule" });
  }

  _climateControls(entityId, name = "") {
    const controls = create("div", undefined, "controls");
    for (const [className, title, options, service, key] of [
      ["mode", "Heizung", { off: "Pause / Frostschutz", heat: "Heizen", auto: "Auto · Gerätezeitplan" }, "set_hvac_mode", "hvac_mode"],
      ["preset", "Preset", CLIMATE_PRESETS, "set_preset_mode", "preset_mode"],
    ]) {
      const label = create("label", title), select = create("select", undefined, className);
      select.setAttribute("aria-label", name ? `${name}: ${title}` : title);
      for (const [value, text] of Object.entries(options)) {
        const option = create("option", text); option.value = value; select.append(option);
      }
      select.onchange = (event) => { if (entityId) this._service({ entity_id: entityId }, service, { [key]: event.target.value }); };
      label.append(select); controls.append(label);
    }
    return controls;
  }

  _updateClimateControls(card, state) {
    const attributes = state?.attributes || {};
    const available = state && !["unknown", "unavailable"].includes(state.state);
    const nativeAuto = state?.state === "auto" || attributes.native_auto;
    const mode = card.querySelector(".mode"), preset = card.querySelector(".preset");
    const supportedModes = attributes.hvac_modes || (nativeAuto ? ["off", "heat", "auto"] : ["off", "heat"]);
    for (const option of mode.options) option.disabled = !supportedModes.includes(option.value);
    if (this.shadowRoot.activeElement !== mode) mode.value = nativeAuto ? "auto" : attributes.desired_hvac_mode || state?.state || "off";
    if (this.shadowRoot.activeElement !== preset) preset.value = attributes.preset_mode || "none";
    const supportedPresets = attributes.preset_modes || Object.keys(CLIMATE_PRESETS);
    for (const option of preset.options) option.disabled = !supportedPresets.includes(option.value);
    mode.disabled = !available;
    preset.disabled = !available || this._nativeAuto(state);
  }

  async _service(room, service, data) {
    if (service !== "set_temperature") this._cancelTarget(room.entity_id);
    this._error("");
    try { await this._hass.callService("climate", service, { entity_id: room.entity_id, ...data }); }
    catch (error) { this._error(this._message(error)); }
    this._updateCards();
    this._updateSystem();
  }

  _targetBounds(state) {
    // Keep the standard range, respecting devices with a narrower supported range.
    const attributes = state?.attributes || {};
    const min = Math.max(TARGET_MIN, Number.isFinite(attributes.min_temp) ? attributes.min_temp : TARGET_MIN);
    const max = Math.min(TARGET_MAX, Number.isFinite(attributes.max_temp) ? attributes.max_temp : TARGET_MAX);
    return [Math.ceil(min / TARGET_STEP) * TARGET_STEP, Math.floor(max / TARGET_STEP) * TARGET_STEP];
  }

  _targetStepper(entityId, name, group = false) {
    const row = create("div", undefined, "target-stepper"); row.setAttribute("role", "group"); row.setAttribute("aria-label", `${name}: Solltemperatur`);
    row.dataset.entityId = entityId || "";
    const display = create("div", undefined, "target-display");
    const input = create("input", undefined, "target-input");
    Object.assign(input, { type: "number", min: TARGET_MIN, max: TARGET_MAX, step: TARGET_STEP, required: true });
    input.setAttribute("inputmode", "decimal"); input.setAttribute("aria-label", group ? `${name}: Sollwert` : "Solltemperatur");
    input.oninput = () => {
      if (input.value && input.checkValidity()) this._queueTarget(entityId, Number(input.value));
      else this._cancelTarget(entityId);
    };
    input.onblur = () => { this._updateCards(); this._updateSystem(); };
    const unit = create("span", "°", "target-unit"); unit.setAttribute("aria-hidden", "true"); display.append(input, unit);
    const buttons = [[-TARGET_STEP, "Temperatur senken", "decrease"], [TARGET_STEP, "Temperatur erhöhen", "increase"]].map(([delta, label, className]) => {
      const button = create("button", delta < 0 ? "−" : "+", className); button.type = "button"; button.setAttribute("aria-label", `${name}: ${label}`);
      button.onclick = () => {
        const current = this._targets.get(entityId)?.value ?? this._hass?.states[entityId]?.attributes.temperature;
        if (!Number.isFinite(current)) return;
        const [min, max] = this._targetBounds(this._hass.states[entityId]);
        const value = Math.min(max, Math.max(min, Math.round((current + delta) / TARGET_STEP) * TARGET_STEP));
        if (value !== current) this._queueTarget(entityId, value);
      };
      return button;
    });
    row.append(buttons[0], display, buttons[1]);
    return row;
  }

  _nativeAuto(state) {
    return state?.state === "auto" || Boolean(state?.attributes?.native_auto || state?.attributes?.auto_rooms?.length);
  }

  _updateTargetStepper(card, entityId, state) {
    const input = card.querySelector(".target-input");
    const [min, max] = this._targetBounds(state);
    const available = Boolean(entityId && state && !this._nativeAuto(state) && !["unknown", "unavailable"].includes(state.state) && Number.isFinite(state.attributes?.temperature) && min <= max);
    if (!available) this._cancelTarget(entityId);
    let pending = this._targets.get(entityId);
    if (pending?.sent && state?.attributes.temperature === pending.value) { this._cancelTarget(entityId); pending = null; }
    const value = pending?.value ?? state?.attributes?.temperature;
    input.min = min; input.max = max;
    if (!available || this.shadowRoot.activeElement !== input || (pending && Number(input.value) !== pending.value)) input.value = Number.isFinite(value) ? value.toFixed(1) : "";
    input.disabled = !available;
    card.querySelector(".decrease").disabled = !available || value <= min;
    card.querySelector(".increase").disabled = !available || value >= max;
    card.querySelector(".target-stepper").setAttribute("aria-busy", String(Boolean(pending)));
  }

  _cancelTarget(entityId, restore = false) {
    const pending = this._targets.get(entityId);
    if (!pending) return;
    clearTimeout(pending.timer); clearTimeout(pending.expiry);
    this._targets.delete(entityId);
    if (restore) {
      const value = this._hass?.states[entityId]?.attributes.temperature;
      for (const row of this.shadowRoot.querySelectorAll(".target-stepper")) {
        if (row.dataset.entityId === entityId) row.querySelector("input").value = Number.isFinite(value) ? value.toFixed(1) : "";
      }
    }
  }

  _queueTarget(entityId, value) {
    const state = this._hass?.states[entityId];
    const [min, max] = this._targetBounds(state);
    if (!this.isConnected || !state || this._nativeAuto(state) || ["unknown", "unavailable"].includes(state.state) || !Number.isFinite(value) || value < min || value > max || value / TARGET_STEP % 1) return;
    const previous = this._targets.get(entityId);
    // The old HA value may still be visible after an earlier command was accepted.
    const hasSentTarget = Boolean(previous?.sent || previous?.hasSentTarget || this._targetRequests.has(entityId));
    this._cancelTarget(entityId);
    if (value !== state.attributes.temperature || hasSentTarget) {
      const pending = { value, sent: false, hasSentTarget };
      pending.timer = setTimeout(() => this._sendTarget(entityId, pending), TARGET_DEBOUNCE);
      this._targets.set(entityId, pending);
    }
    this._updateCards(); this._updateSystem();
  }

  async _sendTarget(entityId, pending) {
    // Serialize overlapping requests for an entity so the final tap always wins.
    const previous = this._targetRequests.get(entityId);
    if (previous) await previous.catch(() => {});
    if (!this.isConnected || this._targets.get(entityId) !== pending || this._nativeAuto(this._hass?.states[entityId])) return;
    pending.sent = true;
    const request = Promise.resolve().then(() => this._hass.callService("climate", "set_temperature", { entity_id: entityId, temperature: pending.value }));
    this._targetRequests.set(entityId, request);
    this._error("");
    try {
      await request;
      if (this._targets.get(entityId) === pending) {
        // A successful service call can precede the HA state event. Preserve the preview.
        pending.expiry = setTimeout(() => {
          if (this._targets.get(entityId) !== pending) return;
          this._cancelTarget(entityId, true); this._updateCards(); this._updateSystem();
        }, TARGET_CONFIRM_TIMEOUT);
      }
    } catch (error) {
      if (this._targets.get(entityId) === pending) { this._cancelTarget(entityId, true); this._error(this._message(error)); }
    } finally {
      if (this._targetRequests.get(entityId) === request) this._targetRequests.delete(entityId);
      if (this.isConnected) { this._updateCards(); this._updateSystem(); }
    }
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
    this._draft = { ...CONTROL_VALUES, heating_type: "radiator", floor: "", group_id: null, use_global_control: true, use_global_calibration: false, ...this._draft };
    form.elements.name.value = this._draft.name;
    form.elements.floor.value = this._draft.floor;
    form.elements.heating_type.value = this._draft.heating_type;
    form.elements.use_global_control.checked = this._draft.use_global_control;
    form.elements.use_global_calibration.checked = this._draft.use_global_calibration;
    this._groupOptions(form.elements.group_id, this._draft.group_id);
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
      fields.append(create("p", "Externe Regelung verwendet Heizen (heat). Auto folgt dem Gerätezeitplan und wird in der Übersicht oder am Thermostat gewählt.", "help wide"));
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
      const modes = this._hass.states[section.dataset.entityId]?.attributes.hvac_modes || [];
      const device = { regulated_mode: modes.includes("auto") && !modes.includes("heat") ? "auto" : "heat" };
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
    for (const picker of this.shadowRoot.querySelectorAll("#editor thermo-control-entity-picker")) picker.disabled = busy;
    this.shadowRoot.querySelector("#saving").hidden = !busy;
  }

  async _save() {
    if (this._busy) return;
    const form = this.shadowRoot.querySelector("#room-form");
    if (!form.reportValidity()) return;
    const root = this.shadowRoot;
    // Commit exact IDs typed into the main fields before TRV changes rebuild device fields.
    for (const name of ["trvs", "temperature_sensor", "window_sensors"]) root.querySelector(`[name="${name}"]`).commit();
    for (const picker of root.querySelectorAll("#editor thermo-control-entity-picker")) {
      picker.commit();
      if (!picker.reportValidity()) return;
    }
    this._readDevices();
    const config = { ...this._draft, name: form.elements.name.value.trim(), trvs: this._selectedTrvs(), temperature_sensor: root.querySelector('[name="temperature_sensor"]').value || null, window_sensors: root.querySelector('[name="window_sensors"]').value };
    Object.assign(config, { floor: form.elements.floor.value.trim(), group_id: form.elements.group_id.value || null, heating_type: form.elements.heating_type.value, use_global_control: form.elements.use_global_control.checked, use_global_calibration: form.elements.use_global_calibration.checked });
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

  _extendUI() {
    const root = this.shadowRoot, main = root.querySelector("main");
    const style = create("style"); style.textContent = `
      .tabs{display:flex;gap:8px;overflow-x:auto;margin:22px 0}.tabs button{white-space:nowrap}.tabs [aria-selected=true]{background:var(--primary-color,#287757);color:white}.system-bar,.master,.group-summary,.analytics,.settings-box,.assignments{padding:20px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde5de);border-radius:14px;margin-bottom:22px}.system-bar{display:flex;flex-wrap:wrap;gap:12px 24px}.system-bar strong{display:block;margin-top:4px}.system-bar span{font-size:12px}.master{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.master label{flex:1;min-width:180px}.master input[type=range]{padding:0;accent-color:var(--primary-color,#287757)}.master output{font-size:22px}.group-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.group-summary .controls{margin-top:14px;grid-template-columns:repeat(2,minmax(0,1fr))}.group-summary label{min-width:0}.group-summary select{min-width:0;min-height:44px;font-size:14px;padding:8px}.chart-controls{display:flex;flex-wrap:wrap;gap:16px;align-items:end}.chart-controls label{flex:1;min-width:150px}.chart-controls .checkbox{flex-direction:row}.chart{display:block;width:100%;min-height:260px;margin:20px 0 0;touch-action:pan-y}.chart text{fill:var(--secondary-text-color,#69786e);font:11px system-ui}.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:12px;margin:14px 0}.legend span:before{content:"";display:inline-block;width:18px;height:3px;margin-right:6px;background:var(--color)}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:14px 10px;border-bottom:1px solid var(--divider-color,#dde5de)}td:first-child{min-width:150px}td .help{overflow-wrap:anywhere}td select{min-width:140px}.settings-box h2{margin-bottom:20px}.settings-box .fields{margin:18px 0}.settings-box .primary{margin-top:16px}.group-row{display:flex;gap:14px;align-items:center;padding:14px 0;border-bottom:1px solid var(--divider-color,#dde5de)}.group-row span{flex:1}.group-form{margin-top:18px;padding-top:16px;border-top:1px solid var(--divider-color,#dde5de)}.target-row input{min-width:65px}.target-row button{padding:10px;font-size:20px}.form-note{margin-top:12px;font-size:13px;color:var(--primary-color,#287757)}@media(max-width:650px){.group-summary .controls{grid-template-columns:minmax(0,1fr)}.tabs button{font-size:12px;padding:9px}.master{gap:10px}.system-bar{padding:14px;font-size:12px}.chart-controls{gap:10px}.chart{min-height:200px}}
      .rooms-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
        padding: 0 4px;
      }
      .rooms-floor { grid-column: 1 / -1; margin: 12px 0 4px; }
      .room-tile {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        background: var(--card-background-color, #1c1c1e);
        border-radius: 14px;
        padding: 10px;
        min-height: 135px;
        min-width: 0;
        color: var(--primary-text-color, #f5f5f7);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
        transition: border-color 0.2s ease, background 0.2s ease;
      }
      .room-tile.heating {
        border-color: rgba(255, 152, 0, 0.6);
        background: linear-gradient(180deg, rgba(255, 152, 0, 0.08) 0%, var(--card-background-color, #1c1c1e) 100%);
      }
      .room-tile .card-head { gap: 4px; }
      .room-tile h2 { min-width: 0; flex: 1; font-size: 15px; overflow-wrap: anywhere; }
      .room-tile .edit { width: 44px; min-width: 44px; min-height: 44px; padding: 0; font-size: 20px; }
      .room-tile .eyebrow { font-size: 9px; overflow-wrap: anywhere; }
      .room-tile .status { gap: 4px; font-size: 11px; }
      .room-tile .dot { flex: none; }
      .room-tile .measure { margin: 12px 0; }
      .room-tile .temperature { font-size: 34px; }
      .room-tile .unit { font-size: 16px; margin-left: 3px; }
      .room-tile .metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px; padding: 8px 0; margin-bottom: 10px; }
      .room-tile .metric span { font-size: 10px; overflow-wrap: anywhere; }
      .room-tile .metric strong { font-size: 12px; overflow-wrap: anywhere; }
      .room-tile .controls { grid-template-columns: minmax(0, 1fr); gap: 8px; }
      .room-tile select { min-width: 0; min-height: 44px; padding: 8px; }
      .room-tile .help { overflow-wrap: anywhere; }
      .schedule-indicator { display: flex; align-items: center; gap: 6px; margin-top: 8px; }
      .schedule-toggle { flex: none; min-width: 44px; min-height: 44px; padding: 6px; }
      .schedule-toggle[aria-pressed=true] { color: var(--primary-color, #287757); background: var(--secondary-background-color, #eef3ef); }
      .schedule-status { font-size: 11px; overflow-wrap: anywhere; }
      .room-tile .control-preview { margin-top: 8px; font-size: 10px; }
      .target-stepper { display: grid; grid-template-columns: minmax(44px, 1fr) minmax(0, 1.2fr) minmax(44px, 1fr); gap: 0; width: 100%; margin-top: 12px; border: 1px solid var(--divider-color, rgba(255,255,255,.08)); border-radius: 999px; background: var(--card-background-color, #29292c); color: var(--primary-text-color, #f5f5f7); overflow: hidden; }
      .room-tile .target-stepper { width: calc(100% + 20px); margin-left: -10px; }
      .target-stepper button { min-width: 44px; min-height: 44px; padding: 0; border: 0; border-radius: 0; background: transparent; font-size: 24px; touch-action: manipulation; }
      .target-stepper button:hover { background: var(--divider-color, rgba(255,255,255,.08)); }
      .target-stepper button:disabled { cursor: default; }
      .target-display { display: flex; align-items: center; justify-content: center; min-width: 0; border-left: 1px solid var(--divider-color, rgba(255,255,255,.08)); border-right: 1px solid var(--divider-color, rgba(255,255,255,.08)); }
      .target-display .target-input { width: 4.2ch; flex: 0 1 4.2ch; min-width: 0; min-height: 44px; padding: 0; border: 0; border-radius: 0; background: transparent; color: inherit; text-align: center; font-size: 18px; font-weight: 650; appearance: textfield; }
      .target-display .target-input::-webkit-inner-spin-button, .target-display .target-input::-webkit-outer-spin-button { appearance: none; margin: 0; }
      .target-unit { font-size: 18px; font-weight: 650; }
      .target-stepper :focus-visible { outline-offset: -3px; }
      @media(max-width:650px) { .room-tile .metrics { grid-template-columns: minmax(0, 1fr); gap: 6px; } .room-tile .metric { display: flex; align-items: baseline; justify-content: space-between; gap: 4px; } .room-tile .metric strong { margin-top: 0; } .master label { overflow-wrap: anywhere; } }
      @media(max-width:360px) { main { padding-left: 8px; padding-right: 8px; } .target-display .target-input, .target-unit { font-size: 14px; } }
    `; root.append(style);
    const system = create("section", undefined, "system-bar"); system.id = "system-bar"; system.setAttribute("aria-label", "Wärmepumpenstatus"); main.prepend(system);
    const tabs = create("nav", undefined, "tabs"); tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Thermo Control Bereiche"); system.after(tabs);
    const overview = create("section"); overview.id = "tab-overview"; overview.setAttribute("role", "tabpanel");
    for (const id of [".intro", "#rooms", "#empty"]) overview.append(main.querySelector(id));
    main.insertBefore(overview, main.querySelector(".footer"));
    const master = create("div", undefined, "master"); master.innerHTML = `<label>Master-Sollwertverschiebung (°C)<input id="master-offset" type="range" min="-5" max="5" step="0.5" value="0"></label><output id="master-value">0 °C</output>`;
    overview.querySelector("#rooms").before(master);
    const groupCards = create("section", undefined, "group-cards"); groupCards.id = "group-cards"; groupCards.setAttribute("aria-label", "Gruppensteuerung"); master.after(groupCards);
    for (const [id, title] of [["overview", "Übersicht"], ["graphs", "Verläufe & Analyse"], ["schedules", "Zeitpläne"], ["groups", "Thermostate & Gruppen"], ["settings", "Einstellungen"]]) {
      const button = create("button", title); button.type = "button"; button.id = `nav-${id}`; button.setAttribute("role", "tab"); button.setAttribute("aria-controls", `tab-${id}`); button.dataset.tab = id; button.onclick = () => this._switchTab(id); tabs.append(button);
      if (id !== "overview") { const section = create("section"); section.id = `tab-${id}`; section.setAttribute("role", "tabpanel"); main.insertBefore(section, main.querySelector(".footer")); }
      root.querySelector(`#tab-${id}`).setAttribute("aria-labelledby", button.id);
    }
    tabs.onkeydown = (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); const buttons = [...tabs.children]; const current = buttons.indexOf(event.target);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      this._switchTab(buttons[next].dataset.tab); buttons[next].focus();
    };
    const scheduleEditor = document.createElement("thermo-control-schedule-editor"); root.querySelector("#tab-schedules").append(scheduleEditor);
    scheduleEditor.addEventListener("schedules-updated", (event) => this._receive({ ...this._data, ...event.detail }));
    const graph = root.querySelector("#tab-graphs"); graph.innerHTML = `<div class="analytics"><h2>Temperaturen und Heizphasen</h2><div class="chart-controls"><label>Raum / Gruppe<select id="graph-room"></select></label><label>Zeitfenster<select id="graph-window"><option value="6">6 Stunden</option><option value="24" selected>24 Stunden</option><option value="48">48 Stunden</option><option value="168">7 Tage</option></select></label><label class="checkbox"><input id="graph-flow" type="checkbox"><span>Vorlauftemperatur einblenden</span></label><button id="refresh-graph">Aktualisieren</button></div><div class="legend"><span style="--color:#287757">Raum Ist</span><span style="--color:#c56a35">Raum Soll</span><span style="--color:#467eb2">Vorlauf</span></div><p class="help">Heizphasen: orange = heating, grau = idle/off, Lücken = unbekannt. Zeige auf eine Kurve für Messwerte.</p><svg id="history-chart" class="chart" viewBox="0 0 900 340" role="img" aria-label="Temperaturverlauf mit Heizphasen"></svg><p id="graph-status" role="status"></p><p id="graph-tooltip" class="help" role="status"></p></div>`;
    for (const id of ["#graph-room", "#graph-window", "#graph-flow"]) root.querySelector(id).onchange = () => this._loadHistory();
    root.querySelector("#refresh-graph").onclick = () => this._loadHistory();
    const groups = root.querySelector("#tab-groups"); groups.innerHTML = `<div class="assignments"><h2>Räume und Thermostate zuordnen</h2><p>Mehrere Thermostate eines Raums werden gemeinsam gesteuert. Raum bearbeiten für Sensoren, Kontakte und Heizkreise.</p><div class="table-wrap"><table><thead><tr><th>Raum / Thermostate</th><th>Etage / Zone</th><th>Gruppe</th><th>Regelung</th><th></th></tr></thead><tbody id="assignment-rows"></tbody></table></div><button class="primary" id="groups-add-room">Raum hinzufügen</button></div><div class="settings-box"><h2>Gruppen verwalten</h2><div id="group-list"></div><button id="add-group">Gruppe hinzufügen</button><form id="group-form" class="group-form" hidden><label>Gruppenname<input name="name" required maxlength="100"></label><label class="checkbox"><input name="override" type="checkbox"><span>Eigene FBH-Parameter für diese Gruppe</span></label><div id="group-control" class="fields"></div><button class="primary" type="submit">Gruppe speichern</button><button type="button" id="cancel-group">Abbrechen</button><p class="form-note" id="group-error" role="alert"></p></form></div>`;
    root.querySelector("#groups-add-room").onclick = () => this._openEditor();
    root.querySelector("#add-group").onclick = () => this._openGroup();
    root.querySelector("#cancel-group").onclick = () => { root.querySelector("#group-form").hidden = true; };
    root.querySelector("#group-form").onsubmit = (event) => { event.preventDefault(); this._saveGroup(); };
    root.querySelector("#group-form [name=override]").onchange = (event) => { root.querySelector("#group-control").hidden = !event.target.checked; };
    const settings = root.querySelector("#tab-settings"); settings.innerHTML = `<form id="system-form" class="settings-box"><h2>Wärmepumpe · Alpha Innotec / Luxtronik</h2><p>Ordne die Entitäten deiner Luxtronik-Integration zu. Die Freigabe prüft Automatikmodus und verfügbare Vorlaufwärme.</p><div class="fields" id="hp-pickers"></div><div class="fields"><label>Automatik-Zustände (mit Komma trennen)<input name="automatic_states" required></label><label class="checkbox"><input name="interlock" type="checkbox"><span>Wärmepumpen-Freigabe für Raumventile aktivieren</span></label><label>Minimaler warmer Vorlauf (°C)<input name="minimum_flow" type="number" required min="15" max="60" step="0.5"></label><label>Vorlauf über Raumtemperatur (°C)<input name="flow_margin" type="number" required min="0" max="15" step="0.5"></label></div><h2>Globale FBH-Regelung</h2><div id="system-control" class="fields"></div><label>Globales Kalibrierungsintervall (s)<input name="calibration_interval" type="number" required min="300" max="86400" step="1"></label><p class="help">FBH-Parameter gelten für Räume mit globaler Regelung; Gruppen können sie überschreiben. Das Kalibrierungsintervall gilt für Räume mit aktiviertem globalem Intervall. Mindestzeiten betreffen Raumventile. Verdichterschutz und Warmwassersteuerung übernimmt Luxtronik.</p><button class="primary" type="submit">Einstellungen speichern</button><p id="settings-status" class="form-note" role="status"></p></form>`;
    for (const [name, label, domain, temp] of [["flow_sensor", "Vorlauftemperatur Ist", "sensor", true], ["target_sensor", "Vorlauftemperatur Soll", "sensor", true], ["mode_entity", "Heizungs-Betriebsmodus", ["sensor", "select", "climate"], false], ["compressor_entity", "Verdichterstatus", "binary_sensor", false]]) {
      const picker = document.createElement("thermo-control-entity-picker"); this._configurePicker(picker, name, label, domain, "", { temperatureOnly: temp, emptyLabel: "Keine Zuordnung" }); root.querySelector("#hp-pickers").append(picker);
    }
    root.querySelector("#system-form").onsubmit = (event) => { event.preventDefault(); this._saveSettings(); };
    const slider = root.querySelector("#master-offset"); slider.oninput = () => { root.querySelector("#master-value").textContent = `${Number(slider.value).toLocaleString("de-DE")} °C`; };
    slider.onchange = () => this._masterOffset(Number(slider.value));
    this._switchTab("overview");
  }

  _switchTab(tab) {
    this._tab = tab;
    for (const button of this.shadowRoot.querySelectorAll("[role=tab]")) { const selected = button.dataset.tab === tab; button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1; this.shadowRoot.querySelector(`#tab-${button.dataset.tab}`).hidden = !selected; }
    if (tab === "graphs") this._loadHistory();
    if (tab === "settings") this._fillSettings();
    if (tab === "schedules") {
      this._updateScheduleEditor();
      this._hass.callWS({ type: "thermo_control/get_schedules" }).then((result) => { if (result && this.isConnected) this._receive({ ...this._data, ...result }); }).catch((error) => this._error(this._message(error)));
    }
    if (tab !== "graphs") this._historyGeneration += 1;
  }

  _groupOptions(select, selected) {
    select.replaceChildren(); const empty = create("option", "Keine Gruppe"); empty.value = ""; select.append(empty);
    for (const group of this._data.settings?.groups || []) { const option = create("option", group.name); option.value = group.id; select.append(option); }
    select.value = selected || "";
  }

  _renderAssignments() {
    const body = this.shadowRoot.querySelector("#assignment-rows"); body.replaceChildren();
    for (const room of this._data.rooms) {
      const row = create("tr"), name = create("td"); name.append(create("strong", room.config.name), create("div", room.config.trvs.map((id) => this._hass.states[id]?.attributes.friendly_name || id).join(", "), "help")); row.append(name, create("td", room.config.floor || "—"));
      const cell = create("td"), select = create("select"); select.setAttribute("aria-label", `${room.config.name}: Gruppe`); this._groupOptions(select, room.config.group_id); cell.append(select); row.append(cell, create("td", room.config.heating_type === "floor" ? "FBH / TPI" : "Thermostat"));
      select.onchange = async () => { select.disabled = true; try { await this._hass.callWS({ type: "thermo_control/save_room", config: { ...room.config, group_id: select.value || null }, room_id: room.id, revision: this._data.revision }); } catch (error) { this._error(this._message(error)); select.value = room.config.group_id || ""; } finally { select.disabled = false; } };
      const edit = create("button", "Raum bearbeiten"); edit.onclick = () => this._openEditor(room); const editCell = create("td"); editCell.append(edit); row.append(editCell); body.append(row);
    }
    const list = this.shadowRoot.querySelector("#group-list"); list.replaceChildren();
    for (const group of this._data.settings.groups) {
      const row = create("div", undefined, "group-row"); row.append(create("span", `${group.name} · ${this._data.rooms.filter((room) => room.config.group_id === group.id).length} Räume`));
      const edit = create("button", "Gruppe bearbeiten"); edit.onclick = () => this._openGroup(group); const remove = create("button", "Gruppe löschen"); remove.onclick = () => this._removeGroup(group.id); row.append(edit, remove); list.append(row);
    }
  }

  _openGroup(group = null) {
    this._editingGroup = group; this._groupRevision = this._data.revision; this._groupSettings = structuredClone(this._data.settings);
    const root = this.shadowRoot, form = root.querySelector("#group-form"); form.hidden = false; form.elements.name.value = group?.name || ""; form.elements.override.checked = Boolean(group && Object.keys(group.control || {}).length);
    this._numberFields(root.querySelector("#group-control"), CONTROL_NUMBERS, { ...this._data.settings.control, ...group?.control }); root.querySelector("#group-control").hidden = !form.elements.override.checked; root.querySelector("#group-error").textContent = ""; form.elements.name.focus();
  }

  async _saveGroup() {
    const form = this.shadowRoot.querySelector("#group-form"); if (!form.reportValidity() || this._groupSaving) return;
    const config = structuredClone(this._groupSettings); const group = { id: this._editingGroup?.id || Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join(""), name: form.elements.name.value.trim(), control: form.elements.override.checked ? Object.fromEntries(CONTROL_NUMBERS.map(([key]) => [key, Number(form.elements[key].value)])) : {} };
    config.groups = config.groups.filter((item) => item.id !== group.id).concat(group); this._groupSaving = true;
    try { await this._hass.callWS({ type: "thermo_control/save_settings", config, revision: this._groupRevision }); form.hidden = true; }
    catch (error) { this.shadowRoot.querySelector("#group-error").textContent = this._message(error); }
    finally { this._groupSaving = false; }
  }

  async _removeGroup(id) {
    try { await this._hass.callWS({ type: "thermo_control/save_settings", config: { ...this._data.settings, groups: this._data.settings.groups.filter((group) => group.id !== id) }, revision: this._data.revision }); }
    catch (error) { this._error(this._message(error)); }
  }

  _renderGroupCards() {
    const container = this.shadowRoot.querySelector("#group-cards"); container.replaceChildren();
    for (const group of this._data.settings.groups) {
      const mapping = this._data.groups?.find((item) => item.id === group.id);
      const card = create("article", undefined, "group-summary"); card.dataset.groupId = group.id;
      card.append(create("h2", group.name), create("p", "", "group-state"));
      card.append(this._climateControls(mapping?.entity_id, group.name), this._targetStepper(mapping?.entity_id, group.name, true)); container.append(card);
    }
  }

  _updateSystem() {
    const root = this.shadowRoot; if (!root.querySelector("#system-bar")) return;
    const status = this._data.system || {}, bar = root.querySelector("#system-bar"); bar.replaceChildren();
    const temperature = (value) => Number.isFinite(value) ? `${value.toLocaleString("de-DE", { maximumFractionDigits: 1 })} °C` : "—";
    for (const [name, value] of [["Vorlauf Ist / Soll", `${temperature(status.flow)} / ${temperature(status.target)}`], ["Verdichter", status.compressor === true ? "Aktiv" : status.compressor === false ? "Inaktiv" : "Unbekannt"], ["Modus", status.mode || "Nicht zugeordnet"], ["Hausbedarf / freigegeben", `${status.demand ?? 0} % / ${status.eligible_demand ?? 0} %`]]) {
      const item = create("span", name); item.append(create("strong", value)); bar.append(item);
    }
    const slider = root.querySelector("#master-offset"); if (root.activeElement !== slider) { slider.value = this._data.settings?.master_offset || 0; root.querySelector("#master-value").textContent = `${Number(slider.value).toLocaleString("de-DE")} °C`; }
    for (const card of root.querySelectorAll("[data-group-id]")) {
      const mapping = this._data.groups?.find((item) => item.id === card.dataset.groupId); const state = this._hass?.states[mapping?.entity_id]; const attributes = state?.attributes || {};
      const members = this._data.rooms.filter((room) => room.config.group_id === card.dataset.groupId);
      const heating = members.some((room) => this._hass?.states[room.entity_id]?.attributes.hvac_action === "heating");
      card.querySelector(".group-state").textContent = `${heating ? "🔥 Heizt" : attributes.hvac_action === "idle" ? "Bereit" : "Aus / unbekannt"} · ${members.length} Räume${attributes.mixed_targets ? " · Unterschiedliche Sollwerte" : ""}${attributes.auto_rooms?.length ? " · Auto-Räume: Gruppensollwert pausiert" : ""}`;
      this._updateClimateControls(card, state);
      this._updateTargetStepper(card, mapping?.entity_id, state);
    }
  }

  async _masterOffset(offset) {
    try { await this._hass.callWS({ type: "thermo_control/master_offset", offset }); this._error(""); }
    catch (error) { this._error(this._message(error)); this._updateSystem(); }
  }

  _fillSettings() {
    const config = this._settingsDraft = structuredClone(this._data.settings || SYSTEM_VALUES); this._settingsRevision = this._data.revision;
    const root = this.shadowRoot, form = root.querySelector("#system-form");
    for (const picker of form.querySelectorAll("thermo-control-entity-picker")) picker.value = config.heat_pump[picker.getAttribute("name")] || "";
    form.elements.automatic_states.value = config.heat_pump.automatic_states.join(", "); form.elements.interlock.checked = config.heat_pump.interlock;
    for (const key of ["minimum_flow", "flow_margin"]) form.elements[key].value = config.heat_pump[key];
    form.elements.calibration_interval.value = config.calibration_interval;
    this._numberFields(root.querySelector("#system-control"), CONTROL_NUMBERS, config.control); root.querySelector("#settings-status").textContent = "";
  }

  async _saveSettings() {
    const root = this.shadowRoot, form = root.querySelector("#system-form"); if (!form.reportValidity() || this._settingsSaving) return;
    const config = structuredClone(this._settingsDraft);
    for (const picker of form.querySelectorAll("thermo-control-entity-picker")) { picker.commit(); if (!picker.reportValidity()) return; config.heat_pump[picker.getAttribute("name")] = picker.value || null; }
    Object.assign(config.heat_pump, { automatic_states: form.elements.automatic_states.value.split(",").map((value) => value.trim()).filter(Boolean), interlock: form.elements.interlock.checked, minimum_flow: Number(form.elements.minimum_flow.value), flow_margin: Number(form.elements.flow_margin.value) });
    config.control = Object.fromEntries(CONTROL_NUMBERS.map(([key]) => [key, Number(form.elements[key].value)])); config.calibration_interval = Number(form.elements.calibration_interval.value);
    this._settingsSaving = true; form.querySelector("button[type=submit]").disabled = true;
    try { await this._hass.callWS({ type: "thermo_control/save_settings", config, revision: this._settingsRevision }); this._settingsRevision = this._data.revision; this._settingsDraft = config; root.querySelector("#settings-status").textContent = "Einstellungen gespeichert."; }
    catch (error) { root.querySelector("#settings-status").textContent = this._message(error); }
    finally { this._settingsSaving = false; form.querySelector("button[type=submit]").disabled = false; }
  }

  _graphChoices() {
    const select = this.shadowRoot.querySelector("#graph-room"), selected = select.value; select.replaceChildren();
    for (const room of this._data.rooms) { const option = create("option", room.config.name); option.value = room.entity_id || ""; select.append(option); }
    for (const group of this._data.settings.groups) { const option = create("option", `Gruppe: ${group.name}`); option.value = this._data.groups?.find((item) => item.id === group.id)?.entity_id || ""; select.append(option); }
    if ([...select.options].some((option) => option.value === selected)) select.value = selected;
  }

  async _loadHistory() {
    const root = this.shadowRoot, entityId = root.querySelector("#graph-room").value, generation = ++this._historyGeneration;
    root.querySelector("#graph-status").textContent = "Verlauf wird geladen …";
    if (!entityId) { root.querySelector("#history-chart").replaceChildren(); root.querySelector("#graph-tooltip").textContent = ""; root.querySelector("#graph-status").textContent = "Lege zuerst einen Raum an."; return; }
    const end = Date.now(), start = end - Number(root.querySelector("#graph-window").value) * 3600000;
    const flowId = root.querySelector("#graph-flow").checked ? this._data.settings.heat_pump.flow_sensor : null;
    try {
      const history = await this._hass.callWS({ type: "history/history_during_period", start_time: new Date(start).toISOString(), end_time: new Date(end).toISOString(), entity_ids: [entityId, flowId].filter(Boolean), significant_changes_only: false, minimal_response: false, no_attributes: false });
      if (generation !== this._historyGeneration || !this.isConnected) return;
      this._drawHistory(history || {}, entityId, flowId, start, end);
    } catch (error) {
      if (generation !== this._historyGeneration) return;
      root.querySelector("#history-chart").replaceChildren(); root.querySelector("#graph-status").textContent = "Verlauf nicht verfügbar. Aktiviere History/Recorder und prüfe, ob Raum- und Vorlaufsensor aufgezeichnet werden. " + this._message(error);
    }
  }

  _drawHistory(history, entityId, flowId, start, end) {
    const root = this.shadowRoot, svg = root.querySelector("#history-chart"); svg.replaceChildren(); root.querySelector("#graph-tooltip").textContent = "";
    const nativeUnit = this._hass.config?.unit_system?.temperature || "°C";
    const celsius = (value, unit = nativeUnit) => value == null || value === "" || !Number.isFinite(Number(value)) ? null : unit === "°F" ? (Number(value) - 32) * 5 / 9 : unit === "K" ? Number(value) - 273.15 : Number(value);
    const points = (history[entityId] || []).map((state) => {
      const a = state.a || state.attributes || {}, raw = state.lu ?? state.lc ?? state.last_updated ?? state.last_changed;
      const time = typeof raw === "number" ? raw * 1000 : Date.parse(raw), valid = !["unknown", "unavailable"].includes(state.s ?? state.state);
      return { time, current: valid ? (Number.isFinite(a.current_temperature_celsius) ? a.current_temperature_celsius : celsius(a.current_temperature)) : null, target: valid ? (Number.isFinite(a.effective_target_temperature) ? a.effective_target_temperature : celsius(a.temperature)) : null, action: valid ? a.hvac_action : null };
    }).filter((point) => Number.isFinite(point.time)).sort((a, b) => a.time - b.time);
    const flow = (history[flowId] || []).map((state) => { const a = state.a || state.attributes || {}, raw = state.lu ?? state.lc ?? state.last_updated ?? state.last_changed; return { time: typeof raw === "number" ? raw * 1000 : Date.parse(raw), value: celsius(state.s ?? state.state, a.unit_of_measurement || "°C") }; }).filter((point) => Number.isFinite(point.time)).sort((a, b) => a.time - b.time);
    const series = [{ points: points.map((p) => ({ time: p.time, value: p.current })), color: "#287757" }, { points: points.map((p) => ({ time: p.time, value: p.target })), color: "#c56a35", step: true }, { points: flow, color: "#467eb2" }];
    const values = series.flatMap((s) => s.points.map((p) => p.value).filter((v) => v !== null));
    if (!values.length) { root.querySelector("#graph-status").textContent = "Keine aufgezeichneten Messwerte im gewählten Zeitraum."; return; }
    const low = Math.floor(values.reduce((minimum, value) => Math.min(minimum, value), Infinity) - 1), high = Math.ceil(values.reduce((maximum, value) => Math.max(maximum, value), -Infinity) + 1), x = (time) => 55 + Math.max(0, Math.min(1, (time - start) / (end - start))) * 820, y = (value) => 260 - (value - low) / (high - low) * 220;
    const node = (tag, attributes, text) => { const element = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value)); if (text !== undefined) element.textContent = text; svg.append(element); return element; };
    for (let index = 0; index <= 4; index++) { const value = low + (high - low) * index / 4; node("line", { x1: 55, x2: 875, y1: y(value), y2: y(value), stroke: "#9baa9f", opacity: 0.2 }); node("text", { x: 5, y: y(value) + 4 }, `${value.toFixed(1)} °C`); const time = start + (end - start) * index / 4; node("text", { x: x(time), y: 328, "text-anchor": index === 0 ? "start" : index === 4 ? "end" : "middle" }, new Date(time).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })); }
    const compact = (points) => {
      if (points.length < 4000) return points;
      const result = []; let bucket = [], key = null;
      const flush = () => {
        if (!bucket.length) return;
        const minimum = bucket.reduce((a, b) => b.value !== null && (a.value === null || b.value < a.value) ? b : a);
        const maximum = bucket.reduce((a, b) => b.value !== null && (a.value === null || b.value > a.value) ? b : a);
        const missing = bucket.find((point) => point.value === null);
        result.push(...[...new Set([bucket[0], minimum, maximum, missing, bucket.at(-1)].filter(Boolean))].sort((a, b) => a.time - b.time));
      };
      for (const point of points) { const next = Math.floor((point.time - start) / (end - start) * 820); if (key !== next) { flush(); bucket = []; key = next; } bucket.push(point); } flush(); return result;
    };
    for (const s of series) {
      let path = "", last = null;
      // Draw recorded measurements; unavailable entries explicitly break the curve.
      for (const point of compact(s.points)) { if (point.value === null) { last = null; continue; } const px = x(point.time), py = y(point.value); path += last ? s.step ? ` H${px} V${py}` : ` L${px},${py}` : ` M${px},${py}`; last = point; }
      if (last) path += ` H${x(end)}`;
      node("path", { d: path, fill: "none", stroke: s.color, "stroke-width": 2 });
    }
    let phase = null;
    const drawPhase = (until) => { if (phase && ["heating", "idle", "off"].includes(phase.action)) node("rect", { x: x(phase.time), y: 283, width: Math.max(0.2, x(until) - x(phase.time)), height: 12, fill: phase.action === "heating" ? "#d18043" : "#bdc9bf" }); };
    for (const point of points) { if (!phase || point.action !== phase.action) { drawPhase(point.time); phase = point; } } drawPhase(end);
    const cursor = node("line", { x1: 55, x2: 55, y1: 35, y2: 299, stroke: "#69786e", visibility: "hidden" });
    svg.onpointermove = (event) => { const rect = svg.getBoundingClientRect(), time = start + Math.max(0, Math.min(1, ((event.clientX - rect.left) / rect.width * 900 - 55) / 820)) * (end - start); let nearest = points[0]; for (const point of points) if (!nearest || Math.abs(point.time - time) < Math.abs(nearest.time - time)) nearest = point; if (!nearest) return; cursor.setAttribute("x1", x(nearest.time)); cursor.setAttribute("x2", x(nearest.time)); cursor.setAttribute("visibility", "visible"); root.querySelector("#graph-tooltip").textContent = `${new Date(nearest.time).toLocaleString("de-DE")} · Ist ${nearest.current?.toFixed(2) ?? "—"} °C · Soll ${nearest.target?.toFixed(2) ?? "—"} °C · ${nearest.action || "unbekannt"}`; };
    root.querySelector("#graph-status").textContent = `${points.length} Raum-Meldungen${flowId ? ` · ${flow.length} Vorlauf-Meldungen` : ""}. Aufzeichnung gemäß HA-Recorder-Aufbewahrung.`;
  }

  _message(error) { return error?.message || "Die Aktion konnte nicht ausgeführt werden. Bitte erneut versuchen."; }
  _error(message) { this.shadowRoot.querySelector("#error").textContent = message; }
}

if (!customElements.get("thermo-control-entity-picker")) customElements.define("thermo-control-entity-picker", ThermoControlEntityPicker);
if (!customElements.get("thermo-control-panel")) customElements.define("thermo-control-panel", ThermoControlPanel);
