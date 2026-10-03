const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({ testDir: "tests/browser", use: { headless: true }, reporter: "list" });
