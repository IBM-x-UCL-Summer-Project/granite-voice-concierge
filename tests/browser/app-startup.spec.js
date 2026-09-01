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

async function prepareApplication(page, capabilities = {}) {
  await page.addInitScript(() => {
    window.localStorage.setItem("granite-personal-settings-v1", JSON.stringify({
      version: 2,
      setup_complete: true,
    }));
  });
  await page.route("**/api/health", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      ...HEALTH_RESPONSE,
      capabilities: { ...HEALTH_RESPONSE.capabilities, ...capabilities },
    }),
  }));
  await page.route("**/api/session", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      state: null,
      routine: { active: false },
      session_history: [],
    }),
  }));
}

test("healthy application leaves the startup screen", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await prepareApplication(page);

  await page.goto("/web/");

  await expect(page.locator("#startup-screen")).toHaveClass(/is-hidden/);
  await expect(page.locator("#runtime-label")).toHaveText("Local pipeline");
  await expect(page.locator("#runtime-model")).toContainText("browser-test-model");
  expect(pageErrors).toEqual([]);
});

test("local data dialog remains visible, scrollable, and closable", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await prepareApplication(page, { privacy_centre: true, reminders: true });
  await page.route("**/api/privacy", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      memories: Array.from({ length: 20 }, (_, index) => ({
        id: index + 1,
        content: `Saved local memory ${index + 1}`,
        layer: "profile",
        layer_description: "Profile memory",
        created: "Saved locally",
      })),
      locations: [{
        name: "Memory database",
        size: "24 KB",
        path: "/tmp/browser-test-memory.db",
      }],
    }),
  }));
  await page.route("**/api/reminders", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      reminders: Array.from({ length: 12 }, (_, index) => ({
        id: index + 1,
        text: `Local reminder ${index + 1}`,
        due: "Tomorrow at 09:00",
        recurrence: "once",
      })),
    }),
  }));

  await page.goto("/web/");
  await page.locator("#local-data-button").click();

  const dialog = page.locator("#local-data-dialog");
  const content = page.locator(".data-content");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("open", "");
  await expect(page.locator("#local-data-title")).toBeVisible();
  await expect(page.locator("#local-data-close")).toBeVisible();
  await expect(page.locator("#memory-summary")).toHaveText("20 memories are saved on this device.");
  await expect(page.locator("#reminder-summary")).toHaveText("12 reminders are scheduled.");

  const dialogBox = await dialog.boundingBox();
  expect(dialogBox.height).toBeGreaterThan(300);
  expect(await content.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);

  await page.locator("#local-data-close").click();
  await expect(dialog).not.toHaveAttribute("open", "");
  await expect(page.locator("#local-data-button")).toBeEnabled();
  expect(pageErrors).toEqual([]);
});
