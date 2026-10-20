import { readFileSync } from "node:fs"
import { expect, request, test } from "@playwright/test"

// RDP-подключения: таб в проекте, создание, скачивание .rdp и индикатор
// сборки в рельсе. Данные готовим через API — спек проверяет экран.

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

test("таб RDP открывает раздел проекта", async ({ page }) => {
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "RDP таб " + Date.now() } })).json()

  await login(page)
  await page.goto("/projects/" + project.id)
  await page.getByRole("link", { name: "RDP" }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/rdp$`))
  await expect(page.getByRole("heading", { name: "RDP-подключения" })).toBeVisible()
  await expect(page.getByText("Подключений пока нет")).toBeVisible()
})

test("подключение создаётся и скачивается .rdp", async ({ page }) => {
  const mark = "rdp" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "RDP " + mark } })).json()

  await login(page)
  await page.goto("/projects/" + project.id + "/rdp")
  // Форма живёт на вкладке «Новый» — открываем её до заполнения.
  await page.getByRole("tab", { name: "Новый" }).click()
  await page.getByLabel("Название").fill("Сервер отчётов " + mark)
  await page.getByLabel("Адрес сервера").fill("files.corp.local")
  await page.getByLabel("Порт").fill("3390")
  await page.getByLabel("Логин").fill("admin")
  await page.getByLabel("Домен").fill("CORP")
  await page.getByRole("button", { name: "Добавить" }).click()

  const row = page.locator(".status-row", { hasText: "Сервер отчётов " + mark })
  await expect(row).toBeVisible()
  await expect(row.locator(".mono-inline", { hasText: "files.corp.local:3390" })).toBeVisible()

  // Кнопка меню подписана символом «⋯», панель телепортируется в body.
  await row.locator(".menu-btn").click()
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Скачать .rdp" }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/\.rdp$/)
  const body = readFileSync(await download.path(), "utf8")
  expect(body).toContain("full address:s:files.corp.local:3390")
  expect(body).toContain("username:s:admin")
  expect(body).toContain("domain:s:CORP")
  expect(body).toContain("prompt for credentials:i:1")
  expect(body.toLowerCase()).not.toContain("password")
})

test("общий поиск находит подключение по адресу", async ({ page }) => {
  const mark = "поиск" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Поиск RDP " + mark } })).json()
  await api.post(`/api/projects/${project.id}/rdp`, {
    data: { name: "Шлюз " + mark, host: "10.77.70.7", username: "ops" },
  })

  await login(page)
  await page.getByLabel("Поиск по всему workspace").fill("10.77.70.7")
  const group = page.locator(".search-group", { hasText: "RDP" })
  await expect(group).toBeVisible()
  await expect(group.locator(".search-item", { hasText: "Шлюз " + mark })).toBeVisible()
  await group.locator(".search-item", { hasText: "Шлюз " + mark }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/rdp$`))
})

test("рельса показывает сборку патча", async ({ page }) => {
  await login(page)
  // Сборка приходит из /healthz живого бэкенда: нет надписи — оболочка
  // устарела; есть — ровно эта версия и крутится.
  const build = page.locator(".rail-build")
  await expect(build).toBeVisible()
  await expect(build).toContainText(/сборка \S+/)
  const context = await request.newContext({ baseURL: test.info().project.use.baseURL })
  const response = await context.get("/healthz")
  expect(response.ok()).toBeTruthy()
  expect((await response.json()).build).toBeTruthy()
})
