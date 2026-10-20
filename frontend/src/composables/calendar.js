// Чистые помощники календаря задач: сетка месяца, группировка задач по дням
// в часовой пояс настройки, человеческие подписи повтора. Без обращений к API.

import { formatWhen } from "./formatDate.js"

export const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

const KIND_LABELS = { daily: "Каждый день", weekly: "Каждую неделю", monthly: "Каждый месяц", yearly: "Каждый год" }
const KIND_UNITS = {
  daily: ["день", "дня", "дней"],
  weekly: ["неделя", "недели", "недель"],
  monthly: ["месяц", "месяца", "месяцев"],
  yearly: ["год", "года", "лет"],
}

function pluralRu(n, one, few, many) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

// Календарный день значения («YYYY-MM-DD») в заданном часовом поясе.
export function dayOf(value, timeZone) {
  return formatWhen(value, "YYYY-MM-DD", timeZone)
}

// Сетка месяца: 6 недель с понедельника, чтобы сетка не прыгала по высоте.
// todayKey — «YYYY-MM-DD» (обычно dayOf(new Date(), zone)), ячейка с ним
// подсвечивается как «сегодня».
export function buildMonth(cursor, todayKey) {
  const year = cursor.year
  const month = cursor.month
  const first = new Date(year, month, 1)
  // Понедельник первым днём недели: (getDay() + 6) % 7.
  const start = new Date(year, month, 1 - ((first.getDay() + 6) % 7))
  const cells = []
  for (let i = 0; i < 42; i += 1) {
    const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const key = date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0")
    cells.push({
      key,
      day: date.getDate(),
      inMonth: date.getMonth() === month,
      isToday: Boolean(todayKey) && key === todayKey,
    })
  }
  const weeks = []
  for (let w = 0; w < 6; w += 1) weeks.push(cells.slice(w * 7, w * 7 + 7))
  return { year, month, title: MONTHS[month] + " " + year, weeks }
}

export function shiftMonth(cursor, delta) {
  const date = new Date(cursor.year, cursor.month + delta, 1)
  return { year: date.getFullYear(), month: date.getMonth() }
}

// Задачи со сроком, сгруппированные по календарным дням в часовом поясе.
// Внутри дня — по времени срока. Возвращает Map<«YYYY-MM-DD», task[]>.
export function tasksByDay(tasks, timeZone) {
  const map = new Map()
  for (const task of tasks || []) {
    if (!task.deadline) continue
    const day = dayOf(task.deadline, timeZone)
    if (!map.has(day)) map.set(day, [])
    map.get(day).push(task)
  }
  for (const list of map.values()) {
    list.sort((a, b) => String(a.deadline).localeCompare(String(b.deadline)))
  }
  return map
}

// Человеческая подпись правила повтора: «Каждую неделю», «Каждые 2 недели».
export function repeatLabel(kind, interval) {
  if (!kind) return ""
  const n = Math.max(1, Math.trunc(Number(interval) || 1))
  if (n === 1) return KIND_LABELS[kind] || kind
  const units = KIND_UNITS[kind]
  if (!units) return kind
  return "Каждые " + n + " " + pluralRu(n, units[0], units[1], units[2])
}
