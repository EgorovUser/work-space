import { ref } from "vue"
import { api } from "../api"

const user = ref(null)
const ready = ref(false)

export function useAuth() {
  async function refresh() {
    try {
      const data = await api("/api/auth/me")
      user.value = data && data.id ? data : null
    } catch (error) {
      user.value = null
      if (!error || error.status !== 401) {
        throw error
      }
    } finally {
      ready.value = true
    }
  }

  async function login(username, password) {
    user.value = await api("/api/auth/login", {
      method: "POST",
      body: { username, password },
    })
    ready.value = true
  }

  async function logout() {
    await api("/api/auth/logout", { method: "POST", body: {} })
    user.value = null
  }

  function clear() {
    user.value = null
    ready.value = true
  }

  return { user, ready, refresh, login, logout, clear }
}
