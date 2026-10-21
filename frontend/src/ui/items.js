// Чистые операции над списком элементов страницы (патч AW): панель
// свойств и тесты работают без API. Элементы страницы уникальны — имя
// служит идентификатором (дубликаты отрезает нормализация бэкенда).

export function findItem(items, element) {
  return items.find((item) => item && item.element === element) || null
}

// Класс ширины для сетки из четырёх колонок. Битое значение (конфиг
// писался старой версией) сводится к безопасной половине.
export function spanClass(span) {
  // Number(null) === 0 — пустые значения обязаны попасть в фолбэк,
  // а не в «четверть ширины».
  const raw = span === null || span === undefined || span === "" ? NaN : Number(span)
  const value = Math.round(raw)
  const clamped = Number.isFinite(value) ? Math.min(4, Math.max(1, value)) : 2
  return "ui-span-" + clamped
}

// Класс фиксированной высоты блока: уровни — доли максимума страницы
// (настройка «Максимальная высота блока»): низкий = ½, средний = ¾,
// высокий = максимум. Всё остальное (и «авто» по умолчанию) — блок
// растёт по содержимому, как до редактора.
export function heightClass(height) {
  return height === "low" || height === "medium" || height === "tall" ? "ui-height-" + height : null
}

// Классы раскладки внутренних элементов (строк) карточки-списка.
// Никакого значения — пустой список: базовый вид строк остаётся как до
// настройки, модификаторы добавляются только за явно выбранные опции.
export function itemsClasses(item) {
  const config = item || {}
  const out = []
  const columns = Number(config.columns)
  if (columns === 2 || columns === 3) out.push("ui-items--cols-" + columns)
  if (config.align === "center" || config.align === "start") out.push("ui-items--align-" + config.align)
  if (config.gap === "compact" || config.gap === "spacious") out.push("ui-items--gap-" + config.gap)
  // Разделители строк включены по умолчанию (ими строки и так разделены),
  // управляем только выключением.
  if (config.dividers === false) out.push("ui-items--no-dividers")
  return out
}

// Конфиг «реально не менялся»: и настройки страницы, и элементы.
// Порядок элементов важен — как у sameItems.
export function sameConfig(left, right) {
  const a = left || {}
  const b = right || {}
  return sameItems(a.items, b.items) && JSON.stringify(a.settings || {}) === JSON.stringify(b.settings || {})
}

export function setItemProp(items, element, key, value) {
  return items.map((item) => (item.element === element ? { ...item, [key]: value } : item))
}

export function removeItem(items, element) {
  return items.filter((item) => item.element !== element)
}

export function addItem(items, element, defaults) {
  if (findItem(items, element)) return items
  return [...items, { ...(defaults || {}), element }]
}

export function moveItem(items, element, delta) {
  const index = items.findIndex((item) => item.element === element)
  const target = index + delta
  if (index < 0 || target < 0 || target >= items.length) return items
  const next = items.slice()
  const moved = next.splice(index, 1)[0]
  next.splice(target, 0, moved)
  return next
}

export function sameItems(left, right) {
  return JSON.stringify(left || []) === JSON.stringify(right || [])
}

// Каталог как словарь: элементы панели и заглушек ищутся по имени.
export function catalogMap(catalog) {
  const map = new Map()
  for (const element of (catalog && catalog.elements) || []) {
    map.set(element.name, element)
  }
  return map
}

// Элементы каталога, которых нет на странице, — кандидаты для пикера.
export function missingElements(items, catalog) {
  const present = new Set((items || []).map((item) => item.element))
  return ((catalog && catalog.elements) || []).filter((element) => !present.has(element.name))
}
