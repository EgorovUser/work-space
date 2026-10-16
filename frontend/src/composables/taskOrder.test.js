import assert from "node:assert/strict"
import test from "node:test"
import { applyTaskOrders } from "./taskOrder.js"

test("перенос в другую колонку не трогает исходный список", () => {
  const tasks = [
    { id: 1, status_id: 10, position: 0, title: "а" },
    { id: 2, status_id: 10, position: 1, title: "б" },
  ]
  const next = applyTaskOrders(tasks, [
    { status_id: 10, ids: [2] },
    { status_id: 20, ids: [1] },
  ])
  assert.equal(tasks[0].status_id, 10)
  assert.equal(next.find((task) => task.id === 1).status_id, 20)
  assert.equal(next.find((task) => task.id === 1).position, 0)
  assert.equal(next.find((task) => task.id === 2).position, 0)
})

test("порядок внутри колонки берётся из списка id", () => {
  const next = applyTaskOrders(
    [
      { id: 1, status_id: 10, position: 0 },
      { id: 2, status_id: 10, position: 1 },
      { id: 3, status_id: 10, position: 2 },
    ],
    [{ status_id: 10, ids: [3, 1, 2] }],
  )
  assert.deepEqual(
    next.map((task) => [task.id, task.position]),
    [[1, 1], [2, 2], [3, 0]],
  )
})
