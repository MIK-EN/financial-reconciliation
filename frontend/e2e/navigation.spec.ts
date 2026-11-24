import { expect, type Page, test } from "@playwright/test";

function landingHeading(page: Page) {
  return page.getByRole("heading", { name: "С каких текстов начинать читать документацию?" });
}

function resultHeading(page: Page) {
  return page.getByRole("heading", { name: "Рекомендуем начать с: Основы" });
}

function firstTextLabel(page: Page) {
  return page.getByText("Текст 1", { exact: true });
}

function startButton(page: Page) {
  return page.getByRole("button", { name: "Подобрать сложность" }).first();
}

function bannerLogo(page: Page) {
  return page.getByRole("banner").getByRole("link", { name: "English for Developers", exact: true });
}

function bannerLogin(page: Page) {
  return page.getByRole("banner").getByRole("button", { name: "Войти", exact: true });
}

async function startRoute(page: Page) {
  await page.goto("/");
  await startButton(page).click();
  await expect(firstTextLabel(page)).toBeVisible();
}

async function completeSimplifiedRoute(page: Page) {
  await startRoute(page);
  for (const word of ["file", "create", "new"]) {
    await page.getByRole("button", { name: word, exact: true }).first().click();
  }
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("button", { name: "Все слова знакомы" }).click();
  await expect(resultHeading(page)).toBeVisible();
}

test("the text-step logo goes home and the landing CTA resumes the marked text", async ({ page }) => {
  await startRoute(page);
  const word = page.getByRole("button", { name: "file", exact: true }).first();
  await word.click();
  await expect(word).toHaveAttribute("aria-pressed", "true");

  await bannerLogo(page).click();
  await expect(landingHeading(page)).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === "/");

  await startButton(page).click();
  await expect(firstTextLabel(page)).toBeVisible();
  await expect(word).toHaveAttribute("aria-pressed", "true");
});

test("browser Back and Forward switch between the landing and first text", async ({ page }) => {
  await startRoute(page);

  await page.goBack();
  await expect(landingHeading(page)).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === "/");

  await page.goForward();
  await expect(firstTextLabel(page)).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === "/onboarding");
});

test("reloading the landing after Back lets the CTA resume the result without starting a run", async ({ page }) => {
  await completeSimplifiedRoute(page);
  await page.goBack();
  await expect(landingHeading(page)).toBeVisible();

  const startRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/onboarding") {
      startRequests.push(request.url());
    }
  });
  await page.reload();
  await expect(landingHeading(page)).toBeVisible();

  await startButton(page).click();
  await expect(resultHeading(page)).toBeVisible();
  expect(startRequests).toHaveLength(0);
});

test("the result logo goes home", async ({ page }) => {
  await completeSimplifiedRoute(page);

  await bannerLogo(page).click();
  await expect(landingHeading(page)).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === "/");
});

test("a fresh entry resumes the completed run at the onboarding URL", async ({ page }) => {
  await completeSimplifiedRoute(page);

  await page.goto("/");
  await expect(resultHeading(page)).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === "/onboarding");
});

test("opening the onboarding URL without a run returns to the landing", async ({ page }) => {
  await page.goto("/onboarding");

  await expect(landingHeading(page)).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === "/");
});

test("canceling the guest header login returns to the text step", async ({ page }) => {
  await startRoute(page);
  const login = bannerLogin(page);
  await expect(login).toBeVisible();

  await login.click();
  await expect(page.getByRole("heading", { name: "Войти", exact: true })).toBeVisible();
  await expect(page.getByLabel("Логин")).toBeVisible();

  await page.getByRole("button", { name: "Отмена", exact: true }).click();
  await expect(firstTextLabel(page)).toBeVisible();
  await expect(login).toBeVisible();
});

test("guest header login opens an inline form on the result screen", async ({ page }) => {
  await completeSimplifiedRoute(page);
  const login = bannerLogin(page);

  await login.click();
  await expect(page.getByLabel("Логин")).toBeVisible();
  await expect(resultHeading(page)).toBeVisible();
  await expect(login).toHaveCount(0);
});

test("registration hides login in the result header and landing navigation", async ({ page }) => {
  const username = `e2e_${Date.now()}_nav`;
  await completeSimplifiedRoute(page);
  await page.getByRole("button", { name: "Сохранить результат" }).click();
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill("correct horse 123");
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  await expect(page.getByText(`Результат сохранён в аккаунте ${username}`)).toBeVisible();

  await expect(bannerLogin(page)).toHaveCount(0);
  await bannerLogo(page).click();
  await expect(landingHeading(page)).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Основная навигация" })
      .getByRole("button", { name: "Войти через Telegram" }),
  ).toHaveCount(0);
});
