import assert from "node:assert/strict"
import test from "node:test"
import { formatWhen, formatSmart } from "./formatDate.js"

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

test("formatSmart: пустое значение остаётся пустым", () => {
  assert.equal(formatSmart("", "YYYY-MM-DD HH:mm", "UTC"), "")
  assert.equal(formatSmart(null, "YYYY-MM-DD HH:mm", "UTC"), "")
})

test("formatSmart: сегодня и вчера по календарным дням зоны", () => {
  // Привязываемся к полудню UTC: −2 часа не пересекают границу суток,
  // поэтому тест стабилен в любое время запуска.
  const base = new Date()
  const todayNoon = Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate(), 12, 0, 0)
  const today = formatSmart(new Date(todayNoon - 2 * 60 * 60 * 1000).toISOString(), "YYYY-MM-DD HH:mm", "UTC")
  const yesterday = formatSmart(new Date(todayNoon - 24 * 60 * 60 * 1000).toISOString(), "YYYY-MM-DD HH:mm", "UTC")
  assert.ok(today.startsWith("Сегодня, "), today)
  assert.ok(yesterday.startsWith("Вчера, "), yesterday)
})

test("formatSmart: старые даты идут обычным шаблоном", () => {
  const text = formatSmart("2026-10-16T07:05:00Z", "YYYY-MM-DD HH:mm", "UTC")
  assert.equal(text, "2026-10-16 07:05")
})
