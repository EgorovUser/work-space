import { expect, request, test } from "@playwright/test"

// Почта master-detail: письмо открывается рядом со списком, без ухода
// со страницы. Сосед-навигация листает письма, Esc закрывает, глубокая
// ссылка сразу открывает читалку, узкий экран отдаёт читалке весь экран.

const CREDS = { username: "e2e", password: "e2e-pass" }

// Кириллица в теме — как в настоящих письмах, encoded-word (RFC 2047):
// сырые 8-битные байты без кодирования парсер читает как latin-1.
function eml({ subject, body, date, messageId }) {
  const encoded = `=?utf-8?B?${Buffer.from(subject).toString("base64")}?=`
  return [
    "From: =?utf-8?B?" + Buffer.from("Начальник").toString("base64") + "?= <boss@corp.example>",
    "To: e2e <e2e@corp.example>",
    `Subject: ${encoded}`,
    `Date: ${date}`,
    `Message-ID: <${messageId}>`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "",
    body,
    "",
  ].join("\r\n")
}

async function apiLogin() {
  const context = await request.newContext({ baseURL: test.info().project.use.baseURL })
  const response = await context.post("/api/auth/login", { data: CREDS })
  expect(response.ok()).toBeTruthy()
  return context
}

async function importLetter(api, projectId, raw) {
  const response = await api.post(`/api/projects/${projectId}/mail/import`, {
    multipart: {
      file: { name: "letter.eml", mimeType: "message/rfc822", buffer: Buffer.from(raw, "utf8") },
    },
  })
  expect(response.status()).toBe(201)
  return (await response.json()).id
}

// В общей базе остались письма из соседних спек — убираем их в архив,
// чтобы счётчики и строки списка были предсказуемыми.
async function cleanMailbox(api) {
  const response = await api.get("/api/mail")
  const data = await response.json()
  for (const item of data.messages || []) {
    if (item.archived) continue
    await api.patch(`/api/mail/messages/${item.id}`, { data: { archived: true } })
  }
}

async function login(page) {
  await page.goto("/login")
  await page.getByLabel("Логин").fill(CREDS.username)
  await page.getByLabel("Пароль").fill(CREDS.password)
  await page.getByRole("button", { name: "Войти" }).click()
  await expect(page.locator(".app")).toBeVisible()
}

test("письмо открывается рядом со списком: сосед-навигация, Esc, счётчик", async ({ page }) => {
  const api = await apiLogin()
  await cleanMailbox(api)
  const project = await (await api.post("/api/projects", { data: { name: "Читалка" } })).json()
  const newer = await importLetter(api, project.id, eml({
    subject: "Смета на ремонт",
    body: "Текст свежего письма: посмотрите смету.",
    date: "Mon, 20 Oct 2026 11:00:00 +0000",
    messageId: "master-detail-1@corp.example",
  }))
  const older = await importLetter(api, project.id, eml({
    subject: "Отчёт за неделю",
    body: "Текст старого письма: отчёт приложен.",
    date: "Mon, 20 Oct 2026 10:00:00 +0000",
    messageId: "master-detail-2@corp.example",
  }))
  await login(page)

  await page.goto("/mail?tab=letters")
  await expect(page.getByText("Непрочитанных: 2")).toBeVisible()
  await expect(page.locator(".mail-row")).toHaveCount(2)

  // Клик по строке — письмо открывается рядом, страница никуда не уходит.
  await page.getByRole("button", { name: /Смета на ремонт/ }).click()
  await expect(page).toHaveURL(new RegExp(`/mail/${newer}$`))
  const detail = page.locator(".mailbox-detail")
  await expect(detail).toBeVisible()
  await expect(detail.locator("h1")).toHaveText("Смета на ремонт")
  await expect(detail.getByText("посмотрите смету")).toBeVisible()
  await expect(page.locator(".mailbox-list")).toBeVisible()

  // Открытие пометило письмо прочитанным — счётчик живой, без F5.
  await expect(page.getByText("Непрочитанных: 1")).toBeVisible({ timeout: 10_000 })

  // Сосед-навигация листает письма, не покидая страницу.
  await detail.getByRole("button", { name: "Старее →" }).click()
  await expect(page).toHaveURL(new RegExp(`/mail/${older}$`))
  await expect(detail.locator("h1")).toHaveText("Отчёт за неделю")
  await expect(page.locator(".mailbox-list")).toBeVisible()

  // Esc возвращает к списку.
  await page.keyboard.press("Escape")
  await expect(page).toHaveURL(/\/mail(\?.*)?$/)
  await expect(page.locator(".mailbox-detail")).toHaveCount(0)
  await expect(page.locator(".mailbox-list")).toBeVisible()
})

test("глубокая ссылка сразу открывает письмо; узкий экран — читалка целиком", async ({ page }) => {
  const api = await apiLogin()
  await cleanMailbox(api)
  const project = await (await api.post("/api/projects", { data: { name: "Глубокая ссылка" } })).json()
  const id = await importLetter(api, project.id, eml({
    subject: "Прямая ссылка",
    body: "Открыто сразу по ссылке.",
    date: "Mon, 20 Oct 2026 12:00:00 +0000",
    messageId: "deep-link-1@corp.example",
  }))
  await login(page)

  await page.goto(`/mail/${id}`)
  await expect(page.locator(".mailbox-detail h1")).toHaveText("Прямая ссылка")
  await expect(page.locator(".mailbox-list")).toBeVisible()

  // Телефон: список уступает место читалке, «К списку» возвращает.
  await page.setViewportSize({ width: 600, height: 800 })
  await expect(page.locator(".mailbox-list")).toBeHidden()
  await expect(page.locator(".mail-back")).toBeVisible()
  await page.getByRole("button", { name: "К списку писем" }).click()
  await expect(page.locator(".mailbox-list")).toBeVisible()
  await expect(page.locator(".mailbox-detail")).toHaveCount(0)
})

test("без подключённых ящиков окно почты открывается на «Письма»", async ({ page }) => {
  const api = await apiLogin()
  await cleanMailbox(api)
  await login(page)

  // Раньше пустой список ящиков перебрасывал на вкладку «Ящик» (патч AI):
  // базовое окно всегда начинается с писем, настройка подключения —
  // осознанный клик по соседней вкладке.
  await page.goto("/mail")
  const lettersTab = page.getByRole("tab", { name: "Письма" })
  await expect(lettersTab).toHaveClass(/active/, { timeout: 10_000 })
  await expect(page.getByRole("tab", { name: "Ящик" })).not.toHaveClass(/active/)
  await expect(page.locator(".mailbox-list")).toBeVisible()
  // URL не тащит за собой служебный ?tab= — чистая ссылка на почту.
  await expect(page).toHaveURL(/\/mail$/)
})

test("вложение письма сохраняется в документы одной кнопкой", async ({ page }) => {
  const mark = "maildoc" + Date.now()
  const api = await apiLogin()
  await cleanMailbox(api)
  const project = await (await api.post("/api/projects", { data: { name: "Документы из почты " + mark } })).json()

  // Письмо с вложением: текстовая часть + файл с base64-содержимым.
  const boundary = "mixed-" + mark
  const payload = Buffer.from("Отчёт: строка один\nстрока два\n" + mark, "utf8")
  const subject = Buffer.from("Счёт за октябрь " + mark, "utf8").toString("base64")
  const raw = [
    "From: =?utf-8?B?" + Buffer.from("Бухгалтерия").toString("base64") + "?= <billing@corp.example>",
    "To: e2e <e2e@corp.example>",
    "Subject: =?utf-8?B?" + subject + "?=",
    "Date: Mon, 19 Oct 2026 10:00:00 +0000",
    `Message-ID: <${mark}@corp.example>`,
    "MIME-Version: 1.0",
    `Content-Type: multipart/mixed; boundary="${boundary}"`,
    "",
    `--${boundary}`,
    "Content-Type: text/plain; charset=utf-8",
    "",
    "Тело письма со счётом.",
    "",
    `--${boundary}`,
    'Content-Type: text/plain; name="invoice.txt"',
    'Content-Disposition: attachment; filename="invoice.txt"',
    "Content-Transfer-Encoding: base64",
    "",
    payload.toString("base64"),
    "",
    `--${boundary}--`,
    "",
  ].join("\r\n")
  const id = await importLetter(api, project.id, raw)

  await login(page)
  await page.goto("/mail/" + id)
  await expect(page.locator(".mail-reader h1")).toHaveText("Счёт за октябрь " + mark)
  await expect(page.getByText("invoice.txt")).toBeVisible()
  await page.getByRole("button", { name: "→ В документы" }).click()
  // Тост укорачивает длинные названия — точный титул проверит API ниже.
  await expect(page.getByText(/Документ создан/)).toBeVisible()

  const documents = await (await api.get(`/api/projects/${project.id}/documents`)).json()
  // Название документа — имя файла без расширения (как при обычной загрузке).
  const found = documents.items.find((item) => item.title === "invoice")
  expect(found).toBeTruthy()
})
