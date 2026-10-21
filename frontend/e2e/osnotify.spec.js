import { expect, request, test } from "@playwright/test"

// Системные уведомления (патч AO): события из вкладки «Уведомления»
// дублируются тостами операционной системы — Web Notifications API,
// разрешение спрашивает карточка на вкладке «Куда писать». Браузерный
// показ подменяем журналом (по образцу focus.spec.js из AM): проверяем
// факт, содержимое и один-единственный показ — тост берёт на себя
// вкладка-лидер (Web Lock), дубли страхует tag ws-<id>.

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

test("уведомление о новой задаче приходит системным тостом — ровно один", async ({ page }) => {
  // Хвост аутбокса от предыдущих сценариев (badges создаёт сотню
  // секретов) дренится партиями по 20 раз в 5 с — даём событию доехать
  // с запасом: expect.poll заканчивается сразу по факту, запас не тормозит.
  test.setTimeout(90_000)
  const marker = "OS-тост " + Date.now()
  await page.addInitScript(() => {
    const notes = []
    window.__notes = notes
    class FakeNotification {
      constructor(title, options) {
        notes.push({ title, tag: options && options.tag })
      }
      close() {}
    }
    FakeNotification.permission = "granted"
    FakeNotification.requestPermission = () => Promise.resolve("granted")
    window.Notification = FakeNotification
  })

  const api = await apiLogin()
  // Канал os включаем в матрице пользователя: события задач должны
  // прилетать системными тостами (по умолчанию канал выключен).
  const put = await api.put("/api/settings", {
    data: {
      module: "notifications",
      key: "matrix",
      scope: "user",
      value: { "task.created": { browser: true, os: true, telegram: false, email: false } },
    },
  })
  expect(put.ok()).toBeTruthy()

  const project = await (
    await api.post("/api/projects", { data: { name: "OS-проверка " + Date.now() } })
  ).json()
  await login(page)

  // Задача создаётся мимо вкладки (API) → outbox (фоновый поток) →
  // notifications.new по SSE → вкладка-лидер показывает тост Windows.
  await api.post(`/api/projects/${project.id}/tasks`, { data: { title: marker } })

  // page.evaluate не переносит замыкания: маркер передаём аргументом.
  await expect
    .poll(
      () => page.evaluate((m) => window.__notes.some((note) => note.title.includes(m)), marker),
      {
        message: "ждём системный тост о новой задаче",
        timeout: 60_000,
      }
    )
    .toBe(true)

  // Ровно один показ: сколько бы вкладок ни слушало канал, тост берёт
  // на себя единственный лидер; от дублей страхует и tag ws-<id>.
  const notes = await page.evaluate(
    (m) => window.__notes.filter((note) => note.title.includes(m)),
    marker
  )
  expect(notes.length).toBe(1)
  expect(notes[0].tag).toMatch(/^ws-\d+$/)
})
