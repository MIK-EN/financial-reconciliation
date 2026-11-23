import { defineConfig, devices } from "@playwright/test";

// Playwright runs this file in Node; avoid adding @types/node just for the CI flag.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command:
        "if [ -f ./.env ]; then set -a; . ./.env; set +a; fi; " +
        ': "${TEST_DATABASE_URL:?TEST_DATABASE_URL must point to a *_test database}"; ' +
        'case "$TEST_DATABASE_URL" in *_test) ;; ' +
        '*) echo "Refusing to run E2E: TEST_DATABASE_URL must end with _test" >&2; exit 1;; esac; ' +
        'export DATABASE_URL="$TEST_DATABASE_URL"; ' +
        // E2E replaces Telegram itself; a real client id from .env must not leak in.
        "unset TELEGRAM_CLIENT_ID; " +
        'export EXPECTED_ORIGIN="http://127.0.0.1:5173"; ' +
        "exec uv run --locked uvicorn english_for_developers.app:create_app --factory " +
        "--host 127.0.0.1 --port 8000",
      cwd: "..",
      url: "http://127.0.0.1:8000/openapi.json",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
