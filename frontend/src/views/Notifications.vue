<template>
  <AppShell>
    <h1>Уведомления</h1>
    <Tabs v-model="tab" :tabs="pageTabs" />

    <div v-show="tab === 'inbox'">
    <div class="row-actions">
      <label class="check"><input v-model="unreadOnly" type="checkbox" @change="load" /><span>Только непрочитанные</span></label>
      <button class="btn secondary" type="button" :disabled="busy" @click="readAll">Прочитать все</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">Загрузка…</p>
    <p v-else-if="!items.length" class="muted">Уведомлений нет</p>
    <div v-else class="inbox-list">
      <article v-for="item in items" :key="item.id" class="inbox-row">
        <div>
          <strong :class="{ unread: !item.read }">{{ line(item) }}</strong>
          <div v-if="extra(item)" class="muted">{{ extra(item) }}</div>
        </div>
        <span class="when">{{ when(item.created_at) }}</span>
        <div class="inbox-actions">
          <router-link v-if="item.link" :to="item.link">Открыть</router-link>
          <button v-if="!item.read" class="text-btn" type="button" :disabled="busy" @click="read(item)">Прочитано</button>
        </div>
      </article>
    </div>
    </div>

    <section v-show="tab === 'routes'" class="card">
      <h2>Какие события куда слать</h2>
      <p class="muted">Наберите событие и выберите его. Можно несколько. Щелчок по плашке убирает его. Чтобы Telegram или почта реально ушли, заполните вкладку «Куда писать».</p>
      <div class="split">
        <label v-for="channel in channels" :key="channel.id">
          {{ channel.label }}
          <MultiSelect
            :options="events"
            :model-value="picked(channel.id)"
            placeholder="Найти событие"
            @update:model-value="setChannel(channel.id, $event)"
          />
        </label>
      </div>
      <p v-if="matrixError" class="error">{{ matrixError }}</p>
      <p v-if="matrixNote" class="ok-text">{{ matrixNote }}</p>
      <div class="row-actions">
        <button class="btn" type="button" :disabled="busy" @click="saveMatrix">Сохранить</button>
      </div>
    </section>

    <ChannelSetup v-if="tab === 'setup'" />
  </AppShell>
</template>

<script>
import { onMounted, ref } from "vue"
import AppShell from "../components/AppShell.vue"
import MultiSelect from "../components/MultiSelect.vue"
import ChannelSetup from "../components/ChannelSetup.vue"
import Tabs from "../components/Tabs.vue"
import { api } from "../api"
import { useSettings } from "../composables/useSettings"
import { useNotice } from "../composables/useNotice"
import { formatWhen } from "../composables/formatDate"

export default {
  components: { AppShell, ChannelSetup, MultiSelect, Tabs },
  setup() {
    const items = ref([])
    const events = ref([])
    const channels = ref([])
    const matrix = ref({})
    const error = ref("")
    const matrixError = ref("")
    const matrixNote = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const unreadOnly = ref(false)
    const tab = ref("inbox")
    const pageTabs = [
      { id: "inbox", label: "Входящие" },
      { id: "routes", label: "Какие события" },
      { id: "setup", label: "Куда писать" },
    ]
    const settings = useSettings()
    const notice = useNotice()

    function when(value) {
      return formatWhen(value, settings.get("core", "ui.date_format"), settings.get("core", "ui.timezone") || undefined)
    }

    function line(item) {
      const event = String(item.event_label || "").trim()
      const title = String(item.title || "").trim()
      if (event && title && event !== title) return event + " · " + title
      return title || event || "Уведомление"
    }

    function extra(item) {
      const body = String(item.body || "").trim()
      if (!body) return ""
      const event = String(item.event_label || "").trim()
      const title = String(item.title || "").trim()
      if (body === event || body === title || body === line(item)) return ""
      return body
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const params = unreadOnly.value ? "?unread_only=true" : ""
        const data = await api("/api/notifications" + params)
        items.value = data.items || []
      } catch (err) {
        error.value = err.message || "Список недоступен"
      } finally {
        loading.value = false
      }
    }

    async function loadMeta() {
      const data = await api("/api/notifications/meta")
      events.value = data.events || []
      channels.value = data.channels || []
      const next = {}
      for (const event of events.value) {
        next[event.id] = {}
        const source = (data.matrix && data.matrix[event.id]) || {}
        for (const channel of channels.value) next[event.id][channel.id] = Boolean(source[channel.id])
      }
      matrix.value = next
    }

    function picked(channelId) {
      return events.value
        .filter((event) => matrix.value[event.id] && matrix.value[event.id][channelId])
        .map((event) => event.id)
    }

    function setChannel(channelId, ids) {
      const chosen = new Set(ids)
      for (const event of events.value) {
        if (!matrix.value[event.id]) matrix.value[event.id] = {}
        matrix.value[event.id][channelId] = chosen.has(event.id)
      }
    }

    async function saveMatrix() {
      matrixError.value = ""
      matrixNote.value = ""
      busy.value = true
      try {
        await api("/api/settings", {
          method: "PUT",
          body: { module: "notifications", key: "matrix", scope: "user", value: matrix.value },
        })
        matrixNote.value = "Сохранено"
      } catch (err) {
        matrixError.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function read(item) {
      const previous = item.read
      item.read = true
      try {
        await api("/api/notifications/" + item.id + "/read", { method: "POST" })
      } catch (err) {
        item.read = previous
        notice.show("Не удалось отметить уведомление. " + (err.message || "Ошибка"))
      }
    }

    async function readAll() {
      const snapshot = items.value.map((item) => item.read)
      items.value.forEach((item) => { item.read = true })
      try {
        await api("/api/notifications/read-all", { method: "POST" })
      } catch (err) {
        items.value.forEach((item, index) => { item.read = snapshot[index] })
        notice.show("Не удалось отметить уведомления. " + (err.message || "Ошибка"))
      }
    }

    onMounted(() => {
      settings.load().catch(() => {})
      loadMeta().catch((err) => { error.value = err.message || "Матрица недоступна" })
      load()
    })

    return {
      items, events, channels, matrix, error, matrixError, matrixNote, loading, busy, unreadOnly, tab, pageTabs,
      when, line, extra, load, saveMatrix, read, readAll, picked, setChannel,
    }
  },
}
</script>
