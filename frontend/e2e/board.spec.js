import { expect, request, test } from "@playwright/test"

// Патч R: карточка задачи на доске переработана — чеклист подзадач
// и списание часов живут прямо на карточке; блок «Списать время»
// переехал на главную страницу задачи; изменения подтверждаются тостами.

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

async function makeProject(api, label) {
  const response = await api.post("/api/projects", { data: { name: label + " " + Date.now() } })
  expect(response.status()).toBe(201)
  return response.json()
}

async function makeTask(api, projectId, title) {
  const response = await api.post(`/api/projects/${projectId}/tasks`, { data: { title } })
  expect(response.status()).toBe(201)
  return response.json()
}

async function addCheck(api, projectId, taskId, title) {
  const response = await api.post(`/api/projects/${projectId}/tasks/${taskId}/checklist`, {
    data: { title },
  })
  expect(response.status()).toBe(201)
  return response.json()
}

test("чеклист подзадач отмечается прямо с доски", async ({ page }) => {
  const api = await apiLogin()
  const project = await makeProject(api, "Доска-чек")
  const task = await makeTask(api, project.id, "Карточка с пунктами")
  await addCheck(api, project.id, task.id, "Первый пункт")
  await addCheck(api, project.id, task.id, "Второй пункт")

  await login(page)
  await page.goto(`/projects/${project.id}`)
  const card = page.locator(".task-card", { hasText: "Карточка с пунктами" })
  await expect(card).toBeVisible()
  // Оба пункта видны на карточке, счётчик честно показывает 0/2.
  await expect(card.locator(".tc-check", { hasText: "Первый пункт" })).toBeVisible()
  await expect(card.locator(".tc-check", { hasText: "Второй пункт" })).toBeVisible()
  await expect(card.locator(".tc-count")).toHaveText("0/2")

  // Отмечаем первый пункт не заходя в задачу.
  await card.locator(".tc-check", { hasText: "Первый пункт" }).locator("input").check()
  await expect(card.locator(".tc-check", { hasText: "Первый пункт" })).toHaveClass(/done/)
  await expect(card.locator(".tc-count")).toHaveText("1/2")

  // Сервер тоже видел отметку — после перезагрузки состояние живо.
  await page.reload()
  const reloaded = page.locator(".task-card", { hasText: "Карточка с пунктами" })
  await expect(reloaded.locator(".tc-check", { hasText: "Первый пункт" })).toHaveClass(/done/)
})

test("часы списываются с карточки и копятся в бейдже", async ({ page }) => {
  const api = await apiLogin()
  const project = await makeProject(api, "Доска-часы")
  const task = await makeTask(api, project.id, "Списываем с карточки")

  await login(page)
  await page.goto(`/projects/${project.id}`)
  const card = page.locator(".task-card", { hasText: "Списываем с карточки" })
  await expect(card.locator(".tc-time")).toBeVisible()

  // 1.5 часа → 90 минут: поле ввода в часах, кнопка рядом.
  await card.locator(".tc-hours").fill("1.5")
  await card.locator(".tc-log").click()
  await expect(page.locator(".toast.success")).toContainText("Списано 1,5 ч")
  await expect(card.locator(".tc-spent")).toContainText("1,5 ч")

  // Enter работает как кнопка: ещё 0.5 ч, бейдж складывает — 2 ч.
  await card.locator(".tc-hours").fill("0.5")
  await card.locator(".tc-hours").press("Enter")
  await expect(card.locator(".tc-spent")).toContainText("2 ч")

  // Минуты дошли до бэкенда и осели в ответе доски.
  const board = await (await api.get(`/api/projects/${project.id}/tasks`)).json()
  const mine = board.items.find((item) => item.id === task.id)
  expect(mine.spent_minutes).toBe(120)
})

test("списание времени живёт на главной странице задачи", async ({ page }) => {
  const api = await apiLogin()
  const project = await makeProject(api, "Страница-часы")
  const task = await makeTask(api, project.id, "Задача со временем")

  await login(page)
  await page.goto(`/projects/${project.id}/tasks/${task.id}`)
  // Отдельной вкладки «Время» больше нет — блок на главной «О задаче».
  await expect(page.locator(".tab", { hasText: "Время" })).toHaveCount(0)
  await expect(page.getByRole("heading", { name: "Списать время" })).toBeVisible()

  await page.getByLabel("Часы", { exact: true }).fill("2")
  await page.getByRole("button", { name: "Списать", exact: true }).click()
  await expect(page.locator(".toast.success")).toContainText("Списано 2 ч")
  // Запись появилась списком, итог поднят в шапку блока.
  await expect(page.locator(".tp-time .inbox-row")).toHaveCount(1)
  await expect(page.locator(".tp-time .inbox-row")).toContainText("2 ч")
  await expect(page.locator(".tp-time-head")).toContainText("Всего: 2 ч")
})

test("секрет добавляется с тостом-подтверждением", async ({ page }) => {
  const api = await apiLogin()
  const project = await makeProject(api, "Тост-секрет")

  await login(page)
  await page.goto(`/projects/${project.id}/secrets`)
  await page.getByRole("tab", { name: "Новый" }).click()
  const name = "Токен " + Date.now()
  await page.getByLabel("Название", { exact: true }).fill(name)
  await page.getByLabel("Секрет", { exact: true }).fill("значение")
  await page.getByRole("button", { name: "Добавить" }).click()

  // Раньше форма молча сбрасывалась; теперь тост объясняет, что случилось.
  await expect(page.locator(".toast.success")).toContainText(`Секрет «${name}» добавлен`)
  await expect(page.getByLabel("Название", { exact: true })).toHaveValue("")

  // Секрет и правда появился в списке.
  await page.getByRole("tab", { name: "Список" }).click()
  await expect(page.locator(".status-row", { hasText: name })).toBeVisible()
})
