import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  globalSetup: "./e2e/global-setup.ts",
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    [
      "junit",
      {
        outputFile:
          process.env.E2E_JUNIT_PATH || "test-results/playwright-junit.xml",
      },
    ],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    channel: "msedge",
    ...devices["Desktop Chrome"],
  },
  outputDir: process.env.E2E_OUTPUT_DIR || ".verification/playwright",
  timeout: 30_000,
});
