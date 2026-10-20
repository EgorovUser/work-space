<template>
  <div class="app">
    <aside class="rail">
      <div class="brand">{{ title || "Рабочее пространство" }}</div>
      <nav class="rail-nav">
        <router-link to="/">Проекты</router-link>
        <router-link to="/mail">Почта</router-link>
        <router-link to="/notifications">Уведомления</router-link>
        <router-link to="/settings">Настройки</router-link>
        <router-link to="/system">Состояние</router-link>
      </nav>
      <nav v-if="extra.length" class="rail-nav">
        <div class="rail-label">{{ caption }}</div>
        <router-link
          v-for="link in extra"
          :key="link.to"
          :to="link.to"
          :class="{ 'router-link-active': link.exact ? route.path === link.to : route.path.startsWith(link.to) }"
        >
          {{ link.label }}
        </router-link>
      </nav>
      <div class="rail-foot">
        <div v-if="user" class="rail-user">{{ user.display_name || user.username }}</div>
        <button class="btn secondary" type="button" @click="onLogout">Выйти</button>
      </div>
    </aside>
    <main class="app-main">
      <header class="topbar">
        <div class="topbar-title">{{ heading }}</div>
        <div class="topbar-tools">
          <ThemeToggle />
          <Bell />
        </div>
      </header>
      <div class="app-body" :class="bare ? 'bare' : 'page'">
        <slot />
      </div>
    </main>
  </div>
</template>

<script>
import { computed, onMounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import Bell from "./Bell.vue"
import ThemeToggle from "./ThemeToggle.vue"
import { useAuth } from "../composables/useAuth"
import { useChrome } from "../composables/useChrome"
import { useSettings } from "../composables/useSettings"

export default {
  props: {
    bare: { type: Boolean, default: false },
  },
  components: { Bell, ThemeToggle },
  setup(props) {
    const auth = useAuth()
    const settings = useSettings()
    const chrome = useChrome()
    const router = useRouter()
    const route = useRoute()

    const heading = computed(() => {
      if (chrome.caption.value) return chrome.caption.value
      if (route.path.startsWith("/mail")) return "Почта"
      if (route.path.startsWith("/notifications")) return "Уведомления"
      if (route.path.startsWith("/settings")) return "Настройки"
      if (route.path.startsWith("/system")) return "Состояние"
      return settings.title.value || "Проекты"
    })

    onMounted(() => {
      settings.load().catch(() => {})
    })

    async function onLogout() {
      await auth.logout()
      router.push("/login")
    }

    return {
      user: auth.user,
      title: settings.title,
      bare: computed(() => props.bare),
      caption: chrome.caption,
      extra: chrome.extra,
      heading,
      route,
      onLogout,
    }
  },
}
</script>
