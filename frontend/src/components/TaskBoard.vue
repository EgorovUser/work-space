<template>
  <section>
    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading && !statuses.length" class="muted">Загрузка…</p>
    <div v-else class="kanban">
      <div ref="root" class="kanban-cols">
      <section v-for="status in statuses" :key="status.id" class="kanban-col" :data-status="status.id" :style="{ borderTop: '3px solid ' + (status.color || '#c5cdd4') }">
        <header class="kanban-head">
          <span class="drag-handle col-handle" title="Перетащить колонку">⋮⋮</span>
          <input :value="status.name" type="text" @change="rename(status, $event)" />
          <span class="count">{{ tasksOf(status.id).length }}</span>
          <ActionMenu :actions="columnActions(status)" @choose="onColumn($event, status)" />
        </header>
        <div class="task-list" :data-status="status.id">
          <article v-for="task in tasksOf(status.id)" :key="task.id" class="task-card" :data-id="task.id">
            <div class="task-card-top">
              <span class="drag-handle" title="Перетащить">⋮⋮</span>
              <router-link class="task-title" :to="'/projects/' + project.id + '/tasks/' + task.id">{{ task.title }}</router-link>
              <ActionMenu :actions="cardActions" @choose="onCard($event, task)" />
            </div>
            <div class="task-meta">
              <span v-if="task.repeat_kind" class="repeat-mark" :title="repeatLabel(task.repeat_kind, task.repeat_interval)">↻</span>
              <span v-if="priorityLabel(task)" class="pill">{{ priorityLabel(task) }}</span>
              <span v-if="task.deadline" :class="{ 'bad-text': late(task) }">{{ when(task.deadline) }}</span>
              <span v-if="task.checklist_total">{{ task.checklist_done }}/{{ task.checklist_total }}</span>
              <span v-if="task.tags.length">{{ task.tags.map((tag) => tag.name).join(", ") }}</span>
            </div>
            <div class="progress" :title="task.progress + ''"><span :style="{ width: bar(task) }" /></div>
          </article>
        </div>
        <form class="composer" @submit.prevent="create(status)">
          <input v-model="drafts[status.id]" type="text" :placeholder="composerPlaceholder" :title="composerHint" />
        </form>
      </section>
      </div>
      <form class="kanban-col add-col" @submit.prevent="addColumn">
        <input v-model="columnName" type="text" placeholder="Новая колонка" />
        <label class="check">
          <input v-model="columnClosed" type="checkbox" />
          <span>Сразу закрытая</span>
        </label>
        <button class="btn" type="submit" :disabled="busy">Добавить колонку</button>
      </form>
    </div>
  </section>
</template>

<script>
import Sortable from "sortablejs"
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { useRouter } from "vue-router"
import ActionMenu from "./ActionMenu.vue"
import { api } from "../api"
import { repeatLabel } from "../composables/calendar"
import { defaultDeadlineISO } from "../composables/deadlineDefault"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { applyTaskOrders } from "../composables/taskOrder"

export default {
  components: { ActionMenu },
  props: { project: { type: Object, required: true } },
  setup(props) {
    const statuses = ref([])
    const tasks = ref([])
    const drafts = reactive({})
    const columnName = ref("")
    const columnClosed = ref(false)
    const error = ref("")
    const unavailable = ref(false)
    const busy = ref(false)
    const loading = ref(true)
    const root = ref(null)
    const { settings, when } = useWhen()
    const notice = useNotice()
    const router = useRouter()
    const sortables = []
    const cardActions = [
      { id: "open", label: "Открыть" },
      { id: "delete", label: "Удалить", danger: true },
    ]

    function tasksOf(id) {
      return tasks.value
        .filter((task) => task.status_id === id)
        .slice()
        .sort((a, b) => a.position - b.position || a.id - b.id)
    }

    function priorities() {
      const raw = settings.get("tasks", "priorities")
      return Array.isArray(raw) ? raw : []
    }

    function priorityLabel(task) {
      const found = priorities().find((item) => item && item.id === task.priority)
      return found ? found.label : ""
    }

    function late(task) {
      if (!task.deadline) return false
      return new Date(task.deadline).getTime() < Date.now()
    }

    // Дефолтный срок новой задачи: сегодня + N дней (tasks.deadlines.default_days,
    // по умолчанию 7). Значение видно в подсказке поля и на карточке после
    // создания; 0 в настройках выключает предзаполнение.
    function deadlineDays() {
      const days = Number(settings.get("tasks", "deadlines.default_days"))
      return Number.isFinite(days) && days > 0 ? days : 0
    }

    function newTaskDeadline() {
      return defaultDeadlineISO(
        settings.get("tasks", "deadlines.default_days"),
        settings.get("core", "ui.timezone")
      )
    }

    function bar(task) {
      const max = Number(settings.get("tasks", "progress.max")) || 100
      const width = Math.max(0, Math.min(100, (Number(task.progress) / max) * 100))
      return width + "%"
    }

    function columnActions(status) {
      const actions = [
        { id: "closed", label: status.is_closed ? "Сделать открытой" : "Сделать закрытой" },
      ]
      if (!tasksOf(status.id).length) actions.push({ id: "delete", label: "Удалить колонку", danger: true })
      return actions
    }

    function destroySort() {
      while (sortables.length) sortables.pop().destroy()
    }

    function mountSort() {
      destroySort()
      if (!root.value) return
      sortables.push(
        Sortable.create(root.value, {
          animation: 0,
          handle: ".col-handle",
          draggable: ".kanban-col",
          filter(event) {
            const origin = event.target
            if (!origin || !origin.closest) return false
            if (origin.closest(".col-handle")) return false
            return Boolean(origin.closest("input, textarea, select, button, a"))
          },
          preventOnFilter: false,
          onEnd: () => moveColumns(),
        })
      )
    }

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
        await api("/api/projects/" + props.project.id + "/tasks/reorder", { method: "POST", body: { orders } })
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

    async function moveColumns() {
      const ids = [...root.value.querySelectorAll(".kanban-col")]
        .map((node) => Number(node.dataset.status))
        .filter((id) => id)
      const snapshot = statuses.value.slice()
      const byId = new Map(snapshot.map((status) => [status.id, status]))
      statuses.value = ids.map((id) => byId.get(id)).filter(Boolean)
      try {
        await api("/api/projects/" + props.project.id + "/task-statuses/order", { method: "POST", body: { ids } })
      } catch (err) {
        statuses.value = snapshot
        notice.show("Не удалось переместить колонку. " + (err.message || "Ошибка"))
        await nextTick()
        mountSort()
      }
    }

    async function load() {
      destroySort()
      error.value = ""
      unavailable.value = false
      try {
        await settings.load(props.project.id)
        const [statusData, taskData] = await Promise.all([
          api("/api/projects/" + props.project.id + "/task-statuses"),
          api("/api/projects/" + props.project.id + "/tasks"),
        ])
        statuses.value = statusData.items || []
        tasks.value = taskData.items || []
      } catch (err) {
        statuses.value = []
        tasks.value = []
        if (err.status === 503) unavailable.value = true
        else error.value = err.message || "Доска недоступна"
      } finally {
        loading.value = false
      }
      await nextTick()
      mountSort()
    }

    async function create(status) {
      if (busy.value) return
      const title = (drafts[status.id] || "").trim()
      if (!title) return
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/tasks", {
          method: "POST",
          body: { title, status_id: status.id, deadline: newTaskDeadline() },
        })
        drafts[status.id] = ""
        await load()
      } catch (err) {
        notice.show("Не удалось создать задачу. " + (err.message || "Ошибка"))
      } finally {
        busy.value = false
      }
    }

    async function addColumn() {
      const name = columnName.value.trim()
      if (!name) return
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/task-statuses", {
          method: "POST",
          body: { name, is_closed: columnClosed.value },
        })
        columnName.value = ""
        columnClosed.value = false
        await load()
      } catch (err) {
        notice.show("Колонка не создана. " + (err.message || "Ошибка"))
      } finally {
        busy.value = false
      }
    }

    async function rename(status, event) {
      const previous = status.name
      const name = event.target.value.trim()
      if (!name || name === previous) {
        event.target.value = previous
        return
      }
      status.name = name
      try {
        await api("/api/projects/" + props.project.id + "/task-statuses/" + status.id, {
          method: "PATCH",
          body: { name },
        })
      } catch (err) {
        status.name = previous
        event.target.value = previous
        notice.show("Не удалось переименовать колонку. " + (err.message || "Ошибка"))
      }
    }

    async function toggleClosed(status) {
      const previous = status.is_closed
      status.is_closed = !previous
      try {
        await api("/api/projects/" + props.project.id + "/task-statuses/" + status.id, {
          method: "PATCH",
          body: { is_closed: status.is_closed },
        })
      } catch (err) {
        status.is_closed = previous
        notice.show("Не удалось изменить колонку. " + (err.message || "Ошибка"))
      }
    }

    async function removeTask(task) {
      if (!window.confirm("Удалить задачу «" + task.title + "»? Отменить будет нельзя.")) return
      const snapshot = tasks.value.map((item) => ({ ...item }))
      tasks.value = tasks.value.filter((item) => item.id !== task.id)
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + task.id, { method: "DELETE" })
      } catch (err) {
        tasks.value = snapshot
        notice.show("Не удалось удалить карточку. " + (err.message || "Ошибка"))
      }
    }

    async function removeColumn(status) {
      if (!window.confirm("Удалить колонку «" + status.name + "»?")) return
      const snapshot = statuses.value.slice()
      statuses.value = statuses.value.filter((item) => item.id !== status.id)
      try {
        await api("/api/projects/" + props.project.id + "/task-statuses/" + status.id, { method: "DELETE" })
      } catch (err) {
        statuses.value = snapshot
        notice.show("Не удалось удалить колонку. " + (err.message || "Ошибка"))
      }
    }

    function onCard(action, task) {
      if (action === "open") router.push("/projects/" + props.project.id + "/tasks/" + task.id)
      if (action === "delete") removeTask(task)
    }

    function onColumn(action, status) {
      if (action === "closed") toggleClosed(status)
      if (action === "delete") removeColumn(status)
    }

    const composerPlaceholder = computed(() => {
      const days = deadlineDays()
      return days ? "Новая задача (срок +" + days + " дн.)" : "Новая задача"
    })

    const composerHint = computed(() => {
      const days = deadlineDays()
      return days ? "Дедлайн через " + days + " дн. — меняется в настройках или на карточке" : ""
    })

    watch(() => props.project.id, load)
    onMounted(() => {
      window.addEventListener("pointerdown", onPointerDown)
      load()
    })
    onBeforeUnmount(() => {
      unbindDrag()
      destroySort()
    })
    return {
      statuses, drafts, columnName, columnClosed, error, unavailable, busy, loading, root, cardActions,
      tasksOf, priorityLabel, repeatLabel, when, late, bar, columnActions, create, addColumn, rename, onCard, onColumn,
      composerPlaceholder, composerHint,
    }
  },
}
</script>
