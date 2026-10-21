// Приоритет задачи на «Сегодня»: подпись и класс пилюли — общий для
// карточек просроченных и ближайших сроков (переехал из Today.vue,
// патч AW).

export const PRIORITIES = {
  high: "важная",
  normal: "обычная",
  low: "низкая",
}

export function priorityLabel(value) {
  return PRIORITIES[value] || ""
}

export function priorityClass(value) {
  if (value === "high") return "warn"
  if (value === "low") return "low"
  return ""
}
