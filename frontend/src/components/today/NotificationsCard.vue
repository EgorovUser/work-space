<template>
  <section class="card" :class="{ 'density-compact': item.density === 'compact' }">
    <h2>{{ item.title || "Уведомления" }}</h2>
    <div class="card-body">
      <p v-if="!notifications.length" class="muted">Уведомлений нет</p>
      <div v-if="notifications.length" class="ui-items" :class="itemsClasses(item)">
        <div v-for="row in notifications" :key="row.id" class="status-row">
          <div>
            <router-link v-if="row.link" :to="row.link">{{ row.title }}</router-link>
            <strong v-else :class="{ unread: !row.read }">{{ row.title }}</strong>
            <div v-if="row.body" class="muted clip">{{ row.body }}</div>
          </div>
          <span class="muted">{{ when(row.created_at) }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script>
import { computed } from "vue"
import { itemsClasses } from "../../ui/items.js"
import { useWhen } from "../../composables/useWhen"

// Элемент «Сегодня» — лента уведомлений пользователя. Внутренние строки —
// .card-body + .ui-items, как у остальных списков.
export default {
  name: "TodayNotifications",
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup(props) {
    const { when } = useWhen()
    const notifications = computed(() => props.context.notifications || [])
    return { when, notifications, itemsClasses }
  },
}
</script>
