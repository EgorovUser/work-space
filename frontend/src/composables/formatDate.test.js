import assert from "node:assert/strict"
import test from "node:test"
import { formatWhen } from "./formatDate.js"

test("пустая дата остаётся пустой", () => {
  assert.equal(formatWhen("", "YYYY-MM-DD"), "")
  assert.equal(formatWhen(null, "YYYY-MM-DD"), "")
})

test("дата собирается из шаблона", () => {
  const text = formatWhen("2026-10-16T07:05:00Z", "YYYY-MM-DD HH:mm", "UTC")
  assert.equal(text, "2026-10-16 07:05")
})

test("битая дата возвращается как была", () => {
  assert.equal(formatWhen("не дата", "YYYY-MM-DD"), "не дата")
})
