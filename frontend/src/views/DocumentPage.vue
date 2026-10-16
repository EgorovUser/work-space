<template>
  <div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!doc" class="muted">Загрузка…</p>
    <template v-else>
      <h1>{{ doc.title }}</h1>
      <Tabs v-model="tab" :tabs="pageTabs" />
      <div v-show="tab === 'card'">
      <form class="card stack" @submit.prevent="save">
        <label>
          Название
          <input v-model="form.title" type="text" required />
        </label>
        <label>
          Заметка
          <textarea v-model="form.note" />
        </label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="row-actions">
          <button class="btn" type="submit" :disabled="busy">Сохранить</button>
          <button class="btn secondary" type="button" :disabled="busy" @click="toggleArchive">
            {{ doc.archived ? "Вернуть из архива" : "В архив" }}
          </button>
          <button class="btn secondary" type="button" :disabled="busy" @click="remove">Удалить</button>
        </div>
      </form>
      <section class="card">
        <h2>Новая версия</h2>
        <form class="stack" @submit.prevent="addVersion">
          <label>
            Файл
            <input ref="fileInput" type="file" @change="onFile" />
          </label>
          <label>
            Комментарий версии
            <input v-model="versionNote" type="text" />
          </label>
          <p v-if="versionError" class="error">{{ versionError }}</p>
          <div class="row-actions">
            <button class="btn" type="submit" :disabled="busy">Загрузить версию</button>
          </div>
        </form>
      </section>
      </div>
      <section v-show="tab === 'text'" class="card">
        <h2>Текст</h2>
        <p v-if="doc.current" class="muted">
          {{ doc.current.extract_label }}
          <span v-if="doc.current.text_length"> · {{ doc.current.text_length }} символов</span>
        </p>
        <p v-if="doc.current && doc.current.extract_error" class="error">{{ doc.current.extract_error }}</p>
        <p v-if="!shownText" class="muted">Текста нет</p>
        <pre v-else class="text-block">{{ shownText }}</pre>
        <div v-if="doc.preview_truncated && !fullLoaded" class="row-actions">
          <button class="btn secondary" type="button" :disabled="busy" @click="loadFull">Показать полностью</button>
        </div>
      </section>

      <section v-show="tab === 'versions'" class="card">
        <h2>Версии</h2>
        <div v-for="item in doc.versions" :key="item.id" class="status-row">
          <div>
            <strong>{{ item.version_number }}.</strong>
            {{ item.original_name }}
            <div class="muted">
              {{ item.extract_label }} · {{ sizeLabel(item.size) }} · {{ when(item.created_at) }}
            </div>
            <div v-if="item.note">{{ item.note }}</div>
          </div>
          <div class="row-actions">
            <a :href="'/api/files/' + item.file_id">Скачать</a>
            <button class="btn secondary" type="button" :disabled="busy" @click="removeVersion(item)">Удалить</button>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script>
import { computed, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"
import Tabs from "../components/Tabs.vue"
import { useSettings } from "../composables/useSettings"
import { useNotice } from "../composables/useNotice"
import { formatWhen } from "../composables/formatDate"

export default {
  components: { Tabs },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const router = useRouter()
    const doc = ref(null)
    const error = ref("")
    const formError = ref("")
    const versionError = ref("")
    const busy = ref(false)
    const tab = ref("text")
    const pageTabs = [
      { id: "text", label: "Текст" },
      { id: "card", label: "Карточка" },
      { id: "versions", label: "Версии" },
    ]
    const form = ref({ title: "", note: "" })
    const versionNote = ref("")
    const file = ref(null)
    const fileInput = ref(null)
    const fullText = ref("")
    const fullLoaded = ref(false)
    const settings = useSettings()
    const notice = useNotice()

    const shownText = computed(() => {
      if (!doc.value) return ""
      if (fullLoaded.value) return fullText.value
      return doc.value.preview || ""
    })

    function when(value) {
      return formatWhen(value, settings.get("core", "ui.date_format"), settings.get("core", "ui.timezone") || undefined)
    }

    function sizeLabel(bytes) {
      const value = Number(bytes) || 0
      if (value < 1024) return value + " Б"
      if (value < 1024 * 1024) return Math.round(value / 1024) + " КБ"
      return (value / (1024 * 1024)).toFixed(1) + " МБ"
    }

    function apply(data) {
      doc.value = data
      form.value = { title: data.title, note: data.note || "" }
      fullLoaded.value = false
      fullText.value = ""
    }

    async function load() {
      error.value = ""
      try {
        apply(await api("/api/projects/" + props.project.id + "/documents/" + route.params.documentId))
      } catch (err) {
        doc.value = null
        error.value = err.message || "Документ недоступен"
      }
    }

    function onFile(event) {
      const list = event.target.files
      file.value = list && list.length ? list[0] : null
    }

    async function save() {
      formError.value = ""
      busy.value = true
      try {
        apply(await api("/api/projects/" + props.project.id + "/documents/" + route.params.documentId, {
          method: "PATCH",
          body: { title: form.value.title, note: form.value.note },
        }))
      } catch (err) {
        formError.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function toggleArchive() {
      const previous = doc.value.archived
      doc.value = { ...doc.value, archived: !previous }
      try {
        apply(await api("/api/projects/" + props.project.id + "/documents/" + route.params.documentId, {
          method: "PATCH",
          body: { archived: !previous },
        }))
      } catch (err) {
        doc.value = { ...doc.value, archived: previous }
        notice.show("Не удалось изменить документ. " + (err.message || "Ошибка"))
      }
    }

    async function remove() {
      if (!window.confirm("Удалить документ и все версии?")) return
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/documents/" + route.params.documentId, { method: "DELETE" })
        router.push("/projects/" + props.project.id + "/documents")
      } catch (err) {
        formError.value = err.message || "Не удалось удалить"
        busy.value = false
      }
    }

    async function addVersion() {
      versionError.value = ""
      if (!file.value) {
        versionError.value = "Выберите файл"
        return
      }
      const body = new FormData()
      body.append("file", file.value)
      body.append("note", versionNote.value)
      busy.value = true
      try {
        apply(await api("/api/projects/" + props.project.id + "/documents/" + route.params.documentId + "/versions", {
          method: "POST",
          body,
        }))
        versionNote.value = ""
        file.value = null
        if (fileInput.value) fileInput.value.value = ""
      } catch (err) {
        versionError.value = err.message || "Версия не загрузилась"
      } finally {
        busy.value = false
      }
    }

    async function removeVersion(item) {
      if (!window.confirm("Удалить версию " + item.version_number + "?")) return
      busy.value = true
      versionError.value = ""
      try {
        await api(
          "/api/projects/" + props.project.id + "/documents/" + route.params.documentId + "/versions/" + item.id,
          { method: "DELETE" },
        )
        await load()
      } catch (err) {
        versionError.value = err.message || "Версия не удалилась"
      } finally {
        busy.value = false
      }
    }

    async function loadFull() {
      busy.value = true
      try {
        const data = await api("/api/projects/" + props.project.id + "/documents/" + route.params.documentId + "/text")
        fullText.value = data.text || ""
        fullLoaded.value = true
      } catch (err) {
        formError.value = err.message || "Текст не загрузился"
      } finally {
        busy.value = false
      }
    }

    watch(() => [props.project && props.project.id, route.params.documentId], () => {
      settings.load(props.project.id).catch(() => {})
      load()
    }, { immediate: true })

    return {
      doc, error, formError, versionError, busy, form, versionNote, fileInput, fullLoaded, tab, pageTabs,
      shownText, when, sizeLabel, onFile, save, toggleArchive, remove, addVersion, removeVersion, loadFull,
    }
  },
}
</script>
