import { test } from "node:test"
import assert from "node:assert/strict"

import { railCount, tabCount } from "./countFormat.js"

// Числа бейджей (патч U): табы проекта капом 9+, боковое меню — 99+,
// ноль показывается, «не знаем» — пусто.
test("tabCount: 0–9 числом, дальше 9+", () => {
  assert.equal(tabCount(0), "0")
  assert.equal(tabCount(1), "1")
  assert.equal(tabCount(9), "9")
  assert.equal(tabCount(10), "9+")
  assert.equal(tabCount(127), "9+")
})

test("tabCount: неизвестное значение — без бейджа", () => {
  assert.equal(tabCount(null), "")
  assert.equal(tabCount(undefined), "")
  assert.equal(tabCount("3"), "")
  assert.equal(tabCount(-1), "")
})

test("railCount: 0–99 числом, дальше 99+", () => {
  assert.equal(railCount(0), "0")
  assert.equal(railCount(42), "42")
  assert.equal(railCount(99), "99")
  assert.equal(railCount(100), "99+")
  assert.equal(railCount(1000), "99+")
})

test("railCount: неизвестное значение — без бейджа", () => {
  assert.equal(railCount(null), "")
  assert.equal(railCount(undefined), "")
  assert.equal(railCount(-5), "")
})
