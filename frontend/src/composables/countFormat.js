// Формат чисел для бейджей (патч U).
//
// В полоске разделов проекта места мало, а счётчики компактные: от 0 до 9
// показываем число как есть, дальше — «9+». В боковом меню места больше:
// от 0 до 99, дальше «99+». null или undefined означают «ещё не знаем» —
// бейджа нет; ноль показываем честно (приглушённым стилем .zero), чтобы
// сразу видеть «здесь пусто», не переходя в раздел.

export function tabCount(value) {
  if (typeof value !== "number" || value < 0) return ""
  return value > 9 ? "9+" : String(value)
}

export function railCount(value) {
  if (typeof value !== "number" || value < 0) return ""
  return value > 99 ? "99+" : String(value)
}
