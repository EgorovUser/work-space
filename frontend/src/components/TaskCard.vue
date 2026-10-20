<template>
  <article class="task-card" :data-id="task.id">
    <div class="task-card-top">
      <span class="drag-handle" title="Перетащить">⋮⋮</span>
      <router-link class="task-title" :to="taskLink">{{ task.title }}</router-link>
      <ActionMenu :actions="menuActions" @choose="$emit('menu', $event)" />
    </div>

    <div v-if="hasMeta" class="task-meta">
      <span v-if="task.repeat_kind" class="repeat-mark" :title="repeatTitle">↻</span>
      <span v-if="priorityLabel" class="pill" :class="priorityClass">{{ priorityLabel }}</span>
      <span v-if="task.deadline" :class="{ 'bad-text': late }">{{ when(task.deadline) }}</span>
      <span v-if="task.tags.length">{{ task.tags.map((tag) => tag.name).join(", ") }}</span>
      <span v-if="task.checklist_total" class="tc-count">{{ task.checklist_done }}/{{ task.checklist_total }}</span>
    </div>

    <div v-if="task.progress" class="progress" :title="progressTitle"><span :style="{ width: bar }" /></div>

    <ul v-if="checks.length" class="tc-checks">
      <li v-for="item in visibleChecks" :key="item.id" class="tc-check" :class="{ done: item.done }">
        <input
          :checked="item.done"
          type="checkbox"
          :title="item.done ? 'Снять отметку' : 'Отметить выполненным'"
          @change="toggleCheck(item, $event)"
        />
        <span>{{ item.title }}</span>
      </li>
      <li v-if="hiddenCount" class="tc-more">
        <button class="text-btn" type="button" @click="expanded = true">Ещё {{ hiddenCount }}</button>
      </li>
      <li v-else-if="expanded && checks.length > VISIBLE_LIMIT" class="tc-more">
        <button class="text-btn" type="button" @click="expanded = false">Свернуть</button>
      </li>
    </ul>

    <form class="tc-time" @submit.prevent="logHours">
      <input
        v-model="hours"
        class="tc-hours"
        type="number"
        inputmode="decimal"
        min="0"
        step="0.25"
        placeholder="ч"
        title="Сколько часов списать на задачу"
        :disabled="busyTime"
      />
      <button class="btn secondary tc-log" type="submit" :disabled="busyTime">Списать</button>
      <span v-if="task.spent_minutes" class="tc-spent" :title="'Всего списано: ' + formatDuration(task.spent_minutes)">
        ⏱ {{ formatHoursCompact(task.spent_minutes) }}
      </span>
    </form>
  </article>
</template>

<script>
import { computed, ref } from "vue"
import ActionMenu from "./ActionMenu.vue"
import { api } from "../api"
import { repeatLabel } from "../composables/calendar"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { formatDuration, formatHoursCompact, hoursToMinutes } from "../composables/timeFormat"

// Сколько пунктов чеклиста видно на карточке до сворачивания: длинные
// списки не раздувают колонку, «Ещё N» разворачивает целиком.
const VISIBLE_LIMIT = 5

// Карточка задачи на доске (патч R): чеклист подзадач с отмечанием прямо
// на доске и быстрое списание часов без захода в задачу. Компонент меняет
// переданный объект задачи на месте — это тот же реактивный элемент
// массива доски, поэтому колонка и бейджи обновляются мгновенно.
export default {
  components: { ActionMenu },
  props: {
    task: { type: Object, required: true },
    project: { type: Object, required: true },
  },
  emits: ["menu"],
  setup(props) {
    const { settings, when, localDay } = useWhen()
    const notice = useNotice()
    const hours = ref("")
    const busyTime = ref(false)
    const expanded = ref(false)
    const menuActions = [
      { id: "open", label: "Открыть" },
      { id: "delete", label: "Удалить", danger: true },
    ]

    const taskLink = computed(() => "/projects/" + props.project.id + "/tasks/" + props.task.id)
    const checks = computed(() => (Array.isArray(props.task.checklist) ? props.task.checklist : []))
    const visibleChecks = computed(() => (expanded.value ? checks.value : checks.value.slice(0, VISIBLE_LIMIT)))
    const hiddenCount = computed(() => Math.max(0, checks.value.length - VISIBLE_LIMIT))

    const priority = computed(() => {
      const raw = settings.get("tasks", "priorities")
      const list = Array.isArray(raw) ? raw : []
      return list.find((item) => item && item.id === props.task.priority) || null
    })
    const priorityLabel = computed(() => (priority.value ? priority.value.label : ""))
    const priorityClass = computed(() => {
      const id = priority.value ? String(priority.value.id) : ""
      if (id === "high") return "bad"
      if (id === "low") return "off"
      return ""
    })

    const late = computed(() => {
      if (!props.task.deadline) return false
      return new Date(props.task.deadline).getTime() < Date.now()
    })

    const repeatTitle = computed(() => repeatLabel(props.task.repeat_kind, props.task.repeat_interval))

    const hasMeta = computed(
      () =>
        Boolean(props.task.repeat_kind) ||
        Boolean(priorityLabel.value) ||
        Boolean(props.task.deadline) ||
        (props.task.tags && props.task.tags.length) ||
        Boolean(props.task.checklist_total)
    )

    const progressTitle = computed(() => "Прогресс: " + props.task.progress)

    const bar = computed(() => {
      const max = Number(settings.get("tasks", "progress.max")) || 100
      const width = Math.max(0, Math.min(100, (Number(props.task.progress) / max) * 100))
      return width + "%"
    })

    // Пересчёт счётчиков и прогресса по чеклисту — та же формула, что у
    // сервиса (_progress): доля отмеченных от максимума, с отсечением
    // дробной части. Вручную заданный прогресс не трогаем.
    function syncChecklist() {
      const task = props.task
      const list = Array.isArray(task.checklist) ? task.checklist : []
      task.checklist_total = list.length
      task.checklist_done = list.filter((row) => row.done).length
      if (task.progress_mode !== "manual" && list.length) {
        const max = Number(settings.get("tasks", "progress.max")) || 100
        task.progress = Math.floor((task.checklist_done * max) / list.length)
      }
    }

    async function toggleCheck(item, event) {
      const previous = item.done
      item.done = event.target.checked
      syncChecklist()
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + props.task.id + "/checklist/" + item.id, {
          method: "PATCH",
          body: { done: item.done },
        })
      } catch (err) {
        item.done = previous
        event.target.checked = previous
        syncChecklist()
        notice.show("Не удалось отметить пункт. " + (err.message || "Ошибка"))
      }
    }

    async function logHours() {
      if (busyTime.value) return
      const minutes = hoursToMinutes(hours.value)
      if (!minutes) {
        notice.show("Введите часы, например 1.5 — полтора часа")
        return
      }
      if (minutes > 1440) {
        notice.show("За одну запись — не больше 24 часов")
        return
      }
      busyTime.value = true
      try {
        const entry = await api("/api/projects/" + props.project.id + "/time/entries", {
          method: "POST",
          body: { task_id: props.task.id, minutes, day: localDay(), note: "" },
        })
        const logged = Number(entry && entry.minutes) || minutes
        props.task.spent_minutes = (Number(props.task.spent_minutes) || 0) + logged
        hours.value = ""
        notice.show("Списано " + formatHoursCompact(logged) + " · «" + props.task.title + "»", { kind: "success" })
      } catch (err) {
        notice.show("Не удалось списать время. " + (err.message || "Ошибка"))
      } finally {
        busyTime.value = false
      }
    }

    return {
      VISIBLE_LIMIT,
      hours,
      busyTime,
      expanded,
      menuActions,
      taskLink,
      checks,
      visibleChecks,
      hiddenCount,
      priorityLabel,
      priorityClass,
      late,
      repeatTitle,
      hasMeta,
      progressTitle,
      bar,
      when,
      formatDuration,
      formatHoursCompact,
      toggleCheck,
      logHours,
    }
  },
}
</script>
