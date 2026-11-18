import { expect, type Page, test } from "@playwright/test";

async function completeSimplifiedRoute(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();
  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("button", { name: "Все слова знакомы" }).click();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
}

async function registerCompletedResult(page: Page, username: string) {
  await page.getByRole("button", { name: "Сохранить результат" }).click();
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill("correct horse 123");
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();
}

async function login(page: Page, username: string) {
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill("correct horse 123");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
}

test("register, log out and log in again restores the saved result", async ({ page }) => {
  const username = `e2e_${Date.now()}_relogin`;
  await completeSimplifiedRoute(page);
  await registerCompletedResult(page, username);

  await page.getByRole("button", { name: "Выйти" }).click();
  await login(page, username);

  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
});

test("lost Set-Cookie on registration does not keep the user signed in after reload", async ({
  page,
}) => {
  const username = `e2e_${Date.now()}_cookie`;
  await page.route("**/api/v1/auth/register", async (route) => {
    const response = await route.fetch();
    // route.fetch() shares the browser context's cookie jar, so the auth
    // cookie is stored before headers can be stripped; drop it explicitly.
    await page.context().clearCookies({ name: "eds_auth_dev" });
    const headers = { ...response.headers() };
    delete headers["set-cookie"];
    await route.fulfill({ response, headers });
  });

  await completeSimplifiedRoute(page);
  await page.getByRole("button", { name: "Сохранить результат" }).click();
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill("correct horse 123");
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  // Without the auth cookie the follow-up run request cannot read the claimed
  // result, so the client keeps its in-memory session but has no saved result.
  await expect(page.getByText(`Вы вошли как ${username}`)).toBeVisible();

  await page.reload();
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Подберём стартовую сложность" }),
  ).toBeVisible();

  await login(page, username);
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();
});

test("503 on claim shows the unavailable message and a retry succeeds", async ({ page }) => {
  const username = `e2e_${Date.now()}_claim503`;
  await completeSimplifiedRoute(page);
  await registerCompletedResult(page, username);
  await page.getByRole("button", { name: "Выйти" }).click();

  await completeSimplifiedRoute(page);
  await login(page, username);
  await expect(page.getByText(`Вы вошли как ${username}`)).toBeVisible();

  let claimAttempt = 0;
  await page.route("**/api/v1/onboarding/*/claim", async (route) => {
    claimAttempt += 1;
    if (claimAttempt === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ code: "unavailable", message: "x" }),
      });
    } else {
      await route.continue();
    }
  });

  await page.getByRole("button", { name: "Сохранить этот результат в аккаунте" }).click();
  await expect(page.getByRole("alert")).toContainText("Сервис временно недоступен");
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toHaveCount(0);

  await page.getByRole("button", { name: "Сохранить этот результат в аккаунте" }).click();
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();
});

test("410 on claim shows a generic error and nothing is saved", async ({ page }) => {
  const username = `e2e_${Date.now()}_claim410`;
  await completeSimplifiedRoute(page);
  await registerCompletedResult(page, username);
  await page.getByRole("button", { name: "Выйти" }).click();

  await completeSimplifiedRoute(page);
  await login(page, username);
  await expect(page.getByText(`Вы вошли как ${username}`)).toBeVisible();

  await page.route("**/api/v1/onboarding/*/claim", async (route) => {
    await route.fulfill({
      status: 410,
      contentType: "application/json",
      body: JSON.stringify({ code: "run_expired", message: "x" }),
    });
  });

  await page.getByRole("button", { name: "Сохранить этот результат в аккаунте" }).click();
  await expect(page.getByRole("alert")).toContainText("Не удалось выполнить действие");
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toHaveCount(0);
});
