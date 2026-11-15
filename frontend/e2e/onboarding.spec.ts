import { expect, test } from "@playwright/test";

test("guest completes the simplified onboarding route", async ({ page }) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: "Подберём стартовую сложность" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Начать" }).click();

  await expect(
    page.getByRole("heading", { name: "Нажмите на слова, которые вам незнакомы" }),
  ).toBeVisible();
  await expect(page.getByText("Текст 1", { exact: true })).toBeVisible();

  const repeatedFileWords = page.getByRole("button", { name: "file", exact: true });
  await repeatedFileWords.first().click();
  await expect(repeatedFileWords).toHaveCount(2);
  await expect(repeatedFileWords.nth(0)).toHaveAttribute("aria-pressed", "true");
  await expect(repeatedFileWords.nth(1)).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "create", exact: true }).click();
  await page.getByRole("button", { name: "new", exact: true }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(page.getByText("Open the file. Read the text. Save your changes.")).toBeVisible();
  await page.getByRole("button", { name: "Все слова знакомы" }).click();

  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
  await expect(
    page.getByText("Это ориентир по отмеченным словам, а не оценка уровня английского."),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /урок/i })).toHaveCount(0);
});

test("draft selection survives a reload", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();

  const fileWords = page.getByRole("button", { name: "file", exact: true });
  await fileWords.first().click();
  await expect(fileWords.nth(0)).toHaveAttribute("aria-pressed", "true");
  await expect(fileWords.nth(1)).toHaveAttribute("aria-pressed", "true");

  await page.reload();

  const restoredFileWords = page.getByRole("button", { name: "file", exact: true });
  await expect(restoredFileWords.nth(0)).toHaveAttribute("aria-pressed", "true");
  await expect(restoredFileWords.nth(1)).toHaveAttribute("aria-pressed", "true");
});

test("unavailable session storage does not block onboarding", async ({ page }) => {
  await page.addInitScript(() => {
    for (const method of ["getItem", "setItem", "removeItem"] as const) {
      Object.defineProperty(Storage.prototype, method, {
        configurable: true,
        value: () => {
          throw new DOMException("Storage unavailable", "SecurityError");
        },
      });
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();

  const fileWords = page.getByRole("button", { name: "file", exact: true });
  await fileWords.first().click();
  await expect(fileWords.nth(0)).toHaveAttribute("aria-pressed", "true");
  await expect(fileWords.nth(1)).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await expect(page.getByRole("button", { name: "Все слова знакомы" })).toBeVisible();
});

test("network retry keeps the selection and original answer", async ({ page }) => {
  const requestBodies: (string | null)[] = [];
  let attempt = 0;
  await page.route("**/api/v1/onboarding/*/answers", async (route) => {
    attempt += 1;
    requestBodies.push(route.request().postData());
    if (attempt === 1) await route.abort("failed");
    else await route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();

  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByRole("alert")).toContainText("Не удалось связаться с сервером");
  await expect(page.getByRole("button", { name: "file", exact: true }).first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  expect(requestBodies).toHaveLength(2);
  expect(requestBodies[1]).toBe(requestBodies[0]);
});

test("conflict reloads the server-authoritative step", async ({ page }) => {
  await page.route("**/api/v1/onboarding/*/answers", async (route) => {
    await route.fetch();
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ code: "answer_conflict", message: "Conflict" }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();

  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
