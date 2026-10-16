import assert from "node:assert/strict"
import test from "node:test"
import { createPopStore } from "./usePop.js"

function fake(store, id, node) {
  const state = { open: false }
  store.register(id, {
    close() {
      state.open = false
      store.close(id)
    },
    contains(target) {
      return target === node
    },
  })
  return state
}

test("второе меню закрывает первое", () => {
  const store = createPopStore()
  const first = fake(store, 1, "a")
  const second = fake(store, 2, "b")
  store.open(1)
  first.open = true
  store.open(2)
  second.open = true
  assert.equal(first.open, false)
  assert.equal(store.current(), 2)
})

test("клик снаружи закрывает, клик внутри нет", () => {
  const store = createPopStore()
  const menu = fake(store, 1, "inside")
  store.open(1)
  menu.open = true
  store.pointer("inside")
  assert.equal(menu.open, true)
  store.pointer("page")
  assert.equal(menu.open, false)
  assert.equal(store.current(), 0)
})

test("escape закрывает только открытое", () => {
  const store = createPopStore()
  const menu = fake(store, 1, "inside")
  assert.equal(store.escape(), false)
  store.open(1)
  menu.open = true
  assert.equal(store.escape(), true)
  assert.equal(menu.open, false)
})
