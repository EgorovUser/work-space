import { reactive } from "vue"
import { api } from "../api.js"

// Помодоро (патч N): один таймер на всё приложение. Состояние живёт в
// модуле, а не в компоненте — переход между экранами не сбрасывает
// отсчёт. Гонки закрыты флагом running: один интервал на процесс.

const SETTINGS_KEY = "ws.pomodoro.settings"

const DEFAULTS = {
  workMinutes: 25,
  breakMinutes: 5,
  autoBreak: true,
  sound: true,
}

function loadSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}")
    return {
      workMinutes: clampMinutes(raw.workMinutes, DEFAULTS.workMinutes, 1, 120),
      breakMinutes: clampMinutes(raw.breakMinutes, DEFAULTS.breakMinutes, 1, 60),
      autoBreak: typeof raw.autoBreak === "boolean" ? raw.autoBreak : DEFAULTS.autoBreak,
      sound: typeof raw.sound === "boolean" ? raw.sound : DEFAULTS.sound,
    }
  } catch {
    return { ...DEFAULTS }
  }
}

function clampMinutes(value, fallback, min, max) {
  const num = Number(value)
  if (!Number.isFinite(num)) return fallback
  return Math.min(max, Math.max(min, Math.round(num)))
}

const state = reactive({
  phase: "idle", // idle | work | break
  running: false,
  remaining: 0,
  task: null, // { id, title, project_id }
  startedAt: null, // ISO момента старта рабочей фазы
  sessions: 0, // завершённых помодоро за жизнь страницы
  settings: loadSettings(),
})

let timer = null
let originalTitle = null

function persistSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(state.settings))
  } catch {
    /* приватный режим — настройки не переживут перезагрузку */
  }
}

function updateSettings(patch) {
  state.settings = {
    ...state.settings,
    ...patch,
    workMinutes: clampMinutes(patch.workMinutes ?? state.settings.workMinutes, state.settings.workMinutes, 1, 120),
    breakMinutes: clampMinutes(patch.breakMinutes ?? state.settings.breakMinutes, state.settings.breakMinutes, 1, 60),
    autoBreak: typeof patch.autoBreak === "boolean" ? patch.autoBreak : state.settings.autoBreak,
    sound: typeof patch.sound === "boolean" ? patch.sound : state.settings.sound,
  }
  persistSettings()
}

function beep() {
  if (!state.settings.sound) return
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    for (let index = 0; index < 3; index += 1) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = "sine"
      osc.frequency.value = 880 - index * 80
      gain.gain.value = 0.08
      osc.connect(gain).connect(ctx.destination)
      const at = ctx.currentTime + index * 0.28
      osc.start(at)
      osc.stop(at + 0.16)
    }
  } catch {
    /* нет звука — не страшно */
  }
}

function applyTitle() {
  if (typeof document === "undefined") return // юнит-тесты без DOM
  if (state.running) {
    if (originalTitle === null) originalTitle = document.title
    document.title = label() + " · " + originalTitle
  } else if (originalTitle !== null) {
    document.title = originalTitle
    originalTitle = null
  }
}

async function saveWorkSession() {
  if (!state.task || !state.task.project_id || !state.startedAt) return
  const endedAt = new Date().toISOString()
  try {
    await api("/api/projects/" + state.task.project_id + "/time/entries", {
      method: "POST",
      body: {
        task_id: state.task.id || null,
        note: "Помодоро: " + (state.task.title || "без названия"),
        started_at: state.startedAt,
        ended_at: endedAt,
      },
    })
  } catch {
    // Учёт времени — желательный, но не критичный итог фокуса: таймер
    // продолжает жить, ошибка не роняет интерфейс.
  }
}

function startPhase(phase) {
  const minutes = phase === "work" ? state.settings.workMinutes : state.settings.breakMinutes
  state.phase = phase
  state.remaining = Math.round(minutes * 60)
  state.running = true
  if (phase === "work") {
    state.startedAt = new Date().toISOString()
  }
  clearInterval(timer)
  timer = setInterval(tick, 1000)
  applyTitle()
}

function tick() {
  if (!state.running) return
  state.remaining -= 1
  if (state.remaining > 0) {
    applyTitle()
    return
  }
  // Фаза закончилась.
  clearInterval(timer)
  timer = null
  if (state.phase === "work") {
    state.sessions += 1
    beep()
    saveWorkSession()
    if (state.settings.autoBreak) {
      startPhase("break")
      return
    }
  } else {
    beep()
  }
  stop(false)
}

function start(task) {
  if (state.running) return
  state.task = task || null
  startPhase("work")
}

function stop(resetTask = true) {
  clearInterval(timer)
  timer = null
  state.running = false
  state.phase = "idle"
  state.remaining = 0
  if (resetTask) {
    state.task = null
    state.startedAt = null
  } else {
    state.startedAt = null
  }
  applyTitle()
}

function skipBreak() {
  if (state.phase !== "break") return
  stop(false)
}

function label() {
  const total = Math.max(0, state.remaining)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  const clock = minutes + ":" + String(seconds).padStart(2, "0")
  const mark = state.phase === "break" ? "перерыв" : "помодоро"
  return clock + " " + mark
}

export function usePomodoro() {
  return {
    state,
    label,
    start,
    stop,
    skipBreak,
    updateSettings,
  }
}
