import { expect, type Page, test } from "@playwright/test";

// The real Telegram popup cannot run in CI, so the official library and the two
// Telegram endpoints are replaced. The backend contract itself is covered by the
// PostgreSQL integration tests; here we check the browser flow around it.

const LIBRARY = "https://oauth.telegram.org/js/telegram-login.js*";

const FAKE_LIBRARY = `
  window.Telegram = { Login: { auth(options, callback) {
    window.__telegramOptions = options;
    callback(window.__telegramResult || { id_token: "e2e-id-token" });
  } } };
`;

async function completeSimplifiedRoute(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Подобрать сложность" }).first().click();
  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("button", { name: "Все слова знакомы" }).click();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
}

async function enableTelegram(page: Page): Promise<{ nonceRequests: () => number }> {
  let nonces = 0;
  await page.route("**/api/v1/auth/telegram/nonce", async (route) => {
    nonces += 1;
    await route.fulfill({ json: { nonce: `e2e-nonce-${nonces}`, client_id: "123456789" } });
  });
  await page.route(LIBRARY, (route) =>
    route.fulfill({ contentType: "text/javascript", body: FAKE_LIBRARY }),
  );
  return { nonceRequests: () => nonces };
}

test("Telegram option is hidden when the server has no Telegram client id", async ({ page }) => {
  await completeSimplifiedRoute(page);
  const nonce = page.waitForResponse((response) => response.url().endsWith("/auth/telegram/nonce"));
  await page.getByRole("button", { name: "Сохранить результат" }).click();

  expect((await nonce).status()).toBe(404);
  await expect(page.getByLabel("Логин")).toBeVisible();
  await expect(page.getByRole("button", { name: "Сохранить через Telegram" })).toHaveCount(0);
});

test("saving the result through Telegram sends the token, nonce and run", async ({ page }) => {
  await enableTelegram(page);
  let signInBody: { id_token: string; run_id: string | null } | null = null;
  await page.route("**/api/v1/auth/telegram", async (route) => {
    signInBody = route.request().postDataJSON();
    await route.fulfill({
      status: 201,
      json: {
        user_id: "00000000-0000-4000-8000-000000000001",
        username: null,
        csrf_token: "e2e-auth-csrf",
        current_run_id: signInBody?.run_id ?? null,
        expires_at: "2030-01-01T00:00:00Z",
      },
    });
  });
  await completeSimplifiedRoute(page);
  await page.getByRole("button", { name: "Сохранить результат" }).click();

  await page.getByRole("button", { name: "Сохранить через Telegram" }).click();

  await expect(page.getByRole("heading", { name: "Вы вошли через Telegram" })).toBeVisible();
  expect(signInBody).not.toBeNull();
  expect(signInBody!.id_token).toBe("e2e-id-token");
  expect(signInBody!.run_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(await page.evaluate(() => (window as any).__telegramOptions)).toEqual({
    client_id: "123456789",
    nonce: "e2e-nonce-1",
    scope: [],
    lang: "ru",
  });
});

test("unknown Telegram account on the login screen explains the next step", async ({ page }) => {
  const telegram = await enableTelegram(page);
  await page.route("**/api/v1/auth/telegram", (route) =>
    route.fulfill({
      status: 409,
      json: { code: "registration_conflict", message: "A completed result is required" },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Войти" }).first().click();

  await page.getByRole("button", { name: "Войти через Telegram" }).click();

  await expect(page.getByRole("alert")).toContainText("Аккаунта с этим Telegram пока нет");
  await expect.poll(telegram.nonceRequests).toBe(2);
  await expect(page.getByRole("button", { name: "Войти через Telegram" })).toBeEnabled();
});

test("closing the Telegram popup leaves the form without an error", async ({ page }) => {
  await enableTelegram(page);
  await page.addInitScript(() => {
    (window as any).__telegramResult = { error: "popup_closed" };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Войти" }).first().click();

  await page.getByRole("button", { name: "Войти через Telegram" }).click();

  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByLabel("Логин")).toBeVisible();
});
