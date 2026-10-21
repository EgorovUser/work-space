<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <h2>{{ item.title || "События на сегодня" }}</h2>
    <p v-if="!events.length" class="muted">Событий из почты на сегодня нет</p>
    <div v-for="row in events" :key="row.id" class="status-row">
      <div>
        <router-link :to="'/mail/' + row.message_id">{{ row.summary }}</router-link>
        <div v-if="row.location" class="muted">{{ row.location }}</div>
      </div>
      <span class="muted">{{ when(row.starts_at) }}</span>
    </div>
  </section>
</template>

<script>
import { computed } from "vue"
import { useWhen } from "../../composables/useWhen"

// Элемент «Сегодня» — события из писем на сегодня.
export default {
  name: "TodayMailEvents",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const { when } = useWhen()
    const events = computed(() => props.context.events || [])
    return { when, events }
  },
}
</script>
