<template>
  <section class="cal">
    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <template v-else>
      <div class="cal-head">
        <button class="btn secondary" type="button" @click="shift(-1)" aria-label="Предыдущий месяц">‹</button>
        <button class="btn secondary" type="button" @click="goToday">Этот месяц</button>
        <button class="btn secondary" type="button" @click="shift(1)" aria-label="Следующий месяц">›</button>
        <h3 class="cal-title">{{ grid.title }}</h3>
        <label class="check cal-closed-toggle">
          <input v-model="showClosed" type="checkbox" />
          <span>Закрытые</span>
        </label>
      </div>

      <div v-if="loading && !tasks.length" class="cal-skeleton"><SkeletonList :rows="6" /></div>
      <div v-else class="cal-grid" aria-label="Календарь задач">
        <div v-for="day in WEEKDAYS" :key="'dow-' + day" class="cal-dow">{{ day }}</div>
        <div v-for="cell in cells" :key="cell.key" class="cal-cell" :class="{ out: !cell.inMonth, today: cell.isToday }">
          <span class="cal-day">{{ cell.day }}</span>
          <router-link
            v-for="task in chipsOf(cell.key)"
            :key="task.id"
            class="cal-chip"
            :class="{ overdue: isOverdue(task), closed: isClosed(task) }"
            :to="'/projects/' + project.id + '/tasks/' + task.id"
            :title="task.title"
          >
            <span v-if="timeOf(task)" class="cal-time">{{ timeOf(task) }}</span>{{ task.title }}
          </router-link>
          <span v-if="moreOf(cell.key)" class="cal-more">+{{ moreOf(cell.key) }} ещё</span>
        </div>
      </div>
      <p v-if="!loading && !cells.some((cell) => chipsOf(cell.key).length)" class="muted cal-empty">
        Нет задач со сроками в этом месяце. Срок задаётся на странице задачи — там же настраивается повтор.
      </p>
    </template>
  </section>
</template>

<script>
import { computed, onMounted, ref, watch } from "vue"
import { api } from "../api"
import SkeletonList from "./SkeletonList.vue"
import { WEEKDAYS, buildMonth, dayOf, shiftMonth, tasksByDay } from "../composables/calendar"
import { formatWhen } from "../composables/formatDate"
import { useWhen } from "../composables/useWhen"

const MAX_CHIPS = 3

export default {
  components: { SkeletonList },
  props: { project: { type: Object, required: true } },
  setup(props) {
    const statuses = ref([])
    const tasks = ref([])
    const error = ref("")
    const unavailable = ref(false)
    const loading = ref(true)
    const showClosed = ref(false)
    const cursor = ref(monthCursor(new Date()))
    const { settings } = useWhen()

    function monthCursor(date) {
      return { year: date.getFullYear(), month: date.getMonth() }
    }

    const zone = computed(() => settings.get("core", "ui.timezone") || undefined)

    const grid = computed(() => buildMonth(cursor.value, dayOf(new Date(), zone.value)))

    const cells = computed(() => grid.value.weeks.flat())

    const closedIds = computed(() => new Set(statuses.value.filter((status) => status.is_closed).map((status) => status.id)))

    const byDay = computed(() => tasksByDay(tasks.value.filter((task) => showClosed.value || !closedIds.value.has(task.status_id)), zone.value))

    function chipsOf(key) {
      return (byDay.value.get(key) || []).slice(0, MAX_CHIPS)
    }

    function moreOf(key) {
      const total = (byDay.value.get(key) || []).length
      return total > MAX_CHIPS ? total - MAX_CHIPS : 0
    }

    function isOverdue(task) {
      if (!task.deadline || isClosed(task)) return false
      return new Date(task.deadline).getTime() < Date.now()
    }

    function isClosed(task) {
      return closedIds.value.has(task.status_id)
    }

    function timeOf(task) {
      const time = formatWhen(task.deadline, "HH:mm", zone.value)
      return time === "00:00" ? "" : time
    }

    function shift(delta) {
      cursor.value = shiftMonth(cursor.value, delta)
    }

    function goToday() {
      cursor.value = monthCursor(new Date())
    }

    async function load() {
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
        else error.value = err.message || "Календарь недоступен"
      } finally {
        loading.value = false
      }
    }

    watch(() => props.project.id, load)
    onMounted(load)
    return {
      WEEKDAYS, statuses, tasks, error, unavailable, loading, showClosed, cursor,
      grid, cells, chipsOf, moreOf, isOverdue, isClosed, timeOf, shift, goToday,
    }
  },
}
</script>
