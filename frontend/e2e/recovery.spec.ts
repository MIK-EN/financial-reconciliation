import { expect, type Page, test } from "@playwright/test";

function levelRadio(page: Page, name: string) {
  return page
    .getByRole("group", { name: "Выбранная сложность" })
    .getByRole("radio", { name });
}

async function reachSecondText(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();
  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
}

async function completeSimplifiedRoute(page: Page) {
  await reachSecondText(page);
  await page.getByRole("button", { name: "Все слова знакомы" }).click();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
}

test("reload after submitting keeps the next step without a stale draft", async ({ page }) => {
  await reachSecondText(page);

  await page.reload();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  // "file" was marked on step 1 and appears again in text 2; it must start unmarked.
  await expect(page.getByRole("button", { name: "file", exact: true }).first()).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expect(page.getByRole("button", { name: "Open", exact: true })).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  await page.getByRole("button", { name: "Все слова знакомы" }).click();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
});

test("draft on the second step survives a reload", async ({ page }) => {
  await reachSecondText(page);

  const openWord = page.getByRole("button", { name: "Open", exact: true });
  await openWord.click();
  await expect(openWord).toHaveAttribute("aria-pressed", "true");

  await page.reload();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("reload on the result screen keeps the result", async ({ page }) => {
  await completeSimplifiedRoute(page);

  await page.reload();

  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Начать" })).toHaveCount(0);
});

test("reload keeps a changed starting level", async ({ page }) => {
  await completeSimplifiedRoute(page);

  await levelRadio(page, "Базовая документация").click();
  await expect(levelRadio(page, "Базовая документация")).toBeChecked();

  await page.reload();

  await expect(levelRadio(page, "Базовая документация")).toBeChecked();
});

test("browser back and forward return to the server step", async ({ page }) => {
  await reachSecondText(page);

  await page.goto("about:blank");
  await page.goBack();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(page.getByText("Текст 1", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Все слова знакомы" }).click();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
});

async function openFirstTextAndSelect(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();
  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
}

test("lost response after the answer was saved recovers on retry", async ({ page }) => {
  const requestBodies: (string | null)[] = [];
  let attempt = 0;
  await page.route("**/api/v1/onboarding/*/answers", async (route) => {
    attempt += 1;
    requestBodies.push(route.request().postData());
    if (attempt === 1) {
      // The server really saves the answer, but the browser never sees the response.
      await route.fetch();
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
  await openFirstTextAndSelect(page);

  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByRole("alert")).toContainText("Не удалось связаться с сервером");
  await expect(page.getByText("Текст 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "file", exact: true }).first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(requestBodies).toHaveLength(2);
  expect(requestBodies[1]).toBe(requestBodies[0]);
});

test("503 on submit shows the unavailable message and keeps the selection", async ({ page }) => {
  let attempt = 0;
  await page.route("**/api/v1/onboarding/*/answers", async (route) => {
    attempt += 1;
    if (attempt === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ code: "unavailable", message: "x" }),
      });
      return;
    }
    await route.continue();
  });
  await openFirstTextAndSelect(page);

  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByRole("alert")).toContainText("Сервис временно недоступен");
  await expect(page.getByText("Текст 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "file", exact: true }).first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("429 on submit shows a generic error and no next step", async ({ page }) => {
  await page.route("**/api/v1/onboarding/*/answers", async (route) => {
    await route.fulfill({
      status: 429,
      headers: { "Retry-After": "30" },
      contentType: "application/json",
      body: JSON.stringify({ code: "rate_limited", message: "x" }),
    });
  });
  await openFirstTextAndSelect(page);

  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByRole("alert")).toContainText("Не удалось выполнить действие");
  await expect(page.getByText("Текст 2", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "file", exact: true }).first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("410 on submit shows a generic error and no result", async ({ page }) => {
  await page.route("**/api/v1/onboarding/*/answers", async (route) => {
    await route.fulfill({
      status: 410,
      contentType: "application/json",
      body: JSON.stringify({ code: "run_expired", message: "x" }),
    });
  });
  await openFirstTextAndSelect(page);

  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByRole("alert")).toContainText("Не удалось выполнить действие");
  await expect(page.getByText("Текст 2", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Рекомендуем начать с/ })).toHaveCount(0);
});
