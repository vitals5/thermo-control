const { test, expect } = require("@playwright/test");
const path = require("path");

async function mount(page, populated = false) {
  await page.setContent('<!doctype html><html><body style="margin:0;--card-background-color:#fff;--primary-background-color:#f4f6f4;--secondary-background-color:#eef3ef;--primary-text-color:#23312d;--secondary-text-color:#69786e;--divider-color:#d4ded5"></body></html>');
  await page.addScriptTag({ path: path.resolve("custom_components/thermo_control/frontend/thermo-control-panel.js") });
  await page.evaluate((populated) => {
    const defaults = { window_sensors: [], tolerance: 0.3, calibration_interval: 600, calibration_threshold: 0.5, window_open_delay: 30, window_close_delay: 60, frost_temperature: 5, preset_none: 20, preset_eco: 17, preset_comfort: 21, preset_boost: 25, preset_away: 15 };
    const deviceDefaults = { temperature_is_calibrated: true, regulated_mode: "heat", calibration_min: -9, calibration_max: 9, calibration_step: 0.5 };
    const config = { ...defaults, name: "Wohnzimmer", trvs: ["climate.trv"], temperature_sensor: "sensor.room", window_sensors: ["binary_sensor.window"], devices: { "climate.trv": { ...deviceDefaults, calibration_entity: "number.offset" } } };
    let data = { rooms: populated ? [{ id: "living", config, entity_id: "climate.living" }] : [], revision: 0, defaults, device_defaults: deviceDefaults };
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
  await page.getByRole("button", { name: "+ Raum hinzufügen" }).click();
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
  await page.getByRole("button", { name: "+ Raum hinzufügen" }).click();
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


test("four tabs are keyboard accessible and master offset is submitted", async ({ page }) => {
  await mount(page, true);
  await expect(page.getByRole("tab")).toHaveCount(4);
  await expect(page.getByRole("tab", { name: "Übersicht", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Party", exact: true }).click();
  expect(await page.evaluate(() => window.messages.find((message) => message.type.endsWith("master_offset")).offset)).toBe(2);
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

test("history charts use recorded room, target and flow data for all time ranges", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    const settings = structuredClone(window.panel._data.settings);
    settings.heat_pump.flow_sensor = "sensor.flow";
    window.updateSnapshot({ settings });
    const now = Date.now() / 1000;
    window.historyData = {
      "climate.living": [
        { s: "heat", lu: now - 3600, a: { current_temperature_celsius: 20, effective_target_temperature: 21, hvac_action: "heating" } },
        { s: "heat", lu: now - 1800, a: { current_temperature_celsius: 20.5, effective_target_temperature: 21, hvac_action: "idle" } },
        { s: "unavailable", lu: now - 900, a: {} },
        { s: "heat", lu: now - 600, a: { current_temperature_celsius: 20.6, effective_target_temperature: 21, hvac_action: "idle" } },
      ], "sensor.flow": [{ s: "32", lu: now - 3600, a: { unit_of_measurement: "°C" } }],
    };
  });
  await page.getByRole("tab", { name: "Verläufe & Analyse", exact: true }).click();
  await expect(page.locator("#graph-status")).toContainText("4 Raum-Meldungen");
  await expect(page.locator("#history-chart path")).toHaveCount(3);
  await page.getByLabel("Vorlauftemperatur einblenden").check();
  await expect(page.locator("#graph-status")).toContainText("1 Vorlauf-Meldungen");
  await expect(page.locator('#history-chart rect[fill="#d18043"]')).toHaveCount(1);
  await page.getByRole("combobox", { name: "Zeitfenster", exact: true }).selectOption("168");
  const message = await page.evaluate(() => window.messages.filter((message) => message.type === "history/history_during_period").at(-1));
  expect(message.entity_ids).toEqual(["climate.living", "sensor.flow"]);
  expect((Date.parse(message.end_time) - Date.parse(message.start_time)) / 3600000).toBe(168);
  expect(message.significant_changes_only).toBe(false);
  await page.locator("#history-chart").hover();
  await expect(page.locator("#graph-tooltip")).toContainText("°C");
  await page.screenshot({ path: "dist/thermo-control-analytics.png", fullPage: true });
  await page.evaluate(() => { window.failHistory = true; });
  await page.getByRole("button", { name: "Aktualisieren", exact: true }).click();
  await expect(page.locator("#graph-status")).toContainText("Verlauf nicht verfügbar");
  await expect(page.locator("#history-chart path")).toHaveCount(0);
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

test("dense week histories retain peaks and bound chart geometry", async ({ page }) => {
  await mount(page, true);
  await page.evaluate(() => {
    const now = Date.now() / 1000;
    const states = Array.from({ length: 12000 }, (_, i) => ({ s: "heat", lu: now - 12000 + i, a: { current_temperature_celsius: i === 7000 ? 29 : 20, effective_target_temperature: 21, hvac_action: "idle" } }));
    window.historyData = { "climate.living": states };
  });
  await page.getByRole("tab", { name: "Verläufe & Analyse", exact: true }).click();
  await expect(page.locator("#graph-status")).toContainText("12000 Raum-Meldungen");
  await expect(page.locator("#history-chart rect")).toHaveCount(1);
  const path = await page.locator('#history-chart path').first().getAttribute('d');
  expect(path.length).toBeLessThan(60000);
  const labels = await page.locator('#history-chart text').allTextContents();
  expect(labels.some((text) => text.includes('30.0'))).toBe(true);
});
