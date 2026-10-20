import test from "node:test"
import assert from "node:assert/strict"
import { _setNotificationSink, usePomodoro } from "./usePomodoro.js"

// Помодоро (патч N): состояние живёт в модуле — один таймер на приложение.
// Здесь проверяем контракт без реального хода времени: настройки
// обрезаются в границы, старт/стоп управляют фазами, подпись таймера
// читаемая. Тик с сетевым запросом не гоняем — это e2e-территория.
//
// Патч AM: тексты уведомлений о смене фаз — через приёмник вместо
// браузерных Notification (их в node нет).

function fresh() {
  const pomo = usePomodoro()
  pomo.stop()
  pomo.state.sessions = 0
  return pomo
}

test("usePomodoro: настройки обрезаются в допустимые границы", () => {
  const pomo = fresh()
  pomo.updateSettings({ workMinutes: 999, breakMinutes: 0 })
  assert.equal(pomo.state.settings.workMinutes, 120)
  assert.equal(pomo.state.settings.breakMinutes, 1)
  pomo.updateSettings({ workMinutes: 25, breakMinutes: 5 })
  assert.equal(pomo.state.settings.workMinutes, 25)
  assert.equal(pomo.state.settings.breakMinutes, 5)
})

test("usePomodoro: мусор в настройках не ломает значения", () => {
  const pomo = fresh()
  pomo.updateSettings({ workMinutes: "восемь", autoBreak: "да", sound: "нет" })
  assert.equal(typeof pomo.state.settings.workMinutes, "number")
  assert.equal(typeof pomo.state.settings.autoBreak, "boolean")
  assert.equal(typeof pomo.state.settings.sound, "boolean")
  pomo.updateSettings({ workMinutes: 25, breakMinutes: 5, autoBreak: true, sound: true })
})

test("usePomodoro: старт запускает рабочую фазу, стоп возвращает в idle", () => {
  const pomo = fresh()
  pomo.start({ id: 7, title: "Задача фокуса", project_id: 3 })
  assert.equal(pomo.state.phase, "work")
  assert.equal(pomo.state.running, true)
  assert.equal(pomo.state.task.id, 7)
  assert.ok(pomo.state.remaining > 0)
  assert.match(pomo.label(), /помодоро/)
  pomo.stop()
  assert.equal(pomo.state.phase, "idle")
  assert.equal(pomo.state.running, false)
  assert.equal(pomo.state.remaining, 0)
  assert.equal(pomo.state.task, null)
})

test("usePomodoro: повторный старт при работающем таймере игнорируется", () => {
  const pomo = fresh()
  pomo.start({ id: 1, title: "Первая", project_id: 1 })
  const startedAt = pomo.state.startedAt
  pomo.start({ id: 2, title: "Вторая", project_id: 2 })
  assert.equal(pomo.state.task.id, 1)
  assert.equal(pomo.state.startedAt, startedAt)
  pomo.stop()
})

test("usePomodoro: старт без задачи — просто таймер", () => {
  const pomo = fresh()
  pomo.start(null)
  assert.equal(pomo.state.task, null)
  assert.equal(pomo.state.running, true)
  pomo.stop()
})

// — Уведомления о смене фаз (патч AM) —>

test("уведомления фаз: конец фокуса — «Пора отдохнуть» с задачей", () => {
  const pomo = fresh()
  const seen = []
  _setNotificationSink((text) => seen.push(text))
  try {
    pomo.updateSettings({ notify: true })
    pomo.start({ id: 5, title: "Важное дело", project_id: 1 })
    pomo._sendPhaseNotification("rest")
    assert.equal(seen.length, 1)
    assert.equal(seen[0].title, "Пора отдохнуть")
    assert.match(seen[0].body, /Важное дело/)
    pomo.stop()
  } finally {
    _setNotificationSink(null)
  }
})

test("уведомления фаз: конец отдыха — «Отдых закончился»", () => {
  const pomo = fresh()
  const seen = []
  _setNotificationSink((text) => seen.push(text))
  try {
    pomo.updateSettings({ notify: true })
    pomo.start(null)
    pomo._sendPhaseNotification("back")
    assert.equal(seen.length, 1)
    assert.equal(seen[0].title, "Отдых закончился")
    assert.equal(seen[0].body, "Можно возвращаться к работе")
    pomo.stop()
  } finally {
    _setNotificationSink(null)
  }
})

test("уведомления фаз: выключенная подписка молчит", () => {
  const pomo = fresh()
  const seen = []
  _setNotificationSink((text) => seen.push(text))
  try {
    pomo.updateSettings({ notify: false })
    pomo.start({ id: 9, title: "Тихий фокус", project_id: 2 })
    pomo._sendPhaseNotification("rest")
    assert.equal(seen.length, 0)
    pomo.stop()
    pomo.updateSettings({ notify: true })
  } finally {
    _setNotificationSink(null)
  }
})
