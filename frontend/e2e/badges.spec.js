import { expect, request, test } from "@playwright/test"

// Бейджи-количества (патч U): в полоске разделов проекта 0–9 числом,
// дальше «9+»; в рельсе — 0–99, дальше «99+». Числа приходят из хаба
// счётчиков (патч T): навигация и мутации их обновляют, SSE оживляет
// глобальные. Ноль показывается приглушённым — «здесь пусто».
// Патч AH: обычные счётчики — нейтральный чип (спокойный фон, без
// класса alert), красный кружок — только у непрочитанных уведомлений.

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

test("рельса показывает количества: ноль приглушён, после удаления — число", async ({ page }) => {
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Бейджи рельсы " + Date.now() } })
  ).json()

  await login(page)
  // Свежая база: корзина пуста, бейдж «0» приглушён (класс zero).
  const trashBadge = page.locator(".rail-nav a", { hasText: "Корзина" }).locator(".rail-badge")
  await expect(trashBadge).toHaveText("0")
  await expect(trashBadge).toHaveClass(/zero/)

  // Мягко удаляем секрет: рельса должна отреагировать без перезагрузки —
  // мутация будит SSE, счётчик корзины прибавляется.
  const secret = await (
    await api.post(`/api/projects/${project.id}/secrets`, {
      data: { title: "В корзину", secret: "x" },
    })
  ).json()
  await api.delete(`/api/projects/${project.id}/secrets/${secret.id}`)
  await expect(trashBadge).toHaveText("1", { timeout: 10_000 })
  await expect(trashBadge).not.toHaveClass(/zero/)
  // Обычный счётчик — спокойный: без alert и с нейтральным фоном чипа
  // (rgba-подложка рельсы), а не красный кружок.
  await expect(trashBadge).not.toHaveClass(/alert/)
  await expect(trashBadge).toHaveCSS("background-color", "rgba(255, 255, 255, 0.08)")
})

test("табы проекта показывают количества разделов", async ({ page }) => {
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Бейджи табов " + Date.now() } })
  ).json()
  // Два секрета, одна заметка и одно RDP-подключение.
  for (const title of ["Альфа", "Бета"]) {
    await api.post(`/api/projects/${project.id}/secrets`, { data: { title, secret: "x" } })
  }
  await api.post(`/api/projects/${project.id}/notes`, { data: { body: "Заметка для бейджа" } })
  await api.post(`/api/projects/${project.id}/rdp`, {
    data: { name: "Сервер", host: "10.10.10.10", port: 3389, username: "admin" },
  })

  await login(page)
  await page.goto(`/projects/${project.id}`)
  const tabs = page.locator(".project-tabs")
  const badge = (label) =>
    tabs.locator("a", { hasText: label }).locator(".tab-badge")

  await expect(badge("Секреты")).toHaveText("2")
  await expect(badge("Заметки")).toHaveText("1")
  await expect(badge("RDP")).toHaveText("1")
  // Пустые разделы честно показывают ноль — приглушённой цифрой без чипа.
  await expect(badge("Документы")).toHaveText("0")
  await expect(badge("Документы")).toHaveClass(/zero/)
  await expect(badge("Документы")).toHaveCSS("background-color", "rgba(0, 0, 0, 0)")
  // Число — спокойный нейтральный чип, не красный кружок.
  await expect(badge("Секреты")).not.toHaveClass(/alert/)
  await expect(badge("Секреты")).toHaveCSS("background-color", "rgb(225, 228, 232)")
  // Разделы без счётчика (доска, время, настройки) бейджа не несут.
  await expect(tabs.locator("a", { hasText: "Доска" }).locator(".tab-badge")).toHaveCount(0)
})

test("красным кружком горят только непрочитанные уведомления", async ({ page }) => {
  const api = await apiLogin()
  // Любое действие (создание проекта) через фоновый outbox приносит
  // непрочитанное уведомление — до 5 секунд, поэтому ждём с запасом.
  await api.post("/api/projects", { data: { name: "Уведомления " + Date.now() } })

  await login(page)
  const notifBadge = page.locator(".rail-nav a", { hasText: "Уведомления" }).locator(".rail-badge")
  await expect(notifBadge).not.toHaveClass(/zero/, { timeout: 15_000 })
  await expect(notifBadge).toHaveClass(/alert/)
  await expect(notifBadge).toHaveCSS("background-color", "rgb(196, 71, 58)")
  // Соседние счётчики остались спокойными, даже если числа не нулевые.
  const secretsBadge = page.locator(".rail-nav a", { hasText: "Секреты" }).locator(".rail-badge")
  await expect(secretsBadge).not.toHaveClass(/alert/)
})

test("табы капятся на 9+, рельса на 99+", async ({ page }) => {
  const api = await apiLogin()
  const project = await (
    await api.post("/api/projects", { data: { name: "Много секретов " + Date.now() } })
  ).json()
  // 105 секретов: в табе проекта видно «9+», в рельсе — «99+» (глобально
  // их не меньше, другие тесты могут только добавить).
  const created = []
  for (let i = 0; i < 105; i++) {
    const response = await api.post(`/api/projects/${project.id}/secrets`, {
      data: { title: "Секрет " + i, secret: "x" },
    })
    created.push((await response.json()).id)
  }

  try {
    await login(page)
    await page.goto(`/projects/${project.id}`)
    const tabs = page.locator(".project-tabs")
    await expect(tabs.locator("a", { hasText: "Секреты" }).locator(".tab-badge")).toHaveText("9+")

    const railSecrets = page.locator(".rail-nav a", { hasText: "Секреты" }).locator(".rail-badge")
    await expect(railSecrets).toHaveText("99+")
    await expect(railSecrets).not.toHaveClass(/zero/)
  } finally {
    // Убираем за собой: 105 секретов в общем списке мешают следующим
    // сценариям (группа их проекта вытесняет чужие группы из выдачи).
    for (const id of created) {
      await api.delete(`/api/projects/${project.id}/secrets/${id}`)
    }
  }
})
