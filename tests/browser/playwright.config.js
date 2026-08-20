const path = require("node:path");
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "*.spec.js",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  timeout: 20_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL: "http://127.0.0.1:4180",
    headless: true,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "firefox", use: { browserName: "firefox" } },
    { name: "webkit", use: { browserName: "webkit" } },
  ],
  webServer: {
    command: "python -m http.server 4180 --bind 127.0.0.1",
    cwd: path.resolve(__dirname, "../.."),
    url: "http://127.0.0.1:4180/web/audio-capture.js",
    reuseExistingServer: true,
    timeout: 10_000,
  },
});
