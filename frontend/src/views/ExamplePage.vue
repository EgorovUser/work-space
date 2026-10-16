<template>
  <div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!example" class="muted">Загрузка…</p>
    <template v-else>
      <h1>{{ example.title }}</h1>
      <Tabs v-model="tab" :tabs="pageTabs" />
      <form v-show="tab === 'text'" class="card stack" @submit.prevent="save">
        <label>
          Название
          <input v-model="form.title" type="text" required />
        </label>
        <label>
          Язык
          <select v-model="form.language">
            <option v-if="form.language && !knownLanguage" :value="form.language">{{ form.language }}</option>
            <option v-for="item in example.languages || []" :key="item.id" :value="item.id">{{ item.label }}</option>
          </select>
        </label>
        <label>
          Текст
          <textarea v-model="form.body" class="mono" />
        </label>
        <label>
          Заметка
          <textarea v-model="form.note" />
        </label>
        <label>
          Метки
          <input v-model="form.tags" type="text" />
        </label>
        <label class="check">
          <input v-model="form.pinned" type="checkbox" />
          <span>Закрепить</span>
        </label>
        <p v-if="formError" class="error">{{ formError }}</p>
        <p v-if="copied" class="ok-text">Скопировано</p>
        <div class="row-actions">
          <button class="btn" type="submit" :disabled="busy">Сохранить</button>
          <button class="btn secondary" type="button" :disabled="busy" @click="copyBody">Копировать текст</button>
          <button class="btn secondary" type="button" :disabled="busy" @click="toggleArchive">
            {{ example.archived ? "Вернуть из архива" : "В архив" }}
          </button>
          <button class="btn secondary" type="button" :disabled="busy" @click="remove">Удалить</button>
        </div>
      </form>

      <section v-show="tab === 'files'" class="card">
        <form class="row-actions" @submit.prevent="upload">
          <input ref="fileInput" type="file" @change="onFile" />
          <button class="btn secondary" type="submit" :disabled="busy">Прикрепить</button>
        </form>
        <p v-if="fileError" class="error">{{ fileError }}</p>
        <p v-if="!example.files.length" class="muted">Файлов нет</p>
        <div v-for="item in example.files" :key="item.id" class="status-row">
          <span>{{ item.original_name }} · {{ sizeLabel(item.size) }}</span>
          <div class="row-actions">
            <a :href="'/api/files/' + item.file_id">Скачать</a>
            <button class="btn secondary" type="button" :disabled="busy" @click="removeFile(item)">Удалить</button>
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
import { useNotice } from "../composables/useNotice"

export default {
  components: { Tabs },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const router = useRouter()
    const example = ref(null)
    const error = ref("")
    const formError = ref("")
    const fileError = ref("")
    const busy = ref(false)
    const tab = ref("text")
    const pageTabs = [
      { id: "text", label: "Текст" },
      { id: "files", label: "Файлы" },
    ]
    const notice = useNotice()
    const copied = ref(false)
    const file = ref(null)
    const fileInput = ref(null)
    const form = ref({ title: "", body: "", note: "", language: "", tags: "", pinned: false })

    const knownLanguage = computed(() => {
      const list = (example.value && example.value.languages) || []
      return list.some((item) => item.id === form.value.language)
    })

    function joinWith(separator) {
      if (!separator) return "\n"
      return separator + (separator.trim() ? " " : "")
    }

    function apply(data) {
      example.value = data
      form.value = {
        title: data.title,
        body: data.body || "",
        note: data.note || "",
        language: data.language || "",
        tags: (data.tags || []).map((tag) => tag.name).join(joinWith(data.tag_separator)),
        pinned: !!data.pinned,
      }
      copied.value = false
    }

    function sizeLabel(bytes) {
      const value = Number(bytes) || 0
      if (value < 1024) return value + " Б"
      if (value < 1024 * 1024) return Math.round(value / 1024) + " КБ"
      return (value / (1024 * 1024)).toFixed(1) + " МБ"
    }

    async function load() {
      error.value = ""
      try {
        apply(await api("/api/projects/" + props.project.id + "/examples/" + route.params.exampleId))
      } catch (err) {
        example.value = null
        error.value = err.message || "Пример недоступен"
      }
    }

    async function save() {
      formError.value = ""
      busy.value = true
      try {
        apply(await api("/api/projects/" + props.project.id + "/examples/" + route.params.exampleId, {
          method: "PATCH",
          body: {
            title: form.value.title,
            body: form.value.body,
            note: form.value.note,
            language: form.value.language,
            pinned: form.value.pinned,
            tags: form.value.tags ? [form.value.tags] : [],
          },
        }))
      } catch (err) {
        formError.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function toggleArchive() {
      const previous = example.value.archived
      example.value = { ...example.value, archived: !previous }
      try {
        apply(await api("/api/projects/" + props.project.id + "/examples/" + route.params.exampleId, {
          method: "PATCH",
          body: { archived: !previous },
        }))
      } catch (err) {
        example.value = { ...example.value, archived: previous }
        notice.show("Не удалось изменить пример. " + (err.message || "Ошибка"))
      }
    }

    async function remove() {
      if (!window.confirm("Удалить пример?")) return
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/examples/" + route.params.exampleId, { method: "DELETE" })
        router.push("/projects/" + props.project.id + "/examples")
      } catch (err) {
        formError.value = err.message || "Не удалось удалить"
        busy.value = false
      }
    }

    async function copyBody() {
      copied.value = false
      const text = form.value.body || ""
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text)
        } else {
          throw new Error("clipboard")
        }
      } catch {
        try {
          const area = document.createElement("textarea")
          area.value = text
          document.body.appendChild(area)
          area.select()
          document.execCommand("copy")
          area.remove()
        } catch {
          formError.value = "Не удалось скопировать"
          return
        }
      }
      copied.value = true
    }

    function onFile(event) {
      const list = event.target.files
      file.value = list && list.length ? list[0] : null
    }

    async function upload() {
      fileError.value = ""
      if (!file.value) {
        fileError.value = "Выберите файл"
        return
      }
      const body = new FormData()
      body.append("file", file.value)
      busy.value = true
      try {
        apply(await api("/api/projects/" + props.project.id + "/examples/" + route.params.exampleId + "/files", {
          method: "POST",
          body,
        }))
        file.value = null
        if (fileInput.value) fileInput.value.value = ""
      } catch (err) {
        fileError.value = err.message || "Файл не прикрепился"
      } finally {
        busy.value = false
      }
    }

    async function removeFile(item) {
      if (!window.confirm("Убрать файл из примера?")) return
      busy.value = true
      fileError.value = ""
      try {
        await api(
          "/api/projects/" + props.project.id + "/examples/" + route.params.exampleId + "/files/" + item.id,
          { method: "DELETE" },
        )
        await load()
      } catch (err) {
        fileError.value = err.message || "Файл не убрался"
      } finally {
        busy.value = false
      }
    }

    watch(() => [props.project && props.project.id, route.params.exampleId], load, { immediate: true })

    return {
      example, error, formError, fileError, busy, copied, form, fileInput, knownLanguage, tab, pageTabs,
      sizeLabel, save, toggleArchive, remove, copyBody, onFile, upload, removeFile,
    }
  },
}
</script>
