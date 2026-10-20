<template>
  <AppShell>
    <div class="page-head">
      <h1>Учёт времени</h1>
      <span class="muted">все проекты · недели с понедельника</span>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="6" />

    <template v-else>
      <div class="week-grid">
        <section class="card week-card" :class="{ active: tab === 'current' }">
          <h2>Текущая неделя</h2>
          <p class="muted week-range">{{ range(data.current_week) }}</p>
          <div class="week-hours">{{ formatDuration(data.current_week.total_minutes) }}</div>
          <span v-if="delta !== null" class="pill" :class="delta > 0 ? 'ok' : delta < 0 ? 'low' : ''">
            {{ delta > 0 ? "+" : "" }}{{ deltaLabel }} к прошлой
          </span>
        </section>
        <section class="card week-card" :class="{ active: tab === 'previous' }">
          <h2>Прошлая неделя</h2>
          <p class="muted week-range">{{ range(data.previous_week) }}</p>
          <div class="week-hours">{{ formatDuration(data.previous_week.total_minutes) }}</div>
        </section>
      </div>

      <Tabs v-model="tab" :tabs="pageTabs" />

      <p v-if="!block.projects.length" class="muted">За эту неделю записей нет ни в одном проекте.</p>
      <section v-for="project in block.projects" :key="project.project_id" class="card">
        <div class="status-row">
          <div>
            <router-link :to="'/projects/' + project.project_id + '/time'">
              {{ project.project_name }}
              <span v-if="project.project_archived" class="pill warn">Архив</span>
            </router-link>
          </div>
          <strong>{{ formatDuration(project.minutes) }}</strong>
        </div>
        <ul class="plain-list">
          <li v-for="entry in project.entries" :key="entry.id">
            <span class="muted">{{ dayLabel(entry.day) }}</span> ·
            <router-link v-if="entry.task_id" :to="'/projects/' + project.project_id + '/tasks/' + entry.task_id">{{ entry.task_title }}</router-link>
            <template v-else>без задачи</template>
            — {{ formatDuration(entry.minutes) }}<span v-if="entry.running" class="pill">идёт</span>
            <div v-if="entry.note" class="muted">{{ entry.note }}</div>
          </li>
        </ul>
      </section>
    </template>
  </AppShell>
</template>

<script>
import { computed, onMounted, ref } from "vue"
import AppShell from "../components/AppShell.vue"
import SkeletonList from "../components/SkeletonList.vue"
import Tabs from "../components/Tabs.vue"
import { api } from "../api"
import { formatDuration } from "../composables/timeFormat"

// Глобальная сводка времени (патч S): две недели рядом — текущая и прошлая,
// границы с понедельника (настройка timetracking.week.starts_on). Внутри —
// сколько часов в каждом проекте и что именно делалось: записи с задачами
// и заметками. Проектная страница «Учёт времени» остаётся для таймера и
// правки записей конкретного проекта.
export default {
  components: { AppShell, SkeletonList, Tabs },
  setup() {
    const data = ref(null)
    const error = ref("")
    const loading = ref(true)
    const tab = ref("current")
    const pageTabs = [
      { id: "current", label: "Текущая неделя" },
      { id: "previous", label: "Прошлая неделя" },
    ]

    const block = computed(() => {
      if (!data.value) return { projects: [] }
      return tab.value === "previous" ? data.value.previous_week : data.value.current_week
    })

    // Разница недель в минутах: null — ещё нет данных для сравнения.
    const delta = computed(() => {
      if (!data.value) return null
      return data.value.current_week.total_minutes - data.value.previous_week.total_minutes
    })

    const deltaLabel = computed(() => {
      if (delta.value === null) return ""
      return formatDuration(Math.abs(delta.value))
    })

    function range(week) {
      if (!week) return ""
      return shortDay(week.start) + " — " + shortDay(week.end)
    }

    function shortDay(iso) {
      const [year, month, day] = String(iso || "").split("-")
      if (!year || !month || !day) return ""
      return day + "." + month
    }

    function dayLabel(iso) {
      const value = String(iso || "")
      if (!value) return ""
      return value.slice(8, 10) + "." + value.slice(5, 7)
    }

    async function load() {
      error.value = ""
      loading.value = true
      try {
        data.value = await api("/api/time/overview")
      } catch (err) {
        data.value = null
        error.value = err.message || "Учёт недоступен"
      } finally {
        loading.value = false
      }
    }

    onMounted(load)
    return { data, error, loading, tab, pageTabs, block, delta, deltaLabel, range, dayLabel, formatDuration }
  },
}
</script>
