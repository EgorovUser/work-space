import test from "node:test"
import assert from "node:assert/strict"

import { formatDuration, formatHoursCompact, hoursToMinutes } from "./timeFormat.js"

test("hoursToMinutes переводит дробные часы в минуты", () => {
  assert.equal(hoursToMinutes(1.5), 90)
  assert.equal(hoursToMinutes("2"), 120)
  assert.equal(hoursToMinutes(0.25), 15)
})

test("hoursToMinutes отбрасывает мусор и неположительные значения", () => {
  assert.equal(hoursToMinutes(""), 0)
  assert.equal(hoursToMinutes("abc"), 0)
  assert.equal(hoursToMinutes(0), 0)
  assert.equal(hoursToMinutes(-3), 0)
  assert.equal(hoursToMinutes(null), 0)
})

test("formatHoursCompact подписывает часы и минуты", () => {
  assert.equal(formatHoursCompact(90), "1,5 ч")
  assert.equal(formatHoursCompact(60), "1 ч")
  assert.equal(formatHoursCompact(75), "1,25 ч")
  assert.equal(formatHoursCompact(45), "45 мин")
  assert.equal(formatHoursCompact(0), "0 мин")
})

test("formatDuration разворачивает длительность словами", () => {
  assert.equal(formatDuration(90), "1 ч 30 мин")
  assert.equal(formatDuration(60), "1 ч")
  assert.equal(formatDuration(45), "45 мин")
  assert.equal(formatDuration(0), "0 мин")
})
