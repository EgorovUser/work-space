<template>
  <section>
    <form class="composer" @submit.prevent="add">
      <input v-model="draft" type="text" placeholder="Новая заметка" />
      <button class="btn" type="submit" :disabled="busy">Добавить</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="3" />
    <div v-else-if="!items.length" class="empty">
      <strong>Заметок пока нет</strong>
      <span>Заметка — быстрый черновик внутри проекта: ссылка, пароль на неделю, идея.</span>
    </div>
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
import SkeletonList from "../components/SkeletonList.vue"
import { useNotice } from "../composables/useNotice"
import { useWhen } from "../composables/useWhen"

export default {
  components: { SkeletonList },
  props: { project: { type: Object, required: true } },
  setup(props) {
    const items = ref([])
    const draft = ref("")
    const editId = ref(0)
    const editBody = ref("")
    const error = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const { settings, when } = useWhen()
    const notice = useNotice()

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
        notice.show("Заметка добавлена", { kind: "success" })
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
        notice.show("Заметка сохранена", { kind: "success" })
        await load()
      } catch (err) {
        error.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function remove(item) {
      if (!window.confirm("Удалить заметку? Отменить будет нельзя.")) return
      busy.value = true
      error.value = ""
      try {
        await api("/api/projects/" + props.project.id + "/notes/" + item.id, { method: "DELETE" })
        notice.show("Заметка удалена", { kind: "success" })
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
