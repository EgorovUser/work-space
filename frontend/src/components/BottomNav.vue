<template>
  <nav class="bottom-nav" aria-label="Основная навигация">
    <router-link
      v-for="item in items"
      :key="item.to"
      :to="item.to"
      class="bottom-link"
      :class="{ active: active(item) }"
      :aria-current="active(item) ? 'page' : undefined"
    >
      <span class="bottom-ico" aria-hidden="true" v-html="item.icon" />
      <span class="bottom-label">{{ item.label }}</span>
      <span v-if="item.to === '/mail' && mailBadge" class="bottom-badge">{{ mailBadge }}</span>
    </router-link>
  </nav>
</template>

<script>
import { computed } from "vue"
import { useRoute } from "vue-router"
import { useEvents } from "../composables/useEvents"

// Нижняя навигация видна только на узких экранах (CSS): пять главных
// адресов приложения с иконками и площадью касания не меньше 44px.
// Бейдж почты — тот же счётчик SSE, что и в рельсе; двойной источник
// не заводим.

const STROKE = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'

const ITEMS = [
  {
    to: "/",
    label: "Проекты",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
  },
  {
    to: "/mail",
    label: "Почта",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
  },
  {
    to: "/notifications",
    label: "Уведомления",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
  },
  {
    to: "/settings",
    label: "Настройки",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>',
  },
  {
    to: "/system",
    label: "Состояние",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
  },
]

export default {
  setup() {
    const route = useRoute()
    const events = useEvents()

    const items = ITEMS

    function active(item) {
      if (item.to === "/") return route.path === "/"
      return route.path.startsWith(item.to)
    }

    const mailBadge = computed(() => {
      const value = events.mailUnread.value
      if (typeof value !== "number" || value <= 0) return ""
      return value > 99 ? "99+" : String(value)
    })

    return { items, active, mailBadge }
  },
}
</script>
