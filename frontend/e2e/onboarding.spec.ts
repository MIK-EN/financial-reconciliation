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

test("guest completes the four-text route", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();

  for (const ordinal of [1, 2, 3, 4]) {
    await expect(page.getByText(`Текст ${ordinal}`, { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Все слова знакомы" }).click();
  }

  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Сложные тексты" }),
  ).toBeVisible();
});

test("guest completes the simplified difficult route", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();

  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await page.getByRole("button", { name: "Read", exact: true }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();

  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
  await expect(
    page.getByText("Даже в самом коротком тексте осталось несколько незнакомых слов."),
  ).toBeVisible();
});

test("guest can deselect a repeated word before submitting", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();

  const fileWords = page.getByRole("button", { name: "file", exact: true });
  await fileWords.first().click();
  await expect(fileWords.nth(0)).toHaveAttribute("aria-pressed", "true");
  await expect(fileWords.nth(1)).toHaveAttribute("aria-pressed", "true");

  await fileWords.first().click();
  await expect(fileWords.nth(0)).toHaveAttribute("aria-pressed", "false");
  await expect(fileWords.nth(1)).toHaveAttribute("aria-pressed", "false");

  await page.getByRole("button", { name: "create", exact: true }).click();
  await page.getByRole("button", { name: "new", exact: true }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();

  // Deselecting "file" leaves only 2 unique marked words out of 14, which is
  // accessible for the start text, so the next step is "installation", not
  // the simplified fallback used by the other tests.
  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(page.getByText(/Before you install the application/)).toBeVisible();
});

test("guest changes the selected starting level", async ({ page }) => {
  await completeSimplifiedRoute(page);

  const level = page.getByRole("combobox", { name: "Выбранная сложность" });
  await expect(level).toHaveValue("foundations");
  await level.selectOption("basic_docs");
  await expect(level).toHaveValue("basic_docs");
  await expect(page.getByText("Выбрано: Базовая документация")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
});

test("guest can dismiss the account offer", async ({ page }) => {
  await completeSimplifiedRoute(page);

  await page.getByRole("button", { name: "Пока не сейчас" }).click();

  await expect(page.getByRole("button", { name: "Сохранить результат" })).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
});

test("registration saves and restores the completed result", async ({ page }) => {
  const username = `e2e_${Date.now()}`;
  await completeSimplifiedRoute(page);
  await registerCompletedResult(page, username);
  await page.reload();
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
});

test("login restores a result after the auth cookie is lost", async ({ context, page }) => {
  const username = `e2e_${Date.now()}`;
  await completeSimplifiedRoute(page);
  await registerCompletedResult(page, username);

  await context.clearCookies({ name: "eds_auth_dev" });
  await page.reload();
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill("correct horse 123");
  await page.getByRole("button", { name: "Войти", exact: true }).click();

  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
});

test("login keeps a guest result separate until explicit claim", async ({ page }) => {
  const username = `e2e_${Date.now()}`;
  await completeSimplifiedRoute(page);
  await registerCompletedResult(page, username);
  await page.getByRole("button", { name: "Выйти" }).click();

  await completeSimplifiedRoute(page);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill("correct horse 123");
  await page.getByRole("button", { name: "Войти", exact: true }).click();

  await expect(page.getByText(`Вы вошли как ${username}`)).toBeVisible();
  await page.getByRole("button", { name: "Сохранить этот результат в аккаунте" }).click();
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();
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

test("mobile guest can start and select a word with the keyboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  // Wait for the app to render before tabbing; otherwise Tab fires before the button exists.
  await expect(page.getByRole("button", { name: "Начать" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Начать" })).toBeFocused();
  await page.keyboard.press("Enter");
  const firstWord = page.getByRole("button", { name: "You", exact: true });
  await firstWord.focus();
  await page.keyboard.press("Space");

  await expect(firstWord).toHaveAttribute("aria-pressed", "true");
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});
