<template>
  <div>
    <h1>Документы</h1>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'add'">
    <form class="card stack" @submit.prevent="upload">
      <label>
        Файл
        <input ref="fileInput" type="file" @change="onFile" />
      </label>
      <label>
        Название
        <input v-model="title" type="text" placeholder="Если пусто — из имени файла" />
      </label>
      <label>
        Заметка
        <textarea v-model="note" />
      </label>
      <p v-if="formError" class="error">{{ formError }}</p>
      <div class="row-actions">
        <button class="btn" type="submit" :disabled="busy">Загрузить</button>
      </div>
    </form>
    </div>

    <div v-show="tab === 'list'">
    <label class="check">
      <input v-model="includeArchived" type="checkbox" @change="load" />
      <span>Показать архив</span>
    </label>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">Загрузка…</p>
    <p v-else-if="!items.length" class="muted">Документов нет</p>
    <div v-else class="list">
      <article v-for="item in items" :key="item.id" class="list-row">
        <div class="status-row">
          <div>
            <router-link :to="'/projects/' + project.id + '/documents/' + item.id">{{ item.title }}</router-link>
            <div class="muted">
              <span v-if="item.current">{{ item.current.original_name }} · версия {{ item.current.version_number }}</span>
              <span v-else>нет файла</span>
              <span v-if="item.archived"> · архив</span>
            </div>
          </div>
          <ActionMenu :actions="actionsFor(item)" @choose="onAction($event, item)" />
        </div>
      </article>
    </div>
    </div>
  </div>
</template>

<script>
import { ref, watch } from "vue"
import { useRouter } from "vue-router"
import { api } from "../api"
import Tabs from "../components/Tabs.vue"
import ActionMenu from "../components/ActionMenu.vue"
import { useSettings } from "../composables/useSettings"
import { useNotice } from "../composables/useNotice"
import { formatWhen } from "../composables/formatDate"

export default {
  components: { ActionMenu, Tabs },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const items = ref([])
    const error = ref("")
    const formError = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const title = ref("")
    const note = ref("")
    const file = ref(null)
    const fileInput = ref(null)
    const includeArchived = ref(false)
    const tab = ref("list")
    const pageTabs = [
      { id: "list", label: "Список" },
      { id: "add", label: "Загрузить" },
    ]
    const settings = useSettings()
    const notice = useNotice()
    const router = useRouter()

    function when(value) {
      return formatWhen(value, settings.get("core", "ui.date_format"), settings.get("core", "ui.timezone") || undefined)
    }

    function onFile(event) {
      const list = event.target.files
      file.value = list && list.length ? list[0] : null
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const flag = includeArchived.value ? "true" : "false"
        const data = await api("/api/projects/" + props.project.id + "/documents?include_archived=" + flag)
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
      body.append("title", title.value)
      body.append("note", note.value)
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/documents", { method: "POST", body })
        title.value = ""
        note.value = ""
        file.value = null
        if (fileInput.value) fileInput.value.value = ""
        await load()
      } catch (err) {
        formError.value = err.message || "Не удалось загрузить"
      } finally {
        busy.value = false
      }
    }

    function actionsFor(item) {
      const actions = [{ id: "open", label: "Открыть" }]
      if (item.current) actions.push({ id: "download", label: "Скачать" })
      actions.push({ id: "delete", label: "Удалить", danger: true })
      return actions
    }

    function onAction(action, item) {
      if (action === "open") router.push("/projects/" + props.project.id + "/documents/" + item.id)
      if (action === "download" && item.current) window.location.assign("/api/files/" + item.current.file_id)
      if (action === "delete") remove(item)
    }

    async function remove(item) {
      const snapshot = items.value.slice()
      items.value = items.value.filter((row) => row.id !== item.id)
      try {
        await api("/api/projects/" + props.project.id + "/documents/" + item.id, { method: "DELETE" })
      } catch (err) {
        items.value = snapshot
        notice.show("Не удалось удалить документ. " + (err.message || "Ошибка"))
      }
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).catch(() => {})
      load()
    }, { immediate: true })

    return { items, error, formError, loading, busy, title, note, fileInput, includeArchived, tab, pageTabs, onFile, load, upload, when, actionsFor, onAction }
  },
}
</script>
