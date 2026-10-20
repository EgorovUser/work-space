import assert from "node:assert/strict"
import test from "node:test"
import { buildMonth, dayOf, repeatLabel, shiftMonth, tasksByDay } from "./calendar.js"

test("сетка месяца начинается с понедельника и содержит 6 недель", () => {
  // Октябрь 2026: 1 октября — четверг, неделя начинается 28 сентября.
  const grid = buildMonth({ year: 2026, month: 9 }, "2026-10-20")
  assert.equal(grid.title, "Октябрь 2026")
  assert.equal(grid.weeks.length, 6)
  assert.equal(grid.weeks[0][0].key, "2026-09-28")
  assert.equal(grid.weeks[0][6].key, "2026-10-04")
  assert.equal(grid.weeks[0][3].key, "2026-10-01")
  assert.equal(grid.weeks[0][3].inMonth, true)
  assert.equal(grid.weeks[0][0].inMonth, false)
})

test("«сегодня» подсвечивается только в своей ячейке", () => {
  const grid = buildMonth({ year: 2026, month: 9 }, "2026-10-20")
  const today = grid.weeks.flatMap((week) => week).filter((cell) => cell.isToday)
  assert.deepEqual(today.map((cell) => cell.key), ["2026-10-20"])
})

test("переход между месяцами заворачивает год", () => {
  assert.deepEqual(shiftMonth({ year: 2026, month: 11 }, 1), { year: 2027, month: 0 })
  assert.deepEqual(shiftMonth({ year: 2027, month: 0 }, -1), { year: 2026, month: 11 })
})

test("задачи группируются по дню в заданном поясе и сортируются по времени", () => {
  const tasks = [
    { id: 1, deadline: "2026-10-20T21:30:00+00:00", title: "поздняя" },
    { id: 2, deadline: "2026-10-20T06:00:00+00:00", title: "ранняя" },
    { id: 3, deadline: "2026-10-21T10:00:00+00:00", title: "завтра" },
    { id: 4, deadline: null, title: "без срока" },
  ]
  // В Москве (UTC+3) «поздняя» в 21:30 UTC — уже 21-е; в UTC — ещё 20-е.
  const msk = tasksByDay(tasks, "Europe/Moscow")
  assert.deepEqual(
    msk.get("2026-10-20").map((task) => task.id),
    [2]
  )
  assert.deepEqual(
    msk.get("2026-10-21").map((task) => task.id),
    [1, 3]
  )
  assert.equal(msk.has("2026-10-22"), false)

  const utc = tasksByDay(tasks, "UTC")
  assert.deepEqual(
    utc.get("2026-10-20").map((task) => task.id),
    [2, 1]
  )
  assert.deepEqual(
    utc.get("2026-10-21").map((task) => task.id),
    [3]
  )
})

test("dayOf считает календарный день в поясе", () => {
  assert.equal(dayOf("2026-10-20T21:30:00+00:00", "Europe/Moscow"), "2026-10-21")
  assert.equal(dayOf("2026-10-20T21:30:00+00:00", "UTC"), "2026-10-20")
})

test("подписи повтора по-русски", () => {
  assert.equal(repeatLabel("", 1), "")
  assert.equal(repeatLabel("daily", 1), "Каждый день")
  assert.equal(repeatLabel("daily", 2), "Каждые 2 дня")
  assert.equal(repeatLabel("daily", 5), "Каждые 5 дней")
  assert.equal(repeatLabel("weekly", 1), "Каждую неделю")
  assert.equal(repeatLabel("weekly", 2), "Каждые 2 недели")
  assert.equal(repeatLabel("monthly", 3), "Каждые 3 месяца")
  assert.equal(repeatLabel("yearly", 1), "Каждый год")
  assert.equal(repeatLabel("yearly", 5), "Каждые 5 лет")
})
