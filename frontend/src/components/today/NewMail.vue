<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <h2>{{ item.title || "Новые письма" }}</h2>
    <div class="card-body">
      <p v-if="!letters.length" class="muted">Непрочитанных нет</p>
      <div v-if="letters.length" class="ui-items" :class="itemsClasses(item)">
        <div v-for="row in letters" :key="row.id" class="status-row">
          <div>
            <router-link :to="'/mail/' + row.id">{{ row.title }}</router-link>
            <span v-if="row.thread_count > 1" class="muted"> · {{ row.thread_count }} в переписке</span>
            <div class="muted">
              {{ row.project_name }}
              <span v-if="row.attachment_count"> · вложения {{ row.attachment_count }}</span>
            </div>
          </div>
          <span class="muted">{{ when(row.received_at) }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script>
import { computed } from "vue"
import { itemsClasses } from "../../ui/items.js"
import { useWhen } from "../../composables/useWhen"

// Элемент «Сегодня» — новые письма всех проектов. Внутренние строки —
// .card-body + .ui-items, как у остальных списков.
export default {
  name: "TodayNewMail",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const { when } = useWhen()
    const letters = computed(() => props.context.letters || [])
    return { when, letters, itemsClasses }
  },
}
</script>
