import test from "node:test"
import assert from "node:assert/strict"
import { neighbors } from "./mailNav.js"

const LIST = [
  { id: 30, title: "новее" },
  { id: 20, title: "середина" },
  { id: 10, title: "старее" },
]

test("mailNav: в середине списка есть оба соседа, prev — новее", () => {
  const { prev, next } = neighbors(LIST, 20)
  assert.deepEqual(prev, { id: 30, title: "новее" })
  assert.deepEqual(next, { id: 10, title: "старее" })
})

test("mailNav: на краях списка сосед только с одной стороны", () => {
  assert.deepEqual(neighbors(LIST, 30), { prev: null, next: { id: 20, title: "середина" } })
  assert.deepEqual(neighbors(LIST, 10), { prev: { id: 20, title: "середина" }, next: null })
})

test("mailNav: письма нет в списке — соседей нет (deep-link мимо списка)", () => {
  assert.deepEqual(neighbors(LIST, 999), { prev: null, next: null })
})

test("mailNav: id из строки маршрута и мусорный ввод не ломают расчёт", () => {
  assert.equal(neighbors(LIST, "20").prev.id, 30)
  assert.deepEqual(neighbors(LIST, "abc"), { prev: null, next: null })
  assert.deepEqual(neighbors(LIST, null), { prev: null, next: null })
  assert.deepEqual(neighbors(null, 20), { prev: null, next: null })
})

test("mailNav: пустой и одноэлементный списки", () => {
  assert.deepEqual(neighbors([], 20), { prev: null, next: null })
  assert.deepEqual(neighbors([{ id: 5 }], 5), { prev: null, next: null })
})
