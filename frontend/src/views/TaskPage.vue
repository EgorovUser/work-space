<template>
  <div>
    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <p v-else-if="!task" class="muted">Загрузка…</p>
    <template v-else>
      <input v-model="form.title" class="title-input" type="text" required @change="save" />
      <Tabs v-model="tab" :tabs="pageTabs" />

      <form v-show="tab === 'about'" class="card stack" @submit.prevent="save">
        <label class="tight">
          Описание
          <textarea v-model="form.description" rows="3" />
        </label>
        <div class="compact-grid">
          <label class="tight">
            Колонка
            <select v-model="form.status_id">
              <option v-for="status in statuses" :key="status.id" :value="status.id">{{ status.name }}</option>
            </select>
          </label>
          <label class="tight">
            Исполнитель
            <select v-model="form.assignee_id">
              <option value="">Не назначен</option>
              <option v-for="person in users" :key="person.id" :value="String(person.id)">
                {{ person.display_name || person.username }}
              </option>
            </select>
          </label>
          <label class="tight">
            Приоритет
            <select v-model="form.priority">
              <option v-for="item in priorities" :key="item.id" :value="item.id">{{ item.label }}</option>
            </select>
          </label>
          <label class="tight">
            Дедлайн
            <input v-model="form.deadline" type="datetime-local" />
          </label>
          <label class="tight">
            Прогресс
            <select v-model="form.progress_mode">
              <option value="auto">По чеклисту</option>
              <option value="manual">Вручную</option>
            </select>
          </label>
          <label v-if="form.progress_mode === 'manual'" class="tight">
            Значение, 0–{{ progressMax }}
            <input v-model.number="form.progress_manual" type="number" min="0" :max="progressMax" />
          </label>
          <p class="muted">Сейчас {{ task.progress }} из {{ progressMax }}.</p>
        </div>
        <div class="tag-row">
          <label v-for="tag in tags" :key="tag.id" class="check">
            <input v-model="form.tag_ids" type="checkbox" :value="tag.id" />
            <span>{{ tag.name }}</span>
          </label>
          <input v-model="newTag" type="text" placeholder="Новая метка" @keydown.enter.prevent="createTag" />
        </div>
        <p v-if="formError" class="error">{{ formError }}</p>
        <div class="row-actions">
          <button class="btn" type="submit" :disabled="busy">Сохранить</button>
          <button class="btn secondary" type="button" :disabled="busy" @click="remove">Удалить</button>
        </div>
      </form>

      <section v-show="tab === 'checks'" class="card">
        <form class="row-actions" @submit.prevent="addCheck">
          <input v-model="checkTitle" type="text" placeholder="Пункт" />
          <button class="btn secondary" type="submit" :disabled="busy">Добавить</button>
        </form>
        <div v-for="item in task.checklist" :key="item.id" class="check check-row">
          <input :checked="item.done" type="checkbox" @change="toggleCheck(item, $event)" />
          <span>{{ item.title }}</span>
          <button class="btn secondary" type="button" :disabled="busy" @click="removeCheck(item)">Убрать</button>
        </div>
        <p v-if="!(task.checklist && task.checklist.length)" class="muted">Пунктов нет. Пустой чеклист даёт прогресс 0 в автоматическом режиме.</p>
      </section>

      <section v-show="tab === 'time'" class="card stack">
        <p class="muted">Минуты записываются на эту задачу. Старт запускает таймер сразу с ней.</p>
        <div class="compact-grid">
          <label class="tight">
            Дата
            <input v-model="spent.day" type="date" />
          </label>
          <label class="tight">
            Минуты
            <input v-model.number="spent.minutes" type="number" min="1" />
          </label>
          <label class="tight">
            Заметка
            <input v-model="spent.note" type="text" />
          </label>
        </div>
        <p v-if="timeError" class="error">{{ timeError }}</p>
        <div class="row-actions">
          <button class="btn" type="button" :disabled="busy" @click="logTime">Списать</button>
          <button class="btn secondary" type="button" :disabled="busy" @click="startOnTask">Старт таймера</button>
        </div>
        <p v-if="!timeEntries.length" class="muted">По этой задаче записей за окно отчёта нет</p>
        <div v-for="item in timeEntries" :key="item.id" class="inbox-row">
          <div>{{ item.running ? "Идёт" : item.minutes + " мин" }}<span v-if="item.note"> · {{ item.note }}</span></div>
          <span class="when">{{ when(item.started_at) }}</span>
          <span></span>
        </div>
      </section>

      <section v-show="tab === 'files'" class="card">
        <p class="muted">Файл создаётся как документ или пример и появляется в их списке. В задаче остаётся только ссылка.</p>
        <form class="composer" @submit.prevent="upload">
          <input ref="fileInput" type="file" />
          <select v-model="fileKind">
            <option value="document">Документ</option>
            <option value="example">Пример</option>
          </select>
          <button class="btn secondary" type="submit" :disabled="busy">Прикрепить</button>
        </form>
        <div v-for="file in task.files" :key="file.kind + '-' + file.id" class="status-row">
          <div>
            <router-link v-if="file.kind === 'document'" :to="'/projects/' + project.id + '/documents/' + file.target_id">{{ file.original_name }}</router-link>
            <router-link v-else-if="file.kind === 'example'" :to="'/projects/' + project.id + '/examples/' + file.target_id">{{ file.original_name }}</router-link>
            <a v-else :href="'/api/files/' + file.file_id">{{ file.original_name }}</a>
            <div class="muted">{{ kindName(file.kind) }}</div>
          </div>
          <button class="text-btn" type="button" @click="removeFile(file)">Убрать ссылку</button>
        </div>
      </section>

      <section v-show="tab === 'feed'" class="card">
        <form class="stack" @submit.prevent="comment">
          <textarea v-model="commentBody" placeholder="Комментарий" rows="3" />
          <div>
            <button class="btn secondary" type="submit" :disabled="busy">Написать</button>
          </div>
        </form>
        <article v-for="item in task.events" :key="item.id" class="setting">
          <p>
            <strong>{{ kindLabel(item.kind) }}</strong>
            <span class="muted"> · {{ when(item.created_at) }}</span>
            <span v-if="personName(item.user_id)" class="muted"> · {{ personName(item.user_id) }}</span>
          </p>
          <p v-if="item.body">{{ item.body }}</p>
        </article>
      </section>
    </template>
  </div>
</template>

<script>
import { onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"
import Tabs from "../components/Tabs.vue"
import { formatWhen } from "../composables/formatDate"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"

const KINDS = {
  created: "Создана",
  status: "Колонка",
  assigned: "Исполнитель",
  comment: "Комментарий",
  checklist: "Чеклист",
  deadline: "Дедлайн",
  attachment: "Файл",
  updated: "Правка",
}

export default {
  components: { Tabs },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const router = useRouter()
    const { settings, when, localDay } = useWhen()
    const notice = useNotice()
    const tab = ref("about")
    const pageTabs = [
      { id: "about", label: "О задаче" },
      { id: "checks", label: "Чеклист" },
      { id: "files", label: "Файлы" },
      { id: "time", label: "Время" },
      { id: "feed", label: "Лента" },
    ]
    const task = ref(null)
    const statuses = ref([])
    const tags = ref([])
    const users = ref([])
    const error = ref("")
    const formError = ref("")
    const unavailable = ref(false)
    const busy = ref(false)
    const checkTitle = ref("")
    const commentBody = ref("")
    const newTag = ref("")
    const fileInput = ref(null)
    const fileKind = ref("document")
    const timeEntries = ref([])
    const timeError = ref("")
    const spent = reactive({ day: localDay(), minutes: 30, note: "" })
    const priorities = ref([])
    const progressMax = ref(100)
    const form = reactive({
      title: "",
      description: "",
      status_id: "",
      assignee_id: "",
      priority: "",
      deadline: "",
      progress_mode: "auto",
      progress_manual: 0,
      tag_ids: [],
    })

    function kindLabel(kind) {
      return KINDS[kind] || kind
    }

    function personName(id) {
      const person = users.value.find((item) => item.id === id)
      return person ? person.display_name || person.username : ""
    }

    function fill(data) {
      task.value = data
      form.title = data.title
      form.description = data.description || ""
      form.status_id = data.status_id
      form.assignee_id = data.assignee_id ? String(data.assignee_id) : ""
      form.priority = data.priority
      form.deadline = data.deadline
        ? formatWhen(data.deadline, "YYYY-MM-DDTHH:mm", settings.get("core", "ui.timezone") || undefined)
        : ""
      form.progress_mode = data.progress_mode
      form.progress_manual = data.progress_manual
      form.tag_ids = (data.tags || []).map((tag) => tag.id)
    }

    async function load() {
      error.value = ""
      unavailable.value = false
      try {
        await settings.load(props.project.id)
        const raw = settings.get("tasks", "priorities")
        priorities.value = Array.isArray(raw) ? raw : []
        progressMax.value = Number(settings.get("tasks", "progress.max")) || 100
        const [statusData, tagData, userData, taskData] = await Promise.all([
          api("/api/projects/" + props.project.id + "/task-statuses"),
          api("/api/projects/" + props.project.id + "/tags"),
          api("/api/users"),
          api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId),
        ])
        statuses.value = statusData.items || []
        tags.value = tagData.items || []
        users.value = userData || []
        fill(taskData)
      } catch (err) {
        task.value = null
        if (err.status === 503) unavailable.value = true
        else error.value = err.message || "Задача недоступна"
      }
    }

    async function save() {
      formError.value = ""
      busy.value = true
      try {
        const saved = await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId, {
          method: "PATCH",
          body: {
            title: form.title,
            description: form.description,
            status_id: Number(form.status_id),
            assignee_id: form.assignee_id ? Number(form.assignee_id) : null,
            priority: form.priority,
            deadline: form.deadline || "",
            progress_mode: form.progress_mode,
            progress_manual: Number(form.progress_manual) || 0,
            tag_ids: form.tag_ids,
          },
        })
        fill(saved)
        notice.show("Сохранено", { kind: "success" })
      } catch (err) {
        formError.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function remove() {
      if (!window.confirm("Удалить задачу?")) return
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId, { method: "DELETE" })
        router.push("/projects/" + props.project.id)
      } catch (err) {
        formError.value = err.message || "Не удалилось"
        busy.value = false
      }
    }

    // Обновляет карточку задачи без перезаписи формы: то, что пользователь
    // печатает в полях (описание, дедлайн, метки), не пропадает от побочных
    // действий вроде комментария или нового пункта чеклиста.
    function refreshTask(data) {
      if (!data) return
      task.value = data
    }

    async function addCheck() {
      if (busy.value) return
      const title = checkTitle.value.trim()
      if (!title) {
        formError.value = "Введите текст пункта"
        return
      }
      formError.value = ""
      busy.value = true
      try {
        const item = await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/checklist", {
          method: "POST",
          body: { title },
        })
        checkTitle.value = ""
        task.value.checklist = (task.value.checklist || []).concat([item])
      } catch (err) {
        formError.value = err.message || "Пункт не добавлен"
      } finally {
        busy.value = false
      }
    }

    async function toggleCheck(item, event) {
      const previous = item.done
      item.done = event.target.checked
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/checklist/" + item.id, {
          method: "PATCH",
          body: { done: item.done },
        })
      } catch (err) {
        item.done = previous
        event.target.checked = previous
        notice.show("Не удалось отметить пункт. " + (err.message || "Ошибка"))
      }
    }

    async function removeCheck(item) {
      const list = task.value.checklist || []
      const snapshot = list.slice()
      task.value.checklist = list.filter((row) => row.id !== item.id)
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/checklist/" + item.id, {
          method: "DELETE",
        })
      } catch (err) {
        task.value.checklist = snapshot
        notice.show("Не удалось убрать пункт. " + (err.message || "Ошибка"))
      }
    }

    async function comment() {
      if (busy.value) return
      const text = commentBody.value.trim()
      if (!text) {
        formError.value = "Комментарий пустой"
        return
      }
      formError.value = ""
      busy.value = true
      try {
        const saved = await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/comments", {
          method: "POST",
          body: { body: text },
        })
        commentBody.value = ""
        // Сервер возвращает всю задачу; форму не трогаем — там могут быть
        // несохранённые правки.
        refreshTask(saved)
      } catch (err) {
        formError.value = err.message || "Комментарий не сохранён"
      } finally {
        busy.value = false
      }
    }

    async function createTag() {
      if (busy.value) return
      const name = newTag.value.trim()
      if (!name) return
      formError.value = ""
      busy.value = true
      try {
        const tag = await api("/api/projects/" + props.project.id + "/tags", {
          method: "POST",
          body: { name },
        })
        newTag.value = ""
        tags.value = tags.value.concat(tag)
        form.tag_ids = form.tag_ids.concat(tag.id)
      } catch (err) {
        formError.value = err.message || "Метка не создана"
      } finally {
        busy.value = false
      }
    }

    async function upload() {
      if (busy.value) return
      const input = fileInput.value
      const file = input && input.files && input.files[0]
      if (!file) {
        formError.value = "Выберите файл"
        return
      }
      const body = new FormData()
      body.append("file", file)
      body.append("kind", fileKind.value)
      formError.value = ""
      busy.value = true
      try {
        const ref = await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/files", {
          method: "POST",
          body,
        })
        input.value = ""
        task.value.files = (task.value.files || []).concat([ref])
      } catch (err) {
        formError.value = err.message || "Файл не прикрепился"
      } finally {
        busy.value = false
      }
    }

    async function removeFile(file) {
      if (busy.value) return
      const snapshot = (task.value.files || []).slice()
      task.value.files = snapshot.filter((row) => !(row.id === file.id && row.kind === file.kind))
      formError.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/files/" + file.id + "?kind=" + encodeURIComponent(file.kind || ""), {
          method: "DELETE",
        })
      } catch (err) {
        task.value.files = snapshot
        formError.value = err.message || "Файл не откреплён"
      } finally {
        busy.value = false
      }
    }

    async function loadTime() {
      timeError.value = ""
      try {
        const data = await api("/api/projects/" + props.project.id + "/time")
        const id = Number(route.params.taskId)
        timeEntries.value = (data.entries || []).filter((item) => Number(item.task_id) === id)
      } catch (err) {
        timeError.value = err.message || "Время недоступно"
      }
    }

    async function logTime() {
      busy.value = true
      timeError.value = ""
      try {
        await api("/api/projects/" + props.project.id + "/time/entries", {
          method: "POST",
          body: {
            task_id: Number(route.params.taskId),
            minutes: Number(spent.minutes),
            day: spent.day,
            note: spent.note,
          },
        })
        spent.note = ""
        await loadTime()
      } catch (err) {
        timeError.value = err.message || "Не записалось"
      } finally {
        busy.value = false
      }
    }

    async function startOnTask() {
      busy.value = true
      timeError.value = ""
      try {
        await api("/api/projects/" + props.project.id + "/time/start", {
          method: "POST",
          body: { task_id: Number(route.params.taskId), note: spent.note },
        })
        await loadTime()
      } catch (err) {
        timeError.value = err.message || "Таймер не запустился"
      } finally {
        busy.value = false
      }
    }

    function kindName(kind) {
      if (kind === "document") return "Документ"
      if (kind === "example") return "Пример"
      return "Старый файл"
    }

    watch(() => route.params.taskId, load)
    watch(tab, (value) => {
      if (value === "time") loadTime()
    })
    onMounted(load)
    return {
      task,
      statuses,
      tags,
      users,
      error,
      formError,
      unavailable,
      busy,
      checkTitle,
      commentBody,
      newTag,
      fileInput,
      fileKind,
      timeEntries,
      timeError,
      spent,
      priorities,
      progressMax,
      form,
      tab,
      pageTabs,
      when,
      kindLabel,
      personName,
      save,
      remove,
      addCheck,
      toggleCheck,
      removeCheck,
      comment,
      createTag,
      upload,
      removeFile,
      kindName,
      logTime,
      startOnTask,
    }
  },
}
</script>
