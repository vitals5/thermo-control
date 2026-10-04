/* Render our editable SVG sources into the Home Assistant brand PNG formats. */
const { chromium } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const root = path.resolve(__dirname, '..');
  const browser = await chromium.launch({ headless: true });
  try {
    for (const source of ['icon', 'dark_icon', 'logo', 'dark_logo']) {
      const svg = fs.readFileSync(path.join(root, 'assets', 'brand', `${source}.svg`), 'utf8');
      const dimensions = svg.match(/viewBox="0 0 (\d+) (\d+)"/);
      if (!dimensions) throw new Error(`Missing dimensions in ${source}`);
      const width = Number(dimensions[1]), height = Number(dimensions[2]);
      for (const scale of [1, 2]) {
        const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scale });
        const page = await context.newPage();
        await page.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
        await page.evaluate(() => document.fonts.ready);
        const destination = path.join(root, 'custom_components', 'thermo_control', 'brand', `${source}${scale === 2 ? '@2x' : ''}.png`);
        await page.screenshot({ path: destination, omitBackground: true });
        await context.close();
        process.stdout.write(`${path.relative(root, destination)} (${width * scale}×${height * scale})\n`);
      }
    }
  } finally {
    await browser.close();
  }
})().catch((error) => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
