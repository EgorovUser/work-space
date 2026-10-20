import { api } from "../api"
import { applyTaskOrders } from "./taskOrder"

// Перетаскивание карточек и панорама доски (патч X): pointer-логика вынесена
// из TaskBoard.vue в composable. Работает по классам и data-атрибутам дом-дерева
// (.task-card с data-id, .task-list с data-status, .kanban-col) — разметку
// не меняет, e2e не затрагивает.
//
// Карточка: pointerdown на .task-card (вне ссылок и кнопок) → при сдвиге
// дальше 5px рождается «призрак», колонка под ним подсвечивается; отпускание
// отправляет порядок на сервер, локально применяется сразу (оптимистично),
// при сбое откат снапшотом.
//
// Панорама: pointerdown на пустом месте доски скроллит её и список колонки.
export function useBoardDrag({ root, tasks, projectId, notice }) {
  let drag = null
  let pan = null

  function clearDrag() {
    if (!drag) return
    if (drag.ghost) drag.ghost.remove()
    if (drag.card) drag.card.classList.remove("drag-source")
    if (drag.column) drag.column.classList.remove("drop-target")
    document.body.classList.remove("dragging-card")
    drag = null
  }

  function columnAt(x, hold) {
    if (!root.value || typeof x !== "number") return hold || null
    let found = null
    for (const column of root.value.querySelectorAll(".kanban-col")) {
      const rect = column.getBoundingClientRect()
      if (x >= rect.left && x <= rect.right) found = column
    }
    if (!found || !hold || found === hold) return found || hold || null
    const rect = found.getBoundingClientRect()
    const margin = Math.min(48, rect.width / 4)
    if (x < rect.left + margin || x > rect.right - margin) return hold
    return found
  }

  function onPointerDown(event) {
    if (event.button !== 0 || !root.value) return
    const card = event.target.closest && event.target.closest(".task-card")
    if (card && root.value.contains(card)) {
      if (event.target.closest("a, button, input, textarea, select, .col-handle")) return
      drag = {
        card,
        id: Number(card.dataset.id),
        startX: event.clientX,
        startY: event.clientY,
        active: false,
        ghost: null,
        column: card.closest(".kanban-col"),
      }
      window.addEventListener("pointermove", onPointerMove)
      window.addEventListener("pointerup", onPointerUp)
      return
    }
    const board = root.value.closest(".kanban")
    if (!board || !board.contains(event.target)) return
    if (event.target.closest("a, button, input, textarea, select, .drag-handle, .col-handle, .pop, .pop-panel")) return
    const list = event.target.closest(".task-list")
    const scroller = scrolling(board)
    pan = {
      board,
      scroller,
      list: list && list.scrollHeight > list.clientHeight + 2 ? list : null,
      startX: event.clientX,
      startY: event.clientY,
      left: scroller.scrollLeft,
      top: (list && list.scrollHeight > list.clientHeight + 2 ? list : scroller).scrollTop,
      active: false,
    }
    window.addEventListener("pointermove", onPanMove)
    window.addEventListener("pointerup", onPanUp)
  }

  function onPointerMove(event) {
    if (!drag) return
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    if (!drag.active) {
      if (dx * dx + dy * dy < 25) return
      const rect = drag.card.getBoundingClientRect()
      const ghost = drag.card.cloneNode(true)
      ghost.classList.add("drag-ghost")
      ghost.style.width = rect.width + "px"
      ghost.style.transform = "translate(" + rect.left + "px, " + rect.top + "px)"
      document.body.appendChild(ghost)
      drag.ghost = ghost
      drag.offsetX = event.clientX - rect.left
      drag.offsetY = event.clientY - rect.top
      drag.active = true
      drag.card.classList.add("drag-source")
      if (drag.column) drag.column.classList.add("drop-target")
      document.body.classList.add("dragging-card")
    }
    drag.ghost.style.transform = "translate(" + (event.clientX - drag.offsetX) + "px, " + (event.clientY - drag.offsetY) + "px)"
    const next = columnAt(event.clientX, drag.column)
    if (next && next !== drag.column) {
      drag.column.classList.remove("drop-target")
      drag.column = next
      next.classList.add("drop-target")
    }
  }

  function idsOf(list, skipId) {
    return [...list.querySelectorAll(":scope > .task-card")]
      .map((node) => Number(node.dataset.id))
      .filter((id) => id && id !== skipId)
  }

  function indexAt(list, y, skipId) {
    const cards = [...list.querySelectorAll(":scope > .task-card")].filter((node) => Number(node.dataset.id) !== skipId)
    for (let i = 0; i < cards.length; i += 1) {
      const rect = cards[i].getBoundingClientRect()
      if (y < rect.top + rect.height / 2) return i
    }
    return cards.length
  }

  async function onPointerUp(event) {
    window.removeEventListener("pointermove", onPointerMove)
    window.removeEventListener("pointerup", onPointerUp)
    const state = drag
    if (!state || !state.active) {
      clearDrag()
      return
    }
    const list = state.column && state.column.querySelector(".task-list")
    const from = state.card.closest(".task-list")
    clearDrag()
    window.addEventListener("click", swallowClick, true)
    if (!list || !from || !state.id) return
    const fromIds = idsOf(from, state.id)
    const same = list === from
    const targetIds = same ? fromIds : idsOf(list, state.id)
    targetIds.splice(indexAt(list, event.clientY, state.id), 0, state.id)
    const orders = same
      ? [{ status_id: Number(from.dataset.status), ids: targetIds }]
      : [
          { status_id: Number(from.dataset.status), ids: fromIds },
          { status_id: Number(list.dataset.status), ids: targetIds },
        ]
    const snapshot = tasks.value.map((task) => ({ ...task }))
    tasks.value = applyTaskOrders(tasks.value, orders)
    try {
      await api("/api/projects/" + projectId + "/tasks/reorder", { method: "POST", body: { orders } })
    } catch (err) {
      tasks.value = snapshot
      notice.show("Не удалось перенести карточку. " + (err.message || "Ошибка"))
    }
  }

  function swallowClick(event) {
    event.preventDefault()
    event.stopPropagation()
    window.removeEventListener("click", swallowClick, true)
  }

  function scrolling(node) {
    let current = node
    while (current) {
      if (current.scrollWidth > current.clientWidth + 2 || current.scrollHeight > current.clientHeight + 2) return current
      current = current.parentElement
    }
    return node
  }

  function onPanMove(event) {
    if (!pan) return
    const dx = event.clientX - pan.startX
    const dy = event.clientY - pan.startY
    if (!pan.active) {
      if (dx * dx + dy * dy < 9) return
      pan.active = true
      pan.board.classList.add("panning")
    }
    pan.scroller.scrollLeft = pan.left - dx
    const vertical = pan.list || pan.scroller
    vertical.scrollTop = pan.top - dy
  }

  function onPanUp() {
    window.removeEventListener("pointermove", onPanMove)
    window.removeEventListener("pointerup", onPanUp)
    if (pan && pan.active) window.addEventListener("click", swallowClick, true)
    if (pan && pan.board) pan.board.classList.remove("panning")
    pan = null
  }

  function unbindDrag() {
    window.removeEventListener("pointermove", onPointerMove)
    window.removeEventListener("pointerup", onPointerUp)
    window.removeEventListener("pointermove", onPanMove)
    window.removeEventListener("pointerup", onPanUp)
    window.removeEventListener("click", swallowClick, true)
    if (pan && pan.board) pan.board.classList.remove("panning")
    pan = null
    clearDrag()
  }

  return { onPointerDown, unbindDrag }
}
