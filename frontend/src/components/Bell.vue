<template>
  <Pop class="bell" placement="up">
    <template #trigger="{ toggle }">
      <button class="btn secondary" type="button" @click="toggle">
        Новые
        <span v-if="count" class="bell-count">{{ count }}</span>
      </button>
    </template>
    <template #default="{ close }">
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!items.length" class="muted">Нет новых</p>
      <ul v-else class="plain-list">
        <li v-for="item in items" :key="item.id">
          <router-link :to="item.link || '/notifications'" @click="read(item, close)">{{ item.title }}</router-link>
          <div class="muted">{{ item.event_label }}</div>
        </li>
      </ul>
      <p><router-link to="/notifications" @click="close">Все уведомления</router-link></p>
    </template>
  </Pop>
</template>

<script>
import { onBeforeUnmount, onMounted, ref } from "vue"
import Pop from "./Pop.vue"
import { api } from "../api"
import { useSettings } from "../composables/useSettings"
import { useNotice } from "../composables/useNotice"

export default {
  components: { Pop },
  setup() {
    const items = ref([])
    const count = ref(0)
    const error = ref("")
    const settings = useSettings()
    const notice = useNotice()
    let timer = null

    async function load() {
      try {
        const data = await api("/api/notifications/unread")
        items.value = data.items || []
        count.value = data.count || 0
        error.value = ""
      } catch (err) {
        error.value = err.message || "Не удалось загрузить"
      }
    }

    async function read(item, close) {
      close()
      const previousItems = items.value.slice()
      const previousCount = count.value
      items.value = items.value.filter((row) => row.id !== item.id)
      count.value = Math.max(0, count.value - 1)
      try {
        await api("/api/notifications/" + item.id + "/read", { method: "POST" })
      } catch (err) {
        items.value = previousItems
        count.value = previousCount
        notice.show("Не удалось отметить уведомление. " + (err.message || "Ошибка"))
      }
    }

    function arm() {
      clearInterval(timer)
      const seconds = Number(settings.get("core", "ui.poll_notifications_seconds")) || 30
      timer = setInterval(load, Math.max(5, seconds) * 1000)
    }

    onMounted(() => {
      settings.load().catch(() => {}).finally(() => {
        load()
        arm()
      })
    })
    onBeforeUnmount(() => clearInterval(timer))

    return { items, count, error, read }
  },
}
</script>
