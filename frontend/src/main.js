import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"
import { setUnauthorizedHandler } from "./api"
import { useAuth } from "./composables/useAuth"
import "./styles.css"

const auth = useAuth()
setUnauthorizedHandler(() => {
  auth.clear()
  if (router.currentRoute.value.path !== "/login") {
    router.push("/login")
  }
})

createApp(App).use(router).mount("#app")
