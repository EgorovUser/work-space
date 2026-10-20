import { expect, request, test } from "@playwright/test"

// Живые события (SSE /api/events): письмо попадает в базу мимо вкладки —
// и вкладка сама показывает счётчик и письмо, без F5.

const CREDS = { username: "e2e", password: "e2e-pass" }

// Кириллица в теме — как в настоящих письмах, encoded-word (RFC 2047):
// сырые 8-битные байты без кодирования парсер читает как latin-1.
const SUBJECT = "Живые события — проверка"
const encodedSubject = `=?utf-8?B?${Buffer.from(SUBJECT).toString("base64")}?=`

const EML = [
  "From: =?utf-8?B?" + Buffer.from("Начальник").toString("base64") + "?= <boss@corp.example>",
  "To: e2e <e2e@corp.example>",
  `Subject: ${encodedSubject}`,
  "Date: Mon, 20 Oct 2026 10:00:00 +0000",
  "Message-ID: <live-events-1@corp.example>",
  "MIME-Version: 1.0",
  "Content-Type: text/plain; charset=utf-8",
  "",
  "Письмо приехало само, без обновления страницы.",
  "",
].join("\r\n")

async function apiLogin() {
  const context = await request.newContext({ baseURL: test.info().project.use.baseURL })
  const response = await context.post("/api/auth/login", { data: CREDS })
  expect(response.ok()).toBeTruthy()
  return context
}

test("новое письмо само всплывает в открытой вкладке: бейдж и список", async ({ page }) => {
  await page.goto("/login")
  await page.getByLabel("Логин").fill(CREDS.username)
  await page.getByLabel("Пароль").fill(CREDS.password)
  await page.getByRole("button", { name: "Войти" }).click()
  await expect(page.locator(".app")).toBeVisible()

  // Бейджа пока нет — непрочитанных нет.
  await expect(page.locator(".rail-badge")).toHaveCount(0)

  // Письмо импортируется в проект мимо вкладки (как забор с сервера).
  const api = await apiLogin()
  const project = await (await api.post("/api/projects", { data: { name: "SSE проект" } })).json()
  const imported = await api.post(`/api/projects/${project.id}/mail/import`, {
    multipart: {
      file: {
        name: "letter.eml",
        mimeType: "message/rfc822",
        buffer: Buffer.from(EML, "utf-8"),
      },
    },
  })
  expect(imported.status()).toBe(201)

  // Живые события дёргают счётчик в шапке — без перезагрузки страницы.
  await expect(page.locator(".rail-badge")).toBeVisible({ timeout: 15_000 })
  await expect(page.locator(".rail-badge")).toHaveText("1")

  // И список писем обновляется сам. Вкладку задаём явно: без ящиков
  // страница сама уводит на настройки «Ящик IMAP».
  await page.goto("/mail?tab=letters")
  await expect(page.getByText("Живые события — проверка")).toBeVisible()
  await expect(page.getByText("Непрочитанных: 1")).toBeVisible()
})
