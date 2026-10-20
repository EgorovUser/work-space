<template>
  <div class="setting">
    <h3>Файл базы</h3>
    <p v-if="info.path" class="muted">{{ info.path }}</p>
    <p class="muted">Файл {{ size(info.size_bytes) }}, журнал {{ size(info.wal_bytes) }}</p>
    <div class="row-actions">
      <button class="btn" type="button" :disabled="busy" @click="run('check')">Проверить целостность</button>
      <button class="btn secondary" type="button" :disabled="busy" @click="run('checkpoint')">Записать журнал</button>
      <button class="btn secondary" type="button" :disabled="busy" @click="run('vacuum')">Сжать</button>
      <button class="btn secondary" type="button" :disabled="busy" @click="run('reindex')">Пересобрать поиск</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="note" class="ok-text">{{ note }}</p>
  </div>
</template>

<script>
import { onMounted, ref } from "vue"
import { api } from "../api"

export default {
  setup() {
    const info = ref({ path: "", size_bytes: 0, wal_bytes: 0 })
    const busy = ref(false)
    const error = ref("")
    const note = ref("")

    function size(bytes) {
      const value = Number(bytes) || 0
      if (value < 1024) return value + " Б"
      if (value < 1024 * 1024) return (value / 1024).toFixed(1) + " КБ"
      return (value / 1024 / 1024).toFixed(1) + " МБ"
    }

    async function load() {
      info.value = await api("/api/system/db")
    }

    async function run(action) {
      busy.value = true
      error.value = ""
      note.value = ""
      try {
        const data = await api("/api/system/db/" + action, { method: "POST" })
        info.value = data
        note.value = data.detail || "Готово"
      } catch (err) {
        error.value = err.message || "Не вышло"
      } finally {
        busy.value = false
      }
    }

    onMounted(() => {
      load().catch((err) => {
        error.value = err.message || "База недоступна"
      })
    })

    return { info, busy, error, note, size, run }
  },
}
</script>
