<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <h2>{{ item.title || "Ближайшие сроки" }}</h2>
    <p v-if="!upcoming.length" class="muted">Открытых задач со сроком нет</p>
    <div v-for="row in upcoming" :key="row.id" class="status-row">
      <div>
        <router-link :to="'/projects/' + row.project_id + '/tasks/' + row.id">{{ row.title }}</router-link>
        <span v-if="priorityLabel(row.priority)" class="pill" :class="priorityClass(row.priority)">{{ priorityLabel(row.priority) }}</span>
        <div class="muted">{{ row.project_name }}</div>
      </div>
      <span class="muted">{{ when(row.deadline) }}</span>
    </div>
    <button
      v-if="context.moreTasks"
      class="btn secondary today-more"
      type="button"
      :disabled="context.moreBusy"
      @click="context.loadMoreTasks()"
    >{{ context.moreBusy ? "Загружаем…" : "Показать ещё задачи" }}</button>
  </section>
</template>

<script>
import { computed } from "vue"
import { priorityClass, priorityLabel } from "./priority.js"
import { useWhen } from "../../composables/useWhen"

// Элемент «Сегодня» — ближайшие сроки, с «Показать ещё» (пагинация
// задачи живут на странице, элемент только дёргает колбэк контекста).
export default {
  name: "TodayUpcomingTasks",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const { when } = useWhen()
    const upcoming = computed(() => props.context.upcoming || [])
    return { when, upcoming, priorityLabel, priorityClass }
  },
}
</script>
