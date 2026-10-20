import { expect, request, test } from "@playwright/test"

// Один активный фокус (патч AL): в рельсе — строка над именем
// пользователя с часами и кнопкой стоп. Активным может быть что-то одно:
// старт помодоро останавливает серверный таймер, старт таймера гасит
// помодоро.

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

test("таймер виден в рельсе над именем и останавливается оттуда", async ({ page }) => {
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Фокус-рельса " + Date.now() } })).json()
  const task = await (await api.post(`/api/projects/${project.id}/tasks`, { data: { title: "Долгая задача" } })).json()
  await api.post(`/api/projects/${project.id}/time/start`, { data: { task_id: task.id, note: "из другой вкладки" } })

  await login(page)
  await page.goto("/")
  const line = page.locator(".rail-focus.timer")
  await expect(line).toBeVisible()
  // Часы идут, подпись — задача фокуса.
  await expect(line.locator(".rail-focus-clock")).toHaveText(/\d+:\d{2}/)
  await expect(line.locator(".rail-focus-sub")).toContainText("Долгая задача")

  // Стоп из рельсы: строка уходит, сервер больше не видит таймера.
  await line.locator(".rail-focus-stop").click()
  await expect(line).toHaveCount(0)
  const check = await api.get("/api/time/running")
  expect((await check.json()).running).toBeNull()
})

test("старт помодоро останавливает серверный таймер", async ({ page }) => {
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Фокус-помо " + Date.now() } })).json()
  await api.post(`/api/projects/${project.id}/time/start`, { data: { note: "потушится" } })

  await login(page)
  await page.goto("/")
  await expect(page.locator(".rail-focus.timer")).toBeVisible()

  // Старт помодоро: рельса переключается на него, таймер на сервере погашен.
  await page.getByRole("button", { name: "Старт", exact: true }).click()
  await expect(page.locator(".rail-focus.pomo")).toBeVisible()
  await expect(page.locator(".rail-focus.timer")).toHaveCount(0)
  await expect
    .poll(async () => {
      const response = await api.get("/api/time/running")
      return (await response.json()).running
    }, { message: "сервер должен погасить таймер после старта помодоро" })
    .toBeNull()

  // Стоп помодоро возвращает рельсу в покой.
  await page.locator(".rail-focus.pomo .rail-focus-stop").click()
  await expect(page.locator(".rail-focus")).toHaveCount(0)
})

test("старт таймера со страницы «Учёт» останавливает помодоро", async ({ page }) => {
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Фокус-учёт " + Date.now() } })).json()

  await login(page)
  await page.goto("/")
  await page.getByRole("button", { name: "Старт", exact: true }).click()
  await expect(page.locator(".pomo-chip")).toBeVisible()

  // Таймер из вкладки «Учёт» проекта: чип помодоро в шапке гаснет,
  // рельса показывает таймер.
  await page.goto(`/projects/${project.id}/time`)
  await page.getByRole("button", { name: "Старт", exact: true }).click()
  await expect(page.locator(".pomo-chip")).toHaveCount(0)
  await expect(page.locator(".rail-focus.timer")).toBeVisible()
})
