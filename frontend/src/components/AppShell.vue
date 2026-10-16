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
      <div class="rail-foot">
        <Bell />
        <div v-if="user" class="rail-user">{{ user.display_name || user.username }}</div>
        <button class="btn secondary" type="button" @click="onLogout">Выйти</button>
      </div>
    </aside>
    <main class="app-main">
      <div :class="bare ? '' : 'page'">
        <slot />
      </div>
    </main>
  </div>
</template>

<script>
import { computed, onMounted } from "vue"
import { useRouter } from "vue-router"
import Bell from "./Bell.vue"
import { useAuth } from "../composables/useAuth"
import { useSettings } from "../composables/useSettings"

export default {
  props: {
    bare: { type: Boolean, default: false },
  },
  components: { Bell },
  setup(props) {
    const auth = useAuth()
    const settings = useSettings()
    const router = useRouter()

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
      onLogout,
    }
  },
}
</script>
