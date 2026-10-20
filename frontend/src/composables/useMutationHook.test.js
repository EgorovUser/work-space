import test from "node:test"
import assert from "node:assert/strict"

// Хук мутаций api() (патч AC): после успешной не-GET записи подписчик
// (useCounters → отложенный bump) получает сигнал. Логика без сети —
// fetch подменяем. GET и /api/auth/* не дёргают подписчика.

const fakeResponse = (ok, status, body) =>
  Promise.resolve({
    ok,
    status,
    text: async () => JSON.stringify(body || {}),
  })

test("успешный не-GET дергает подписчика мутации один раз", async () => {
  const { api, setMutationHandler } = await freshApi()
  let calls = 0
  setMutationHandler(() => {
    calls += 1
  })
  globalThis.fetch = async () => fakeResponse(true, 200, { ok: true })
  await api("/api/projects/1/notes", { method: "POST", body: { body: "x" } })
  assert.equal(calls, 1)
})

test("GET не дергает подписчика", async () => {
  const { api, setMutationHandler } = await freshApi()
  let calls = 0
  setMutationHandler(() => {
    calls += 1
  })
  globalThis.fetch = async () => fakeResponse(true, 200, [])
  await api("/api/counters")
  assert.equal(calls, 0)
})

test("логин и логаут не считаются мутациями данных", async () => {
  const { api, setMutationHandler } = await freshApi()
  let calls = 0
  setMutationHandler(() => {
    calls += 1
  })
  globalThis.fetch = async () => fakeResponse(true, 200, { ok: true })
  await api("/api/auth/login", { method: "POST", body: {} })
  await api("/api/auth/logout", { method: "POST" })
  assert.equal(calls, 0)
})

test("провалившийся запрос не дергает подписчика", async () => {
  const { api, setMutationHandler } = await freshApi()
  let calls = 0
  setMutationHandler(() => {
    calls += 1
  })
  globalThis.fetch = async () => fakeResponse(false, 400, { detail: "no" })
  await assert.rejects(() => api("/api/projects/1/notes", { method: "POST", body: {} }))
  assert.equal(calls, 0)
})

// api.js — модуль с внутренним состоянием (обработчики в замыкании):
// каждый тест берёт свежую копию через кеш-банстер.
let counter = 0
async function freshApi() {
  counter += 1
  return import(`../api.js?test=${counter}`)
}
