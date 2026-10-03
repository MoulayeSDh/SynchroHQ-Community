import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e", timeout: 60000, workers: 1,
  use: { headless: true, channel: process.platform === "win32" ? "msedge" : undefined,
    viewport: { width: 1280, height: 900 } },
});
