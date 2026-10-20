import test from "node:test"
import assert from "node:assert/strict"
import { _setSourceFactory, useEvents } from "./useEvents.js"

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

function cleanup() {
  const events = useEvents()
  events.stop()
  _setSourceFactory(null)
}

test("useEvents: без EventSource (node, старый браузер) start не бросает и канал не открывает", () => {
  const events = useEvents()
  events.start()
  assert.equal(events.connected.value, false)
  assert.equal(events.mailUnread.value, null)
  cleanup()
})

test("useEvents: state обновляет счётчики, mail.sync доходит подписчикам", () => {
  const created = []
  _setSourceFactory(() => {
    const es = fakeSource()
    created.push(es)
    return es
  })
  const events = useEvents()
  const seen = []
  events.on((type, payload) => seen.push([type, payload]))
  events.start()

  created[0].dispatch("state", JSON.stringify({ mail_unread: 4, notifications_unread: 2 }))
  assert.equal(events.mailUnread.value, 4)
  assert.equal(events.notificationsUnread.value, 2)

  created[0].dispatch("mail.sync", JSON.stringify({ account: "Рабочий", fetched: 3 }))
  assert.deepEqual(seen[1], ["mail.sync", { account: "Рабочий", fetched: 3 }])

  // изменение письма (прочитано/архив/удалено, в т.ч. из другой вкладки)
  created[0].dispatch("mail.changed", "{}")
  assert.deepEqual(seen[2], ["mail.changed", {}])

  // мусорный JSON не роняет канал
  created[0].dispatch("state", "{не json")
  assert.equal(events.mailUnread.value, 4)
  cleanup()
})

test("useEvents: открытие канала поднимает connected, stop закрывает источник", () => {
  const created = []
  _setSourceFactory(() => {
    const es = fakeSource()
    created.push(es)
    return es
  })
  const events = useEvents()
  events.start()
  created[0].onopen()
  assert.equal(events.connected.value, true)

  events.stop()
  assert.equal(created[0].closed, true)
  assert.equal(events.connected.value, false)
  cleanup()
})

test("useEvents: обрыв (CLOSED) планирует переподключение, открытие сбрасывает паузы", () => {
  const created = []
  _setSourceFactory(() => {
    const es = fakeSource()
    created.push(es)
    return es
  })
  const events = useEvents()
  events.start()
  created[0].onopen()

  // Сервер закрыл канал (например, 401 при протухшей сессии) — пауза, потом новая попытка.
  created[0].readyState = 2
  created[0].onerror()
  assert.equal(events.connected.value, false)
  assert.equal(created.length, 1)
  return new Promise((resolve) => {
    setTimeout(() => {
      assert.equal(created.length, 2)
      created[1].onopen()
      assert.equal(events.connected.value, true)
      cleanup()
      resolve()
    }, 3200)
  })
})
