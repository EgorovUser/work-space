<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <div class="page-head">
      <h2>{{ item.title || "Проекты" }}</h2>
      <router-link to="/projects" class="text-btn">Все проекты →</router-link>
    </div>
    <div class="card-body">
      <p v-if="!projects.length" class="muted">
        Проектов пока нет —
        <router-link to="/projects">создайте первый</router-link>.
      </p>
      <!-- .ui-items задаёт раскладку строк (колонки/выравнивание/отступы),
           .list — привычную рамку списка: классы соседствуют, сетка
           designer.css приходит позже и отвечает за раскладку. -->
      <div v-else class="list ui-items" :class="itemsClasses(item)">
        <router-link v-for="project in projects" :key="project.id" class="list-row" :to="'/projects/' + project.id">
          <strong>{{ project.name }}</strong>
          <span v-if="project.description" class="muted clip">{{ project.description }}</span>
          <span class="stats">
            <span v-if="project.card.show_open_tasks">Открытые {{ project.open_tasks ?? "—" }}</span>
            <span v-if="project.card.show_overdue && project.overdue_tasks">Просроченные {{ project.overdue_tasks }}</span>
            <span v-if="project.card.show_new_mail && project.new_mail">Письма {{ project.new_mail }}</span>
          </span>
        </router-link>
      </div>
    </div>
  </section>
</template>

<script>
import { computed } from "vue"
import { itemsClasses } from "../../ui/items.js"

// Элемент «Сегодня» — быстрый список проектов. Внутренние строки —
// .card-body + .ui-items поверх привычной .list-рамки.
export default {
  name: "TodayProjects",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const projects = computed(() => props.context.projects || [])
    return { projects, itemsClasses }
  },
}
</script>
