// Перевод и подписи времени для списания в часах (патч R).
// Везде, где пользователь вводит длительность, он пишет часы («1.5»),
// API хранит минуты — конвертация в одном месте, чтобы не расползалась
// по экранам. Подписи двух видов: компактная для бейджа карточки
// («1.5 ч») и развёрнутая для списков («1 ч 30 мин»).

export function hoursToMinutes(hours) {
  const value = Number(hours)
  if (!Number.isFinite(value) || value <= 0) return 0
  return Math.round(value * 60)
}

function trimDecimal(number) {
  return String(Number(number.toFixed(2))).replace(".", ",")
}

// 90 -> «1,5 ч», 60 -> «1 ч», 45 -> «45 мин», 0 -> «0 ч».
// Дробные часы пишутся с запятой — как в остальных числах интерфейса.
export function formatHoursCompact(minutes) {
  const total = Math.max(0, Math.round(Number(minutes) || 0))
  if (total < 60) return total + " мин"
  return trimDecimal(total / 60) + " ч"
}

// 90 -> «1 ч 30 мин», 60 -> «1 ч», 45 -> «45 мин».
export function formatDuration(minutes) {
  const total = Math.max(0, Math.round(Number(minutes) || 0))
  const hours = Math.floor(total / 60)
  const mins = total % 60
  if (!hours) return mins + " мин"
  if (!mins) return hours + " ч"
  return hours + " ч " + mins + " мин"
}
