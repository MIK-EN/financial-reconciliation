import { expect, test, type Page } from "@playwright/test";
import type { Exercise, TrainerData } from "../src/trainer/types";

async function answer(page: Page, exercise: Exercise, correct = true) {
  const option = exercise.options.find(
    (o) => (o.id === exercise.correct_option_id) === correct,
  );
  if (option === undefined) throw new Error("Missing test option");
  await page.getByRole("radio", { name: option.text, exact: true }).check();
  await page.getByRole("button", { name: "Проверить ответ" }).click();
  await expect(
    page.getByRole("heading", {
      name: correct ? "✓ Верно!" : "Попробуем разобраться",
    }),
  ).toBeFocused();
  await expect(
    page.getByText(option.explanation, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("✓ Лучший вариант", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /Следующее задание|Результат темы/ })
    .click();
}

async function content(page: Page): Promise<TrainerData> {
  const response = await page.request.get("/api/v1/trainer");
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test("all four topics use real imported content and show explanations and results", async ({
  page,
}) => {
  const data = await content(page);
  await page.goto("/trainer");
  for (const topic of data.content.topics) {
    await page.getByRole("button").filter({ hasText: topic.title }).click();
    for (const exercise of topic.exercises) {
      await expect(
        page.getByRole("heading", { name: exercise.title }),
      ).toBeFocused();
      await expect(
        page.getByRole("button", { name: "Проверить ответ" }),
      ).toBeDisabled();
      await answer(page, exercise);
    }
    await expect(
      page.getByText("Пройдено 3 из 3. Правильно: 3 из 3.", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Выбрать тему" }).click();
  }
  await expect(
    page.getByText("Пройдено 12 из 12", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Пройдено 12 из 12", { exact: true }),
  ).toBeVisible();
});

test("reload resumes an unfinished topic and replay replaces rather than adds answers", async ({
  page,
}) => {
  const data = await content(page);
  const topic = data.content.topics[0]!;
  await page.goto("/trainer");
  await page.getByRole("button").filter({ hasText: topic.title }).click();
  await answer(page, topic.exercises[0]!, false);
  await page.reload();
  const card = page.getByRole("button").filter({ hasText: topic.title });
  await expect(card).toContainText("Пройдено 1/3 · Правильно 0/3");
  await card.click();
  await expect(
    page.getByRole("heading", { name: topic.exercises[1]!.title }),
  ).toBeVisible();
  await answer(page, topic.exercises[1]!);
  await answer(page, topic.exercises[2]!);
  await page.getByRole("button", { name: "Выбрать тему" }).click();
  await card.click();
  await answer(page, topic.exercises[0]!);
  await page.getByRole("button", { name: "← Все темы" }).click();
  await expect(card).toContainText("Пройдено 3/3 · Правильно 3/3");
  await page.reload();
  await expect(card).toContainText("Пройдено 3/3 · Правильно 3/3");
});

for (const unavailable of ["blocked", "quota"]) {
  test(`practice keeps answers in memory when storage is ${unavailable}`, async ({
    page,
  }) => {
    const data = await content(page);
    const topic = data.content.topics[0]!;
    await page.addInitScript((mode) => {
      if (mode === "blocked")
        Storage.prototype.getItem = () => {
          throw new DOMException("Blocked", "SecurityError");
        };
      Storage.prototype.setItem = () => {
        throw new DOMException("Full", "QuotaExceededError");
      };
    }, unavailable);
    await page.goto("/trainer");
    await page.getByRole("button").filter({ hasText: topic.title }).click();
    await answer(page, topic.exercises[0]!);
    await expect(
      page.getByText(/Браузер не разрешил сохранить прогресс/),
    ).toBeVisible();
    await answer(page, topic.exercises[1]!);
    await page.getByRole("button", { name: "← Все темы" }).click();
    await expect(
      page.getByRole("button").filter({ hasText: topic.title }),
    ).toContainText("Пройдено 2/3 · Правильно 2/3");
  });
}

test("corrupt and old-version storage does not prevent a new start", async ({
  page,
}) => {
  const data = await content(page);
  await page.addInitScript((hash) => {
    localStorage.setItem(
      `english-for-developers:trainer:v1:${hash}`,
      "{broken",
    );
    localStorage.setItem(
      "english-for-developers:trainer:v1:old",
      '{"review-empty-list":"b"}',
    );
  }, data.content_hash);
  await page.goto("/trainer");
  await expect(
    page.getByText("Пройдено 0 из 12", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button").filter({ hasText: "Code review" }).click();
  await answer(page, data.content.topics[0]!.exercises[0]!);
});

test("a failed content request has a working retry", async ({ page }) => {
  await page.route("**/api/v1/trainer", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/trainer");
  await expect(page.getByRole("alert")).toContainText(
    "Не удалось загрузить задания",
  );
  await page.unroute("**/api/v1/trainer");
  await page.getByRole("button", { name: "Повторить загрузку" }).click();
  await expect(
    page.getByRole("heading", { name: /вашего рабочего дня/ }),
  ).toBeVisible();
});

test("keyboard and 375px layout, links and browser back remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.getByRole("link", { name: "Открыть тренажёр →" }).click();
  await expect(page).toHaveURL(/\/trainer$/);
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button").filter({ hasText: "Code review" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("radio").first()).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "✓ Верно!" })).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.goBack();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "С каких текстов",
  );
});

test("a second tab receives saved progress", async ({ page, context }) => {
  const data = await content(page);
  await page.goto("/trainer");
  await expect(
    page.getByText("Пройдено 0 из 12", { exact: true }),
  ).toBeVisible();
  const other = await context.newPage();
  await other.goto("/trainer");
  await other.getByRole("button").filter({ hasText: "Code review" }).click();
  await answer(other, data.content.topics[0]!.exercises[0]!);
  await expect(
    page.getByText("Пройдено 1 из 12", { exact: true }),
  ).toBeVisible();
});
