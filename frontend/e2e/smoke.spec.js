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
  // Девять разделов, включая доску и RDP.
  await expect(tabs.locator("a")).toHaveCount(9)
  await expect(tabs.locator("a", { hasText: "Доска" })).toHaveClass(/router-link-active/)
  // Переход в соседний раздел без участия рельсы.
  await tabs.locator("a", { hasText: "Документы" }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/documents$`))
  await expect(tabs.locator("a", { hasText: "Документы" })).toHaveClass(/router-link-active/)
  // «Доска» — индекс-маршрут: раньше vue-router подсвечивал её
  // (router-link-active) на любом дочернем разделе — вместе с текущей
  // вкладкой. Теперь горит только один таб.
  await expect(tabs.locator("a", { hasText: "Доска" })).not.toHaveClass(/router-link-active/)
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
  // Поле поиска занимает всю ширину контейнера (регрессия: input[type=search]
  // не попадал в базовые стили полей и оставался узким, ~20 символов).
  // Шапка дозагружает заголовок — раскладка ширин дышит, поэтому опрашиваем,
  // а не мерим один раз.
  await expect
    .poll(async () => {
      const fieldBox = await page.locator(".topbar-search input").boundingBox()
      const wrapBox = await page.locator(".topbar-search").boundingBox()
      return wrapBox.width - fieldBox.width
    })
    .toBeLessThan(2)
  await page.getByPlaceholder("Поиск: задачи, письма, заметки…", { exact: false }).fill(word)
  const group = page.locator(".search-group", { hasText: "Задачи" })
  const hit = group.locator(".search-item-title", { hasText: `Задача ${word}` })
  await expect(hit).toBeVisible()
  await hit.click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/tasks/\\d+`))
  // Страница задачи открывается с доски — вкладка «Доска» остаётся подсвеченной.
  await expect(page.locator(".project-tabs a", { hasText: "Доска" })).toHaveClass(/router-link-active/)
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

test("помодоро на «Сегодня»: старт показывает чип в шапке", async ({ page }) => {
  await login(page)
  await expect(page.getByRole("heading", { name: "Помодоро" })).toBeVisible()
  await page.getByRole("button", { name: "Старт", exact: true }).click()
  // Чип в шапке — живой индикатор; клик возвращает на «Сегодня».
  const chip = page.locator(".pomo-chip")
  await expect(chip).toBeVisible()
  await expect(chip).toContainText(/помодоро/)
  await page.getByRole("button", { name: "Стоп", exact: true }).click()
  await expect(page.locator(".pomo-chip")).toHaveCount(0)
})

test("помодоро: задача для фокуса выбирается поиском", async ({ page }) => {
  const api = await apiLogin()
  const stamp = Date.now()
  const project = await (await api.post("/api/projects", { data: { name: "Пикер " + stamp } })).json()
  await api.post(`/api/projects/${project.id}/tasks`, { data: { title: "Задача уникум" + stamp } })

  await login(page)
  // Пикер вместо селекта: печатаем — выпадают открытые задачи всех проектов.
  await page.getByPlaceholder("Задача для фокуса: поиск…").fill("уникум" + stamp)
  const drop = page.locator(".task-picker-drop")
  await expect(drop).toBeVisible()
  const item = drop.locator(".task-picker-item", { hasText: "Задача уникум" + stamp })
  await expect(item).toBeVisible()
  await item.click()
  // Выбранная задача — чипом рядом со «Старт»; время после фокуса уйдёт ей.
  await expect(page.locator(".pomo-task-chip")).toContainText("Задача уникум" + stamp)
  await page.getByRole("button", { name: "Старт", exact: true }).click()
  await expect(page.locator(".pomo-task-chip", { hasText: "Задача уникум" + stamp })).toBeHidden()
  await expect(page.getByText(/запишется в «Время»/)).toBeVisible()
  await page.getByRole("button", { name: "Стоп", exact: true }).click()
})
