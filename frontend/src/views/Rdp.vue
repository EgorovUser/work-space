<template>
  <div>
    <h1>RDP-подключения</h1>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'add'">
    <p class="muted">
      Пароль не хранится: файл .rdp собирается на сервере, а Windows сам спросит
      учётные данные при подключении.
    </p>
    <form class="card stack" @submit.prevent="submit">
      <label>
        Название
        <input v-model="form.name" type="text" required autocomplete="off" />
      </label>
      <label>
        Адрес сервера
        <input v-model="form.host" type="text" required autocomplete="off" placeholder="server.local или 10.0.0.7" />
      </label>
      <label>
        Порт
        <input v-model="form.port" type="number" min="1" max="65535" :placeholder="portPlaceholder" />
      </label>
      <label>
        Логин
        <input v-model="form.username" type="text" autocomplete="off" placeholder="admin" />
      </label>
      <label>
        Домен
        <input v-model="form.domain" type="text" autocomplete="off" placeholder="CORP" />
      </label>
      <label>
        Заметка
        <textarea v-model="form.note" />
      </label>
      <p v-if="formError" class="error">{{ formError }}</p>
      <div class="row-actions">
        <button class="btn" type="submit" :disabled="busy">
          {{ editId ? "Сохранить" : "Добавить" }}
        </button>
        <button v-if="editId" class="btn secondary" type="button" :disabled="busy" @click="resetForm">
          Отмена
        </button>
      </div>
    </form>
    </div>

    <div v-show="tab === 'list'">
    <form class="row-actions" @submit.prevent="load">
      <input v-model="query" type="text" placeholder="Название или адрес" />
      <button class="btn secondary" type="submit">Показать</button>
    </form>
    <label class="check">
      <input v-model="includeArchived" type="checkbox" @change="load" />
      <span>Показать архив</span>
    </label>

    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="4" />
    <div v-else-if="!items.length" class="empty">
      <strong>Подключений пока нет</strong>
      <span>Добавьте первый сервер формой выше — файл .rdp для mstrc скачается одной кнопкой.</span>
    </div>
    <div v-else class="card">
      <div v-for="item in items" :key="item.id" class="status-row">
        <div>
          <strong>{{ item.name }}</strong>
          <div class="muted mono-inline">{{ item.host }}<span v-if="item.port !== 3389">:{{ item.port }}</span></div>
          <div class="muted">
            <span v-if="item.username">логин {{ item.username }}<span v-if="item.domain"> · домен {{ item.domain }}</span> · </span>
            <span v-if="item.archived">архив · </span>
            {{ when(item.updated_at) }}
          </div>
        </div>
        <ActionMenu :actions="rowActions(item)" @choose="onAction($event, item)" />
      </div>
    </div>
    </div>
  </div>
</template>

<script>
import { computed, ref, watch } from "vue"
import { api } from "../api"
import ActionMenu from "../components/ActionMenu.vue"
import SkeletonList from "../components/SkeletonList.vue"
import Tabs from "../components/Tabs.vue"
import { useNotice } from "../composables/useNotice"
import { useWhen } from "../composables/useWhen"

// RDP-подключения проекта: адрес, порт, логин и домен — без пароля. Кнопка
// «Скачать .rdp» забирает файл с сервера (content-disposition сам предлагает
// сохранение), «Копировать адрес» кладёт host:port в буфер.
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
    const query = ref("")
    const includeArchived = ref(false)
    const tab = ref("list")
    const pageTabs = computed(() => [
      { id: "list", label: "Список" },
      { id: "add", label: editId.value ? "Правка" : "Новый" },
    ])
    const form = ref(emptyForm())
    const editId = ref(null)
    const editVersion = ref("")
    const portPlaceholder = ref("3389")
    const notice = useNotice()
    const { settings, when } = useWhen()

    function emptyForm() {
      return { name: "", host: "", port: "", username: "", domain: "", note: "" }
    }

    function rowActions(item) {
      return [
        { id: "file", label: "Скачать .rdp" },
        { id: "copy", label: "Копировать адрес" },
        { id: "edit", label: "Изменить" },
        { id: "archive", label: item.archived ? "Вернуть из архива" : "В архив" },
        { id: "delete", label: "Удалить", danger: true },
      ]
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const params = new URLSearchParams()
        if (includeArchived.value) params.set("include_archived", "true")
        if (query.value) params.set("q", query.value)
        const data = await api("/api/projects/" + props.project.id + "/rdp?" + params.toString())
        items.value = data.items || []
      } catch (err) {
        items.value = []
        error.value = err.message || "Список недоступен"
      } finally {
        loading.value = false
      }
    }

    async function submit() {
      formError.value = ""
      busy.value = true
      const body = {
        name: form.value.name,
        host: form.value.host,
        username: form.value.username,
        domain: form.value.domain,
        note: form.value.note,
      }
      if (form.value.port) body.port = Number(form.value.port)
      try {
        if (editId.value) {
          body.updated_at = editVersion.value
          await api("/api/projects/" + props.project.id + "/rdp/" + editId.value, { method: "PATCH", body })
          notice.show("Подключение сохранено")
        } else {
          await api("/api/projects/" + props.project.id + "/rdp", { method: "POST", body })
          notice.show("Подключение добавлено")
        }
        resetForm()
        await load()
      } catch (err) {
        formError.value = err.message || "Не удалось сохранить"
      } finally {
        busy.value = false
      }
    }

    function resetForm() {
      editId.value = null
      editVersion.value = ""
      form.value = emptyForm()
      tab.value = "list"
    }

    function startEdit(item) {
      editId.value = item.id
      editVersion.value = item.updated_at
      form.value = {
        name: item.name,
        host: item.host,
        port: item.port === 3389 ? "" : String(item.port),
        username: item.username,
        domain: item.domain,
        note: item.note,
      }
      tab.value = "add"
    }

    function download(item) {
      window.location.assign("/api/projects/" + props.project.id + "/rdp/" + item.id + "/file")
    }

    async function copyAddress(item) {
      const text = item.host + (item.port === 3389 ? "" : ":" + item.port)
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text)
        } else {
          const area = document.createElement("textarea")
          area.value = text
          document.body.appendChild(area)
          area.select()
          document.execCommand("copy")
          area.remove()
        }
        notice.show("Адрес скопирован: " + text)
      } catch {
        notice.show("Не удалось скопировать — скопируйте вручную: " + text)
      }
    }

    async function toggleArchive(item) {
      try {
        await api("/api/projects/" + props.project.id + "/rdp/" + item.id, {
          method: "PATCH",
          body: { archived: !item.archived, updated_at: item.updated_at },
        })
        await load()
      } catch (err) {
        notice.show((err.message || "Ошибка") + " — обновите список и попробуйте снова")
      }
    }

    async function remove(item) {
      if (!window.confirm("Удалить подключение «" + item.name + "»? Отменить будет нельзя.")) return
      const snapshot = items.value.slice()
      items.value = items.value.filter((row) => row.id !== item.id)
      try {
        await api("/api/projects/" + props.project.id + "/rdp/" + item.id, { method: "DELETE" })
      } catch (err) {
        items.value = snapshot
        notice.show("Не удалось удалить. " + (err.message || "Ошибка"))
      }
    }

    function onAction(action, item) {
      if (action === "file") download(item)
      if (action === "copy") copyAddress(item)
      if (action === "edit") startEdit(item)
      if (action === "archive") toggleArchive(item)
      if (action === "delete") remove(item)
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).then(() => {
        const fallback = settings.get("rdp", "port.default")
        portPlaceholder.value = String(fallback || 3389)
      }).catch(() => {})
      resetForm()
      includeArchived.value = false
      query.value = ""
      load()
    }, { immediate: true })

    return {
      items, error, formError, loading, busy, query, includeArchived, tab, pageTabs,
      form, editId, portPlaceholder, when, rowActions, load, submit, resetForm, onAction,
    }
  },
}
</script>
