import { ref } from "vue"
import { api } from "../api"
import { useEvents } from "./useEvents"

// Числа для бейджей (патч U): один клиент на /api/counters из патча T.
//
// Источники, от быстрого к запасному:
// - SSE-канал: событие state несёт глобальные числа — применяем их сразу;
// - навигация: router.afterEach дёргает refresh() — после перехода по
//   разделам бейджи сверяются, сервер отдаёт из кеша (дёшево);
// - опрос раз в минуту, пока открыта страница: страхует от пропущенного.
//
// Проектные числа привязываются к текущему проекту (bindProject): смена
// проекта сбрасывает их, поздний ответ старого проекта не перезатрёт новый.
// Мутации интерфейса сбрасывают серверный кеш сами (патч T), поэтому
// навигация после действия всегда видит свежие числа.

const GLOBAL_KEYS = ["mail_unread", "notifications_unread", "trash_total", "secrets_total"]

const globalCounts = ref(null)
const projectCounts = ref(null)
let boundProjectId = null
let pollTimer = null
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
    applyGlobal(data)
    if (projectId != null && projectId === boundProjectId && data && typeof data.project === "object") {
      projectCounts.value = data.project
    }
  } catch {
    // Бейджи не критичны: промахнулись — попробуем на следующем обновлении.
  }
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
    if (type === "state") applyGlobal(payload)
    // Письма менялись — проектный бейдж «Почта» тоже живой: подтягиваем.
    if (type === "mail.changed" || type === "mail.sync") refresh()
  })
}

function start() {
  bindEvents()
  stopPolling()
  // Опрос — страховка от пропущенных событий; сервер отдаёт из кеша,
  // поэтому редкий интервал ничего не стоит.
  pollTimer = setInterval(refresh, 20 * 1000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function stop() {
  stopPolling()
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
