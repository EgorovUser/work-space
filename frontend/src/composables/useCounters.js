import { ref } from "vue"
import { api, setMutationHandler } from "../api"
import { useEvents } from "./useEvents"

// Числа для бейджей (патч U; свежесть — патч AC): один клиент на
// /api/counters. Источники, от быстрых к запасным:
//
// 1. SSE-канал: событие state несёт глобальные числа — применяем сразу,
//    в том числе из другой вкладки; письма менялись — проектный бейдж
//    «Почта» подтягивается отдельным refresh;
// 2. собственные изменения: api() после успешной не-GET записи дёргает
//    отложенное обновление (пачка правок = один запрос). Серверный кеш
//    мутации сбрасывают сами (touch_project, publish-обёртки), поэтому
//    здесь обычное чтение;
// 3. навигация: router.afterEach — после перехода по разделам бейджи
//    сверяются;
// 4. опрос раз в минуту, пока вкладка видима, и refresh при возврате
//    на вкладку, если данные протухли (окно свежести 25 с);
// 5. смена проекта (bindProject) сбрасывает проектные числа, поздний
//    ответ старого проекта не перезатрёт новый.
//
// Опрос дёшев: сервер отвечает из кеша с TTL, а «невидимая» вкладка
// вообще не спрашивает.

const GLOBAL_KEYS = ["mail_unread", "notifications_unread", "trash_total", "secrets_total"]

const POLL_MS = 60_000
const FRESH_MS = 25_000

const globalCounts = ref(null)
const projectCounts = ref(null)
let boundProjectId = null
let pollTimer = null
let bumpTimer = null
let loadedAt = 0
let eventsBound = false

function applyGlobal(data) {
  if (!data || typeof data !== "object") return
  const next = { ...(globalCounts.value || {}) }
  for (const key of GLOBAL_KEYS) {
    if (typeof data[key] === "number") next[key] = data[key]
  }
  globalCounts.value = next
}

async function load() {
  const projectId = boundProjectId
  const query = projectId != null ? "?project_id=" + projectId : ""
  try {
    const data = await api("/api/counters" + query)
    loadedAt = Date.now()
    applyGlobal(data)
    if (projectId != null && projectId === boundProjectId && data && typeof data.project === "object") {
      projectCounts.value = data.project
    }
  } catch {
    // Бейджи не критичны: промахнулись — попробуем на следующем обновлении.
  }
}

// Мутации идут пачками (сохранил форму → тост → перешёл): отложенный
// bump сворачивает их в один запрос, когда правки закончились.
function bump() {
  if (bumpTimer) return
  bumpTimer = setTimeout(() => {
    bumpTimer = null
    load()
  }, 800)
}

function onVisibility() {
  if (document.visibilityState === "visible" && Date.now() - loadedAt > FRESH_MS) load()
}

function bindProject(projectId) {
  boundProjectId = projectId
  projectCounts.value = null
  load()
}

function refresh() {
  load()
}

function bindEvents() {
  if (eventsBound) return
  eventsBound = true
  const events = useEvents()
  events.on((type, payload) => {
    if (type === "state") {
      applyGlobal(payload)
      loadedAt = Date.now()
    }
    // Письма менялись — проектный бейдж «Почта» тоже живой: подтягиваем.
    if (type === "mail.changed" || type === "mail.sync") refresh()
  })
  setMutationHandler(bump)
}

function start() {
  bindEvents()
  stopPolling()
  // Опрос — страховка от пропущенных событий; сервер отдаёт из кеша,
  // а спрятанная вкладка не спрашивает вовсе.
  pollTimer = setInterval(() => {
    if (document.visibilityState === "visible") load()
  }, POLL_MS)
  document.addEventListener("visibilitychange", onVisibility)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function stop() {
  stopPolling()
  document.removeEventListener("visibilitychange", onVisibility)
}

function reset() {
  stopPolling()
  globalCounts.value = null
  projectCounts.value = null
  boundProjectId = null
}

export function useCounters() {
  bindEvents()
  return { globalCounts, projectCounts, bindProject, refresh, start, stop, reset }
}
