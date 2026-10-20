import test from "node:test"
import assert from "node:assert/strict"
import { resolveTheme, nextTheme, useTheme } from "./useTheme.js"

test("resolveTheme: сохранённый выбор побеждает системную тему", () => {
  assert.equal(resolveTheme("dark", false), "dark")
  assert.equal(resolveTheme("light", true), "light")
})

test("resolveTheme: без выбора следует системе, мусор игнорирует", () => {
  assert.equal(resolveTheme(null, true), "dark")
  assert.equal(resolveTheme(null, false), "light")
  assert.equal(resolveTheme("мусор", true), "dark")
  assert.equal(resolveTheme("мусор", false), "light")
})

test("nextTheme: цикл авто → светлая → тёмная → авто", () => {
  assert.equal(nextTheme("auto"), "light")
  assert.equal(nextTheme("light"), "dark")
  assert.equal(nextTheme("dark"), "auto")
})

test("useTheme: без DOM и localStorage не падает, режим по умолчанию — авто", () => {
  const theme = useTheme()
  assert.equal(theme.mode.value, "auto")
})

test("useTheme: cycleTheme и setTheme меняют режим (персист и DOM опциональны)", () => {
  const theme = useTheme()
  theme.cycleTheme()
  assert.equal(theme.mode.value, "light")
  theme.cycleTheme()
  assert.equal(theme.mode.value, "dark")
  theme.setTheme("auto")
  assert.equal(theme.mode.value, "auto")
  theme.setTheme("неизвестный")
  assert.equal(theme.mode.value, "auto")
})
