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
        Секрет с логином
        <select v-model="form.secret_id">
          <option value="">Не связывать</option>
          <option v-for="item in secrets" :key="item.id" :value="String(item.id)">{{ item.title }}</option>
        </select>
        <span class="muted">Логин подтянется в .rdp, если поле «Логин» пустое.</span>
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
          <span v-if="item.secret_title" class="pill" :title="'Связан с секретом «' + item.secret_title + '»'">секрет: {{ item.secret_title }}</span>
          <div class="muted mono-inline">{{ item.host }}<span v-if="item.port !== 3389">:{{ item.port }}</span></div>
          <div class="muted">
            <span v-if="item.username">логин {{ item.username }}<span v-if="item.domain"> · домен {{ item.domain }}</span> · </span>
            <span v-if="item.archived">архив · </span>
            {{ when(item.updated_at) }}
          </div>
        </div>
        <div class="rdp-tools">
          <ActionMenu :actions="rowActions(item)" @choose="onAction($event, item)" />
        </div>
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
import { useSoftDelete } from "../composables/useSoftDelete"
import { useNotice } from "../composables/useNotice"
import { useWhen } from "../composables/useWhen"

// RDP-подключения проекта: адрес, порт, логин и домен — без пароля. Кнопка
// «Скачать .rdp» забирает файл с сервера, «Копировать адрес» кладёт
// host:port в буфер. Связка с секретом (патч N) подтягивает логин в .rdp
// из хранилища. Правка важных полей (адрес, порт, логин, домен, секрет)
// подтверждается диалогом «было → станет» (патч O): опечатка в адресе
// не затирает сохранённое значение молча.
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
    const secrets = ref([])
    const editOriginal = ref(null)
    const notice = useNotice()
    const { softRemove } = useSoftDelete()
    const { settings, when } = useWhen()

    function emptyForm() {
      return { name: "", host: "", port: "", username: "", domain: "", secret_id: "", note: "" }
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

    async function loadSecrets() {
      try {
        const data = await api("/api/projects/" + props.project.id + "/secrets")
        secrets.value = (data.items || []).filter((item) => !item.archived)
      } catch {
        secrets.value = [] // модуль секретов может быть выключен
      }
    }

    function importantChanges() {
      // Что меняется в важные полях относительно загруженной записи —
      // из этого собирается диалог «было → станет» перед сохранением.
      const origin = editOriginal.value
      if (!origin) return []
      const lines = []
      const newPort = form.value.port ? Number(form.value.port) : Number(portPlaceholder.value || 3389)
      if ((form.value.host || "") !== (origin.host || "")) {
        lines.push("Адрес сервера: " + origin.host + " → " + form.value.host)
      }
      if (newPort !== origin.port) {
        lines.push("Порт: " + origin.port + " → " + newPort)
      }
      if ((form.value.username || "") !== (origin.username || "")) {
        lines.push("Логин: " + (origin.username || "—") + " → " + (form.value.username || "—"))
      }
      if ((form.value.domain || "") !== (origin.domain || "")) {
        lines.push("Домен: " + (origin.domain || "—") + " → " + (form.value.domain || "—"))
      }
      const newSecretId = form.value.secret_id ? Number(form.value.secret_id) : null
      const oldSecretId = origin.secret_id || null
      if (newSecretId !== oldSecretId) {
        lines.push("Секрет: " + secretLabel(oldSecretId) + " → " + secretLabel(newSecretId))
      }
      return lines
    }

    function secretLabel(id) {
      if (!id) return "не связан"
      const found = secrets.value.find((item) => item.id === id)
      return found ? "«" + found.title + "»" : "секрет №" + id
    }

    async function submit() {
      formError.value = ""
      if (editId.value) {
        const changes = importantChanges()
        if (changes.length) {
          const ok = window.confirm("Изменяются важные поля:\n" + changes.join("\n") + "\n\nСохранить?")
          if (!ok) return
        }
      }
      busy.value = true
      const body = {
        name: form.value.name,
        host: form.value.host,
        username: form.value.username,
        domain: form.value.domain,
        note: form.value.note,
      }
      body.secret_id = form.value.secret_id ? Number(form.value.secret_id) : null
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
      editOriginal.value = null
      form.value = emptyForm()
      tab.value = "list"
    }

    function startEdit(item) {
      editId.value = item.id
      editVersion.value = item.updated_at
      editOriginal.value = {
        host: item.host,
        port: item.port,
        username: item.username,
        domain: item.domain,
        secret_id: item.secret_id || null,
      }
      form.value = {
        name: item.name,
        host: item.host,
        port: item.port === 3389 ? "" : String(item.port),
        username: item.username,
        domain: item.domain,
        secret_id: item.secret_id ? String(item.secret_id) : "",
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
      // RDP удаляется мягко — раньше тост не предлагал «Отменить», хотя
      // запись лежит в корзине 30 дней; теперь достаёт оттуда как остальные.
      const snapshot = items.value.slice()
      items.value = items.value.filter((row) => row.id !== item.id)
      const ok = await softRemove({
        confirm: "Удалить подключение «" + item.name + "»? Оно попадёт в корзину — 30 дней на восстановление.",
        url: "/api/projects/" + props.project.id + "/rdp/" + item.id,
        restoreUrl: "/api/trash/rdp/" + item.id + "/restore",
        doneText: "Подключение «" + item.name + "» удалено в корзину",
        restoredText: "Подключение «" + item.name + "» восстановлено",
        restoreFailText: "Не удалось восстановить подключение. ",
        afterRestore: load,
      })
      if (!ok) items.value = snapshot
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
      loadSecrets()
    }, { immediate: true })

    return {
      items, error, formError, loading, busy, query, includeArchived, tab, pageTabs,
      form, editId, portPlaceholder, secrets, when,
      rowActions, load, submit, resetForm, onAction,
    }
  },
}
</script>
