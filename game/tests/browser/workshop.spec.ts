import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Остров искр", exact: true }),
  ).toBeVisible();
});

test("complete starter adventure, save, and reload", async ({ page }) => {
  await page.locator('.map-entity[aria-label="Садовник Мир"]').click();
  await page.getByRole("button", { name: "Взяться за дело" }).click();
  for (let i = 0; i < 3; i++) {
    await page
      .locator('.map-entity[aria-label="Спелое яблоко"]')
      .first()
      .click();
    await expect(
      page.locator('.map-entity[aria-label="Спелое яблоко"]'),
    ).toHaveCount(2 - i);
  }
  await page.locator('.map-entity[aria-label="Садовник Мир"]').click();
  await expect(
    page.getByText("Спасибо, хранитель! Ты отлично справился."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Закрыть окно", exact: true }).click();
  await page.locator('.map-entity[aria-label="Ворота в рощу"]').click();
  await expect(page.locator(".entity-gate")).toHaveClass(/entity-opened/);
  await page.locator('.map-entity[aria-label="Сундук хранителя"]').click();
  await expect(page.locator(".entity-chest")).toHaveClass(/entity-opened/);
  await expect(page.locator(".hero-stat-grid")).toContainText("65");
  await expect(page.locator(".save-status")).toHaveText("Сохранено в браузере");
  await page.reload();
  await expect(page.locator(".entity-chest")).toHaveClass(/entity-opened/);
  await expect(page.locator(".hero-stat-grid")).toContainText("65");
});

test("create custom stat, item, button and window; test then publish without contaminating live state", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Открыть мастерскую" }).click();
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: "Характеристики", exact: true })
    .click();
  await page.getByRole("button", { name: "Новая характеристика" }).click();
  await page.getByLabel("Название", { exact: true }).fill("Удача");
  await page.getByLabel("Начальное значение", { exact: true }).fill("7");
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: "Предметы", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Новый предмет", exact: true })
    .click();
  await page.getByLabel("Название", { exact: true }).fill("Талисман удачи");
  await page.getByLabel("Тип", { exact: true }).selectOption("equipment");
  await page
    .getByRole("button", { name: "Добавить действие", exact: true })
    .click();
  await page.getByLabel("Действие 1: тип").selectOption("stat");
  await page
    .getByLabel("Характеристика", { exact: true })
    .selectOption({ label: "Удача" });
  await page.locator('.action-row input[type="number"]').fill("2");
  await page.getByRole("button", { name: "Разместить на карте" }).click();
  await page.getByRole("button", { name: "Клетка 6, 8", exact: true }).click();
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: "Кнопки и окна" })
    .click();
  await page.getByRole("button", { name: "Окна", exact: true }).click();
  await page.getByRole("button", { name: "Новое окно", exact: true }).click();
  await page.getByLabel("Заголовок окна").fill("Моя лаборатория");
  await page.getByLabel("Текст / история").fill("Это окно создано без кода.");
  await page.getByLabel("Удача", { exact: true }).check();
  await page
    .getByRole("button", { name: "Кнопки действий", exact: true })
    .click();
  await page.getByRole("button", { name: "Новая кнопка", exact: true }).click();
  await page.getByLabel("Название кнопки").fill("Лаборатория");
  await page.getByLabel("Действие 1: тип").selectOption("window");
  await page
    .getByLabel("Окно", { exact: true })
    .selectOption({ label: "Моя лаборатория" });
  await expect(page.locator(".validation-box")).toHaveCount(0);
  await page.getByRole("button", { name: "Проверить", exact: true }).click();
  await expect(page.locator(".test-banner")).toBeVisible();
  await page
    .locator(".quick-buttons")
    .getByRole("button", { name: "Лаборатория" })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "Это окно создано без кода.",
  );
  await expect(page.locator(".custom-window-stats")).toContainText("7");
  await page.getByRole("button", { name: "Закрыть окно", exact: true }).click();
  await page.locator('.map-entity[aria-label="Талисман удачи"]').click();
  await expect(
    page.locator('.map-entity[aria-label="Талисман удачи"]'),
  ).toHaveCount(0);
  await page
    .locator(".quick-buttons")
    .getByRole("button", { name: "Рюкзак" })
    .click();
  await page
    .locator(".inventory-item")
    .filter({ hasText: "Талисман удачи" })
    .getByRole("button", { name: "Применить" })
    .click();
  await page.getByRole("button", { name: "Закрыть окно", exact: true }).click();
  await page
    .locator(".quick-buttons")
    .getByRole("button", { name: "Лаборатория" })
    .click();
  await expect(page.locator(".custom-window-stats")).toContainText("9");
  await page.getByRole("button", { name: "Закрыть окно", exact: true }).click();
  await page.getByRole("button", { name: "Вернуться в мастерскую" }).click();
  await page.getByRole("button", { name: "Опубликовать в мире" }).click();
  await expect(page.locator(".test-banner")).toHaveCount(0);
  await expect(page.locator(".world-version")).toHaveText("v2");
  await page
    .locator(".quick-buttons")
    .getByRole("button", { name: "Лаборатория" })
    .click();
  await expect(page.locator(".custom-window-stats")).toContainText("7");
  await page.getByRole("button", { name: "Закрыть окно", exact: true }).click();
  await page.getByRole("button", { name: "Мой персонаж", exact: true }).click();
  await expect(page.locator(".character-stats")).toContainText("Удача");
});

test("visual rule responds to a new button and rollback restores a working world", async ({
  page,
}) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Открыть мастерскую" }).click();
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: "Кнопки и окна" })
    .click();
  await page.getByRole("button", { name: "Новая кнопка", exact: true }).click();
  await page.getByLabel("Название кнопки").fill("Разведка");
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: /Правила/ })
    .click();
  await page
    .getByRole("button", { name: "Новое правило", exact: true })
    .click();
  await page.getByLabel("Название правила").fill("Награда разведчика");
  await page.getByLabel("Событие", { exact: true }).selectOption("button");
  await page.getByLabel("Источник события").selectOption({ label: "Разведка" });
  await page
    .getByRole("button", { name: "Добавить условие", exact: true })
    .click();
  await page.getByLabel("Тип условия").selectOption("flag");
  await page.getByLabel("Событие условия").fill("scouted");
  await page.getByLabel("Произошло", { exact: true }).uncheck();
  await page.getByLabel("Действие 1: тип").selectOption("stat");
  await page
    .getByLabel("Характеристика", { exact: true })
    .selectOption({ label: "Опыт" });
  await page.locator('.action-row input[type="number"]').fill("9");
  await page
    .getByRole("button", { name: "Добавить действие", exact: true })
    .click();
  await page.getByLabel("Действие 2: тип").selectOption("flag");
  await page.getByLabel("Название события").fill("scouted");
  await page.getByRole("button", { name: "Проверить", exact: true }).click();
  await page
    .locator(".quick-buttons")
    .getByRole("button", { name: "Разведка", exact: true })
    .click();
  await expect(page.locator(".hero-stat-grid")).toContainText("9");
  await page
    .locator(".quick-buttons")
    .getByRole("button", { name: "Разведка", exact: true })
    .click();
  await expect(page.locator(".hero-stat-grid")).toContainText("9");
  await page.getByRole("button", { name: "Вернуться в мастерскую" }).click();
  await page.getByRole("button", { name: "Опубликовать в мире" }).click();
  await expect(page.locator(".hero-stat-grid")).toContainText("0");
  await page
    .locator(".quick-buttons")
    .getByRole("button", { name: "Разведка", exact: true })
    .click();
  await expect(page.locator(".hero-stat-grid")).toContainText("9");
  await page.getByRole("button", { name: "Открыть мастерскую" }).click();
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: "История и копии" })
    .click();
  await page.getByRole("button", { name: "Восстановить", exact: true }).click();
  await expect(page.locator(".world-version")).toHaveText("v1");
  await expect(
    page
      .locator(".quick-buttons")
      .getByRole("button", { name: "Разведка", exact: true }),
  ).toHaveCount(0);
});

test("upload graphics, create and position a character, export/import world", async ({
  page,
}) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Открыть мастерскую" }).click();
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: "Графика", exact: true })
    .click();
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nzsAAAAASUVORK5CYII=",
    "base64",
  );
  await page.locator("input[type=file][multiple]").setInputFiles({
    name: "my-sprite.png",
    mimeType: "image/png",
    buffer: png,
  });
  await expect(page.locator(".asset-card")).toHaveCount(1);
  await page
    .locator(".studio-nav")
    .getByRole("button", { name: "Персонажи и объекты" })
    .click();
  await page.getByRole("button", { name: "Создать", exact: true }).click();
  await page.getByLabel("Имя", { exact: true }).fill("Мой странник");
  await page
    .getByLabel("Изображение", { exact: true })
    .selectOption({ label: "my-sprite.png" });
  await page.getByRole("button", { name: "Клетка 6, 8", exact: true }).click();
  await expect(page.locator(".placement-button strong")).toHaveText("6, 8");
  await page.getByRole("button", { name: "Опубликовать в мире" }).click();
  await expect(
    page.locator('.map-entity[aria-label="Мой странник"] img'),
  ).toHaveAttribute("src", /^data:image\/webp;base64,/);
  const downloadEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Скачать резервную копию", exact: true })
    .click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("iskra-world-v2.json");
  const path = await download.path();
  await page
    .locator('input[type=file][accept=".json,application/json"]')
    .setInputFiles(path!);
  await expect(
    page.locator('.map-entity[aria-label="Мой странник"]'),
  ).toHaveCount(1);
  await expect(page.locator(".world-version")).toHaveText("v2");
});

test("mobile layout, touch movement and editor have no horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".mobile-controls")).toBeVisible();
  await page.getByRole("button", { name: "Идти вправо", exact: true }).click();
  await expect(page.locator(".coordinates")).toHaveText("5, 7");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Мастерская", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /Мастерская мира/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/mobile-studio.png",
    fullPage: true,
  });
});

test("invalid import is rejected without changing the game", async ({
  page,
}) => {
  await page
    .locator('input[type=file][accept=".json,application/json"]')
    .setInputFiles({
      name: "broken.json",
      mimeType: "application/json",
      buffer: Buffer.from('{"world":{"schemaVersion":1}}'),
    });
  await expect(page.locator(".toast")).toBeVisible();
  await expect(page.locator(".world-version")).toHaveText("v1");
  await expect(
    page.locator('.map-entity[aria-label="Садовник Мир"]'),
  ).toBeVisible();
});
