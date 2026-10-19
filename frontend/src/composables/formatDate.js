export function formatWhen(value, pattern, timeZone) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const options = {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }
  if (timeZone) options.timeZone = timeZone
  let parts
  try {
    parts = new Intl.DateTimeFormat("en-GB", options).formatToParts(date)
  } catch {
    delete options.timeZone
    parts = new Intl.DateTimeFormat("en-GB", options).formatToParts(date)
  }
  const map = {}
  for (const part of parts) map[part.type] = part.value
  return (pattern || "YYYY-MM-DD HH:mm")
    .replaceAll("YYYY", map.year || "")
    .replaceAll("MM", map.month || "")
    .replaceAll("DD", map.day || "")
    .replaceAll("HH", map.hour || "")
    .replaceAll("mm", map.minute || "")
}

// Даты младше 48 часов показываются как «Сегодня, 14:05» / «Вчера, 09:30».
// Сравнение идёт по календарным дням в timeZone (или зоне браузера, если не задана) —
// так «вчера вечером» не превращается в «сегодня» на границе суток UTC.
export function formatSmart(value, pattern, timeZone) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const dayOf = (when) => formatWhen(when, "YYYY-MM-DD", timeZone)
  const day = dayOf(date)
  const now = new Date()
  const today = dayOf(now)
  const yesterday = dayOf(new Date(now.getTime() - 24 * 60 * 60 * 1000))
  if (day === today) return "Сегодня, " + formatWhen(date, "HH:mm", timeZone)
  if (day === yesterday) return "Вчера, " + formatWhen(date, "HH:mm", timeZone)
  return formatWhen(date, pattern, timeZone)
}
