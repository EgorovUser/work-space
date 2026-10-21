import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"
import { setUnauthorizedHandler } from "./api"
import { useAuth } from "./composables/useAuth"
import { useEvents } from "./composables/useEvents"
import "./styles.css"

const auth = useAuth()
setUnauthorizedHandler(() => {
  // Сессия протухла: мало увести на логин — SSE-канал продолжал бы
  // переподключаться с нарастающей паузой до перезагрузки страницы.
  useEvents().stop()
  auth.clear()
  if (router.currentRoute.value.path !== "/login") {
    const current = router.currentRoute.value
    const redirect = current.fullPath && current.fullPath !== "/" ? current.fullPath : null
    router.push(redirect ? { path: "/login", query: { redirect } } : "/login")
  }
})

const app = createApp(App)
app.use(router)
// Ошибки компонентов (рендер, setup, watcher) больше не глотаются молча:
// последний успешный рендер остаётся на экране, причина — в консоли.
app.config.errorHandler = (err, _instance, info) => {
  console.error("[app] ошибка Vue:", info, err)
}
app.mount("#app")
