<template>
  <div class="login-wrap">
    <form class="card login-card stack" @submit.prevent="submit">
      <h1>{{ title || "Рабочее пространство" }}</h1>
      <p class="muted">Вход</p>
      <label>
        Логин
        <input v-model="username" type="text" autocomplete="username" required />
      </label>
      <label>
        Пароль
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
      <button class="btn" type="submit" :disabled="busy">Войти</button>
    </form>
  </div>
</template>

<script>
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { useAuth } from "../composables/useAuth"
import { useSettings } from "../composables/useSettings"

export default {
  setup() {
    const username = ref("")
    const password = ref("")
    const error = ref("")
    const busy = ref(false)
    const auth = useAuth()
    const settings = useSettings()
    const router = useRouter()

    onMounted(() => {
      settings.loadPublicTitle().catch(() => {})
    })

    async function submit() {
      error.value = ""
      busy.value = true
      try {
        await auth.login(username.value, password.value)
        router.push("/")
      } catch (err) {
        error.value = err.message || "Не удалось войти"
      } finally {
        busy.value = false
      }
    }

    return { username, password, error, busy, title: settings.title, submit }
  },
}
</script>
