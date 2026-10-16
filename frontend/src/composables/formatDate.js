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
