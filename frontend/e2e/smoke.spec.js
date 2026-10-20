import { expect, request, test } from "@playwright/test"

// Дымовые сценарии: цепочка «вход → навигация → данные → поиск → тема».
// Хрупких деталей (позиции, анимации) не трогаем — только пользовательские
// пути, которые обязаны работать в любой сборке.

const CREDS = { username: "e2e", password: "e2e-pass" }

async function login(page) {
  await page.goto("/login")
  await page.getByLabel("Логин").fill(CREDS.username)
  await page.getByLabel("Пароль").fill(CREDS.password)
  await page.getByRole("button", { name: "Войти" }).click()
  // Ждём, пока вход завершится и сессия закрепится: click резолвится до
  // ответа сервера, и последующий goto может оборвать запрос логина.
  await expect(page.locator(".app")).toBeVisible()
}

async function apiLogin() {
  const context = await request.newContext({ baseURL: test.info().project.use.baseURL })
  const response = await context.post("/api/auth/login", { data: CREDS })
  expect(response.ok()).toBeTruthy()
  return context
}

test("логин ведёт на экран «Сегодня»", async ({ page }) => {
  await page.goto("/")
  await expect(page).toHaveURL(/\/login/)
  await login(page)
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole("heading", { name: "Сегодня", exact: true })).toBeVisible()
})

test("проект создаётся и открывается доска задач", async ({ page }) => {
  await login(page)
  // Список проектов — отдельный раздел: добираемся через рельсу.
  // exact: иначе «Все проекты →» из хаба тоже попадает под имя.
  await page.getByRole("link", { name: "Проекты", exact: true }).click()
  await expect(page).toHaveURL(/\/projects$/)
  const name = "E2E проект " + Date.now()
  await page.getByPlaceholder("Новый проект").fill(name)
  await page.getByRole("button", { name: "Создать" }).click()
  await expect(page).toHaveURL(/\/projects\/\d+/)
  await expect(page.getByText(name).first()).toBeVisible()
})

test("разделы проекта переключаются горизонтальными табами", async ({ page }) => {
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Табы " + Date.now() } })
  ).json()

  await login(page)
  await page.goto(`/projects/${project.id}`)
  const tabs = page.locator(".project-tabs")
  await expect(tabs).toBeVisible()
  // Восемь разделов, включая доску.
  await expect(tabs.locator("a")).toHaveCount(8)
  await expect(tabs.locator("a", { hasText: "Доска" })).toHaveClass(/router-link-active/)
  // Переход в соседний раздел без участия рельсы.
  await tabs.locator("a", { hasText: "Документы" }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/documents$`))
  await expect(tabs.locator("a", { hasText: "Документы" })).toHaveClass(/router-link-active/)
})

test("глобальный поиск находит задачу и ведёт на неё", async ({ page }) => {
  const word = "поисковоеслово" + Date.now()
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Проект для поиска " + word } })
  ).json()
  await api.post(`/api/projects/${project.id}/tasks`, {
    data: { title: `Задача ${word}` },
  })

  await login(page)
  await page.getByPlaceholder("Поиск: задачи, письма, заметки…", { exact: false }).fill(word)
  const group = page.locator(".search-group", { hasText: "Задачи" })
  const hit = group.locator(".search-item-title", { hasText: `Задача ${word}` })
  await expect(hit).toBeVisible()
  await hit.click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/tasks/\\d+`))
})

test("тёмная тема переключается и переживает перезагрузку", async ({ page }) => {
  await login(page)
  const html = page.locator("html")
  await expect(html).toHaveAttribute("data-theme", /light|dark/)

  await page.getByRole("button", { name: /Тема:/ }).click()
  await page.getByRole("button", { name: /Тема:/ }).click()
  await expect(html).toHaveAttribute("data-theme", "dark")

  await page.reload()
  await expect(html).toHaveAttribute("data-theme", "dark")
})

test("новая задача на доске получает дедлайн по умолчанию", async ({ page }) => {
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Дедлайн " + Date.now() } })
  ).json()

  await login(page)
  await page.goto(`/projects/${project.id}`)
  // Подсказка в композере честно предупреждает про будущий срок.
  const composer = page.locator(".composer input").first()
  await expect(composer).toHaveAttribute("placeholder", "Новая задача (срок +7 дн.)")
  await composer.fill("Задача со сроком")
  await composer.press("Enter")
  const card = page.locator(".task-card", { hasText: "Задача со сроком" })
  await expect(card).toBeVisible()
  // Срок виден прямо на карточке — дата примерно через неделю.
  await expect(card.locator(".task-meta")).toHaveText(/\d{4}-\d{2}-\d{2}/)
})

test("неизвестный маршрут не даёт белого экрана", async ({ page }) => {
  await login(page)
  await page.goto("/такого/маршрута/нет")
  // Catch-all уводит на главный экран — оболочка приложения на месте.
  await expect(page).toHaveURL(/\/$/)
  await expect(page.locator(".app")).toBeVisible()
})

test("healthz жив", async ({ request }) => {
  const response = await request.get("/healthz")
  expect(response.status()).toBe(200)
  const payload = await response.json()
  expect(payload.status).toMatch(/ok|degraded/)
})
