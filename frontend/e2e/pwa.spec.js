import { expect, test } from "@playwright/test"

// PWA-обвязка: манифест и иконки раздаются с правильными заголовками,
// сервис-воркер активен и спасает офлайн — оболочка приложения достаётся
// из кеша даже без сети.

test("манифест, иконки и сервис-воркер раздаются", async ({ page }) => {
  await page.goto("/login")

  const manifest = await page.request.get("/manifest.webmanifest")
  expect(manifest.ok()).toBeTruthy()
  expect(manifest.headers()["content-type"]).toContain("manifest+json")
  const body = await manifest.json()
  expect(body.icons.length).toBeGreaterThanOrEqual(3)
  for (const icon of body.icons) {
    const response = await page.request.get(icon.src)
    expect(response.ok(), icon.src).toBeTruthy()
  }

  const sw = await page.request.get("/sw.js")
  expect(sw.ok()).toBeTruthy()
  expect(sw.headers()["content-type"]).toContain("javascript")
  expect(sw.headers()["cache-control"]).toContain("no-cache")

  // Регистрация из index.html: ждём активацию воркера в этом контексте.
  const active = await page.evaluate(() => navigator.serviceWorker.ready.then((reg) => Boolean(reg.active)))
  expect(active).toBe(true)
})

test("офлайн: оболочка приложения достаётся из кеша сервис-воркера", async ({ page }) => {
  await page.goto("/login")
  await page.evaluate(() => navigator.serviceWorker.ready)
  // Прогрев: пока сеть есть, ходим по приложению уже через сервис-воркер —
  // чанк экрана входа оседает в кеш (как у реального пользователя PWA).
  await page.goto("/")
  await expect(page.locator(".login-card")).toBeVisible()

  await page.context().setOffline(true)
  // Полная навигация без сети: SW отдаёт оболочку и ассеты из кеша, SPA
  // грузится и рисует экран входа — вместо браузерной ошибки «нет сети».
  await page.goto("/")
  await expect(page.locator(".login-card")).toBeVisible({ timeout: 10_000 })
  await page.context().setOffline(false)
})

test("на телефоне основная навигация уезжает вниз", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/login")
  await page.getByLabel("Логин").fill("e2e")
  await page.getByLabel("Пароль").fill("e2e-pass")
  await page.getByRole("button", { name: "Войти" }).click()
  await expect(page.locator(".app")).toBeVisible()

  const nav = page.locator(".bottom-nav")
  await expect(nav).toBeVisible()
  // Панель прижата к низу экрана (в пределах высоты вьюпорта).
  const box = await nav.boundingBox()
  expect(box.y + box.height).toBeGreaterThan(800)
  // Пять адресов, у каждого — подпись и иконка.
  await expect(nav.locator(".bottom-link")).toHaveCount(5)
  await expect(nav.locator(".bottom-label")).toHaveCount(5)
  // Вкладка «Проекты» активна.
  await expect(nav.locator(".bottom-link").first()).toHaveClass(/active/)

  // Переход по нижней навигации ведёт в почту.
  await nav.locator(".bottom-link", { hasText: "Почта" }).click()
  await expect(page).toHaveURL(/\/mail$/)
})
