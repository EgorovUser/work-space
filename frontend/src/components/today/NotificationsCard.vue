<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <h2>{{ item.title || "Уведомления" }}</h2>
    <p v-if="!notifications.length" class="muted">Уведомлений нет</p>
    <div v-for="row in notifications" :key="row.id" class="status-row">
      <div>
        <router-link v-if="row.link" :to="row.link">{{ row.title }}</router-link>
        <strong v-else :class="{ unread: !row.read }">{{ row.title }}</strong>
        <div v-if="row.body" class="muted clip">{{ row.body }}</div>
      </div>
      <span class="muted">{{ when(row.created_at) }}</span>
    </div>
  </section>
</template>

<script>
import { computed } from "vue"
import { useWhen } from "../../composables/useWhen"

// Элемент «Сегодня» — лента уведомлений пользователя.
export default {
  name: "TodayNotifications",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const { when } = useWhen()
    const notifications = computed(() => props.context.notifications || [])
    return { when, notifications }
  },
}
</script>
