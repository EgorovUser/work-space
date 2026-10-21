import { expect, request, test } from "@playwright/test"

// Визуальный редактор «Сегодня» (патч AW): вход в режим правки, выбор
// элемента, смена ширины, скрытие, добавление, сброс, история. Двигаем
// только пользовательскими путями: кнопки «Настроить»/«Готово», список
// и поля панели свойств.

const CREDS = { username: "e2e", password: "e2e-pass" }

async function login(page) {
  await page.goto("/login")
  await page.getByLabel("Логин").fill(CREDS.username)
  await page.getByLabel("Пароль").fill(CREDS.password)
  await page.getByRole("button", { name: "Войти" }).click()
  await expect(page.locator(".app")).toBeVisible()
}

async function apiLogin() {
  const context = await request.newContext({ baseURL: test.info().project.use.baseURL })
  const response = await context.post("/api/auth/login", { data: CREDS })
  expect(response.ok()).toBeTruthy()
  return context
}

async function openEditor(page) {
  await page.goto("/")
  await page.getByRole("button", { name: "Настроить" }).click()
  await expect(page.locator(".designer-panel")).toBeVisible()
  await expect(page).toHaveURL(/\/\?edit=1$/)
}

// «Готово» в шапке и в панели — сужаем до панели (строгий режим
// Playwright не прощает двух одинаковых кнопок).
async function closeEditor(page) {
  await page.locator(".designer-panel").getByRole("button", { name: "Готово" }).click()
  await expect(page.locator(".designer-panel")).toHaveCount(0)
}

// Тесты сюжета редактора меняют раскладку: после каждого — возврат к
// стандартной, чтобы состояние не утекало в соседние спеки.
test.afterEach(async ({ request }) => {
  await request.post("/api/auth/login", { data: CREDS })
  await request.post("/api/ui/today/reset")
})

async function selectElement(page, title) {
  await page.locator(".designer-row", { hasText: title }).click()
  await expect(page.locator(".designer-props-head")).toContainText(title)
}

test("редактор открывается, элемент выделяется кликом по карточке", async ({ page }) => {
  await login(page)
  await openEditor(page)
  // Клик по карточке на странице выделяет элемент: рамка акцента.
  const card = page.locator(".ui-item[data-element='pomodoro']")
  await card.click()
  await expect(card).toHaveClass(/ui-selected/)
  await expect(page.locator(".designer-props-head")).toContainText("Помодоро")
  // Ссылки внутри карточек закрыты плёнкой — клик не уводит со страницы.
  await expect(page).toHaveURL(/\/\?edit=1$/)
})

test("ширина элемента меняется и переживает перезагрузку", async ({ page }) => {
  await login(page)
  await openEditor(page)
  await selectElement(page, "Помодоро")
  // Половина → вся ширина.
  const card = page.locator(".ui-item[data-element='pomodoro']")
  await expect(card).toHaveClass(/ui-span-2/)
  await page.locator(".designer-field", { hasText: "Ширина" }).locator("select").selectOption("4")
  await expect(card).toHaveClass(/ui-span-4/)
  // Автосохранение с дебаунсом: ждём надпись «Сохраняем…» и её исчезновение.
  await expect(page.locator(".designer-saving")).toBeVisible()
  await expect(page.locator(".designer-saving")).toHaveCount(0)
  // Выход из редактора — раскладка остаётся, адрес чистый.
  await closeEditor(page)
  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator(".ui-item[data-element='pomodoro']")).toHaveClass(/ui-span-4/)
  // Перезагрузка — конфиг на месте (ui_configs на бэкене, не localStorage).
  await page.reload()
  await expect(page.locator(".ui-item[data-element='pomodoro']")).toHaveClass(/ui-span-4/)
})

test("свой заголовок и плотность применяются к карточке", async ({ page }) => {
  await login(page)
  await openEditor(page)
  await selectElement(page, "Новые письма")
  const field = page.locator(".designer-field", { hasText: "Свой заголовок" }).locator("input")
  await field.fill("Входящие")
  await page.locator(".designer-field", { hasText: "Плотность строк" }).locator("select").selectOption("compact")
  await expect(page.locator(".designer-saving")).toBeVisible()
  await expect(page.locator(".designer-saving")).toHaveCount(0)
  await closeEditor(page)
  await expect(page.getByRole("heading", { name: "Входящие" })).toBeVisible()
  await expect(page.locator(".ui-item[data-element='new-mail'] .card")).toHaveClass(/density-compact/)
})

test("порядок элементов двигается стрелками", async ({ page }) => {
  await login(page)
  await openEditor(page)
  // «Ближайшие сроки» — второй; сдвигаем вверх, он становится первым.
  await page.locator(".designer-row", { hasText: "Ближайшие сроки" }).locator('button[title="Выше"]').click()
  const order = page.locator(".ui-grid .ui-item")
  await expect(order.first()).toHaveAttribute("data-element", "upcoming-tasks")
})

test("элемент скрывается и возвращается", async ({ page }) => {
  await login(page)
  await openEditor(page)
  await selectElement(page, "Уведомления")
  const hideField = page.locator(".designer-field", { hasText: "Скрыть на странице" }).locator("input")
  await hideField.check()
  // В режиме правки скрытый виден вполовину силы и помечен.
  const card = page.locator(".ui-item[data-element='notifications']")
  await expect(card).toHaveClass(/ui-hidden-item/)
  await closeEditor(page)
  // Вне редактора скрытого элемента нет.
  await expect(page.locator(".ui-item[data-element='notifications']")).toHaveCount(0)
  // Обратный ход — снятие галочки возвращает карточку.
  await openEditor(page)
  await selectElement(page, "Уведомления")
  await hideField.uncheck()
  await closeEditor(page)
  await expect(page.locator(".ui-item[data-element='notifications']")).toBeVisible()
})

test("удалённый элемент возвращается пикером", async ({ page }) => {
  await login(page)
  await openEditor(page)
  await selectElement(page, "События на сегодня")
  page.once("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "Убрать" }).click()
  await expect(page.locator(".ui-item[data-element='mail-events']")).toHaveCount(0)
  // Добавление: пикер показывает только отсутствующие.
  await page.getByRole("button", { name: "+ Добавить элемент" }).click()
  await page.locator(".designer-picker-item", { hasText: "События на сегодня" }).click()
  await expect(page.locator(".ui-item[data-element='mail-events']")).toBeVisible()
})

test("сброс к стандартной и история изменений", async ({ page }) => {
  const api = await apiLogin()
  // Два сохранения подряд: второе меняет первое — в истории появляется
  // снимок «одна карточка» (первое сохранение снимков не создаёт: прежде
  // сохранять нечего).
  await api.put("/api/ui/today", { data: { items: [{ element: "pomodoro", span: 2 }], settings: {} } })
  const put = await api.put("/api/ui/today", { data: { items: [{ element: "pomodoro", span: 4 }], settings: {} } })
  expect(put.ok()).toBeTruthy()

  await login(page)
  await expect(page.locator(".ui-grid .ui-item")).toHaveCount(1)
  await openEditor(page)
  // История: свежий снимок — прежняя раскладка из одного элемента.
  await page.locator(".designer-history summary").click()
  const rev = page.locator(".designer-rev").first()
  await expect(rev).toContainText("· 1 элемент")
  // Сброс: подтверждение + возврат семи карточек.
  page.once("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "Сбросить к стандартной" }).click()
  await expect(page.locator(".ui-grid .ui-item")).toHaveCount(7)
  // Откат из истории: блок уже открыт, список обновился сам после сброса —
  // «Вернуть» возвращает раскладку «одна карточка».
  await page.locator(".designer-rev").first().getByRole("button", { name: "Вернуть" }).click()
  await expect(page.locator(".ui-grid .ui-item")).toHaveCount(1)
})

test("высота блока настраивается уровнем, страница — максимумом", async ({ page }) => {
  await login(page)
  await openEditor(page)
  // Вкладка «Страница»: максимум высоты блоков.
  await page.getByRole("button", { name: "Страница" }).click()
  await expect(page.locator(".designer-page")).toBeVisible()
  await page.locator(".designer-field", { hasText: "Максимальная высота блока" }).locator("select").selectOption("640")
  await expect(page.locator(".designer-saving")).toBeVisible()
  await expect(page.locator(".designer-saving")).toHaveCount(0)
  // Переменная приехала на сетку страницы.
  const cssVar = await page.locator(".ui-grid").evaluate((el) => el.style.getPropertyValue("--ui-max-h"))
  expect(cssVar).toBe("640px")
  // «Средний» = три четверти максимума = ровно 480px. «Авто» ничего
  // не фиксирует — высоту даёт только выбранный уровень.
  await page.getByRole("button", { name: "Элементы" }).click()
  await selectElement(page, "Просроченные")
  const card = page.locator(".ui-item[data-element='overdue-tasks']")
  await expect(card).not.toHaveClass(/ui-height/)
  await page.locator(".designer-field", { hasText: "Высота" }).locator("select").selectOption("medium")
  await expect(card).toHaveClass(/ui-height-medium/)
  await expect(card).toHaveCSS("height", "480px")
  // Блок не растёт: содержимое скроллится внутри тела карточки.
  await expect(card.locator(".card-body")).toHaveCSS("overflow-y", "auto")
  await expect(page.locator(".designer-saving")).toBeVisible()
  await expect(page.locator(".designer-saving")).toHaveCount(0)
  // Переживает перезагрузку: конфиг на бэкенде, не в localStorage.
  await page.reload()
  await expect(page.locator(".ui-item[data-element='overdue-tasks']")).toHaveCSS("height", "480px")
})

test("внутренние элементы: колонки, выравнивание, отступы, разделители", async ({ page }) => {
  const api = await apiLogin()
  // Строки «Проектов» появляются только с данными: создаём проект.
  await api.post("/api/projects", { data: { name: "Раскладка " + Date.now() } })

  await login(page)
  await openEditor(page)
  await selectElement(page, "Проекты")
  const list = page.locator(".ui-item[data-element='projects'] .ui-items")
  // База — как до настройки: контейнер без модификаторов.
  await expect(list).toBeVisible()
  await expect(list).not.toHaveClass(/ui-items--/)
  // Две колонки.
  await page.locator(".designer-field", { hasText: "Колонки" }).locator("select").selectOption("2")
  await expect(list).toHaveClass(/ui-items--cols-2/)
  // Выравнивание по центру — строки сжимаются к середине.
  await page.locator(".designer-field", { hasText: "Выравнивание" }).locator("select").selectOption("center")
  await expect(list).toHaveClass(/ui-items--align-center/)
  // Отступ свободный, разделители выкл.
  await page.locator(".designer-field", { hasText: "Отступ между строками" }).locator("select").selectOption("spacious")
  await page.locator(".designer-field", { hasText: "Разделители строк" }).locator("input").uncheck()
  await expect(list).toHaveClass(/ui-items--gap-spacious/)
  await expect(list).toHaveClass(/ui-items--no-dividers/)
  await expect(page.locator(".designer-saving")).toBeVisible()
  await expect(page.locator(".designer-saving")).toHaveCount(0)
  // Переживает перезагрузку.
  await page.reload()
  await expect(page.locator(".ui-item[data-element='projects'] .ui-items")).toHaveClass(/ui-items--cols-2/)
})

test("конфиг страницы не ломается мусором с клиента", async ({ page }) => {
  const api = await apiLogin()
  // Прямая запись мусора через API (минуя нормализацию нельзя — но
  // проверяем конверт): посторонние ключи долой, span и height вне
  // списка — дефолт, дубль отброшен, неизвестный элемент жив заглушкой,
  // настройка страницы из списка не выпала — дефолт.
  const put = await api.put("/api/ui/today", {
    data: {
      settings: { max_block_height: "очень" },
      items: [
        { element: "pomodoro", span: 99, junk: "x", height: "огромный" },
        { element: "pomodoro", span: 1 },
        { element: "legacy-card", span: 3 },
      ],
    },
  })
  expect(put.ok()).toBeTruthy()
  const state = await (await api.get("/api/ui/today")).json()
  expect(state.items).toEqual([
    { element: "pomodoro", span: 2, hidden: false, title: "", height: "auto" },
    { element: "legacy-card", span: 3, hidden: false, height: "auto" },
  ])
  expect(state.settings).toEqual({ max_block_height: 480 })
  // Страница рендерится: знакомая карточка + заглушка неизвестного.
  await login(page)
  await page.goto("/")
  await expect(page.locator(".ui-item[data-element='pomodoro']")).toBeVisible()
  await expect(page.locator(".ui-stub")).toContainText("legacy-card")
  // И в редакторе заглушка редактируется и удаляется.
  await openEditor(page)
  await expect(page.locator(".ui-item[data-element='legacy-card']")).toBeVisible()
})
