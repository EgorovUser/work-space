<template>
  <Pop align="end" wide>
    <template #trigger="{ toggle, open }">
      <button class="icon-btn" type="button" :class="{ on: open }" title="Уведомления" @click="toggle">
        Новые
        <span v-if="count" class="bell-count">{{ count > 99 ? "99+" : count }}</span>
      </button>
    </template>
    <template #default="{ close }">
      <div class="bell-head">
        <strong>Уведомления</strong>
        <button class="text-btn" type="button" :disabled="!count || busy" @click="readAll">Прочитать все</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!items.length" class="muted">Новых нет</p>
      <div v-else class="bell-list">
        <article v-for="item in items" :key="item.id" class="bell-item">
          <div>
            <router-link :to="item.link || '/notifications'" @click="read(item, close)">{{ item.title }}</router-link>
            <div class="muted">{{ item.event_label }}</div>
          </div>
          <button class="text-btn" type="button" :disabled="busy" @click="read(item)">Прочитано</button>
        </article>
      </div>
      <div class="bell-foot">
        <router-link to="/notifications" @click="close">Все уведомления</router-link>
      </div>
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
    const busy = ref(false)
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
        if (err.status !== 401) error.value = err.message || "Не удалось загрузить"
      }
    }

    async function read(item, close) {
      if (close) close()
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

    async function readAll() {
      busy.value = true
      const previousItems = items.value.slice()
      const previousCount = count.value
      items.value = []
      count.value = 0
      try {
        await api("/api/notifications/read-all", { method: "POST" })
      } catch (err) {
        items.value = previousItems
        count.value = previousCount
        notice.show("Не удалось отметить уведомления. " + (err.message || "Ошибка"))
      } finally {
        busy.value = false
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

    return { items, count, error, busy, read, readAll }
  },
}
</script>
