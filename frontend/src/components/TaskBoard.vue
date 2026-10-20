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
          <TaskCard
            v-for="task in tasksOf(status.id)"
            :key="task.id"
            :task="task"
            :project="project"
            @menu="onCard($event, task)"
          />
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
import TaskCard from "./TaskCard.vue"
import { api } from "../api"
import { defaultDeadlineISO } from "../composables/deadlineDefault"
import { useBoardDrag } from "../composables/useBoardDrag"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"

// Доска задач: колонки, композеры, перетаскивание колонок (SortableJS).
// Pointer-логика перетаскивания карточек и панорамы — в
// composables/useBoardDrag.js (патч X).
export default {
  components: { ActionMenu, TaskCard },
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
    const { settings } = useWhen()
    const notice = useNotice()
    const router = useRouter()
    const sortables = []
    // Перетаскивание карточек и панорама доски — composable (патч X).
    const { onPointerDown, unbindDrag } = useBoardDrag({
      root,
      tasks,
      projectId: props.project.id,
      notice,
    })

    function tasksOf(id) {
      return tasks.value
        .filter((task) => task.status_id === id)
        .slice()
        .sort((a, b) => a.position - b.position || a.id - b.id)
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
        notice.show("Задача «" + title + "» создана", { kind: "success" })
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
        notice.show("Колонка «" + name + "» добавлена", { kind: "success" })
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
      if (!window.confirm("Удалить задачу «" + task.title + "»?")) return
      const snapshot = tasks.value.map((item) => ({ ...item }))
      tasks.value = tasks.value.filter((item) => item.id !== task.id)
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + task.id, { method: "DELETE" })
        // Удаление мягкое — задача лежит в корзине, поэтому тост несёт
        // «Отменить»: восстановление возвращает карточку на доску.
        notice.show("Задача «" + task.title + "» удалена в корзину", {
          kind: "success",
          timeout: 9000,
          action: {
            label: "Отменить",
            run: async () => {
              try {
                await api("/api/trash/tasks/" + task.id + "/restore", { method: "POST" })
                notice.show("Задача «" + task.title + "» восстановлена", { kind: "success" })
                await load()
              } catch (err) {
                notice.show("Не удалось восстановить задачу. " + (err.message || "Ошибка"))
              }
            },
          },
        })
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
        notice.show("Колонка «" + status.name + "» удалена", { kind: "success" })
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
      statuses, drafts, columnName, columnClosed, error, unavailable, busy, loading, root,
      tasksOf, columnActions, create, addColumn, rename, onCard, onColumn,
      composerPlaceholder, composerHint,
    }
  },
}
</script>
