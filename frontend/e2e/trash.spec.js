import { expect, request, test } from "@playwright/test"

// Корзина (патч N): мягко удалённое видно на /trash, восстановление
// возвращает запись в модуль, «Удалить навсегда» вычищает окончательно.

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

test("задача из корзины восстанавливается на доску", async ({ page }) => {
  const mark = "trash" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Корзина " + mark } })).json()
  const task = await (
    await api.post(`/api/projects/${project.id}/tasks`, { data: { title: "Задача в корзину " + mark } })
  ).json()
  await api.delete(`/api/projects/${project.id}/tasks/${task.id}`)

  await login(page)
  await page.goto("/trash")
  const group = page.locator(".card", { hasText: "Задачи" })
  const row = group.locator(".status-row", { hasText: "Задача в корзину " + mark })
  await expect(row).toBeVisible()
  // Проект и момент удаления — рядом с названием.
  await expect(row.getByText(project.name)).toBeVisible()

  await row.getByRole("button", { name: "Восстановить" }).click()
  await expect(page.getByText("Восстановлено: Задача в корзину " + mark)).toBeVisible()

  const board = await (await api.get(`/api/projects/${project.id}/tasks`)).json()
  expect(board.items.some((item) => item.id === task.id)).toBeTruthy()
})

test("удалить навсегда вычищает запись без возврата", async ({ page }) => {
  const mark = "purge" + Date.now()
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "Корзина навсегда " + mark } })).json()
  const task = await (
    await api.post(`/api/projects/${project.id}/tasks`, { data: { title: "На вечную " + mark } })
  ).json()
  await api.delete(`/api/projects/${project.id}/tasks/${task.id}`)

  await login(page)
  await page.goto("/trash")
  const row = page.locator(".status-row", { hasText: "На вечную " + mark })
  await expect(row).toBeVisible()
  page.once("dialog", (dialog) => dialog.accept())
  await row.getByRole("button", { name: "Удалить навсегда" }).click()
  await expect(page.getByText("Удалено навсегда")).toBeVisible()
  await expect(page.locator(".status-row", { hasText: "На вечную " + mark })).toHaveCount(0)

  // И через API записи больше нет — даже из корзины.
  const response = await api.post(`/api/trash/tasks/${task.id}/restore`)
  expect(response.status()).toBe(404)
})

test("корзина в рельсе доступна с любого экрана", async ({ page }) => {
  await login(page)
  await page.goto("/projects")
  await page.getByRole("link", { name: "Корзина", exact: true }).click()
  await expect(page).toHaveURL(/\/trash$/)
  await expect(page.getByRole("heading", { name: "Корзина", exact: true })).toBeVisible()
})
