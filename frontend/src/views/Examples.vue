<template>
  <div>
    <div class="page-head">
      <h1>Примеры</h1>
      <label class="check">
        <input v-model="includeArchived" type="checkbox" @change="load" />
        <span>Архив</span>
      </label>
    </div>
    <p class="muted">Сюда кладутся файлы, которые прислал заказчик: pdf, таблицы, документы, картинки. Текст не обязателен.</p>
    <form class="composer" @submit.prevent="upload">
      <input ref="fileInput" type="file" @change="onFile" />
      <input v-model="note" type="text" placeholder="Заметка, можно пустой" />
      <button class="btn" type="submit" :disabled="busy">Добавить файл</button>
    </form>
    <p v-if="formError" class="error">{{ formError }}</p>
    <form class="composer" @submit.prevent="load">
      <input v-model="query" type="text" placeholder="Найти по названию" />
      <button class="btn secondary" type="submit">Найти</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="4" />
    <div v-else-if="!items.length" class="empty">
      <strong>Файлов пока нет</strong>
      <span>Загрузите файл от заказчика формой выше — pdf, таблицу, картинку.</span>
    </div>
    <div v-else class="list">
      <article v-for="item in items" :key="item.id" class="list-row">
        <div class="status-row">
          <div>
            <router-link :to="'/projects/' + project.id + '/examples/' + item.id">{{ item.title }}</router-link>
            <div class="muted">
              <span v-if="item.files && item.files.length">{{ item.files.map((file) => file.original_name).join(", ") }}</span>
              <span v-else>файла нет</span>
              <span v-if="item.note"> · {{ item.note }}</span>
              <span v-if="item.archived"> · архив</span>
            </div>
          </div>
          <span class="muted">{{ when(item.updated_at) }}</span>
          <ActionMenu :actions="actionsFor(item)" @choose="onAction($event, item)" />
        </div>
      </article>
    </div>
  </div>
</template>

<script>
import { ref, watch } from "vue"
import { useRouter } from "vue-router"
import ActionMenu from "../components/ActionMenu.vue"
import SkeletonList from "../components/SkeletonList.vue"
import { api, downloadFile } from "../api"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { useSoftDelete } from "../composables/useSoftDelete"

export default {
  components: { ActionMenu, SkeletonList },
  props: { project: { type: Object, required: true } },
  setup(props) {
    const items = ref([])
    const error = ref("")
    const formError = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const query = ref("")
    const note = ref("")
    const file = ref(null)
    const fileInput = ref(null)
    const includeArchived = ref(false)
    const notice = useNotice()
    const { softRemove } = useSoftDelete()
    const router = useRouter()
    const { when } = useWhen()

    function onFile(event) {
      const list = event.target.files
      file.value = list && list.length ? list[0] : null
    }

    function actionsFor(item) {
      const actions = [{ id: "open", label: "Открыть" }]
      const first = item.files && item.files[0]
      if (first) actions.push({ id: "download", label: "Скачать" })
      actions.push({ id: "delete", label: "Удалить", danger: true })
      return actions
    }

    function onAction(action, item) {
      if (action === "open") router.push("/projects/" + props.project.id + "/examples/" + item.id)
      if (action === "download" && item.files && item.files[0]) downloadFile(item.files[0].file_id)
      if (action === "delete") remove(item)
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const params = new URLSearchParams()
        if (includeArchived.value) params.set("include_archived", "true")
        if (query.value.trim()) params.set("q", query.value.trim())
        const data = await api("/api/projects/" + props.project.id + "/examples?" + params.toString())
        items.value = data.items || []
      } catch (err) {
        items.value = []
        error.value = err.message || "Список недоступен"
      } finally {
        loading.value = false
      }
    }

    async function upload() {
      formError.value = ""
      if (!file.value) {
        formError.value = "Выберите файл"
        return
      }
      const body = new FormData()
      body.append("file", file.value)
      body.append("note", note.value)
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/examples/upload", { method: "POST", body })
        note.value = ""
        file.value = null
        if (fileInput.value) fileInput.value.value = ""
        notice.show("Пример загружен", { kind: "success" })
        await load()
      } catch (err) {
        formError.value = err.message || "Не удалось добавить"
      } finally {
        busy.value = false
      }
    }

    async function remove(item) {
      // Примеры удаляются окончательно (в корзину не попадают) — просто
      // подтверждаем действие, без кнопки отката.
      const snapshot = items.value.slice()
      items.value = items.value.filter((row) => row.id !== item.id)
      const ok = await softRemove({
        confirm: "Удалить пример «" + item.title + "» и его файлы?",
        url: "/api/projects/" + props.project.id + "/examples/" + item.id,
        doneText: "Пример «" + item.title + "» удалён",
      })
      if (!ok) items.value = snapshot
    }

    watch(() => props.project && props.project.id, load, { immediate: true })
    return { items, error, formError, loading, busy, query, note, fileInput, includeArchived, when, onFile, load, upload, actionsFor, onAction }
  },
}
</script>
