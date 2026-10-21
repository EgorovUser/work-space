<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <h2>{{ item.title || "Просроченные" }} <span v-if="overdue.length" class="pill warn">{{ overdue.length }}</span></h2>
    <p v-if="!overdue.length" class="muted">Просроченных нет — можно выдыхать</p>
    <div v-for="row in overdue" :key="row.id" class="status-row">
      <div>
        <router-link :to="'/projects/' + row.project_id + '/tasks/' + row.id">{{ row.title }}</router-link>
        <span v-if="priorityLabel(row.priority)" class="pill" :class="priorityClass(row.priority)">{{ priorityLabel(row.priority) }}</span>
        <div class="muted">{{ row.project_name }}</div>
      </div>
      <span class="bad-text">{{ when(row.deadline) }}</span>
    </div>
  </section>
</template>

<script>
import { computed } from "vue"
import { priorityClass, priorityLabel } from "./priority.js"
import { useWhen } from "../../composables/useWhen"

// Элемент «Сегодня» — просроченные задачи. Данные приходят в контексте
// страницы (сводка /api/home), элемент ведает только показом.
export default {
  name: "TodayOverdueTasks",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const { when } = useWhen()
    const overdue = computed(() => props.context.overdue || [])
    return { when, overdue, priorityLabel, priorityClass }
  },
}
</script>
