import { expect, request, test } from "@playwright/test"

// Календарь и повторяющиеся задачи: вид «Календарь» у доски, переход по чипу
// в задачу, продолжение серии при закрытии.

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

test("календарь показывает задачу со сроком и ведёт на неё", async ({ page }) => {
  const word = "календарноеслово" + Date.now()
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Календарь " + word } })
  ).json()
  const task = await (
    await api.post(`/api/projects/${project.id}/tasks`, {
      data: { title: `Дедлайн ${word}`, deadline: new Date().toISOString() },
    })
  ).json()
  expect(task.deadline).toBeTruthy()

  await login(page)
  await page.goto(`/projects/${project.id}?view=calendar`)
  await expect(page.locator(".cal-grid")).toBeVisible()
  await expect(page.getByRole("button", { name: "Календарь" })).toHaveClass(/active/)
  // Чип лежит в ячейке «сегодня» — месяц правильный без кликов.
  const chip = page.locator(".cal-cell.today .cal-chip", { hasText: `Дедлайн ${word}` })
  await expect(chip).toBeVisible()

  await chip.click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/tasks/\\d+`))
  await expect(page.locator(".title-input")).toHaveValue(`Дедлайн ${word}`)
})

test("закрытие повторяющейся задачи создаёт следующее вхождение", async ({ page }) => {
  const word = "повторслово" + Date.now()
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Повторы " + word } })
  ).json()
  const statuses = (await (await api.get(`/api/projects/${project.id}/task-statuses`)).json()).items
  const closed = statuses.find((status) => status.is_closed)
  expect(closed).toBeTruthy()
  await api.post(`/api/projects/${project.id}/tasks`, {
    data: { title: `Полив ${word}`, deadline: new Date().toISOString(), repeat_kind: "weekly" },
  })
  const items = (await (await api.get(`/api/projects/${project.id}/tasks`)).json()).items
  expect(items.filter((item) => item.title === `Полив ${word}`).length).toBe(1)

  // Закрываем первое вхождение — должно появиться следующее.
  await api.patch(`/api/projects/${project.id}/tasks/${items[0].id}`, { data: { status_id: closed.id } })
  const after = (await (await api.get(`/api/projects/${project.id}/tasks`)).json()).items
  const series = after.filter((item) => item.title === `Полив ${word}`)
  expect(series.length).toBe(2)

  await login(page)
  await page.goto(`/projects/${project.id}`)
  // На доске обе карточки, у обеих — знак повтора.
  const cards = page.locator(".task-card", { hasText: `Полив ${word}` })
  await expect(cards).toHaveCount(2)
  await expect(cards.locator(".repeat-mark")).toHaveCount(2)
})
