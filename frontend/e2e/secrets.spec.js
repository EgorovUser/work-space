import { expect, request, test } from "@playwright/test"

// Глобальный раздел «Секреты»: список всех проектов разом, поиск и переход
// в проект. Данные готовим через API — спек проверяет экран, а не формы.

const CREDS = { username: "e2e", password: "e2e-pass" }

async function apiLogin() {
  const context = await request.newContext({ baseURL: test.info().project.use.baseURL })
  const response = await context.post("/api/auth/login", { data: CREDS })
  expect(response.ok()).toBeTruthy()
  return context
}

async function login(page) {
  await page.goto("/login")
  await page.getByLabel("Логин").fill(CREDS.username)
  await page.getByLabel("Пароль").fill(CREDS.password)
  await page.getByRole("button", { name: "Войти" }).click()
  await expect(page.locator(".app")).toBeVisible()
}

test("общий список секретов группирует по проектам", async ({ page }) => {
  const mark = "глоб" + Date.now()
  const api = await apiLogin()
  const first = await (await api.post("/api/projects", { data: { name: "Альфа " + mark } })).json()
  const second = await (await api.post("/api/projects", { data: { name: "Бета " + mark } })).json()
  await api.post(`/api/projects/${first.id}/secrets`, {
    data: { title: "Ключ альфа " + mark, username: "alpha-user", secret: "alpha-value" },
  })
  await api.post(`/api/projects/${second.id}/secrets`, {
    data: { title: "Токен бета " + mark, secret: "beta-value" },
  })

  await login(page)
  await page.goto("/secrets")
  await expect(page.getByRole("heading", { name: "Секреты", exact: true })).toBeVisible()

  const firstGroup = page.locator(".card", { hasText: "Альфа " + mark })
  await expect(firstGroup).toBeVisible()
  await expect(firstGroup.locator("a", { hasText: "Ключ альфа " + mark })).toBeVisible()
  await expect(firstGroup.getByText("логин задан")).toBeVisible()

  const secondGroup = page.locator(".card", { hasText: "Бета " + mark })
  await expect(secondGroup.locator("a", { hasText: "Токен бета " + mark })).toBeVisible()

  // Сами значения в списке не светятся — только признаки.
  await expect(page.getByText("alpha-value")).toHaveCount(0)
  await expect(page.getByText("beta-value")).toHaveCount(0)
})

test("поиск сужает общий список до совпадений", async ({ page }) => {
  const mark = "поиск" + Date.now()
  const api = await apiLogin()
  const first = await (await api.post("/api/projects", { data: { name: "Поиск А " + mark } })).json()
  const second = await (await api.post("/api/projects", { data: { name: "Поиск Б " + mark } })).json()
  await api.post(`/api/projects/${first.id}/secrets`, { data: { title: "Игла " + mark } })
  await api.post(`/api/projects/${second.id}/secrets`, { data: { title: "Стог " + mark } })

  await login(page)
  await page.goto("/secrets")
  await page.getByPlaceholder("Название").fill("Игла " + mark)
  await page.getByRole("button", { name: "Показать" }).click()
  await expect(page.locator(".card", { hasText: "Поиск А " + mark })).toBeVisible()
  await expect(page.locator(".card", { hasText: "Поиск Б " + mark })).toHaveCount(0)
})

test("рельса ведёт в общий список, группа — в проект", async ({ page }) => {
  const mark = "рельс" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Рельса " + mark } })).json()
  await api.post(`/api/projects/${project.id}/secrets`, { data: { title: "Рельсовый " + mark } })

  await login(page)
  await page.getByRole("link", { name: "Секреты", exact: true }).click()
  await expect(page).toHaveURL(/\/secrets$/)

  const group = page.locator(".card", { hasText: "Рельса " + mark })
  await group.locator(".group-head a", { hasText: "Рельса " + mark }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/secrets$`))
})

test("пустой общий список объясняет, куда добавлять", async ({ page }) => {
  await login(page)
  await page.goto("/secrets")
  // Поиск без совпадений честно показывает пустое состояние с подсказкой.
  await page.getByPlaceholder("Название").fill("ничеготакого" + Date.now() + "нет")
  await page.getByRole("button", { name: "Показать" }).click()
  await expect(page.locator(".empty")).toBeVisible()
  await expect(page.getByText("Здесь собираются секреты всех проектов")).toBeVisible()
})

test("генерация поверх заданного секрета подтверждается и откатывается одной кнопкой", async ({ page }) => {
  const mark = "gen" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Генерация " + mark } })).json()
  const secret = await (
    await api.post(`/api/projects/${project.id}/secrets`, {
      data: { title: "Учётка " + mark, username: "user-" + mark, secret: "old-secret-value" },
    })
  ).json()

  await login(page)
  await page.goto(`/projects/${project.id}/secrets/${secret.id}`)
  const secretInput = page.locator('input[autocomplete="new-password"]')

  // Кнопка «Сгенерировать» больше не затирает пароль молча: сначала вопрос.
  let dialogMessage = ""
  page.once("dialog", (dialog) => {
    dialogMessage = dialog.message()
    dialog.accept()
  })
  await page.getByRole("button", { name: "Сгенерировать", exact: true }).click()
  expect(dialogMessage).toContain("Заменить текущий секрет")
  await expect(secretInput).not.toHaveValue("")

  await page.getByRole("button", { name: "Сохранить", exact: true }).click()
  await expect(page.locator(".toast.success")).toContainText("Сохранено: пароль")

  // Прежний пароль не потерян: откат прямо из тоста, без похода в историю.
  await page.getByRole("button", { name: "Отменить" }).click()
  await expect(page.locator(".toast.success")).toContainText("Возвращены прежние значения")

  await page.getByRole("button", { name: "Показать", exact: true }).click()
  await expect(secretInput).toHaveValue("old-secret-value")
  // Два снимка: до генерации и до отката — «Вернуть» работает в обе стороны.
  await expect(page.locator(".status-row")).toHaveCount(2)
})

test("отказ от генерации оставляет текущий секрет нетронутым", async ({ page }) => {
  const mark = "no" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Отказ " + mark } })).json()
  const secret = await (
    await api.post(`/api/projects/${project.id}/secrets`, {
      data: { title: "Учётка " + mark, secret: "kept-secret-value" },
    })
  ).json()

  await login(page)
  await page.goto(`/projects/${project.id}/secrets/${secret.id}`)
  const secretInput = page.locator('input[autocomplete="new-password"]')

  page.once("dialog", (dialog) => dialog.dismiss())
  await page.getByRole("button", { name: "Сгенерировать", exact: true }).click()
  await expect(secretInput).toHaveValue("")
  await expect(page.getByText("Секрет задан и скрыт.")).toBeVisible()

  // Сохранение без правки секретного поля — история не растёт, отменять нечего.
  await page.getByRole("button", { name: "Сохранить", exact: true }).click()
  await expect(page.locator(".toast.success")).toContainText("Сохранено")
  await expect(page.getByRole("button", { name: "Отменить" })).toHaveCount(0)
})

test("история хранит прежние значения: возврат и копирование", async ({ page }) => {
  const mark = "rev" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Версии " + mark } })).json()
  const secret = await (
    await api.post(`/api/projects/${project.id}/secrets`, {
      data: { title: "Учётка " + mark, username: "user-" + mark, secret: "first-pass" },
    })
  ).json()
  await api.patch(`/api/projects/${project.id}/secrets/${secret.id}`, {
    data: { secret: "second-pass", username: "other-" + mark },
  })

  await login(page)
  await page.goto(`/projects/${project.id}/secrets/${secret.id}`)

  // Один снимок, в нём отмечено что менялось; значения не светятся.
  const row = page.locator(".status-row")
  await expect(row).toHaveCount(1)
  await expect(row).toContainText("изменялись: пароль, логин")
  await expect(page.getByText("first-pass")).toHaveCount(0)

  let dialogMessage = ""
  page.once("dialog", (dialog) => {
    dialogMessage = dialog.message()
    dialog.accept()
  })
  await row.getByRole("button", { name: "Вернуть" }).click()
  expect(dialogMessage).toContain("Вернуть прежние значения")
  await expect(page.locator(".toast.success")).toContainText("Возвращены прежние значения")

  await page.getByRole("button", { name: "Показать", exact: true }).click()
  await expect(page.locator('input[autocomplete="new-password"]')).toHaveValue("first-pass")
  await expect(page.getByLabel("Логин")).toHaveValue("user-" + mark)

  // Прежний пароль из снимка — в буфер, с автоочисткой через 30 секунд.
  // Разрешения на буфер нужны headless-браузеру, иначе writeText отклоняется.
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
  await row.first().getByRole("button", { name: "Скопировать" }).click()
  await expect(page.getByText("Скопировано. Буфер очистится")).toBeVisible()
})
