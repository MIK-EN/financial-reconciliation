import { expect, type Page, test } from "@playwright/test";

async function startRoute(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Начать" }).click();
  await expect(page.getByText("Текст 1", { exact: true })).toBeVisible();
}

async function markUnfamiliarWords(page: Page) {
  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
}

async function reachSecondText(page: Page) {
  await startRoute(page);
  await markUnfamiliarWords(page);
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

test("stale tab with a different answer shows the server step", async ({ context, page }) => {
  await startRoute(page);

  const second = await context.newPage();
  await second.goto("/");
  await expect(second.getByText("Текст 1", { exact: true })).toBeVisible();

  await markUnfamiliarWords(page);
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();

  await second.getByRole("button", { name: "Все слова знакомы" }).click();

  await expect(second.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(second.getByRole("alert")).toHaveCount(0);
});

test("stale tab repeating the same answer gets the next step", async ({ context, page }) => {
  await startRoute(page);

  const second = await context.newPage();
  await second.goto("/");
  await expect(second.getByText("Текст 1", { exact: true })).toBeVisible();

  await markUnfamiliarWords(page);
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();

  await markUnfamiliarWords(second);
  await second.getByRole("button", { name: "Продолжить" }).click();

  await expect(second.getByText("Текст 2", { exact: true })).toBeVisible();
  await expect(second.getByRole("alert")).toHaveCount(0);
});

test("stale level change does not overwrite the newer choice", async ({ context, page }) => {
  await completeSimplifiedRoute(page);

  const second = await context.newPage();
  await second.goto("/");
  await expect(
    second.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();

  const pageLevel = page.getByRole("combobox", { name: "Выбранная сложность" });
  await pageLevel.selectOption("basic_docs");
  await expect(pageLevel).toHaveValue("basic_docs");
  await expect(page.getByText("Выбрано: Базовая документация")).toBeVisible();

  const secondLevel = second.getByRole("combobox", { name: "Выбранная сложность" });
  await secondLevel.selectOption("confident_reading");

  await expect(secondLevel).toHaveValue("basic_docs");
  await expect(second.getByText("Выбрано: Базовая документация")).toBeVisible();
  await expect(second.getByRole("alert")).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole("combobox", { name: "Выбранная сложность" })).toHaveValue(
    "basic_docs",
  );
});
