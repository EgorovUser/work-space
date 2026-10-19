import assert from "node:assert/strict"
import test from "node:test"
import { formatSize } from "./formatBytes.js"

test("байты, килобайты и мегабайты форматируются по-человечески", () => {
  assert.equal(formatSize(0), "0 Б")
  assert.equal(formatSize(512), "512 Б")
  assert.equal(formatSize(2048), "2 КБ")
  assert.equal(formatSize(150 * 1024), "150 КБ")
  assert.equal(formatSize(3.5 * 1024 * 1024), "3.5 МБ")
})

test("мусорные значения не ломают форматирование", () => {
  assert.equal(formatSize(null), "0 Б")
  assert.equal(formatSize("abc"), "0 Б")
  assert.equal(formatSize(undefined), "0 Б")
})
