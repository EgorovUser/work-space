<template>
  <section>
    <form class="composer" @submit.prevent="add">
      <input v-model="draft" type="text" placeholder="Новая заметка" />
      <button class="btn" type="submit" :disabled="busy">Добавить</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">Загрузка…</p>
    <p v-else-if="!items.length" class="muted">Заметок нет</p>
    <div v-else class="inbox-list">
      <article v-for="item in items" :key="item.id" class="inbox-row">
        <form v-if="editId === item.id" class="composer" @submit.prevent="save(item)">
          <input v-model="editBody" type="text" />
          <button class="btn" type="submit" :disabled="busy">Сохранить</button>
          <button class="btn secondary" type="button" @click="editId = 0">Отмена</button>
        </form>
        <template v-else>
          <div>{{ item.body }}</div>
          <span class="when">{{ when(item.updated_at) }}</span>
          <div class="inbox-actions">
            <button class="text-btn" type="button" @click="begin(item)">Изменить</button>
            <button class="text-btn" type="button" @click="remove(item)">Удалить</button>
          </div>
        </template>
      </article>
    </div>
  </section>
</template>

<script>
import { onMounted, ref } from "vue"
import { api } from "../api"
import { useSettings } from "../composables/useSettings"
import { formatWhen } from "../composables/formatDate"

export default {
  props: { project: { type: Object, required: true } },
  setup(props) {
    const items = ref([])
    const draft = ref("")
    const editId = ref(0)
    const editBody = ref("")
    const error = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const settings = useSettings()

    function when(value) {
      return formatWhen(value, settings.get("core", "ui.date_format"), settings.get("core", "ui.timezone") || undefined)
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const data = await api("/api/projects/" + props.project.id + "/notes")
        items.value = data.items || []
      } catch (err) {
        error.value = err.message || "Заметки недоступны"
      } finally {
        loading.value = false
      }
    }

    async function add() {
      const body = draft.value.trim()
      if (!body) return
      busy.value = true
      error.value = ""
      try {
        await api("/api/projects/" + props.project.id + "/notes", { method: "POST", body: { body } })
        draft.value = ""
        await load()
      } catch (err) {
        error.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    function begin(item) {
      editId.value = item.id
      editBody.value = item.body
    }

    async function save(item) {
      busy.value = true
      error.value = ""
      try {
        await api("/api/projects/" + props.project.id + "/notes/" + item.id, {
          method: "PATCH",
          body: { body: editBody.value },
        })
        editId.value = 0
        await load()
      } catch (err) {
        error.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function remove(item) {
      busy.value = true
      error.value = ""
      try {
        await api("/api/projects/" + props.project.id + "/notes/" + item.id, { method: "DELETE" })
        await load()
      } catch (err) {
        error.value = err.message || "Не удалилось"
      } finally {
        busy.value = false
      }
    }

    onMounted(() => {
      settings.load(props.project.id).catch(() => {})
      load()
    })

    return { items, draft, editId, editBody, error, loading, busy, when, add, begin, save, remove }
  },
}
</script>
