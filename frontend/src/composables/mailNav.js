// Соседние письма для навигации в читалке: список свежие-сверху,
// поэтому prev — новее (вверх по списку), next — старее (вниз).
// Чистая функция без зависимостей — легко проверять тестами.

export function neighbors(list, id) {
  const empty = { prev: null, next: null }
  if (!Array.isArray(list)) return empty
  const target = Number(id)
  if (!Number.isFinite(target) || target <= 0) return empty
  const at = list.findIndex((item) => item && Number(item.id) === target)
  if (at < 0) return empty
  return {
    prev: at > 0 ? list[at - 1] : null,
    next: at + 1 < list.length ? list[at + 1] : null,
  }
}
