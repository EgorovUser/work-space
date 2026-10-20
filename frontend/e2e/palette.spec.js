import { expect, request, test } from "@playwright/test"

// Командная палитра (патч N): Ctrl+K, команды разделов, стрелки, фильтры
// по типам и недавние запросы. Данные готовим через API.

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

test("Ctrl+K открывает палитру с командами, Esc закрывает", async ({ page }) => {
  await login(page)
  await page.keyboard.press("Control+k")
  const drop = page.locator(".search-drop")
  await expect(drop).toBeVisible()
  const commands = drop.locator(".search-group", { hasText: "Разделы" })
  await expect(commands).toBeVisible()
  // Команды разделов ведут куда надо: «Корзина» — новый раздел патча N.
  await commands.locator(".search-item", { hasText: "Корзина" }).click()
  await expect(page).toHaveURL(/\/trash$/)

  await page.keyboard.press("Control+k")
  await expect(page.locator(".search-drop")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(page.locator(".search-drop")).toHaveCount(0)
})

test("стрелки и Enter ведут на первый результат", async ({ page }) => {
  const mark = "палитра" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Палитра " + mark } })).json()
  await api.post(`/api/projects/${project.id}/tasks`, {
    data: { title: "Задача для палитры " + mark, deadline: "2026-10-01T10:00:00", priority: "high" },
  })

  await login(page)
  await page.keyboard.press("Control+k")
  await page.getByLabel("Поиск по всему workspace").fill(mark)
  const group = page.locator(".search-group", { hasText: "Задачи" })
  await expect(group.locator(".search-item", { hasText: "Задача для палитры " + mark })).toBeVisible()

  // Курсор стоит на первом пункте: Enter без стрелок открывает его.
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/tasks/\\d+$`))
})

test("фильтр по типу оставляет только выбранный раздел", async ({ page }) => {
  const mark = "фильтр" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Фильтр " + mark } })).json()
  await api.post(`/api/projects/${project.id}/tasks`, { data: { title: "Задача-фильтр " + mark } })
  await api.post(`/api/projects/${project.id}/documents`, {
    multipart: {
      title: "Документ-фильтр " + mark,
      file: { name: "filter.txt", mimeType: "text/plain", buffer: Buffer.from("содержимое", "utf8") },
    },
  })

  await login(page)
  await page.getByLabel("Поиск по всему workspace").fill(mark)
  // Оба раздела находятся…
  await expect(page.locator(".search-group", { hasText: "Задачи" })).toBeVisible()
  await expect(page.locator(".search-group", { hasText: "Документы" })).toBeVisible()

  // …чип «Документы» оставляет только документы.
  await page.locator(".search-filters").getByRole("button", { name: "Документы" }).click()
  await expect(page.locator(".search-group", { hasText: "Задачи" })).toHaveCount(0)
  await expect(page.locator(".search-group", { hasText: "Документы" })).toBeVisible()

  // Фильтр запоминается и применяется к новому запросу.
  await page.getByLabel("Поиск по всему workspace").fill("фильтр " + mark)
  await expect(page.locator(".search-group", { hasText: "Документы" })).toBeVisible()
  await expect(page.locator(".search-group", { hasText: "Задачи" })).toHaveCount(0)
})

test("недавние запросы всплывают при пустой строке", async ({ page }) => {
  const mark = "недавние" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Недавние " + mark } })).json()
  await api.post(`/api/projects/${project.id}/tasks`, { data: { title: "Недавняя задача " + mark } })

  await login(page)
  await page.keyboard.press("Control+k")
  await page.getByLabel("Поиск по всему workspace").fill(mark)
  const group = page.locator(".search-group", { hasText: "Задачи" })
  await expect(group.locator(".search-item", { hasText: "Недавняя задача " + mark })).toBeVisible()
  await group.locator(".search-item", { hasText: "Недавняя задача " + mark }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/tasks/\\d+$`))

  // Палитра закрылась; открываем заново — запрос уже в недавних.
  await page.keyboard.press("Control+k")
  const recents = page.locator(".search-recents")
  await expect(recents).toBeVisible()
  await expect(recents.locator(".search-chip", { hasText: mark })).toBeVisible()
  await page.keyboard.press("Escape")
})
