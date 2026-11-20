import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// 壳层冒烟不依赖后端：用一份最小 verify 报告起 modou ui（仅 127.0.0.1），
// 浏览器直接访问真实构建产物与 /api 端点。
const PORT = 18765;
const reportDir = mkdtempSync(join(tmpdir(), "modou-e2e-"));
const reportFile = join(reportDir, "verify.json");
writeFileSync(
  reportFile,
  JSON.stringify({
    report_version: 1,
    exit_code: 0,
    summary: { missing_execution: 0, wrong_execution: 0, historical_drift: 0 },
    env_errors: [],
    databases: {},
  }),
);

export default defineConfig({
  testDir: "e2e",
  forbidOnly: true,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `uv run --directory .. modou ui --report ${reportFile} --bind 127.0.0.1 --port ${PORT} --no-open`,
    url: `http://127.0.0.1:${PORT}/api/reports`,
    cwd: resolve(import.meta.dirname),
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
