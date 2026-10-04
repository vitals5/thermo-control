const { test, expect } = require("@playwright/test");
const path = require("path");

async function mount(page, populated = false) {
  await page.setContent('<!doctype html><html><body style="margin:0"></body></html>');
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
        if (message.type.endsWith("save_room")) {
          const room = { id: message.room_id || "living", config: message.config, entity_id: "climate.living" };
          data = { ...data, rooms: [room], revision: data.revision + 1 }; listener(data); return { room_id: room.id };
        }
        if (message.type.endsWith("delete_room")) { data = { ...data, rooms: [], revision: data.revision + 1 }; listener(data); return {}; }
      },
      callService: async (domain, service, data) => { window.services.push({ domain, service, data }); },
    };
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
