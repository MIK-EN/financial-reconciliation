import { expect, type Page, test } from "@playwright/test";

async function expectNoHorizontalOverflow(page: Page) {
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
}

test("keyboard completes the route on a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const start = page.getByRole("button", { name: "Начать" });
  await start.focus();
  await page.keyboard.press("Enter");

  await expect(page.getByText("Текст 1", { exact: true })).toBeVisible();
  for (const word of ["file", "create", "new"]) {
    const wordButton = page.getByRole("button", { name: word, exact: true }).first();
    await wordButton.focus();
    await page.keyboard.press("Space");
    await expect(wordButton).toHaveAttribute("aria-pressed", "true");
  }
  await expectNoHorizontalOverflow(page);

  const continueButton = page.getByRole("button", { name: "Продолжить" });
  await continueButton.focus();
  await page.keyboard.press("Enter");

  await expect(page.getByText("Текст 2", { exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  const knownButton = page.getByRole("button", { name: "Все слова знакомы" });
  await knownButton.focus();
  await page.keyboard.press("Enter");

  await expect(
    page.getByRole("heading", { name: "Рекомендуем начать с: Основы" }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
