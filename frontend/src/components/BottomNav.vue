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
      <span
        v-if="item.key && badge(item.key)"
        class="bottom-badge"
        :class="{ zero: zero(item.key), alert: Boolean(item.alert) && !zero(item.key) }"
        >{{ badge(item.key) }}</span
      >
    </router-link>
  </nav>
</template>

<script>
import { useRoute } from "vue-router"
import { useCounters } from "../composables/useCounters"
import { railCount } from "../composables/countFormat"

// Нижняя навигация видна только на узких экранах (CSS): шесть главных
// адресов приложения с иконками и площадью касания не меньше 44px.
// «Состояние» — редкая диагностика, она осталась в рельсе; палец на
// телефоне должен тянуться к ежедневному, а не к техническому.
// Бейджи — тот же хаб счётчиков, что и в рельсе (патч U): почта, секреты,
// уведомления; двойной источник не заводим. Патч AH: красным остаётся
// только непрочитанные уведомления, остальные числа — спокойные.

const STROKE = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'

const ITEMS = [
  {
    to: "/",
    label: "Сегодня",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>',
  },
  {
    to: "/projects",
    label: "Проекты",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
  },
  {
    to: "/mail",
    label: "Почта",
    key: "mail_unread",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
  },
  {
    to: "/secrets",
    label: "Секреты",
    key: "secrets_total",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.8 12.2 8.7-8.7"/><path d="m16.2 4.3 3.5 3.5"/><path d="m13.5 7 3.5 3.5"/></svg>',
  },
  {
    to: "/notifications",
    label: "Уведомления",
    key: "notifications_unread",
    alert: true,
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
  },
  {
    to: "/settings",
    label: "Настройки",
    icon:
      '<svg viewBox="0 0 24 24" ' + STROKE + '><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>',
  },
]

export default {
  setup() {
    const route = useRoute()
    const counters = useCounters()
    const globalCounts = counters.globalCounts

    const items = ITEMS

    function active(item) {
      if (item.to === "/") return route.path === "/"
      return route.path.startsWith(item.to)
    }

    function badge(key) {
      return railCount(globalCounts.value ? globalCounts.value[key] : null)
    }

    function zero(key) {
      return !globalCounts.value || !globalCounts.value[key]
    }

    return { items, active, badge, zero }
  },
}
</script>
