import { computed, ref } from "vue"
import { api } from "../api.js"

// Идущий серверный таймер — общий для всего приложения (патч AL): рельса
// показывает его над именем пользователя, откуда бы он ни был запущен —
// из «Учёта» проекта, со страницы задачи или из другой вкладки.
//
// Источники состояния, от быстрых к запасным:
// 1. явный refresh() после мутаций — «Учёт» и страница задачи зовут его
//    сами сразу после старта/стопа;
// 2. опрос раз в 20 секунд — ловит старт из другой вкладки;
// 3. часовой циферблат локальный: секунды тикают от started_at, сервер
//    не спрашивается.
//
// Единственный активный фокус держат двое: старт помодоро останавливает
// серверный таймер (usePomodoro), старт таймера останавливает помодоро
// (страницы «Учёт» и задачи).

const POLL_MS = 20_000

const running = ref(null)
const now = ref(Date.now())
let pollTimer = null
let clockTimer = null
let started = false
let requestInFlight = false

async function refresh() {
  if (requestInFlight) return
  requestInFlight = true
  try {
    const data = await api("/api/time/running")
    running.value = (data && data.running) || null
  } catch {
    // Рельса не критична: промахнулись — следующий опрос поправит.
  } finally {
    requestInFlight = false
  }
}

async function stop() {
  const previous = running.value
  running.value = null
  try {
    await api("/api/time/stop", { method: "POST" })
  } catch (err) {
    running.value = previous
    throw err
  }
}

// Часы идущего таймера: HH:MM из started_at. Секунды не показываем —
// рельса узкая, а точность до минуты для «сколько уже идёт» достаточна.
const elapsed = computed(() => {
  const row = running.value
  if (!row || !row.started_at) return ""
  now.value
  const seconds = Math.max(0, Math.floor((now.value - new Date(row.started_at).getTime()) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours + ":" + String(minutes).padStart(2, "0")
})

// Подпись контекста: задача, иначе заметка, иначе «без задачи».
const sub = computed(() => {
  const row = running.value
  if (!row) return ""
  return row.task_title || row.note || "Без задачи"
})

function start() {
  if (started) return
  started = true
  refresh()
  pollTimer = setInterval(refresh, POLL_MS)
  clockTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

function stopPolling() {
  clearInterval(pollTimer)
  clearInterval(clockTimer)
  pollTimer = null
  clockTimer = null
  started = false
}

function reset() {
  running.value = null
}

export function useRunningTimer() {
  return { running, elapsed, sub, start, stopPolling, stop, refresh, reset }
}
