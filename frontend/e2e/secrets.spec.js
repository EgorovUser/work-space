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
