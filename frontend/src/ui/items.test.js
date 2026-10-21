import assert from "node:assert/strict"
import test from "node:test"

import {
  addItem,
  catalogMap,
  findItem,
  missingElements,
  moveItem,
  removeItem,
  sameItems,
  setItemProp,
  spanClass,
} from "../ui/items.js"

// Чистые операции над элементами страницы (патч AW): панель свойств
// опирается на них, тестам не нужен ни API, ни Vue.

const ITEMS = [
  { element: "overdue-tasks", span: 4, hidden: false, title: "" },
  { element: "pomodoro", span: 2, hidden: false, title: "" },
  { element: "projects", span: 4, hidden: false, title: "" },
]

test("spanClass держит ширину в 1–4 и лечит мусор", () => {
  assert.equal(spanClass(1), "ui-span-1")
  assert.equal(spanClass(4), "ui-span-4")
  assert.equal(spanClass(9), "ui-span-4")
  assert.equal(spanClass(0), "ui-span-1")
  assert.equal(spanClass(2.6), "ui-span-3")
  assert.equal(spanClass("3"), "ui-span-3")
  assert.equal(spanClass(undefined), "ui-span-2")
  assert.equal(spanClass(null), "ui-span-2")
})

test("findItem находит и честно промахивается", () => {
  assert.equal(findItem(ITEMS, "pomodoro").span, 2)
  assert.equal(findItem(ITEMS, "nope"), null)
})

test("setItemProp меняет только свой элемент, без мутации исходника", () => {
  const next = setItemProp(ITEMS, "pomodoro", "span", 3)
  assert.equal(next[1].span, 3)
  assert.equal(ITEMS[1].span, 2)
  assert.equal(next[0], ITEMS[0])
})

test("addItem не плодит дубликаты и вливает дефолты каталога", () => {
  const withDefault = addItem(ITEMS, "new-mail", { span: 2, hidden: false, title: "" })
  assert.equal(withDefault.length, 4)
  assert.deepEqual(withDefault[3], { element: "new-mail", span: 2, hidden: false, title: "" })
  const again = addItem(withDefault, "new-mail", { span: 4 })
  assert.equal(again.length, 4)
  assert.equal(again[3].span, 2) // дубль проигнорирован
})

test("removeItem убирает элемент", () => {
  const next = removeItem(ITEMS, "pomodoro")
  assert.deepEqual(
    next.map((item) => item.element),
    ["overdue-tasks", "projects"]
  )
})

test("moveItem двигает в пределах списка и не двигает за края", () => {
  const up = moveItem(ITEMS, "pomodoro", -1)
  assert.deepEqual(
    up.map((item) => item.element),
    ["pomodoro", "overdue-tasks", "projects"]
  )
  const down = moveItem(ITEMS, "projects", 1)
  assert.equal(down, ITEMS) // дальше некуда — тот же массив
  const edge = moveItem(ITEMS, "overdue-tasks", -1)
  assert.equal(edge, ITEMS)
  const missing = moveItem(ITEMS, "nope", 1)
  assert.equal(missing, ITEMS)
})

test("sameItems сравнивает по содержимому, порядок важен", () => {
  assert.equal(sameItems(ITEMS, ITEMS.slice()), true)
  assert.equal(sameItems(ITEMS, [ITEMS[1], ITEMS[0], ITEMS[2]]), false)
  assert.equal(sameItems([], []), true)
  assert.equal(sameItems(null, []), true)
})

test("catalogMap и missingElements кормят пикер", () => {
  const catalog = {
    elements: [
      { name: "overdue-tasks", title: "Просроченные" },
      { name: "pomodoro", title: "Помодоро" },
      { name: "new-mail", title: "Новые письма" },
    ],
  }
  const byName = catalogMap(catalog)
  assert.equal(byName.get("pomodoro").title, "Помодоро")
  assert.equal(catalogMap(null).size, 0)
  const missing = missingElements(ITEMS, catalog)
  assert.deepEqual(
    missing.map((item) => item.name),
    ["new-mail"]
  )
})
