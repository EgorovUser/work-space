import test from "node:test"
import assert from "node:assert/strict"
import { usePomodoro } from "./usePomodoro.js"

// Помодоро (патч N): состояние живёт в модуле — один таймер на приложение.
// Здесь проверяем контракт без реального хода времени: настройки
// обрезаются в границы, старт/стоп управляют фазами, подпись таймера
// читаемая. Тик с сетевым запросом не гоняем — это e2e-территория.

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
