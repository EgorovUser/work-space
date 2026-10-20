import { ref } from "vue"

// Тема интерфейса: авто (как в системе) / светлая / тёмная.
// Выбор — localStorage устройства (тема — предпочтение браузера, а не серверная настройка),
// применяется через data-theme на <html>, чтобы CSS-токены переключались без перезагрузки.

const KEY = "ws-theme"
const ORDER = ["auto", "light", "dark"]

/** Чистая функция: сохранённый выбор побеждает системную тему. */
export function resolveTheme(stored, prefersDark) {
  if (stored === "light" || stored === "dark") return stored
  return prefersDark ? "dark" : "light"
}

/** Чистая функция: цикл переключения авто → светлая → тёмная → авто. */
export function nextTheme(mode) {
  const index = ORDER.indexOf(mode)
  return ORDER[(index + 1) % ORDER.length]
}

function readStored() {
  try {
    const value = typeof localStorage === "undefined" ? null : localStorage.getItem(KEY)
    return ORDER.includes(value) ? value : "auto"
  } catch {
    return "auto"
  }
}

function systemDark() {
  try {
    return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches
  } catch {
    return false
  }
}

function persist(mode) {
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    /* приватный режим браузера — просто не запоминаем */
  }
}

function applyToDocument(resolved) {
  if (typeof document === "undefined") return
  document.documentElement.dataset.theme = resolved
}

const mode = ref(readStored())
const resolved = ref(resolveTheme(mode.value, systemDark()))

applyToDocument(resolved.value)

// В режиме «как в системе» следим за изменением системной темы на лету.
if (typeof matchMedia === "function") {
  try {
    const mq = matchMedia("(prefers-color-scheme: dark)")
    const onChange = () => {
      if (mode.value !== "auto") return
      resolved.value = resolveTheme("auto", mq.matches)
      applyToDocument(resolved.value)
    }
    if (mq.addEventListener) mq.addEventListener("change", onChange)
    else if (mq.addListener) mq.addListener(onChange)
  } catch {
    /* старый браузер без matchMedia — тема останется выбранной при загрузке */
  }
}

function setTheme(next) {
  mode.value = ORDER.includes(next) ? next : "auto"
  resolved.value = resolveTheme(mode.value, systemDark())
  persist(mode.value)
  applyToDocument(resolved.value)
}

function cycleTheme() {
  setTheme(nextTheme(mode.value))
}

export function useTheme() {
  return { mode, resolved, setTheme, cycleTheme }
}
