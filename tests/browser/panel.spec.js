const { test, expect } = require("@playwright/test");
const path = require("path");

async function mount(page, populated = false) {
  await page.setContent('<!doctype html><html><body style="margin:0;--card-background-color:#fff;--primary-background-color:#f4f6f4;--secondary-background-color:#eef3ef;--primary-text-color:#23312d;--secondary-text-color:#69786e;--divider-color:#d4ded5"></body></html>');
  await page.addScriptTag({ path: path.resolve("custom_components/thermo_control/frontend/thermo-control-panel.js") });
  await page.evaluate((populated) => {
    const defaults = { window_sensors: [], tolerance: 0.3, calibration_interval: 600, calibration_threshold: 0.5, window_open_delay: 30, window_close_delay: 60, frost_temperature: 5, preset_none: 20, preset_eco: 17, preset_comfort: 21, preset_boost: 25, preset_away: 15 };
    const deviceDefaults = { temperature_is_calibrated: true, regulated_mode: "heat", calibration_min: -9, calibration_max: 9, calibration_step: 0.5 };
    const config = { ...defaults, name: "Wohnzimmer", trvs: ["climate.trv"], temperature_sensor: "sensor.room", window_sensors: ["binary_sensor.window"], devices: { "climate.trv": { ...deviceDefaults, calibration_entity: "number.offset" } } };
    const days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
    const template = (name, blocks) => ({ name, weekdays: Object.fromEntries(days.map((day) => [day, blocks.map(([from, to, temp]) => ({ from, to, temp }))])) });
    let data = { schedules: [], schedule_revision: 0, time_zone: "Europe/Berlin", schedule_templates: { standard_fbh: template("Standard FBH", [["00:00", "06:00", 19], ["06:00", "22:00", 21.5], ["22:00", "24:00", 19]]), homeoffice: template("Homeoffice", [["00:00", "08:00", 18], ["08:00", "22:00", 21.5], ["22:00", "24:00", 18]]), away: template("Abwesend", [["00:00", "24:00", 18]]) }, rooms: populated ? [{ id: "living", config, entity_id: "climate.living" }] : [], revision: 0, defaults, device_defaults: deviceDefaults };
    let listener;
    window.messages = [];
    window.services = [];
    const panel = window.panel = document.createElement("thermo-control-panel");
    const hass = {
      states: {
        "climate.trv": { state: "heat", attributes: { friendly_name: "Heizkörper", hvac_modes: ["heat", "off"], current_temperature: 21.4, temperature_unit: "°C" } },
        "climate.wall": { state: "heat", attributes: { friendly_name: "Wandthermostat", hvac_modes: ["heat", "off"], current_temperature: 22.2, temperature_unit: "°C" } },
        "sensor.humidity": { state: "45", attributes: { friendly_name: "Luftfeuchtigkeit", unit_of_measurement: "%" } },
        "sensor.position": { state: "40", attributes: { friendly_name: "Ventilöffnung", unit_of_measurement: "%" } },
        "sensor.room": { state: "20.3", attributes: { friendly_name: "Raumtemperatur", unit_of_measurement: "°C" } },
        "number.offset": { state: "0", attributes: { friendly_name: "Temperaturkalibrierung" } },
        "binary_sensor.window": { state: "off", attributes: { friendly_name: "Fenster" } },
        "climate.living": { state: "heat", attributes: { current_temperature: 20.3, temperature: 21, min_temp: 5, max_temp: 30, desired_hvac_mode: "heat", preset_mode: "none", valve_position: 40, window_open: false, hvac_action: "idle" } },
      },
      config: { unit_system: { temperature: "°C" } },
      connection: { subscribeMessage: async (callback) => { listener = callback; callback(data); return () => { window.unsubscribed = true; }; } },
      callWS: async (message) => {
        window.messages.push(structuredClone(message));
        if (window.failSave && message.type.endsWith("save_room")) throw { message: "Ein Thermostat ist bereits einem anderen Raum zugeordnet." };
        if (message.type.endsWith("rooms")) return data;
        if (message.type.endsWith("get_schedules")) return { schedules: data.schedules, schedule_revision: data.schedule_revision, schedule_templates: data.schedule_templates, time_zone: data.time_zone };
        if (message.type.endsWith("save_schedule")) {
          if (window.failSchedule) throw { message: "Zeitblöcke überschneiden sich." };
          if (message.revision !== data.schedule_revision) throw { message: "Zeitpläne wurden inzwischen geändert. Bitte neu laden." };
          const same = (plan) => message.schedule.room_id ? plan.room_id === message.schedule.room_id : plan.group_id === message.schedule.group_id;
          data = { ...data, schedules: [...data.schedules.filter((plan) => !same(plan)), message.schedule], schedule_revision: data.schedule_revision + 1 }; listener(data); return { schedules: data.schedules, schedule_revision: data.schedule_revision };
        }
        if (message.type.endsWith("copy_schedule")) {
          if (window.failCopy) throw { message: "Zeitplan konnte nicht kopiert werden." };
          data = { ...data, schedule_revision: data.schedule_revision + 1 }; listener(data); return { schedules: data.schedules, schedule_revision: data.schedule_revision };
        }
        if (message.type.endsWith("save_settings")) {
          if (window.failSettings) throw { message: "Die Konfiguration wurde inzwischen geändert." };
          data = { ...data, settings: message.config, revision: data.revision + 1 }; listener(data); return {};
        }
        if (message.type.endsWith("master_offset")) { data = { ...data, settings: { ...data.settings, master_offset: message.offset }, revision: data.revision + 1 }; listener(data); return {}; }
        if (message.type === "history/history_during_period") {
          if (window.failHistory) throw { message: "History ist nicht eingerichtet." };
          return window.historyData || {};
        }
        if (message.type.endsWith("save_room")) {
          const room = { id: message.room_id || "living", config: message.config, entity_id: "climate.living" };
          data = { ...data, rooms: [room], revision: data.revision + 1 }; listener(data); return { room_id: room.id };
        }
        if (message.type.endsWith("delete_room")) { data = { ...data, rooms: [], revision: data.revision + 1 }; listener(data); return {}; }
      },
      callService: async (domain, service, data) => { window.services.push({ domain, service, data }); },
    };
    window.updateSnapshot = (snapshot) => { data = { ...data, ...snapshot }; listener(data); };
    window.updateEntity = (id, state) => { hass.states[id] = state; panel.hass = { ...hass }; };
    window.updateTemperature = (value) => { hass.states["climate.living"].attributes.current_temperature = value; panel.hass = { ...hass }; };
    panel.hass = hass;
    document.body.append(panel);
  }, populated);
  await expect(page.getByText("Mit Home Assistant verbunden")).toBeVisible();
}

async function pick(page, label, entityId, query = entityId) {
  await page.getByRole("combobox", { name: label, exact: true }).fill(query);
  await page.getByRole("listbox").getByRole("option").filter({ has: page.getByText(entityId, { exact: true }) }).click();
}

test("create a room entirely in the panel", async ({ page }) => {
  await mount(page);
  await page.getByRole("button", { name: "Ersten Raum anlegen" }).click();
  await page.getByLabel("Raumname").fill("Schlafzimmer");
  await pick(page, "Thermostate", "climate.trv");
  await pick(page, "Externer Raumtemperatursensor (optional)", "sensor.room");
  await pick(page, "Kalibrierungs-Number-Entität", "number.offset");
  await pick(page, "Sensor für die Ventilöffnung", "sensor.position");
  await pick(page, "Interner Temperatursensor (optional)", "sensor.room");
  await page.getByRole("button", { name: "Raum speichern" }).click();
  await expect(page.getByRole("heading", { name: "Schlafzimmer" })).toBeVisible();
  const message = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_room")));
  expect(message.config.trvs).toEqual(["climate.trv"]);
  expect(message.config.devices["climate.trv"].calibration_entity).toBe("number.offset");
  expect(message.config.devices["climate.trv"].position_entity).toBe("sensor.position");
  expect(message.config.devices["climate.trv"].internal_sensor).toBe("sensor.room");
  expect(message.config.calibration_interval).toBe(600);
});

test("display live values, control heating, edit and delete", async ({ page }) => {
  await mount(page, true);
  await expect(page.getByText("20,3", { exact: true })).toBeVisible();
  await expect(page.getByText("40 %", { exact: true })).toBeVisible();
  await page.screenshot({ path: "dist/thermo-control-panel.png", fullPage: true });
  await page.evaluate(() => window.updateTemperature(22.1));
  await expect(page.getByText("22,1", { exact: true })).toBeVisible();
  await page.getByLabel("Heizung", { exact: true }).selectOption("off");
  expect(await page.evaluate(() => window.services[0].data.hvac_mode)).toBe("off");
  await page.getByRole("button", { name: "Konfigurieren" }).click();
  await page.getByLabel("Raumname").fill("Wohnbereich");
  await page.getByRole("button", { name: "Fenster entfernen", exact: true }).click();
  await page.getByRole("button", { name: "Raum speichern" }).click();
  await expect(page.getByRole("heading", { name: "Wohnbereich" })).toBeVisible();
  await page.getByRole("button", { name: "Konfigurieren" }).click();
  await page.getByRole("button", { name: "Raum löschen", exact: true }).click();
  await page.locator("#confirm-delete-button").click();
  await expect(page.getByText("Hier beginnt deine Raumregelung")).toBeVisible();
});

test("errors preserve unsaved configuration", async ({ page }) => {
  await mount(page);
  await page.getByRole("tab", { name: "Thermostate & Gruppen", exact: true }).click();
  await page.getByRole("button", { name: "Raum hinzufügen", exact: true }).click();
  await page.getByLabel("Raumname").fill("Mein Raum");
  await pick(page, "Thermostate", "climate.trv");
  await pick(page, "Externer Raumtemperatursensor (optional)", "sensor.room");
  await page.evaluate(() => { window.failSave = true; });
  await page.getByRole("button", { name: "Raum speichern" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "bereits" })).toBeVisible();
  await expect(page.getByLabel("Raumname")).toHaveValue("Mein Raum");
  await expect(page.getByRole("button", { name: "Raum speichern" })).toBeEnabled();
});

test("mobile layout, local assets and no injected markup", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mount(page, true);
  await page.evaluate(() => {
    const data = structuredClone(window.panel._data);
    data.rooms[0].config.name = '<img src=x onerror="window.injected=true">';
    window.panel._receive(data);
  });
  await expect(page.getByRole("heading", { name: '<img src=x onerror="window.injected=true">' })).toBeVisible();
  expect(await page.locator("thermo-control-panel img").count()).toBe(0);
  await page.getByRole("button", { name: "Konfigurieren" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Abbrechen" }).click();
  await page.evaluate(() => window.panel.remove());
  expect(await page.evaluate(() => window.unsubscribed)).toBe(true);
});


test("search names and IDs with live temperature previews and temperature filtering", async ({ page }) => {
  await mount(page);
  await page.getByRole("button", { name: "Ersten Raum anlegen" }).click();
  const input = page.getByRole("combobox", { name: "Thermostate", exact: true });
  await input.fill("Heiz");
  const trv = page.getByRole("listbox").getByRole("option").filter({ has: page.getByText("climate.trv", { exact: true }) });
  await expect(trv).toContainText("21,4 °C");
  await expect(page.getByRole("listbox").getByRole("option")).toHaveCount(1);
  await page.evaluate(() => window.updateEntity("climate.trv", { state: "heat", attributes: { friendly_name: "Heizkörper", current_temperature: 23.8, temperature_unit: "°C", hvac_modes: ["heat", "off"] } }));
  await expect(input).toHaveValue("Heiz");
  await expect(input).toBeFocused();
  await expect(trv).toContainText("23,8 °C");
  await trv.click();
  await expect(page.locator('thermo-control-entity-picker[name="trvs"] .selection')).toContainText("23,8 °C");
  await page.evaluate(() => window.updateEntity("climate.trv", { state: "heat", attributes: { friendly_name: "Heizkörper", current_temperature: 24, temperature_unit: "°C", hvac_modes: ["heat", "off"] } }));
  await expect(page.locator('thermo-control-entity-picker[name="trvs"] .selection')).toContainText("24 °C");
  const sensor = page.getByRole("combobox", { name: "Externer Raumtemperatursensor (optional)" });
  await sensor.fill("humidity");
  await expect(page.getByRole("listbox").getByRole("option")).toHaveCount(0);
  await expect(page.getByText("Keine passenden Entitäten gefunden.")).toBeVisible();
  await sensor.fill("sensor.room");
  await expect(page.getByRole("listbox").getByRole("option")).toContainText("20.3 °C");
});

test("save exact typed entity ID with no external sensor", async ({ page }) => {
  await mount(page);
  await page.getByRole("button", { name: "Ersten Raum anlegen" }).click();
  await page.getByLabel("Raumname").fill("Wandthermostat-Raum");
  await page.getByRole("combobox", { name: "Thermostate", exact: true }).fill("climate.wall");
  await page.getByRole("button", { name: "Raum speichern" }).click();
  await expect(page.getByRole("heading", { name: "Wandthermostat-Raum" })).toBeVisible();
  await expect(page.locator(".temperature-source")).toHaveText("Thermostattemperatur");
  const message = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_room")));
  expect(message.config.trvs).toEqual(["climate.wall"]);
  expect(message.config.temperature_sensor).toBeNull();
});

test("multiple selections preserve device settings and keyboard contact selection", async ({ page }) => {
  await mount(page);
  await page.getByRole("button", { name: "Ersten Raum anlegen" }).click();
  await page.getByLabel("Raumname").fill("Zwei Thermostate");
  await pick(page, "Thermostate", "climate.trv", "Heizkorper");
  await pick(page, "Kalibrierungs-Number-Entität", "number.offset", "Kalibrierung");
  await pick(page, "Thermostate", "climate.wall", "Wand");
  const contact = page.getByRole("combobox", { name: "Fenster- und Türkontakte", exact: true });
  await contact.fill("Fenster");
  await contact.press("ArrowDown");
  await contact.press("Enter");
  await contact.press("ArrowDown");
  await contact.press("Escape");
  await expect(page.locator("#editor")).toBeVisible();
  await expect(contact).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "Raum speichern" }).click();
  const message = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_room")));
  expect(message.config.trvs).toEqual(["climate.trv", "climate.wall"]);
  expect(message.config.devices["climate.trv"].calibration_entity).toBe("number.offset");
  expect(message.config.window_sensors).toEqual(["binary_sensor.window"]);
});

test("clear an external sensor and edit without losing device settings", async ({ page }) => {
  await mount(page, true);
  await page.getByRole("button", { name: "Konfigurieren" }).click();
  await page.getByRole("combobox", { name: "Externer Raumtemperatursensor (optional)" }).fill("");
  await page.getByRole("button", { name: "Raum speichern" }).click();
  const message = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_room")));
  expect(message.config.temperature_sensor).toBeNull();
  expect(message.config.devices["climate.trv"].calibration_entity).toBe("number.offset");
  await page.getByRole("button", { name: "Konfigurieren" }).click();
  await expect(page.getByRole("combobox", { name: "Externer Raumtemperatursensor (optional)" })).toHaveValue("");
  await expect(page.getByText("Thermostattemperatur verwenden", { exact: true })).toBeVisible();
});

test("unresolved searches and empty required selections cannot be saved", async ({ page }) => {
  await mount(page);
  await page.getByRole("button", { name: "Ersten Raum anlegen" }).click();
  await page.getByLabel("Raumname").fill("Mein Raum");
  await pick(page, "Thermostate", "climate.wall");
  await page.getByRole("combobox", { name: "Externer Raumtemperatursensor (optional)" }).fill("sensor.missing");
  await page.getByRole("button", { name: "Raum speichern" }).click();
  expect(await page.evaluate(() => window.messages.filter((message) => message.type.endsWith("save_room")).length)).toBe(0);
  await page.getByRole("combobox", { name: "Externer Raumtemperatursensor (optional)" }).fill("");
  await page.getByRole("button", { name: "Wandthermostat entfernen", exact: true }).click();
  await page.getByRole("button", { name: "Raum speichern" }).click();
  expect(await page.evaluate(() => window.messages.filter((message) => message.type.endsWith("save_room")).length)).toBe(0);
  await expect(page.getByLabel("Raumname")).toHaveValue("Mein Raum");
});

test("entity search is safe on mobile and excludes virtual and assigned climates", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mount(page, true);
  await page.evaluate(() => window.updateEntity("climate.wall", { state: "heat", attributes: { friendly_name: '<img src=x onerror="window.injected=true">', current_temperature: 22.2, temperature_unit: "°C" } }));
  await page.getByRole("tab", { name: "Thermostate & Gruppen", exact: true }).click();
  await page.getByRole("button", { name: "Raum hinzufügen", exact: true }).click();
  await page.getByLabel("Raumname").fill("Zweiter Raum");
  await page.getByRole("combobox", { name: "Thermostate", exact: true }).fill("climate.");
  await expect(page.getByRole("listbox").getByRole("option")).toHaveCount(1);
  await expect(page.getByRole("listbox").getByRole("option")).toContainText("climate.wall");
  await expect(page.getByRole("listbox").getByRole("option")).toContainText('<img src=x onerror="window.injected=true">');
  expect(await page.locator("thermo-control-panel img").count()).toBe(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  await page.getByRole("listbox").getByRole("option").click();
  await page.screenshot({ path: "dist/thermo-control-room-editor.png", fullPage: true });
  const overflowing = await page.evaluate(() => {
    const body = window.panel.shadowRoot.querySelector(".dialog-body");
    return body.scrollWidth > body.clientWidth;
  });
  expect(overflowing).toBe(false);
});


test("five tabs are keyboard accessible and master offset is submitted", async ({ page }) => {
  await mount(page, true);
  await expect(page.getByRole("tab")).toHaveCount(5);
  await expect(page.getByRole("tab", { name: "Übersicht", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".master button")).toHaveCount(0);
  await page.locator("#master-offset").focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  expect(await page.evaluate(() => window.messages.filter((message) => message.type.endsWith("master_offset")).at(-1).offset)).toBe(2);
  await expect(page.locator("#master-value")).toHaveText("2 °C");
  await page.getByRole("tab", { name: "Übersicht", exact: true }).focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Einstellungen", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Globales Kalibrierungsintervall (s)")).toBeVisible();
  await page.keyboard.press("Home");
  await expect(page.getByRole("tab", { name: "Übersicht", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true }).click();
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("21.5");
  await expect.poll(() => page.evaluate(() => window.services.at(-1)?.data.temperature)).toBe(21.5);
});

async function pauseClock(page) {
  const time = new Date("2026-10-04T00:00:00Z");
  await page.clock.install({ time });
  await page.clock.pauseAt(time);
}

test("rapid room taps preview immediately, debounce from the final tap and survive stale HA snapshots", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  const target = page.getByLabel("Solltemperatur", { exact: true });
  await page.evaluate(() => {
    const plus = window.panel.shadowRoot.querySelector("#rooms .increase");
    plus.click(); plus.click(); plus.click();
  });
  await expect(target).toHaveValue("22.5");
  expect(await page.evaluate(() => window.services)).toEqual([]);
  await page.clock.runFor(350);
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur senken", exact: true }).click();
  await expect(target).toHaveValue("22.0");
  await page.evaluate(() => {
    window.updateTemperature(20.9);
    window.updateSnapshot({ revision: 1 }); // Rebuild the tiles while a command is queued.
  });
  await expect(target).toHaveValue("22.0");
  await page.clock.runFor(399);
  expect(await page.evaluate(() => window.services)).toEqual([]);
  await page.clock.runFor(1);
  await expect.poll(() => page.evaluate(() => window.services)).toEqual([
    { domain: "climate", service: "set_temperature", data: { entity_id: "climate.living", temperature: 22 } },
  ]);
  await page.evaluate(() => window.updateTemperature(21.1));
  await expect(target).toHaveValue("22.0");
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.attributes.temperature = 22;
    window.updateEntity("climate.living", state);
  });
  expect(await page.evaluate(() => window.panel._targets.size)).toBe(0);
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur senken", exact: true }).click();
  await expect(target).toHaveValue("21.5");
});

test("room and group steppers debounce independently in half-degree steps", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings);
    settings.groups = [{ id: "ground", name: "Erdgeschoss", control: {} }];
    window.updateEntity("climate.ground", { state: "heat", attributes: { temperature: 20, min_temp: 5, max_temp: 35, target_temp_step: 1, hvac_action: "idle" } });
    window.updateSnapshot({ settings, groups: [{ id: "ground", entity_id: "climate.ground" }] });
    const root = window.panel.shadowRoot;
    root.querySelector("#rooms .increase").click();
    root.querySelector("#group-cards .increase").click();
    root.querySelector("#group-cards .increase").click();
    root.querySelector("#group-cards .decrease").click();
  });
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("21.5");
  await expect(page.getByLabel("Erdgeschoss: Sollwert", { exact: true })).toHaveValue("20.5");
  await page.clock.runFor(399);
  expect(await page.evaluate(() => window.services)).toEqual([]);
  await page.clock.runFor(1);
  await expect.poll(() => page.evaluate(() => window.services.length)).toBe(2);
  const calls = await page.evaluate(() => window.services.map((call) => call.data));
  expect(calls).toContainEqual({ entity_id: "climate.living", temperature: 21.5 });
  expect(calls).toContainEqual({ entity_id: "climate.ground", temperature: 20.5 });
});

test("returning to the old HA target after an accepted command still sends the final target", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true }).click();
  await page.clock.runFor(400);
  await expect.poll(() => page.evaluate(() => window.services.length)).toBe(1);
  // The call succeeded, but HA still reports 21 °C. Undo the accepted change.
  await page.evaluate(() => {
    const root = window.panel.shadowRoot;
    root.querySelector(".increase").click();
    root.querySelector(".decrease").click(); root.querySelector(".decrease").click();
  });
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("21.0");
  await page.clock.runFor(400);
  await expect.poll(() => page.evaluate(() => window.services.length)).toBe(2);
  expect(await page.evaluate(() => window.services.at(-1).data.temperature)).toBe(21);
});

test("target bounds are 5 to 30 degrees, reject invalid input and avoid redundant commands", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  const target = page.getByLabel("Solltemperatur", { exact: true });
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    Object.assign(state.attributes, { temperature: 29.5, min_temp: 0, max_temp: 40 });
    window.updateEntity("climate.living", state);
  });
  await expect(target).toHaveAttribute("step", "0.5");
  await expect(target).toHaveAttribute("min", "5");
  await expect(target).toHaveAttribute("max", "30");
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true }).click();
  await expect(target).toHaveValue("30.0");
  await expect(page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true })).toBeDisabled();
  await page.clock.runFor(400);
  await expect.poll(() => page.evaluate(() => window.services.at(-1)?.data.temperature)).toBe(30);
  for (const value of ["30.5", "4.5", "22.3"]) {
    await target.fill(value);
    await page.clock.runFor(500);
  }
  expect(await page.evaluate(() => window.services.length)).toBe(1);
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.attributes.temperature = 5.5;
    window.updateEntity("climate.living", state);
  });
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur senken", exact: true }).click();
  await expect(target).toHaveValue("5.0");
  await expect(page.getByRole("button", { name: "Wohnzimmer: Temperatur senken", exact: true })).toBeDisabled();
  await page.clock.runFor(400);
  await expect.poll(() => page.evaluate(() => window.services.at(-1)?.data.temperature)).toBe(5);
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.attributes.temperature = 5;
    window.updateEntity("climate.living", structuredClone(state));
    state.attributes.temperature = 21;
    window.updateEntity("climate.living", state);
    const root = window.panel.shadowRoot;
    root.querySelector(".increase").click(); root.querySelector(".decrease").click();
  });
  await page.clock.runFor(500);
  expect(await page.evaluate(() => window.services.length)).toBe(2);
});

test("failed commands roll back the preview and disconnected panels cancel queued commands", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  await page.evaluate(() => {
    window.panel.hass.callService = async () => { throw { message: "Kein Zugriff auf den Thermostat." }; };
  });
  await page.getByLabel("Solltemperatur", { exact: true }).fill("22.5");
  await page.clock.runFor(400);
  await expect(page.locator("#error")).toHaveText("Kein Zugriff auf den Thermostat.");
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("21.0");
  await page.evaluate(() => {
    window.panel.hass.callService = async (domain, service, data) => window.services.push({ domain, service, data });
    window.panel.shadowRoot.querySelector("#rooms .increase").click();
    window.panel.remove();
  });
  await page.clock.runFor(1000);
  expect(await page.evaluate(() => window.services)).toEqual([]);
});

test("typing a target preserves decimal entry and an unconfirmed preview expires", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  const target = page.getByLabel("Solltemperatur", { exact: true });
  await target.fill("");
  await target.pressSequentially("22.5");
  await expect(target).toHaveValue("22.5");
  await page.clock.runFor(399);
  expect(await page.evaluate(() => window.services)).toEqual([]);
  await page.clock.runFor(1);
  await expect.poll(() => page.evaluate(() => window.services.at(-1)?.data.temperature)).toBe(22.5);
  await page.clock.runFor(9999);
  await expect(target).toHaveValue("22.5");
  await page.clock.runFor(1);
  await expect(target).toHaveValue("21.0");
});

test("unavailable thermostats cancel queued targets and narrower hardware limits are respected", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true }).click();
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.state = "unavailable";
    window.updateEntity("climate.living", state);
  });
  await expect(page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true })).toBeDisabled();
  await page.clock.runFor(500);
  expect(await page.evaluate(() => window.services)).toEqual([]);
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.state = "heat";
    Object.assign(state.attributes, { temperature: 23.5, min_temp: 15, max_temp: 24 });
    window.updateEntity("climate.living", state);
  });
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true }).click();
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("24.0");
  await expect(page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true })).toBeDisabled();
  await page.clock.runFor(400);
  await expect.poll(() => page.evaluate(() => window.services.at(-1)?.data.temperature)).toBe(24);
});

test("overlapping target calls are serialized and stale responses preserve the last tap", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  await page.evaluate(() => {
    window.resolveServices = [];
    window.panel.hass.callService = async (domain, service, data) => {
      window.services.push({ domain, service, data });
      await new Promise((resolve) => window.resolveServices.push(resolve));
    };
    window.panel.shadowRoot.querySelector("#rooms .increase").click();
  });
  await page.clock.runFor(400);
  await expect.poll(() => page.evaluate(() => window.services.length)).toBe(1);
  await page.evaluate(() => {
    const button = window.panel.shadowRoot.querySelector("#rooms .increase"); button.click(); button.click();
  });
  await page.clock.runFor(400);
  expect(await page.evaluate(() => window.services.length)).toBe(1);
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("22.5");
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.attributes.temperature = 21.5;
    window.updateEntity("climate.living", state);
    window.resolveServices[0]();
  });
  await expect.poll(() => page.evaluate(() => window.services.length)).toBe(2);
  expect(await page.evaluate(() => window.services.at(-1).data.temperature)).toBe(22.5);
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("22.5");
  await page.evaluate(() => window.resolveServices[1]());
});

for (const [width, font] of [[320, "system-ui"], [390, "system-ui"], [1280, "system-ui"], [320, "Arial, sans-serif"], [320, "FreeSans, sans-serif"]]) {
  test(`two-column room tiles and full-width touch steppers at ${width}px with ${font}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mount(page, true);
    await page.evaluate((font) => {
      window.panel.style.setProperty("--paper-font-body1_-_font-family", font);
      const room = structuredClone(window.panel._data.rooms[0]);
      room.id = "bedroom"; room.config.name = "Schlafzimmer mit sehr langem Namen";
      window.updateSnapshot({ rooms: [...window.panel._data.rooms, room] });
      const state = structuredClone(window.panel.hass.states["climate.living"]);
      state.attributes.hvac_action = "heating";
      window.updateEntity("climate.living", state);
    }, font);
    const geometry = await page.evaluate(() => {
      const root = window.panel.shadowRoot, grid = root.querySelector(".rooms-grid"), tiles = [...grid.querySelectorAll(".room-tile")];
      return {
        columns: getComputedStyle(grid).gridTemplateColumns.split(" ").length,
        gap: getComputedStyle(grid).gap,
        positions: tiles.map((tile) => ({ x: tile.getBoundingClientRect().x, y: tile.getBoundingClientRect().y })),
        buttons: [...grid.querySelectorAll(".target-stepper button")].map((button) => ({ width: button.getBoundingClientRect().width, height: button.getBoundingClientRect().height })),
        targetsFit: [...grid.querySelectorAll(".target-input")].filter((input) => input.scrollWidth > input.clientWidth).map((input) => ({ value: input.value, width: input.clientWidth, scrollWidth: input.scrollWidth, font: getComputedStyle(input).font })),
        pills: tiles.map((tile) => ({ parts: tile.querySelector(".target-stepper").children.length, width: tile.querySelector(".target-stepper").getBoundingClientRect().width, available: tile.clientWidth })),
        overflow: [root.host, root.querySelector("main"), grid, ...tiles, ...grid.querySelectorAll(".measure,.eyebrow")].filter((node) => node.scrollWidth > node.clientWidth).map((node) => ({ className: node.className, width: node.clientWidth, scrollWidth: node.scrollWidth })),
        heating: tiles.every((tile) => tile.classList.contains("heating")),
        border: getComputedStyle(tiles[0]).borderColor,
      };
    });
    expect(geometry.columns).toBe(2);
    expect(geometry.gap).toBe("8px");
    expect(geometry.positions[0].y).toBe(geometry.positions[1].y);
    expect(geometry.positions[0].x).not.toBe(geometry.positions[1].x);
    expect(geometry.overflow).toEqual([]);
    expect(geometry.targetsFit).toEqual([]);
    expect(geometry.heating).toBe(true);
    for (const button of geometry.buttons) { expect(button.width).toBeGreaterThanOrEqual(44); expect(button.height).toBeGreaterThanOrEqual(44); }
    for (const pill of geometry.pills) { expect(pill.parts).toBe(3); expect(Math.abs(pill.width - pill.available)).toBeLessThan(1); }
    if (width === 390) await page.screenshot({ path: "dist/thermo-control-stepper-mobile.png", fullPage: true });
  });
}

test("FBH room options and global Luxtronik settings are editable and validated", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    window.updateEntity("sensor.flow", { state: "32", attributes: { friendly_name: "Luxtronik Vorlauf", unit_of_measurement: "°C" } });
    window.updateEntity("sensor.flow_target", { state: "35", attributes: { friendly_name: "Luxtronik Soll", unit_of_measurement: "°C" } });
    window.updateEntity("select.pump_mode", { state: "automatic", attributes: { friendly_name: "Luxtronik Heizmodus" } });
    window.updateEntity("binary_sensor.compressor", { state: "on", attributes: { friendly_name: "Verdichter" } });
  });
  await page.getByRole("tab", { name: "Einstellungen", exact: true }).click();
  await pick(page, "Vorlauftemperatur Ist", "sensor.flow");
  await pick(page, "Vorlauftemperatur Soll", "sensor.flow_target");
  await pick(page, "Heizungs-Betriebsmodus", "select.pump_mode");
  await pick(page, "Verdichterstatus", "binary_sensor.compressor");
  await page.getByLabel("Wärmepumpen-Freigabe für Raumventile aktivieren").check();
  await page.getByLabel("Trend-Zeitfenster (Min.)", { exact: true }).fill("60");
  await page.getByRole("button", { name: "Einstellungen speichern", exact: true }).click();
  await expect(page.getByText("Einstellungen gespeichert.")).toBeVisible();
  const settings = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_settings")));
  expect(settings.config.heat_pump.flow_sensor).toBe("sensor.flow");
  expect(settings.config.heat_pump.mode_entity).toBe("select.pump_mode");
  expect(settings.config.heat_pump.interlock).toBe(true);
  expect(settings.config.control.trend_window).toBe(60);
  await page.getByRole("tab", { name: "Übersicht", exact: true }).click();
  await page.getByRole("button", { name: "Konfigurieren", exact: true }).click();
  await page.getByRole("combobox", { name: "Heizungstyp", exact: true }).selectOption("floor");
  await page.getByLabel("Etage / Zone", { exact: true }).fill("Erdgeschoss");
  await page.getByLabel("Globale FBH-Parameter verwenden", { exact: false }).uncheck();
  await page.locator("#advanced summary").click();
  await page.locator('#room-form input[name=lookahead]').fill("240");
  await page.getByRole("button", { name: "Raum speichern", exact: true }).click();
  const room = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_room")));
  expect(room.config.heating_type).toBe("floor");
  expect(room.config.floor).toBe("Erdgeschoss");
  expect(room.config.lookahead).toBe(240);
  expect(room.config.use_global_control).toBe(false);
});

test("group configuration and selector matrix assign rooms", async ({ page }) => {
  await mount(page, true);
  await page.getByRole("tab", { name: "Thermostate & Gruppen", exact: true }).click();
  await page.getByRole("button", { name: "Gruppe hinzufügen", exact: true }).click();
  await page.getByLabel("Gruppenname", { exact: true }).fill("Wohnbereich");
  await page.getByLabel("Eigene FBH-Parameter für diese Gruppe").check();
  await page.locator('#group-form input[name=lookahead]').fill("120");
  await page.getByRole("button", { name: "Gruppe speichern", exact: true }).click();
  const group = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_settings")).config.groups[0]);
  expect(group.name).toBe("Wohnbereich");
  expect(group.control.lookahead).toBe(120);
  await page.getByLabel("Wohnzimmer: Gruppe", { exact: true }).selectOption(group.id);
  const room = await page.evaluate(() => window.messages.find((message) => message.type.endsWith("save_room")));
  expect(room.config.group_id).toBe(group.id);
  await page.getByRole("tab", { name: "Übersicht", exact: true }).click();
  await expect(page.locator("#group-cards")).toContainText("Wohnbereich");
  await page.getByRole("button", { name: "Konfigurieren", exact: true }).click();
  await expect(page.locator('#room-form select[name=group_id]')).toHaveValue(group.id);
});

test("history selection loads recorded room and dual-axis flow without refresh controls", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings);
    settings.heat_pump.flow_sensor = "sensor.flow";
    window.updateSnapshot({ settings });
    const now = Date.now() / 1000;
    window.historyData = {
      "climate.living": [
        { s: "heat", lu: now - 3600, a: { current_temperature_celsius: 20, effective_target_temperature: 21, hvac_action: "heating", valve_position: 45 } },
        { s: "heat", lu: now - 1800, a: { current_temperature_celsius: 20.5, effective_target_temperature: 21, hvac_action: "idle" } },
        { s: "unavailable", lu: now - 900, a: {} },
        { s: "heat", lu: now - 600, a: { current_temperature_celsius: 20.6, effective_target_temperature: 21, hvac_action: "idle" } },
      ], "sensor.flow": [{ s: "32", lu: now - 3600, a: { unit_of_measurement: "°C" } }],
    };
  });
  await page.getByRole("tab", { name: "Verläufe & Analyse", exact: true }).click();
  await expect(page.locator("#history-chart path")).toHaveCount(2);
  await expect(page.locator("#history-chart")).toHaveAttribute("data-room-low", "19.5");
  await expect(page.locator("#history-chart")).toHaveAttribute("data-room-high", "21.5");
  await page.getByRole("checkbox", { name: "Vorlauf", exact: true }).check();
  await expect(page.locator("#history-chart path")).toHaveCount(3);
  await expect(page.locator("#history-chart")).toHaveAttribute("data-room-high", "21.5");
  await expect(page.locator("#history-chart")).toHaveAttribute("data-flow-low", "31.5");
  await expect(page.locator("#history-chart .flow-axis")).toHaveCount(5);
  await expect(page.locator("#history-chart .heating-band")).toHaveCount(1);
  for (const hours of [6, 24, 48]) {
    await page.getByRole("button", { name: `${hours}h`, exact: true }).click();
    await expect(page.getByRole("button", { name: `${hours}h`, exact: true })).toHaveAttribute("aria-pressed", "true");
    const message = await page.evaluate(() => window.messages.filter((message) => message.type === "history/history_during_period").at(-1));
    expect(message.entity_ids).toEqual(["climate.living", "sensor.flow"]);
    expect((Date.parse(message.end_time) - Date.parse(message.start_time)) / 3600000).toBe(hours);
    expect(message.significant_changes_only).toBe(false);
  }
  await expect(page.getByRole("button", { name: "Aktualisieren", exact: true })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Zeitfenster", exact: true })).toHaveCount(0);
  await page.evaluate(() => { window.failHistory = true; });
  await page.getByRole("button", { name: "6h", exact: true }).click();
  await expect(page.locator("#graph-status")).toContainText("Verlauf nicht verfügbar");
  await expect(page.locator("#history-chart path")).toHaveCount(0);
  await expect(page.locator("#graph-tooltip")).toBeHidden();
});

test("settings conflict preserves draft and incoming telemetry preserves focused input", async ({ page }) => {
  await mount(page, true);
  await page.getByLabel("Solltemperatur", { exact: true }).fill("22.5");
  await page.evaluate(() => window.updateSnapshot({ system: { flow: 33, demand: 50, eligible_demand: 50, compressor: true, mode: "Automatik" } }));
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("22.5");
  await expect(page.locator("#system-bar")).toContainText("33 °C");
  await expect(page.locator("#system-bar")).toContainText("Aktiv");
  await page.getByRole("tab", { name: "Einstellungen", exact: true }).click();
  await page.locator('#system-form input[name=lookahead]').fill("240");
  await page.evaluate(() => { window.failSettings = true; });
  await page.getByRole("button", { name: "Einstellungen speichern", exact: true }).click();
  await expect(page.locator("#settings-status")).toContainText("inzwischen geändert");
  await expect(page.locator('#system-form input[name=lookahead]')).toHaveValue("240");
});

test("all tabs fit a mobile viewport without remote assets", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const external = [];
  page.on("request", (request) => { if (/^https?:/.test(request.url())) external.push(request.url()); });
  await mount(page, true);
  for (const name of ["Einstellungen", "Thermostate & Gruppen", "Verläufe & Analyse", "Übersicht"]) {
    await page.getByRole("tab", { name, exact: true }).click();
    const overflowing = await page.evaluate(() => window.panel.shadowRoot.querySelector("main").scrollWidth > window.panel.shadowRoot.querySelector("main").clientWidth);
    expect(overflowing).toBe(false);
  }
  expect(external).toEqual([]);
  await page.screenshot({ path: "dist/thermo-control-overview-mobile.png", fullPage: true });
});

test("dense histories retain peaks and bound chart geometry", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    const now = Date.now() / 1000;
    const states = Array.from({ length: 12000 }, (_, i) => ({ s: "heat", lu: now - 12000 + i, a: { current_temperature_celsius: i === 7000 ? 29 : 20, effective_target_temperature: 21, hvac_action: "idle" } }));
    window.historyData = { "climate.living": states };
  });
  await page.getByRole("tab", { name: "Verläufe & Analyse", exact: true }).click();
  await expect(page.locator("#history-chart path")).toHaveCount(2);
  await expect(page.locator("#history-chart .heating-band")).toHaveCount(0);
  const path = await page.locator('#history-chart path').first().getAttribute('d');
  expect(path.length).toBeLessThan(60000);
  const labels = await page.locator('#history-chart text').allTextContents();
  expect(labels.some((text) => text.includes('29.5'))).toBe(true);
});

test("native Auto shows the device target and requires a deliberate manual takeover", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.attributes.hvac_modes = ["off", "heat", "auto"];
    window.updateEntity("climate.living", state);
  });
  await page.getByLabel("Heizung", { exact: true }).selectOption("auto");
  expect(await page.evaluate(() => window.services.map((call) => [call.service, call.data.hvac_mode]))).toEqual([["set_hvac_mode", "auto"]]);
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.state = "auto";
    Object.assign(state.attributes, { native_auto: true, temperature: 19, hvac_action: "heating", desired_hvac_mode: "heat" });
    window.updateEntity("climate.living", state);
  });
  await expect(page.getByLabel("Heizung", { exact: true })).toHaveValue("auto");
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("19.0");
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Preset", { exact: true })).toBeDisabled();
  await expect(page.getByText("Auto · Gerätezeitplan; externe Regelung pausiert.", { exact: true })).toBeVisible();
  await expect(page.locator(".room-tile")).toHaveClass(/heating/);
  await page.getByLabel("Heizung", { exact: true }).selectOption("heat");
  expect(await page.evaluate(() => window.services.map((call) => [call.service, call.data.hvac_mode]))).toEqual([["set_hvac_mode", "auto"], ["set_hvac_mode", "heat"]]);
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.state = "heat";
    Object.assign(state.attributes, { native_auto: false, temperature: 21 });
    window.updateEntity("climate.living", state);
  });
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toBeEnabled();
  await expect(page.getByLabel("Preset", { exact: true })).toBeEnabled();
});

test("switching a device to Auto cancels a debounced target before it is sent", async ({ page }) => {
  await pauseClock(page);
  await mount(page, true);
  await page.getByLabel("Solltemperatur", { exact: true }).fill("21.5");
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("21.5");
  await page.clock.runFor(200);
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    state.state = "auto";
    Object.assign(state.attributes, { native_auto: true, temperature: 18.5 });
    window.updateEntity("climate.living", state);
  });
  await page.clock.runFor(500);
  expect(await page.evaluate(() => window.services)).toEqual([]);
  await expect(page.getByLabel("Solltemperatur", { exact: true })).toHaveValue("18.5");
  await expect(page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true })).toBeDisabled();
});

test("groups containing Auto rooms disable their target but allow explicit mode changes", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings);
    settings.groups = [{ id: "ground", name: "Erdgeschoss", control: {} }];
    window.updateEntity("climate.ground", { state: "heat", attributes: { temperature: 20, hvac_modes: ["off", "heat", "auto"], auto_rooms: ["climate.living"], hvac_action: "idle" } });
    window.updateSnapshot({ settings, groups: [{ id: "ground", entity_id: "climate.ground" }] });
  });
  await expect(page.getByLabel("Erdgeschoss: Sollwert", { exact: true })).toBeDisabled();
  await expect(page.locator("#group-cards .increase")).toBeDisabled();
  await expect(page.getByLabel("Erdgeschoss: Heizung", { exact: true })).toBeEnabled();
  await expect(page.getByLabel("Erdgeschoss: Preset", { exact: true })).toBeDisabled();
  await page.getByLabel("Erdgeschoss: Heizung", { exact: true }).selectOption("auto");
  expect(await page.evaluate(() => window.services)).toEqual([{ domain: "climate", service: "set_hvac_mode", data: { entity_id: "climate.ground", hvac_mode: "auto" } }]);
});

test("group mode and preset selectors control the whole group and fit mobile cards", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings);
    settings.groups = [{ id: "ground", name: "Erdgeschoss", control: {} }];
    window.updateEntity("climate.ground", { state: "heat", attributes: { temperature: 21, hvac_modes: ["off", "heat"], preset_modes: ["none", "eco", "comfort", "boost", "away"], preset_mode: "comfort", hvac_action: "idle" } });
    window.updateSnapshot({ settings, groups: [{ id: "ground", entity_id: "climate.ground" }] });
  });
  const mode = page.getByLabel("Erdgeschoss: Heizung", { exact: true });
  const preset = page.getByLabel("Erdgeschoss: Preset", { exact: true });
  await expect(mode).toHaveValue("heat");
  await expect(preset).toHaveValue("comfort");
  await expect(page.locator('#group-cards .controls button')).toHaveCount(0);
  await expect(mode.locator('option[value="auto"]')).toHaveJSProperty("disabled", true);
  await preset.selectOption("eco");
  await mode.selectOption("off");
  expect(await page.evaluate(() => window.services)).toEqual([
    { domain: "climate", service: "set_preset_mode", data: { entity_id: "climate.ground", preset_mode: "eco" } },
    { domain: "climate", service: "set_hvac_mode", data: { entity_id: "climate.ground", hvac_mode: "off" } },
  ]);
  const fits = await page.evaluate(() => {
    const card = window.panel.shadowRoot.querySelector(".group-card");
    const bounds = card.getBoundingClientRect();
    return bounds.left >= 0 && bounds.right <= innerWidth && [...card.querySelectorAll("select")].every((select) => select.getBoundingClientRect().right <= bounds.right && select.getBoundingClientRect().height === 38);
  });
  expect(fits).toBe(true);
  await page.evaluate(() => window.updateEntity("climate.ground", { state: "unavailable", attributes: { temperature: 21 } }));
  await expect(mode).toBeDisabled();
  await expect(preset).toBeDisabled();
});

async function schedules(page) {
  await page.getByRole("tab", { name: "Zeitpläne", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Wochenzeitpläne", exact: true })).toBeVisible();
  return page.locator("thermo-control-schedule-editor");
}

test("visual weekly editor loads FBH templates and edits weekdays without changing weekends", async ({ page }) => {
  await mount(page, true);
  const editor = await schedules(page);
  await editor.getByLabel("Vorlage", { exact: true }).selectOption("standard_fbh");
  await editor.getByRole("button", { name: "Mo–Fr", exact: true }).click();
  await editor.getByRole("button", { name: "Zeitblock 06:00 bis 22:00, 21.5 °C", exact: true }).click();
  await editor.getByLabel("Block-Sollwert (°C)", { exact: true }).fill("22");
  await editor.getByRole("button", { name: "Block übernehmen", exact: true }).click();
  await editor.getByLabel("Automatikmodus aktiv", { exact: true }).check();
  await editor.getByLabel("Vorausschauendes Vorheizen bei FBH", { exact: true }).check();
  await editor.getByRole("button", { name: "Zeitplan speichern", exact: true }).click();
  await expect(editor.getByRole("alert").filter({ hasText: "Zeitplan gespeichert" })).toBeVisible();
  const call = await page.evaluate(() => window.messages.find((message) => message.type === "thermo_control/save_schedule"));
  expect(call.schedule.room_id).toBe("living"); expect(call.schedule.enabled).toBe(true); expect(call.schedule.preheat).toBe(true);
  for (const day of ["monday", "tuesday", "wednesday", "thursday", "friday"]) expect(call.schedule.weekdays[day][1].temp).toBe(22);
  expect(call.schedule.weekdays.saturday[1].temp).toBe(21.5);
  expect(call.schedule.weekdays.sunday[1].temp).toBe(21.5);
  const lengths = await editor.locator("#timeline button").evaluateAll((buttons) => buttons.map((button) => parseFloat(button.style.width)));
  [25, 100 * 16 / 24, 100 * 2 / 24].forEach((value, index) => expect(lengths[index]).toBeCloseTo(value, 4));
});

test("night blocks appear on the next day and can be edited from their carry segment", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await mount(page, true); const editor = await schedules(page);
  await editor.getByRole("button", { name: "+ Block hinzufügen", exact: true }).click();
  await editor.getByLabel("Startzeit", { exact: true }).fill("22:00");
  await editor.getByLabel("Endzeit", { exact: true }).fill("06:00");
  await editor.getByLabel("Block-Sollwert (°C)", { exact: true }).fill("18");
  await editor.getByRole("button", { name: "Block übernehmen", exact: true }).click();
  await editor.getByRole("button", { name: "Di", exact: true }).click();
  const night = editor.getByRole("button", { name: "Nachtblock 22:00 bis 06:00, 18 °C", exact: true });
  await expect(night).toBeVisible();
  expect(await night.evaluate((button) => button.style.width)).toBe("25%");
  await night.click();
  await expect(editor.getByRole("button", { name: "Mo", exact: true })).toHaveAttribute("aria-pressed", "true");
  await editor.getByLabel("Block-Sollwert (°C)", { exact: true }).fill("18.5");
  await editor.getByRole("button", { name: "Block übernehmen", exact: true }).click();
  await editor.getByRole("button", { name: "Zeitplan speichern", exact: true }).click();
  const plan = await page.evaluate(() => window.messages.find((message) => message.type === "thermo_control/save_schedule").schedule);
  expect(plan.weekdays.monday).toEqual([{ from: "22:00", to: "06:00", temp: 18.5 }]);
  expect(plan.weekdays.tuesday).toEqual([]);
  expect(await editor.evaluate((element) => element.getBoundingClientRect().right <= innerWidth && element.shadowRoot.querySelector("section").scrollWidth <= element.getBoundingClientRect().width)).toBe(true);
});

test("weekly and day copies use the selected room group and days", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings); settings.groups = [{ id: "ground", name: "Erdgeschoss", control: {} }];
    window.updateSnapshot({ settings, groups: [{ id: "ground", entity_id: "climate.ground" }] });
  });
  const editor = await schedules(page);
  await editor.getByLabel("Vorlage", { exact: true }).selectOption("homeoffice");
  await editor.getByRole("button", { name: "Zeitplan speichern", exact: true }).click();
  await editor.getByRole("button", { name: "Plan auf andere Räume übertragen", exact: true }).click();
  await editor.getByLabel("Zielräume und Gruppen", { exact: true }).selectOption("group:ground");
  await editor.getByRole("button", { name: "Kopieren", exact: true }).click();
  let call = await page.evaluate(() => window.messages.filter((message) => message.type === "thermo_control/copy_schedule").at(-1));
  expect(call.source).toBe("room:living"); expect(call.targets).toEqual(["group:ground"]); expect(call.source_day).toBeUndefined();
  await editor.getByRole("button", { name: "Plan auf andere Räume übertragen", exact: true }).click();
  await editor.getByLabel("Kopierumfang", { exact: true }).selectOption("day");
  await editor.getByLabel("Zielräume und Gruppen", { exact: true }).selectOption("room:living");
  await editor.getByLabel("Zieltage", { exact: true }).selectOption(["saturday", "sunday"]);
  await editor.getByRole("button", { name: "Kopieren", exact: true }).click();
  call = await page.evaluate(() => window.messages.filter((message) => message.type === "thermo_control/copy_schedule").at(-1));
  expect(call.source_day).toBe("monday"); expect(call.target_days).toEqual(["saturday", "sunday"]);
});

test("schedule validation errors and concurrent snapshots preserve editor and open block drafts", async ({ page }) => {
  await mount(page, true); const editor = await schedules(page);
  await editor.getByLabel("Vorlage", { exact: true }).selectOption("away");
  await editor.getByRole("button", { name: "Zeitblock 00:00 bis 24:00, 18 °C", exact: true }).click();
  await editor.getByLabel("Block-Sollwert (°C)", { exact: true }).fill("19.5");
  await page.evaluate(() => window.updateSnapshot({ schedule_revision: 2 }));
  await expect(editor.getByLabel("Block-Sollwert (°C)", { exact: true })).toHaveValue("19.5");
  await editor.getByRole("button", { name: "Block übernehmen", exact: true }).click();
  await page.evaluate(() => { window.failSchedule = true; });
  await editor.getByRole("button", { name: "Zeitplan speichern", exact: true }).click();
  await expect(editor.getByRole("alert").filter({ hasText: "überschneiden" })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Zeitblock 00:00 bis 24:00, 19.5 °C", exact: true })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Zeitplan speichern", exact: true })).toBeEnabled();
  await page.evaluate(() => { window.failSchedule = false; });
  await editor.getByRole("button", { name: "Zeitplan speichern", exact: true }).click();
  await expect(editor.getByRole("alert").filter({ hasText: "inzwischen geändert" })).toBeVisible();
});

test("room calendar switches automation and shows timed overrides while steppers remain usable", async ({ page }) => {
  await pauseClock(page); await mount(page, true);
  const toggle = page.getByRole("button", { name: "Wohnzimmer: Zeitplan umschalten", exact: true });
  await toggle.click();
  await expect(page.getByRole("tab", { name: "Zeitpläne", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.evaluate(() => {
    window.updateSnapshot({ schedules: [{ room_id: "living", enabled: true, weekdays: {} }], schedule_revision: 1 });
    const state = structuredClone(window.panel.hass.states["climate.living"]);
    Object.assign(state.attributes, { schedule_active: true, schedule_override: true, schedule_until: "2026-10-04T14:00:00Z", preset_mode: "schedule" });
    window.updateEntity("climate.living", state);
  });
  await page.getByRole("tab", { name: "Übersicht", exact: true }).click();
  await expect(page.getByText("Override (bis 16:00)", { exact: true })).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Wohnzimmer: Temperatur erhöhen", exact: true }).click();
  await page.clock.runFor(400);
  expect(await page.evaluate(() => window.services.at(-1).data.temperature)).toBe(21.5);
  await toggle.click();
  expect(await page.evaluate(() => window.services.at(-1).data.preset_mode)).toBe("none");
  await page.evaluate(() => {
    const state = structuredClone(window.panel.hass.states["climate.living"]); state.attributes.schedule_active = false; state.attributes.preset_mode = "none"; window.updateEntity("climate.living", state);
  });
  await toggle.click();
  expect(await page.evaluate(() => window.services.at(-1).data.preset_mode)).toBe("schedule");
});

async function analyticsFixture(page) {
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings);
    settings.heat_pump.flow_sensor = "sensor.flow";
    window.updateSnapshot({ settings });
    window.updateEntity("sensor.flow", { state: "34", attributes: { unit_of_measurement: "°C" } });
    const end = Date.now() / 1000, start = end - 86400;
    window.historyData = {
      "climate.living": [
        { s: "heat", lu: start, a: { current_temperature_celsius: 21, effective_target_temperature: 21, hvac_action: "idle", valve_position: 0 } },
        { s: "heat", lu: start + 21600, a: { current_temperature_celsius: 21.1, effective_target_temperature: 21, hvac_action: "heating", valve_position: 45 } },
        { s: "heat", lu: start + 32400, a: { current_temperature_celsius: 21.2, effective_target_temperature: 21, hvac_action: "idle", valve_position: 0 } },
        { s: "unavailable", lu: start + 43200, a: {} },
        { s: "heat", lu: start + 64800, a: { current_temperature_celsius: 21.1, effective_target_temperature: 21, hvac_action: "heating", valve_position: 30 } },
      ],
      "sensor.flow": [{ s: "29", lu: start, a: { unit_of_measurement: "°C" } }, { s: "35", lu: start + 43200, a: { unit_of_measurement: "°C" } }],
    };
  });
  await page.getByRole("tab", { name: "Verläufe & Analyse", exact: true }).click();
  await expect(page.locator("#history-chart .room-curve")).toHaveCount(2);
}

test("mobile analytics fills height with readable axes, compact header and touch tooltip", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await analyticsFixture(page);
  await page.getByRole("checkbox", { name: "Vorlauf", exact: true }).check();
  await expect(page.locator("#history-chart .flow-curve")).toHaveCount(1);
  const dimensions = await page.evaluate(() => {
    const root = window.panel.shadowRoot, svg = root.querySelector("#history-chart"), card = root.querySelector(".analytics");
    return { chart: svg.getBoundingClientRect().toJSON(), card: card.getBoundingClientRect().toJSON(), headerHeight: root.querySelector(".chart-header").getBoundingClientRect().height, viewBox: svg.viewBox.baseVal.width, font: getComputedStyle(svg.querySelector("text")).fontSize };
  });
  expect(dimensions.chart.height).toBeGreaterThanOrEqual(320);
  expect(dimensions.chart.width).toBeGreaterThan(dimensions.card.width - 16);
  expect(dimensions.viewBox).toBeCloseTo(dimensions.chart.width, 1);
  expect(dimensions.headerHeight).toBeLessThan(100);
  const dots = await page.evaluate(() => [...window.panel.shadowRoot.querySelectorAll(".legend span")].map((node) => ({ content: getComputedStyle(node, "::before").content, width: getComputedStyle(node, "::before").width, color: getComputedStyle(node, "::before").backgroundColor })));
  expect(dots.map((dot) => dot.color)).toEqual(["rgb(40, 119, 87)", "rgb(197, 106, 53)", "rgb(70, 126, 178)"]);
  expect(dots.every((dot) => dot.content === '\"\"' && dot.width === "6px")).toBe(true);
  expect(parseFloat(dimensions.font)).toBeGreaterThanOrEqual(12);
  await expect(page.locator("#history-chart .time-axis")).toHaveCount(4);
  const chart = page.locator("#history-chart");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  const x = box.x + 44 + (box.width - 88) * 0.3, y = box.y + box.height * 0.7;
  await chart.dispatchEvent("pointerdown", { clientX: x, clientY: y, pointerType: "touch", pointerId: 1 });
  await expect(page.locator("#graph-tooltip")).toContainText("Ist: 21.1 °C");
  await expect(page.locator("#graph-tooltip")).toContainText("Heizen (Ventil 45%)");
  await expect(page.locator("#history-chart .chart-cursor")).toHaveAttribute("visibility", "visible");
  const tip = await page.locator("#graph-tooltip").boundingBox();
  expect(tip.y + tip.height).toBeLessThan(y);
  expect(tip.x).toBeGreaterThanOrEqual(box.x);
  expect(tip.x + tip.width).toBeLessThanOrEqual(box.x + box.width);
  await page.locator(".analytics").screenshot({ path: "dist/thermo-control-analytics-mobile.png" });
  await chart.focus(); await page.keyboard.press("Escape");
  await expect(page.locator("#graph-tooltip")).toBeHidden();
  await page.setViewportSize({ width: 320, height: 640 });
  await expect.poll(async () => Number((await chart.getAttribute("viewBox")).split(" ")[2])).toBeCloseTo((await chart.boundingBox()).width, 0);
  const overflow = await page.evaluate(() => window.panel.shadowRoot.querySelector("main").scrollWidth > window.panel.shadowRoot.querySelector("main").clientWidth);
  expect(overflow).toBe(false);
});

test("room scale preserves small drift when flow is shown and heating bands occupy the background", async ({ page }) => {
  await analyticsFixture(page);
  const chart = page.locator("#history-chart");
  await expect(chart).toHaveAttribute("data-room-low", "20.5");
  await expect(chart).toHaveAttribute("data-room-high", "21.7");
  const before = await page.locator("#history-chart .room-curve").first().getAttribute("d");
  await page.getByRole("checkbox", { name: "Vorlauf", exact: true }).check();
  await expect(chart).toHaveAttribute("data-room-low", "20.5");
  await expect(chart).toHaveAttribute("data-room-high", "21.7");
  await expect(chart).toHaveAttribute("data-flow-low", "28.5");
  await expect(chart).toHaveAttribute("data-flow-high", "35.5");
  const after = await page.locator("#history-chart .room-curve").first().getAttribute("d");
  const yValues = (path) => [...path.matchAll(/[,V]([0-9.]+)/g)].map((match) => Number(match[1]));
  expect(yValues(after)).toEqual(yValues(before));
  const geometry = await page.evaluate(() => {
    const svg = window.panel.shadowRoot.querySelector("#history-chart"), bands = [...svg.querySelectorAll(".heating-band")];
    return { heights: bands.map((band) => Number(band.getAttribute("height"))), widths: bands.map((band) => Number(band.getAttribute("width"))), fills: bands.map((band) => band.getAttribute("fill")), children: [...svg.children].map((element) => element.tagName) };
  });
  expect(geometry.heights).toHaveLength(2);
  expect(geometry.heights.every((height) => height > 260)).toBe(true);
  expect(geometry.fills.every((fill) => fill === "rgba(255, 152, 0, 0.15)")).toBe(true);
  expect(geometry.widths[1] / geometry.widths[0]).toBeCloseTo(2, 2);
  expect(geometry.children.indexOf("rect")).toBeLessThan(geometry.children.indexOf("path"));
  expect((after.match(/ M/g) || []).length).toBe(2);
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  await chart.dispatchEvent("pointermove", { clientX: box.x + 44 + (box.width - 88) * 0.6, clientY: box.y + 100, pointerType: "mouse" });
  await expect(page.locator("#graph-tooltip")).toContainText("Ist: —");
  await expect(page.locator("#graph-tooltip")).toContainText("Status: Unbekannt");
});

test("legend shows live Celsius values, missing flow and empty history have compact feedback", async ({ page }) => {
  await analyticsFixture(page);
  await expect(page.locator("#graph-current")).toHaveText("20.3°");
  await expect(page.locator("#graph-target")).toHaveText("21.0°");
  await expect(page.locator("#graph-flow-legend")).toBeHidden();
  await page.evaluate(() => window.updateTemperature(24.6));
  await expect(page.locator("#graph-current")).toHaveText("24.6°");
  await page.getByRole("checkbox", { name: "Vorlauf", exact: true }).check();
  await expect(page.locator("#graph-flow-value")).toHaveText("34.0°");
  await page.evaluate(() => {
    window.historyData = {};
    window.updateEntity("climate.living", { state: "heat", attributes: { current_temperature: 68, temperature: 69.8 } });
    window.panel.hass.config.unit_system.temperature = "°F";
    window.panel._updateGraphLegend();
  });
  await expect(page.locator("#graph-current")).toHaveText("20.0°");
  await expect(page.locator("#graph-target")).toHaveText("21.0°");
  await page.getByRole("button", { name: "6h", exact: true }).click();
  await expect(page.locator("#graph-status")).toContainText("Keine aufgezeichneten Messwerte");
  await expect(page.locator("#history-chart path")).toHaveCount(0);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings); settings.heat_pump.flow_sensor = null;
    window.updateSnapshot({ settings });
    window.historyData = { "climate.living": [{ s: "heat", lu: Date.now() / 1000 - 60, a: { current_temperature_celsius: 21, effective_target_temperature: 21 } }] };
  });
  await page.getByRole("button", { name: "24h", exact: true }).click();
  await expect(page.locator("#graph-status")).toHaveText("Kein Vorlaufsensor zugeordnet.");
  await expect(page.getByText("Orange Flächen zeigen gemeldete Heizphasen.", { exact: false })).toBeHidden();
  await page.getByLabel("Informationen zum Diagramm").click();
  await expect(page.getByText("Orange Flächen zeigen gemeldete Heizphasen.", { exact: false })).toBeVisible();
});

test("late history responses cannot replace a newer time range or restore a disconnected chart", async ({ page }) => {
  await analyticsFixture(page);
  await page.evaluate(() => {
    const old = window.panel.hass.callWS;
    window.resolveHistory = [];
    window.panel.hass.callWS = (message) => message.type === "history/history_during_period" ? new Promise((resolve) => window.resolveHistory.push(resolve)) : old(message);
  });
  await page.getByRole("button", { name: "6h", exact: true }).click();
  await page.getByRole("button", { name: "48h", exact: true }).click();
  await page.evaluate(() => window.resolveHistory[1]({ "climate.living": [{ s: "heat", lu: Date.now() / 1000 - 60, a: { current_temperature_celsius: 22, effective_target_temperature: 22 } }] }));
  await expect(page.locator("#history-chart")).toHaveAttribute("data-room-high", "22.5");
  await page.evaluate(() => window.resolveHistory[0]({ "climate.living": [{ s: "heat", lu: Date.now() / 1000 - 60, a: { current_temperature_celsius: 29, effective_target_temperature: 29 } }] }));
  await expect(page.locator("#history-chart")).toHaveAttribute("data-room-high", "22.5");
  await page.getByRole("button", { name: "6h", exact: true }).click();
  await page.evaluate(() => { window.panel.remove(); window.resolveHistory[2](window.historyData); });
  const children = await page.evaluate(() => window.panel.shadowRoot.querySelector("#history-chart").children.length);
  expect(children).toBe(0);
});

async function compactGroups(page) {
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings);
    settings.groups = [{ id: "ground", name: "Erdgeschoss", control: {} }, { id: "upper", name: "Obergeschoss", control: {} }];
    const original = window.panel._data.rooms[0];
    const rooms = [original, ...["kitchen", "office", "bath"].map((id) => ({ id, config: { ...original.config, name: id, trvs: ["climate.wall"] }, entity_id: `climate.${id}` }))].map((room) => ({ ...room, config: { ...room.config, group_id: "ground" } }));
    window.updateEntity("climate.living", { state: "heat", attributes: { temperature: 18, current_temperature: 21, hvac_action: "heating" } });
    window.updateEntity("climate.kitchen", { state: "heat", attributes: { temperature: 18, current_temperature: 22, hvac_action: "idle" } });
    window.updateEntity("climate.office", { state: "unavailable", attributes: { current_temperature: 99, hvac_action: "heating" } });
    window.updateEntity("climate.bath", { state: "heat", attributes: { temperature: 18, current_temperature: 23, hvac_action: "idle" } });
    window.updateEntity("climate.ground", { state: "heat", attributes: { temperature: 18, current_temperature: 22, hvac_modes: ["off", "heat"], preset_modes: ["none", "eco", "comfort", "schedule"], preset_mode: "schedule", hvac_action: "heating" } });
    window.updateEntity("climate.upper", { state: "unavailable", attributes: {} });
    window.updateSnapshot({ rooms, settings, groups: [{ id: "ground", entity_id: "climate.ground" }, { id: "upper", entity_id: "climate.upper" }] });
  });
}

for (const width of [320, 390, 1280]) {
  test(`group cards stay two rows and 84px tall with inline actions at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await compactGroups(page);
    const card = page.locator('.group-card[data-group-id="ground"]');
    await expect(card.locator(".group-state")).toHaveText("· 4 Räume");
    await expect(card.locator(".group-current")).toHaveText("22,0 °C");
    await expect(card.locator(".group-heating")).toBeVisible();
    await expect(card.locator('.group-heating ha-icon')).toHaveAttribute("icon", "mdi:fire");
    await expect(card.locator(".group-heating-count")).toHaveText("1 heizt");
    await expect(page.getByLabel("Erdgeschoss: Preset", { exact: true })).toHaveValue("schedule");
    await expect(card.locator("label")).toHaveCount(0);
    const geometry = await card.evaluate((node) => {
      const box = node.getBoundingClientRect(), controls = [...node.querySelectorAll('.group-card-actions > *')];
      return { box: box.toJSON(), controls: controls.map((item) => item.getBoundingClientRect().toJSON()), buttons: [...node.querySelectorAll('.target-stepper button')].map((item) => item.getBoundingClientRect().toJSON()), header: node.querySelector('.group-card-header').getBoundingClientRect().toJSON(), targetFont: getComputedStyle(node.querySelector('.target-input')).fontSize, overflow: node.scrollWidth > node.clientWidth };
    });
    expect(geometry.box.height).toBe(84);
    expect(geometry.header.height).toBe(16);
    expect(geometry.controls).toHaveLength(3);
    expect(geometry.controls.every((control) => control.height === 38 && control.y === geometry.controls[0].y && control.left >= geometry.box.left && control.right <= geometry.box.right)).toBe(true);
    expect(geometry.buttons.every((button) => button.width === 34 && button.height === 36)).toBe(true);
    expect(geometry.targetFont).toBe("13px");
    expect(geometry.overflow).toBe(false);
    const upper = page.locator('.group-card[data-group-id="upper"]');
    await expect(upper.locator(".group-current")).toHaveText("—");
    await expect(upper.locator(".group-heating")).toBeHidden();
    await expect(page.getByLabel("Obergeschoss: Heizung", { exact: true })).toBeDisabled();
    if (width === 390) await page.locator("#group-cards").screenshot({ path: "dist/thermo-control-groups-mobile.png" });
    await page.evaluate(() => {
      const settings = structuredClone(window.panel._data.settings); settings.groups[0].name = "Erdgeschoss mit einem sehr langen Gruppennamen";
      window.updateSnapshot({ settings, revision: window.panel._data.revision + 1 });
    });
    const long = page.locator('.group-card[data-group-id="ground"]');
    await expect(long.locator("h2")).toHaveAttribute("title", "Erdgeschoss mit einem sehr langen Gruppennamen");
    expect(await long.evaluate((node) => node.scrollWidth <= node.clientWidth && node.getBoundingClientRect().height === 84)).toBe(true);
  });
}

test("compact group status updates averages and excludes unavailable room readings", async ({ page }) => {
  await compactGroups(page);
  const card = page.locator('.group-card[data-group-id="ground"]');
  await page.evaluate(() => window.updateEntity("climate.kitchen", { state: "heat", attributes: { current_temperature: 24, temperature: 18, hvac_action: "idle" } }));
  await expect(card.locator(".group-current")).toHaveText("22,7 °C");
  await page.evaluate(() => window.updateEntity("climate.living", { state: "unknown", attributes: { current_temperature: 50, hvac_action: "heating" } }));
  await expect(card.locator(".group-current")).toHaveText("23,5 °C");
  await expect(card.locator(".group-heating")).toBeHidden();
  await page.evaluate(() => {
    window.updateEntity("climate.ground", { state: "unavailable", attributes: { current_temperature: 22 } });
    for (const id of ["kitchen", "bath"]) window.updateEntity(`climate.${id}`, { state: "unavailable", attributes: { current_temperature: 50 } });
  });
  await expect(card.locator(".group-current")).toHaveText("—");
  await expect(page.getByLabel("Erdgeschoss: Sollwert", { exact: true })).toBeDisabled();
});

async function homeAssistantRoute(page, path) {
  await page.route("http://thermo.test/**", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><html><body></body></html>" }));
  await page.goto(`http://thermo.test${path}`);
}

test("overview alone contains heating values and room creation remains in configuration", async ({ page }) => {
  await mount(page, true);
  await expect(page.locator("#tab-overview #add-room")).toHaveCount(0);
  await expect(page.locator("#tab-overview").getByRole("button", { name: "Raum hinzufügen", exact: true })).toHaveCount(0);
  const heating = page.getByRole("region", { name: "Heizungswerte", exact: true });
  await expect(heating.getByRole("heading", { name: "Heizung", exact: true })).toBeVisible();
  await expect(page.locator("#tab-overview #system-bar")).toHaveCount(1);
  for (const tab of ["Verläufe & Analyse", "Zeitpläne", "Thermostate & Gruppen", "Einstellungen"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(heating).toBeHidden();
  }
  await page.evaluate(() => window.updateSnapshot({ system: { flow: 31, target: 33, demand: 40, eligible_demand: 40, compressor: true, mode: "Automatik" } }));
  await page.getByRole("tab", { name: "Übersicht", exact: true }).click();
  await expect(heating).toContainText("31 °C / 33 °C");
  await expect(heating).toContainText("Aktiv");
  await expect(heating.getByRole("heading", { name: "Heizung", exact: true })).toHaveCount(1);
  await page.getByRole("tab", { name: "Thermostate & Gruppen", exact: true }).click();
  await page.getByRole("button", { name: "Raum hinzufügen", exact: true }).click();
  await expect(page.locator("#editor")).toBeVisible();
});

for (const width of [320, 1280]) {
  test(`brand menu button and dashboard back fit the toolbar at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await homeAssistantRoute(page, "/lovelace/wohnzimmer?view=house");
    await page.evaluate(() => {
      history.replaceState({ root: true }, "");
      history.pushState({ from: "/lovelace/wohnzimmer?view=house" }, "", "/thermo-control?back=1");
    });
    await mount(page, true);
    await page.evaluate(() => {
      window.menuEvents = 0;
      document.addEventListener("hass-toggle-menu", (event) => { if (event.bubbles && event.composed) window.menuEvents++; });
    });
    const brand = page.getByRole("button", { name: "Seitenleiste öffnen", exact: true });
    const back = page.getByRole("button", { name: "Zurück zum Dashboard", exact: true });
    await expect(brand.locator("svg")).toHaveCount(1);
    await expect(back).toBeVisible();
    await expect(page.locator(".menu")).toHaveCount(0);
    await expect(page.locator(".toolbar")).not.toContainText("☰");
    await brand.click(); await brand.focus(); await page.keyboard.press("Enter");
    expect(await page.evaluate(() => window.menuEvents)).toBe(2);
    const geometry = await page.evaluate(() => {
      const root = window.panel.shadowRoot, toolbar = root.querySelector(".toolbar");
      return { overflow: toolbar.scrollWidth > toolbar.clientWidth, controls: [...toolbar.querySelectorAll("button")].map((node) => node.getBoundingClientRect().toJSON()) };
    });
    expect(geometry.overflow).toBe(false);
    expect(geometry.controls.every((control) => control.width >= 44 && control.height >= 44 && control.right <= width)).toBe(true);
    if (width === 320) await page.locator("thermo-control-panel").screenshot({ path: "dist/thermo-control-navigation-mobile.png" });
    await back.click();
    await expect(page).toHaveURL("http://thermo.test/lovelace/wohnzimmer?view=house");
    await expect(back).toBeHidden();
  });
}

test("back marker responds to SPA navigation and listeners are removed on disconnect", async ({ page }) => {
  await homeAssistantRoute(page, "/thermo_control");
  await mount(page, true);
  const back = page.locator(".back");
  await expect(back).toBeHidden();
  for (const flag of ["0", "2", "true"]) {
    await page.evaluate((flag) => { history.replaceState({}, "", `?back=${flag}`); window.dispatchEvent(new CustomEvent("location-changed")); }, flag);
    await expect(back).toBeHidden();
  }
  await page.evaluate(() => { history.replaceState({}, "", "?back=1"); window.dispatchEvent(new CustomEvent("location-changed")); });
  await expect(back).toBeVisible();
  await page.evaluate(() => { history.replaceState({}, "", "/thermo_control"); window.panel.route = { path: "" }; });
  await expect(back).toBeHidden();
  const calls = await page.evaluate(() => {
    window.panel.remove(); let count = 0; window.panel._updateNavigation = () => count++;
    window.dispatchEvent(new CustomEvent("location-changed")); window.dispatchEvent(new PopStateEvent("popstate")); return count;
  });
  expect(calls).toBe(0);
});

test("direct dashboard links fall back to the HA start view rather than an auth history entry", async ({ page }) => {
  await homeAssistantRoute(page, "/auth/authorize");
  await page.evaluate(() => {
    history.pushState({ root: true, customState: "keep" }, "", "/thermo-control?back=1");
  });
  await mount(page, true);
  await page.evaluate(() => { window.navigationEvents = []; window.addEventListener("location-changed", (event) => window.navigationEvents.push(event.detail)); });
  await page.getByRole("button", { name: "Zurück zum Dashboard", exact: true }).click();
  await expect(page).toHaveURL("http://thermo.test/");
  expect(await page.evaluate(() => window.navigationEvents)).toEqual([{ replace: true }]);
  expect(await page.evaluate(() => history.state)).toEqual({ root: true, customState: "keep" });
  await expect(page.locator(".back")).toBeHidden();
});

test("setpoint phases have no vertical connectors and zero-duration spikes do not widen the axis", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mount(page, true);
  const timing = await page.evaluate(() => {
    const end = Date.now(), start = end - 24 * 3600000;
    const state = (seconds, target, hvac = "heat") => ({ s: hvac, lu: (start + seconds * 1000) / 1000, a: { current_temperature_celsius: 24, effective_target_temperature: target, hvac_action: "idle" } });
    window.historyData = { "climate.living": [state(0, 21), state(3600, 26), state(3600, 5), state(3600, 21), state(10800, 18), state(14400, 18, "unavailable"), state(18000, 18), state(72000, 21.5)] };
    return { start, end };
  });
  await page.getByRole("tab", { name: "Verläufe & Analyse", exact: true }).click();
  const chart = page.locator("#history-chart"), curve = chart.locator(".target-curve");
  await expect(curve).toHaveCount(1);
  await expect(chart).toHaveAttribute("data-room-low", "17.5");
  await expect(chart).toHaveAttribute("data-room-high", "24.5");
  const path = await curve.getAttribute("d");
  expect(path).not.toMatch(/[VL]/);
  expect((path.match(/ M/g) || []).length).toBe(4); // 21, 18, explicit gap, 18, 21.5.
  const phases = [...path.matchAll(/M([0-9.]+),([0-9.]+) H([0-9.]+)/g)].map((match) => ({ start: Number(match[1]), y: Number(match[2]), end: Number(match[3]) }));
  expect(phases.every((phase) => phase.end > phase.start)).toBe(true);
  expect(phases[1].end).toBeLessThan(phases[2].start);
  const cursor = chart.locator(".chart-cursor");
  await expect(cursor).toHaveAttribute("visibility", "hidden");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  await chart.dispatchEvent("pointerdown", { clientX: box.x + phases[3].start + 5, clientY: box.y + 150, pointerType: "touch" });
  await expect(page.locator("#graph-tooltip")).toContainText("Soll: 21.5 °C");
  await chart.focus(); await page.keyboard.press("Escape");
  await page.locator(".analytics").screenshot({ path: "dist/thermo-control-setpoint-plateaus-mobile.png" });
  expect(timing.end).toBeGreaterThan(timing.start);
});

test("real short and sustained frost setpoints remain visible and available in the tooltip", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    const end = Date.now() / 1000, start = end - 86400;
    const state = (offset, target) => ({ s: "heat", lu: start + offset, a: { current_temperature_celsius: 24, effective_target_temperature: target, hvac_action: "idle" } });
    window.historyData = { "climate.living": [state(0, 21), state(3600, 5), state(3601, 21), state(7200, 5), state(14400, 18)] };
  });
  await page.getByRole("tab", { name: "Verläufe & Analyse", exact: true }).click();
  const chart = page.locator("#history-chart");
  await expect(chart).toHaveAttribute("data-room-low", "4.5");
  const path = await chart.locator(".target-curve").getAttribute("d");
  expect(path).not.toMatch(/[VL]/);
  expect((path.match(/ M/g) || []).length).toBe(5);
  const plateaus = [...path.matchAll(/M([0-9.]+),([0-9.]+) H([0-9.]+)/g)].map((match) => ({ start: Number(match[1]), end: Number(match[3]) }));
  expect(plateaus[1].end - plateaus[1].start).toBeLessThan(1);
  expect(plateaus[3].end - plateaus[3].start).toBeGreaterThan(10);
  await chart.scrollIntoViewIfNeeded(); const box = await chart.boundingBox();
  await chart.dispatchEvent("pointerdown", { clientX: box.x + (plateaus[3].start + plateaus[3].end) / 2, clientY: box.y + 150, pointerType: "touch" });
  await expect(page.locator("#graph-tooltip")).toContainText("Soll: 5.0 °C");
});
