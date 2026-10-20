// Сервис-воркер «Рабочего пространства».
//
// Стратегии:
//   - навигация (открытие страниц) — сначала сеть; при обрыве — оболочка
//     из кеша (единственный слот «/», обновляется каждым успешным заходом);
//     если и кеша нет — простая офлайн-страница;
//   - /assets/* — сначала кеш: у файлов Vite хеш в имени, они неизменны;
//   - /api/* и /healthz — всегда мимо кеша: живые данные и SSE-канал
//     не должны застревать в офлайн-копии.
//
// Обновление: VERSION меняется вручную при смене стратегии; activate
// вычищает чужие кеши, skipWaiting + clients.claim забирают управление
// сразу, не дожидаясь закрытия вкладок.

const VERSION = "ws-pwa-v1"
const SHELL = "/"

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      self.skipWaiting()
      const cache = await caches.open(VERSION)
      await precacheShell(cache)
    })()
  )
})

async function precacheShell(cache) {
  let html = ""
  try {
    // cache:"reload" — берём оболочку с сервера, а не из HTTP-кеша.
    const response = await fetch(new Request(SHELL, { cache: "reload" }))
    await cache.put(SHELL, response.clone())
    html = await response.text()
  } catch {
    // Сервер недоступен в момент установки — оболочка попадёт в кеш
    // первым успешным заходом (см. обработчик fetch).
    return
  }
  // Хешированные ассеты из index.html (входной чанк и стили) кладём
  // рядом с оболочкой: приложение оживает офлайн сразу после установки.
  // Чанки маршрутов — лениво: первый онлайн-заход по маршруту оседает
  // в кеше (cacheFirst ниже), и маршрут остаётся доступным офлайн.
  const urls = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((match) => match[1])
  await Promise.all(
    urls.map(async (url) => {
      try {
        await cache.add(new Request(url, { cache: "reload" }))
      } catch {
        // один ассет не скачался — не срываем установку ради него
      }
    })
  )
}

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await self.clients.claim()
      const names = await caches.keys()
      await Promise.all(names.filter((name) => name !== VERSION).map((name) => caches.delete(name)))
    })()
  )
})

const OFFLINE_HTML =
  '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">' +
  "<title>Нет соединения</title>" +
  "<style>body{font-family:system-ui,sans-serif;background:#f3f4f6;color:#1c2127;display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center}" +
  "div{padding:24px;text-align:center}h1{font-size:1.1rem;margin:0 0 8px}p{color:#5d6772;margin:0}</style></head><body>" +
  "<div><h1>Нет соединения с сервером</h1><p>Приложение откроется, когда сервер снова будет доступен.</p></div></body></html>"

self.addEventListener("fetch", (event) => {
  const request = event.request
  if (request.method !== "GET") return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  // Живые данные и канал событий — только сеть.
  if (url.pathname === "/api" || url.pathname.startsWith("/api/") || url.pathname === "/healthz") return

  if (request.mode === "navigate") {
    event.respondWith(handleNavigation(request))
    return
  }
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(cacheFirst(request))
  }
})

async function handleNavigation(request) {
  try {
    const response = await fetch(request)
    if (response.ok) {
      const cache = await caches.open(VERSION)
      // Оболочка одна на все маршруты SPA — обновляем её каждым заходом.
      cache.put(SHELL, response.clone())
    }
    return response
  } catch {
    const cache = await caches.open(VERSION)
    const shell = await cache.match(SHELL)
    if (shell) return shell
    return new Response(OFFLINE_HTML, {
      status: 503,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    })
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(VERSION)
  const cached = await cache.match(request)
  if (cached) return cached
  try {
    const response = await fetch(request)
    if (response.ok) cache.put(request, response.clone())
    return response
  } catch {
    // Нет в кеше и нет сети — честный 503 вместо обрыва запроса.
    return new Response("", { status: 503, statusText: "Offline" })
  }
}
