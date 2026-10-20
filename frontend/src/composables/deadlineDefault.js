import { formatWhen } from "./formatDate.js"

// Дефолтный дедлайн новой задачи: сегодня + N дней, в часовом поясе
// приложения (core.ui.timezone) — тот же, в котором бэкенд разбирает
// наивные даты. 0, отрицательное или мусорное значение — дедлайн не
// предзаполняется (пустая строка, сервер трактует её как «без срока»).
export function defaultDeadlineISO(days, timeZone, from = new Date()) {
  const count = Number(days)
  if (!count || !Number.isFinite(count) || count <= 0) return ""
  const target = new Date(from.getTime() + count * 24 * 60 * 60 * 1000)
  return formatWhen(target, "YYYY-MM-DDTHH:mm", timeZone || undefined)
}
