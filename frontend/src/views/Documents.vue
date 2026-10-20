<template>
  <div>
    <h1>Документы</h1>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'add'">
    <form class="card stack" @submit.prevent="upload">
      <div
        class="dropzone"
        :class="{ over: dragOver }"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <p class="muted">Перетащите файл сюда или выберите кнопкой ниже · до {{ maxUploadMb }} МБ</p>
        <label>
          Файл
          <input ref="fileInput" type="file" @change="onFile" />
        </label>
        <p v-if="file" class="muted">{{ file.name }} · {{ formatSize(file.size) }}</p>
      </div>
      <label>
        Название
        <input v-model="title" type="text" placeholder="Если пусто — из имени файла" />
      </label>
      <label>
        Заметка
        <textarea v-model="note" />
      </label>
      <div v-if="progress > 0" class="progress"><span :style="{ width: progress + '%' }" /></div>
      <p v-if="formError" class="error">{{ formError }}</p>
      <div class="row-actions">
        <button class="btn" type="submit" :disabled="busy">{{ busy ? "Загружаем…" : "Загрузить" }}</button>
      </div>
    </form>
    </div>

    <div v-show="tab === 'list'">
    <label class="check">
      <input v-model="includeArchived" type="checkbox" @change="load" />
      <span>Показать архив</span>
    </label>

    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="4" />
    <div v-else-if="!items.length" class="empty">
      <strong>Документов пока нет</strong>
      <span>Перетащите файл в область загрузки выше или выберите его кнопкой.</span>
    </div>
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
import { computed, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { api, downloadFile, uploadApi } from "../api"
import Tabs from "../components/Tabs.vue"
import ActionMenu from "../components/ActionMenu.vue"
import SkeletonList from "../components/SkeletonList.vue"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { formatSize } from "../composables/formatBytes"

export default {
  components: { ActionMenu, Tabs, SkeletonList },
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
    const dragOver = ref(false)
    const progress = ref(0)
    const { settings, when } = useWhen()
    const notice = useNotice()
    const router = useRouter()

    const maxUploadMb = computed(() => Number(settings.get("files", "max_upload_mb")) || 50)

    function pickFile(chosen) {
      if (!chosen) {
        file.value = null
        return
      }
      const limit = maxUploadMb.value * 1024 * 1024
      if (chosen.size > limit) {
        file.value = null
        formError.value = "Файл больше " + maxUploadMb.value + " МБ — сервер его не примет. Сожмите или разбейте файл."
        return
      }
      formError.value = ""
      file.value = chosen
    }

    function onFile(event) {
      const list = event.target.files
      pickFile(list && list.length ? list[0] : null)
    }

    function onDrop(event) {
      dragOver.value = false
      const list = event.dataTransfer && event.dataTransfer.files
      pickFile(list && list.length ? list[0] : null)
      if (fileInput.value && file.value) fileInput.value.value = ""
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
      progress.value = 0
      try {
        await uploadApi("/api/projects/" + props.project.id + "/documents", body, (loaded, total) => {
          progress.value = Math.round((loaded / total) * 100)
        })
        title.value = ""
        note.value = ""
        file.value = null
        if (fileInput.value) fileInput.value.value = ""
        await load()
        tab.value = "list"
        notice.show("Документ загружен", { kind: "success" })
      } catch (err) {
        formError.value = err.message || "Не удалось загрузить"
      } finally {
        busy.value = false
        progress.value = 0
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
      if (action === "download" && item.current) downloadFile(item.current.file_id)
      if (action === "delete") remove(item)
    }

    async function remove(item) {
      if (!window.confirm("Удалить документ «" + item.title + "» и все его версии?")) return
      const snapshot = items.value.slice()
      items.value = items.value.filter((row) => row.id !== item.id)
      try {
        await api("/api/projects/" + props.project.id + "/documents/" + item.id, { method: "DELETE" })
        // Документы удаляются мягко — «Отменить» достаёт его из корзины.
        notice.show("Документ «" + item.title + "» удалён в корзину", {
          kind: "success",
          timeout: 9000,
          action: {
            label: "Отменить",
            run: async () => {
              try {
                await api("/api/trash/documents/" + item.id + "/restore", { method: "POST" })
                notice.show("Документ «" + item.title + "» восстановлен", { kind: "success" })
                await load()
              } catch (err) {
                notice.show("Не удалось восстановить документ. " + (err.message || "Ошибка"))
              }
            },
          },
        })
      } catch (err) {
        items.value = snapshot
        notice.show("Не удалось удалить документ. " + (err.message || "Ошибка"))
      }
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).catch(() => {})
      load()
    }, { immediate: true })

    return { items, error, formError, loading, busy, title, note, fileInput, includeArchived, tab, pageTabs, dragOver, progress, maxUploadMb, formatSize, onFile, onDrop, load, upload, when, actionsFor, onAction }
  },
}
</script>
