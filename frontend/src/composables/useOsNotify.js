import { reactive } from "vue"
import { useEvents } from "./useEvents.js"

// Системные уведомления (патч AO): событие «notifications.new» из SSE-канала →
// тост операционной системы (Web Notifications API — в Windows это всплывашки
// в правом нижнем углу). Работает, пока открыта хотя бы одна вкладка или окно
// приложения — в фоне тоже. «Без вкладки» потребовало бы Push API с ключами
// и сервис-воркером — для личного self-hosted приложения это лишний этаж.
//
// Настройки двух уровней:
// - серверный канал «Системные уведомления» в матрице событий (вкладка
//   «Какие события») решает, какие события несут флаг os — общий для
//   всех устройств пользователя;
// - местные тумблеры (localStorage, см. ниже) решают, показывает ли их
//   именно ЭТО устройство: общий выключатель и «только когда вкладка
//   не на экране».
//
// Несколько открытых вкладок слушают один и тот же SSE и получили бы
// столько же тостов. Показывает только «лидер»: владелец Web Lock
// (Chromium/Firefox/Safari 16.4+; замок живёт, пока вкладка жива) либо,
// без Web Locks, вкладка-арендатор метки в localStorage с сердцебиением.
// От дублей страхует и tag «ws-<id>»: ОС схлопывает одинаковые теги.

const SETTINGS_KEY = "ws.os-notify.settings"
const LEASE_KEY = "ws.os-notify.leader"
const LOCK_NAME = "ws-os-notify"
const LEASE_MS = 15_000
const HEARTBEAT_MS = 5_000

const state = reactive({
  enabled: true,
  onlyHidden: false,
  permission: "unsupported", // default | granted | denied | unsupported
})

let bound = false
let leader = false
let heartbeatTimer = null
let tabId = ""

// Тесты подменяют показ приёмником (по образцу _setNotificationSink
// в usePomodoro) и назначают лидера руками.
let osSink = null

export function _setOsSink(fn) {
  osSink = fn
}

export function _setLeader(value) {
  leader = Boolean(value)
}

function loadSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}")
    return {
      enabled: typeof raw.enabled === "boolean" ? raw.enabled : true,
      onlyHidden: typeof raw.onlyHidden === "boolean" ? raw.onlyHidden : false,
    }
  } catch {
    return { enabled: true, onlyHidden: false }
  }
}

function persistSettings() {
  try {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ enabled: state.enabled, onlyHidden: state.onlyHidden })
    )
  } catch {
    /* приватный режим — настройки живут до перезагрузки */
  }
}

function applySettings(patch) {
  if (patch && typeof patch.enabled === "boolean") state.enabled = patch.enabled
  if (patch && typeof patch.onlyHidden === "boolean") state.onlyHidden = patch.onlyHidden
  persistSettings()
}

function refreshPermission() {
  if (typeof Notification === "undefined") {
    state.permission = "unsupported"
    return
  }
  state.permission = Notification.permission
}

async function requestPermission() {
  if (typeof Notification === "undefined") return
  try {
    state.permission = await Notification.requestPermission()
  } catch {
    state.permission = Notification.permission
  }
}

// --- лидер-вкладка -------------------------------------------------------

function readLease() {
  try {
    const raw = JSON.parse(localStorage.getItem(LEASE_KEY) || "null")
    if (raw && typeof raw.id === "string" && Date.now() - raw.ts < LEASE_MS) return raw.id
  } catch {
    /* битая метка — считаем аренду свободной */
  }
  return null
}

function leaseTick() {
  const owner = readLease()
  if (owner === null || owner === tabId) {
    try {
      localStorage.setItem(LEASE_KEY, JSON.stringify({ id: tabId, ts: Date.now() }))
    } catch {
      /* нет localStorage — показываем лучшим усилием */
    }
    leader = true
  } else {
    leader = false
  }
}

function releaseLease() {
  try {
    if (readLease() === tabId) localStorage.removeItem(LEASE_KEY)
  } catch {
    /* ничего не делаем */
  }
}

function acquireLeadership() {
  const locks =
    typeof navigator !== "undefined" && navigator.locks && typeof navigator.locks.request === "function"
      ? navigator.locks
      : null
  if (locks) {
    // Замок либо наш (держим его незавершённым обещанием до закрытия
    // вкладки), либо чей-то — тогда тихо ждём следующего тика: когда
    // лидер закроется, замок освободится сам.
    const attempt = () => {
      if (leader) return
      locks
        .request(LOCK_NAME, { ifAvailable: true }, (lock) => {
          if (!lock) return undefined
          leader = true
          return new Promise(() => {})
        })
        .catch(() => {
          /* API моргнул — попробуем на следующем тике */
        })
    }
    attempt()
    heartbeatTimer = setInterval(attempt, HEARTBEAT_MS)
    return
  }
  leaseTick()
  heartbeatTimer = setInterval(leaseTick, HEARTBEAT_MS)
}

// --- показ ---------------------------------------------------------------

function hidden() {
  return typeof document !== "undefined" && document.visibilityState !== "visible"
}

function onBusEvent(type, payload) {
  if (type !== "notifications.new" || !payload || typeof payload !== "object") return
  if (!state.enabled || !payload.os) return
  if (state.onlyHidden && !hidden()) return
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return
  if (!leader) return
  const title = String(payload.title || "Уведомление")
  const body = String(payload.body || "")
  if (osSink) {
    osSink({ title, body, tag: "ws-" + String(payload.id), link: String(payload.link || "") })
    return
  }
  try {
    const note = new Notification(title, { body, tag: "ws-" + String(payload.id) })
    note.onclick = () => {
      note.close()
      if (typeof window !== "undefined") window.focus()
      // Роутер подтягиваем лениво: он живёт в браузере, а юнит-тесты
      // этого модуля крутятся в node без DOM.
      import("../router.js")
        .then(({ default: routerApp }) => {
          routerApp.push(String(payload.link || "") || "/notifications").catch(() => {})
        })
        .catch(() => {})
    }
  } catch {
    /* браузер отказал — остаются лента, колокольчик и бейдж */
  }
}

function start() {
  if (bound) return
  bound = true
  Object.assign(state, loadSettings())
  refreshPermission()
  useEvents().on(onBusEvent)
  if (typeof window === "undefined") return // юнит-тесты без DOM
  tabId = Math.random().toString(36).slice(2) + "-" + Date.now().toString(36)
  acquireLeadership()
  window.addEventListener("pagehide", releaseLease)
}

export function useOsNotify() {
  return { state, start, refreshPermission, requestPermission, applySettings }
}
