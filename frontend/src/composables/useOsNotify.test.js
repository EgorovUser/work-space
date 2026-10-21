import test from "node:test"
import assert from "node:assert/strict"
import { _setSourceFactory, useEvents } from "./useEvents.js"
import { _setLeader, _setOsSink, useOsNotify } from "./useOsNotify.js"

// Системные уведомления (патч AO): показ решают четыре условия — канал os
// у события, местный тумблер, разрешение браузера и лидерство вкладки.
// Здесь гоняем их по отдельности: браузерный показ подменён приёмником,
// лидер назначается руками (Web Locks в node нет).

class FakeNotification {
  static permission = "granted"
}

function fakeSource() {
  const es = {
    readyState: 0,
    closed: false,
    handlers: {},
    addEventListener(name, fn) {
      this.handlers[name] = fn
    },
    dispatch(name, data) {
      if (this.handlers[name]) this.handlers[name]({ data })
    },
    close() {
      this.closed = true
      this.readyState = 2
    },
  }
  return es
}

function fresh() {
  const shown = []
  _setOsSink((note) => shown.push(note))
  _setLeader(true)
  globalThis.Notification = FakeNotification
  const os = useOsNotify()
  os.applySettings({ enabled: true, onlyHidden: false })
  let source = null
  _setSourceFactory(() => {
    source = fakeSource()
    return source
  })
  useEvents().start()
  os.start()
  return { os, shown, source }
}

function cleanup() {
  useEvents().stop()
  _setSourceFactory(null)
  delete globalThis.document
}

function send(source, payload) {
  source.dispatch("notifications.new", JSON.stringify(payload))
}

test("useOsNotify: событие с флагом os показывается тостом с тегом ws-<id>", () => {
  const { shown, source } = fresh()
  send(source, { id: 5, title: "Час по таймеру", body: "по задаче", link: "/projects/1/tasks/2", os: true })
  assert.equal(shown.length, 1)
  assert.equal(shown[0].title, "Час по таймеру")
  assert.equal(shown[0].body, "по задаче")
  assert.equal(shown[0].tag, "ws-5")
  assert.equal(shown[0].link, "/projects/1/tasks/2")
  cleanup()
})

test("useOsNotify: событие без флага os (канал выключен в матрице) молчит", () => {
  const { shown, source } = fresh()
  send(source, { id: 6, title: "Тихое", body: "", link: "", os: false })
  assert.equal(shown.length, 0)
  cleanup()
})

test("useOsNotify: местный тумблер глушит показ на устройстве", () => {
  const { os, shown, source } = fresh()
  os.applySettings({ enabled: false })
  send(source, { id: 7, title: "Выключено", body: "", link: "", os: true })
  assert.equal(shown.length, 0)
  os.applySettings({ enabled: true })
  send(source, { id: 8, title: "Снова вкручено", body: "", link: "", os: true })
  assert.equal(shown.length, 1)
  cleanup()
})

test("useOsNotify: «только когда вкладка не на экране» — видимая молчит, скрытая показывает", () => {
  const { os, shown, source } = fresh()
  os.applySettings({ onlyHidden: true })
  globalThis.document = { visibilityState: "visible" }
  send(source, { id: 9, title: "Видимая", body: "", link: "", os: true })
  assert.equal(shown.length, 0)
  globalThis.document = { visibilityState: "hidden" }
  send(source, { id: 10, title: "Скрытая", body: "", link: "", os: true })
  assert.equal(shown.length, 1)
  assert.equal(shown[0].title, "Скрытая")
  cleanup()
})

test("useOsNotify: без разрешения браузера показа нет", () => {
  const { shown, source } = fresh()
  FakeNotification.permission = "denied"
  send(source, { id: 11, title: "Запрещено", body: "", link: "", os: true })
  assert.equal(shown.length, 0)
  FakeNotification.permission = "granted"
  cleanup()
})

test("useOsNotify: не-лидер не показывает (тост берёт на себя одна вкладка)", () => {
  const { shown, source } = fresh()
  _setLeader(false)
  send(source, { id: 12, title: "Чужой тост", body: "", link: "", os: true })
  assert.equal(shown.length, 0)
  _setLeader(true)
  cleanup()
})

test("useOsNotify: браузер без Notification API молча живёт", () => {
  const { shown, source } = fresh()
  delete globalThis.Notification
  send(source, { id: 13, title: "Старый браузер", body: "", link: "", os: true })
  assert.equal(shown.length, 0)
  globalThis.Notification = FakeNotification
  cleanup()
})
