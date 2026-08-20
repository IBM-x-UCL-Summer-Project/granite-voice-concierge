const { expect, test } = require("@playwright/test");

const HEALTH_RESPONSE = {
  status: "ready",
  message: "Local engine is ready.",
  capabilities: {
    text_input: true,
    voice_input: false,
    voice_output: false,
    wake_word: false,
    routine_barge_in: false,
    playback_barge_in: false,
    diagnostics: false,
    reminders: false,
    guided_routines: false,
    privacy_centre: false,
  },
  runtime: {
    model: "browser-test-model",
    policy_profile: "uat_relaxed",
  },
};

test("healthy application leaves the startup screen", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.addInitScript(() => {
    window.localStorage.setItem("granite-personal-settings-v1", JSON.stringify({
      version: 2,
      setup_complete: true,
    }));
  });
  await page.route("**/api/health", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(HEALTH_RESPONSE),
  }));
  await page.route("**/api/session", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      state: null,
      routine: { active: false },
      session_history: [],
    }),
  }));

  await page.goto("/web/");

  await expect(page.locator("#startup-screen")).toHaveClass(/is-hidden/);
  await expect(page.locator("#runtime-label")).toHaveText("Local pipeline");
  await expect(page.locator("#runtime-model")).toContainText("browser-test-model");
  expect(pageErrors).toEqual([]);
});
