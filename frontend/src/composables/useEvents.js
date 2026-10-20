import { ref } from "vue"

// Живые события: один SSE-канал /api/events на вкладку, сколько бы
// компонентов ни подписалось. Шапка показывает счётчики, «Почта»
// перезагружает список, когда забор писем что-то принёс, и подтягивает
// изменения отдельных писем (прочитано/архив/удалено — в том числе
// из другой вкладки).
//
// Канал — только ускоритель: всё, что он доставляет, доступно и обычными
// запросами. Обрыв связи не ломает интерфейс — просто возвращаемся к опросу.

const connected = ref(false)
const mailUnread = ref(null)
const notificationsUnread = ref(null)

let source = null
let retryTimer = null
let retryStep = 0
const RETRY_DELAYS = [3, 6, 12, 30, 60]
const listeners = new Set()

// Подменяется в тестах; в браузере — настоящий EventSource.
let sourceFactory = null

export function _setSourceFactory(factory) {
  sourceFactory = factory
}

function emit(type, payload) {
  for (const fn of [...listeners]) {
    try {
      fn(type, payload)
    } catch {
      // слушатель не должен ронять канал
    }
  }
}

function applyState(data) {
  if (!data || typeof data !== "object") return
  if (typeof data.mail_unread === "number") mailUnread.value = data.mail_unread
  if (typeof data.notifications_unread === "number") notificationsUnread.value = data.notifications_unread
}

function handleEvent(name, raw) {
  let payload = null
  try {
    payload = raw && raw.data ? JSON.parse(raw.data) : null
  } catch {
    payload = null
  }
  if (name === "state") applyState(payload)
  emit(name, payload)
}

function armRetry() {
  if (retryTimer) return
  const delay = RETRY_DELAYS[Math.min(retryStep, RETRY_DELAYS.length - 1)] * 1000
  retryStep = Math.min(retryStep + 1, RETRY_DELAYS.length - 1)
  retryTimer = setTimeout(() => {
    retryTimer = null
    open()
  }, delay)
}

function closeSource() {
  if (!source) return
  const es = source
  source = null
  es.onopen = null
  es.onerror = null
  es.close()
}

function open() {
  if (source) return
  let es
  try {
    es = sourceFactory ? sourceFactory() : new EventSource("/api/events")
  } catch {
    armRetry()
    return
  }
  source = es
  es.onopen = () => {
    connected.value = true
    retryStep = 0
  }
  es.onerror = () => {
    connected.value = false
    // 0/CONNECTING — браузер переподключает сам; 2/CLOSED — например, выход
    // или выключенные события: переподключаемся сами, с нарастающей паузой.
    if (es.readyState === 2 && source === es) {
      closeSource()
      armRetry()
    }
  }
  for (const name of ["state", "mail.sync", "mail.changed"]) {
    es.addEventListener(name, (raw) => handleEvent(name, raw))
  }
}

function start() {
  // Без EventSource (старый браузер, node) — тихо живём опросом.
  if (typeof EventSource === "undefined" && !sourceFactory) return
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  retryStep = 0
  open()
}

function stop() {
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  retryStep = 0
  closeSource()
  connected.value = false
}

function on(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function useEvents() {
  return { connected, mailUnread, notificationsUnread, start, stop, on }
}
