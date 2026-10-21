import test from "node:test"
import assert from "node:assert/strict"
import { fromLine } from "./mailFormat.js"

test("fromLine: имя и адрес собираются в «Имя <адрес>»", () => {
  assert.equal(fromLine({ from_name: "Иван", from_addr: "ivan@test" }), "Иван <ivan@test>")
})

test("fromLine: только адрес или только имя проходят как есть", () => {
  assert.equal(fromLine({ from_addr: "ivan@test" }), "ivan@test")
  assert.equal(fromLine({ from_name: "Иван" }), "Иван")
  assert.equal(fromLine({}), "")
})

test("fromLine: null (письмо ещё не загрузилось) — пустая строка", () => {
  assert.equal(fromLine(null), "")
  assert.equal(fromLine(undefined), "")
})
