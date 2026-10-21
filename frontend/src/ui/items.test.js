import assert from "node:assert/strict"
import test from "node:test"

import {
  addItem,
  catalogMap,
  findItem,
  heightClass,
  itemsClasses,
  missingElements,
  moveItem,
  removeItem,
  sameConfig,
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

test("heightClass опознаёт только три уровня, остальное — авто", () => {
  assert.equal(heightClass("low"), "ui-height-low")
  assert.equal(heightClass("medium"), "ui-height-medium")
  assert.equal(heightClass("tall"), "ui-height-tall")
  assert.equal(heightClass("auto"), null)
  assert.equal(heightClass(undefined), null)
  assert.equal(heightClass("huge"), null)
  assert.equal(heightClass(2), null)
})

test("itemsClasses включает модификаторы только за явные выборы", () => {
  // Дефолт (ничего не трогали) — пустой список: вид строк как до настройки.
  assert.deepEqual(itemsClasses(null), [])
  assert.deepEqual(itemsClasses({}), [])
  assert.deepEqual(itemsClasses({ columns: 1, align: "stretch", gap: "normal", dividers: true }), [])
  // Явные выборы включают модификаторы.
  assert.deepEqual(itemsClasses({ columns: 2 }), ["ui-items--cols-2"])
  assert.deepEqual(itemsClasses({ columns: 3, align: "center" }), ["ui-items--cols-3", "ui-items--align-center"])
  assert.deepEqual(itemsClasses({ align: "start", gap: "spacious" }), ["ui-items--align-start", "ui-items--gap-spacious"])
  assert.deepEqual(itemsClasses({ gap: "compact" }), ["ui-items--gap-compact"])
  assert.deepEqual(itemsClasses({ dividers: false }), ["ui-items--no-dividers"])
  // Мусорные значения ничего не включают — как spanClass, битый конфиг
  // не ломает страницу.
  assert.deepEqual(itemsClasses({ columns: 9, align: "left", gap: "tight" }), [])
})

test("sameConfig сравнивает и настройки страницы, и элементы", () => {
  const base = { settings: { max_block_height: 480 }, items: ITEMS }
  assert.equal(sameConfig(base, { settings: { max_block_height: 480 }, items: ITEMS.slice() }), true)
  // Изменилась только настройка страницы — это уже изменение.
  assert.equal(sameConfig(base, { settings: { max_block_height: 640 }, items: ITEMS.slice() }), false)
  // Изменились только элементы.
  assert.equal(
    sameConfig(base, { settings: { max_block_height: 480 }, items: [ITEMS[1], ITEMS[0], ITEMS[2]] }),
    false
  )
  // Пустые значения эквивалентны пустым.
  assert.equal(sameConfig(null, { settings: {}, items: [] }), true)
  assert.equal(sameConfig(undefined, undefined), true)
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
