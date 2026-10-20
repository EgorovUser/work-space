import test from "node:test"
import assert from "node:assert/strict"

import { defaultDeadlineISO } from "./deadlineDefault.js"

test("нулевое и мусорное значение — без дедлайна", () => {
  const from = new Date("2024-06-01T12:00:00Z")
  assert.equal(defaultDeadlineISO(0, "Europe/Moscow", from), "")
  assert.equal(defaultDeadlineISO(undefined, "Europe/Moscow", from), "")
  assert.equal(defaultDeadlineISO(-3, "Europe/Moscow", from), "")
  assert.equal(defaultDeadlineISO("мусор", "Europe/Moscow", from), "")
  assert.equal(defaultDeadlineISO(null, "Europe/Moscow", from), "")
})

test("семь дней от опорной даты", () => {
  const from = new Date("2024-06-01T12:00:00Z")
  const value = defaultDeadlineISO(7, "UTC", from)
  assert.equal(value, "2024-06-08T12:00")
})

test("часовой пояс приложения сдвигает дату на границе суток", () => {
  // 23:30 UTC + 7 дней = 02:30 следующего дня по Москве.
  const from = new Date("2024-01-01T23:30:00Z")
  assert.equal(defaultDeadlineISO(7, "Europe/Moscow", from), "2024-01-09T02:30")
  assert.equal(defaultDeadlineISO(7, "UTC", from), "2024-01-08T23:30")
})

test("без пояса используется зона браузера/рантайма", () => {
  const from = new Date("2024-06-01T12:00:00Z")
  const value = defaultDeadlineISO(1, "", from)
  assert.match(value, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
})
