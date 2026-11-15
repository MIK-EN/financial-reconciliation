import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
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
        'set -a; . ./.env; set +a; export DATABASE_URL="$TEST_DATABASE_URL"; ' +
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
