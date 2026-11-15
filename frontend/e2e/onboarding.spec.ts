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
