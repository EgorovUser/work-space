<template>
  <div class="app">
    <aside class="rail">
      <div class="brand">{{ title || "Рабочее пространство" }}</div>
      <nav class="rail-nav">
        <router-link to="/">Сегодня</router-link>
        <router-link to="/projects">Проекты</router-link>
        <router-link to="/mail">Почта<span v-if="mailBadge" class="rail-badge">{{ mailBadge }}</span></router-link>
        <router-link to="/secrets">Секреты</router-link>
        <router-link to="/notifications">Уведомления</router-link>
        <router-link to="/settings">Настройки</router-link>
        <router-link to="/system">Состояние</router-link>
      </nav>
      <div class="rail-foot">
        <div v-if="user" class="rail-user">{{ user.display_name || user.username }}</div>
        <button class="btn secondary" type="button" @click="onLogout">Выйти</button>
      </div>
    </aside>
    <main class="app-main">
      <header class="topbar">
        <div class="topbar-title">{{ heading }}</div>
        <GlobalSearch />
        <div class="topbar-tools">
          <ThemeToggle />
          <Bell />
        </div>
      </header>
      <div class="app-body" :class="bare ? 'bare' : 'page'">
        <slot />
      </div>
    </main>
    <!-- Нижняя навигация для телефонов: CSS прячет её на широких экранах. -->
    <BottomNav />
  </div>
</template>

<script>
import { computed, onMounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import Bell from "./Bell.vue"
import BottomNav from "./BottomNav.vue"
import ThemeToggle from "./ThemeToggle.vue"
import GlobalSearch from "./GlobalSearch.vue"
import { useAuth } from "../composables/useAuth"
import { useChrome } from "../composables/useChrome"
import { useEvents } from "../composables/useEvents"
import { useSettings } from "../composables/useSettings"

// Рельса несёт только глобальные разделы. Навигация внутри проекта живёт
// в горизонтальных табах под шапкой (ProjectLayout) — раньше ссылки
// проекта сваливались в этот же столбец, и в нём было 13 строк.
export default {
  props: {
    bare: { type: Boolean, default: false },
  },
  components: { Bell, BottomNav, ThemeToggle, GlobalSearch },
  setup(props) {
    const auth = useAuth()
    const settings = useSettings()
    const chrome = useChrome()
    const events = useEvents()
    const router = useRouter()
    const route = useRoute()

    const heading = computed(() => {
      if (chrome.caption.value) return chrome.caption.value
      if (route.path === "/") return "Сегодня"
      if (route.path.startsWith("/projects")) return "Проекты"
      if (route.path.startsWith("/mail")) return "Почта"
      if (route.path.startsWith("/secrets")) return "Секреты"
      if (route.path.startsWith("/notifications")) return "Уведомления"
      if (route.path.startsWith("/settings")) return "Настройки"
      if (route.path.startsWith("/system")) return "Состояние"
      return settings.title.value || "Сегодня"
    })

    const mailBadge = computed(() => {
      const value = events.mailUnread.value
      if (typeof value !== "number" || value <= 0) return ""
      return value > 99 ? "99+" : String(value)
    })

    onMounted(() => {
      settings.load().catch(() => {})
      events.start()
    })

    async function onLogout() {
      events.stop()
      await auth.logout()
      router.push("/login")
    }

    return {
      user: auth.user,
      title: settings.title,
      bare: computed(() => props.bare),
      caption: chrome.caption,
      heading,
      mailBadge,
      route,
      onLogout,
    }
  },
}
</script>
