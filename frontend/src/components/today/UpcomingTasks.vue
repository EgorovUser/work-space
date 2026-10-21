<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <h2>{{ item.title || "Ближайшие сроки" }}</h2>
    <div class="card-body">
      <p v-if="!upcoming.length" class="muted">Открытых задач со сроком нет</p>
      <div v-if="upcoming.length" class="ui-items" :class="itemsClasses(item)">
        <div v-for="row in upcoming" :key="row.id" class="status-row">
          <div>
            <router-link :to="'/projects/' + row.project_id + '/tasks/' + row.id">{{ row.title }}</router-link>
            <span v-if="priorityLabel(row.priority)" class="pill" :class="priorityClass(row.priority)">{{ priorityLabel(row.priority) }}</span>
            <div class="muted">{{ row.project_name }}</div>
          </div>
          <span class="muted">{{ when(row.deadline) }}</span>
        </div>
      </div>
    </div>
    <!-- Кнопка пагинации не прокручивается вместе со списком: она
         относится к карточке, а не к строкам. -->
    <div v-if="context.moreTasks" class="card-foot">
      <button
        class="btn secondary today-more"
        type="button"
        :disabled="context.moreBusy"
        @click="context.loadMoreTasks()"
      >{{ context.moreBusy ? "Загружаем…" : "Показать ещё задачи" }}</button>
    </div>
  </section>
</template>

<script>
import { computed } from "vue"
import { itemsClasses } from "../../ui/items.js"
import { priorityClass, priorityLabel } from "./priority.js"
import { useWhen } from "../../composables/useWhen"

// Элемент «Сегодня» — ближайшие сроки, с «Показать ещё» (пагинация
// задачи живут на странице, элемент только дёргает колбэк контекста).
// Внутренние строки — как у остальных списков: .card-body скроллится
// при фиксированной высоте, .ui-items раскладывает по конфигу.
export default {
  name: "TodayUpcomingTasks",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const { when } = useWhen()
    const upcoming = computed(() => props.context.upcoming || [])
    return { when, upcoming, priorityLabel, priorityClass, itemsClasses }
  },
}
</script>
