import { expect, type Page, test } from "@playwright/test";

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

  const level = page.getByRole("combobox", { name: "Выбранная сложность" });
  await level.selectOption("basic_docs");
  await expect(level).toHaveValue("basic_docs");
  await expect(page.getByText("Выбрано: Базовая документация")).toBeVisible();

  await page.reload();

  await expect(page.getByRole("combobox", { name: "Выбранная сложность" })).toHaveValue(
    "basic_docs",
  );
});
