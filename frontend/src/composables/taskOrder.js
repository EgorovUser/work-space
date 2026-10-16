/** Новый порядок карточек. Исходный список не меняется. */

export function applyTaskOrders(tasks, orders) {
  const next = tasks.map((task) => ({ ...task }))
  const byId = new Map(next.map((task) => [task.id, task]))
  for (const order of orders) {
    order.ids.forEach((id, index) => {
      const task = byId.get(id)
      if (!task) return
      task.status_id = order.status_id
      task.position = index
    })
  }
  return next
}
