<template>
  <div>
    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <p v-else-if="!task" class="muted">Загрузка…</p>
    <template v-else>
      <input v-model="form.title" class="title-input" type="text" required @change="save" />
      <Tabs v-model="tab" :tabs="pageTabs" />

      <!-- Списание времени — прямо на главной странице задачи (патч R):
           раньше ради формы приходилось идти на отдельную вкладку.
           Компонент — в task/TaskTimeLog.vue (патч X). -->
      <TaskTimeLog v-show="tab === 'about'" :project="project" :task="task" />

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
            Повтор
            <select v-model="form.repeat_kind">
              <option value="">Нет</option>
              <option value="daily">Ежедневно</option>
              <option value="weekly">Еженедельно</option>
              <option value="monthly">Ежемесячно</option>
              <option value="yearly">Ежегодно</option>
            </select>
          </label>
          <label v-if="form.repeat_kind" class="tight">
            Интервал, каждые
            <input v-model.number="form.repeat_interval" type="number" min="1" :max="repeatMax" />
          </label>
          <label v-if="form.repeat_kind" class="tight">
            До даты (включительно)
            <input v-model="form.repeat_until" type="date" />
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
          <p v-if="form.repeat_kind" class="muted">
          Повтор: {{ repeatLabel(form.repeat_kind, form.repeat_interval) }}. Закрытие задачи создаёт следующее вхождение{{ form.repeat_until ? " до " + form.repeat_until + " включительно" : "" }}.
        </p>
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

      <TaskChecklist v-show="tab === 'checks'" :project="project" :task="task" />
      <TaskFiles v-show="tab === 'files'" :project="project" :task="task" />
      <TaskFeed v-show="tab === 'feed'" :project="project" :task="task" :users="users" @refresh="refreshTask" />
    </template>
  </div>
</template>

<script>
import { onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"
import Tabs from "../components/Tabs.vue"
import TaskChecklist from "../components/task/TaskChecklist.vue"
import TaskFeed from "../components/task/TaskFeed.vue"
import TaskFiles from "../components/task/TaskFiles.vue"
import TaskTimeLog from "../components/task/TaskTimeLog.vue"
import { repeatLabel } from "../composables/calendar"
import { formatWhen } from "../composables/formatDate"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { useSoftDelete } from "../composables/useSoftDelete"

// Страница задачи: шапка с названием, форма «О задаче» и вкладки.
// Чеклист, файлы, лента и списание времени живут в компонентах task/
// (патч X) — этот файл отвечает за загрузку задачи, форму и метки.
export default {
  components: { Tabs, TaskChecklist, TaskFeed, TaskFiles, TaskTimeLog },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const router = useRouter()
    const { settings } = useWhen()
    const notice = useNotice()
    const { softRemove } = useSoftDelete()
    const tab = ref("about")
    const pageTabs = [
      { id: "about", label: "О задаче" },
      { id: "checks", label: "Чеклист" },
      { id: "files", label: "Файлы" },
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
    const newTag = ref("")
    const priorities = ref([])
    const progressMax = ref(100)
    const repeatMax = ref(999)
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
      repeat_kind: "",
      repeat_interval: 1,
      repeat_until: "",
    })

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
      form.repeat_kind = data.repeat_kind || ""
      form.repeat_interval = data.repeat_interval || 1
      form.repeat_until = data.repeat_until
        ? formatWhen(data.repeat_until, "YYYY-MM-DD", settings.get("core", "ui.timezone") || undefined)
        : ""
    }

    async function load() {
      error.value = ""
      unavailable.value = false
      try {
        await settings.load(props.project.id)
        const raw = settings.get("tasks", "priorities")
        priorities.value = Array.isArray(raw) ? raw : []
        progressMax.value = Number(settings.get("tasks", "progress.max")) || 100
        repeatMax.value = Number(settings.get("tasks", "repeat.interval.max")) || 999
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
            repeat_kind: form.repeat_kind || "",
            repeat_interval: form.repeat_kind ? Math.max(1, Number(form.repeat_interval) || 1) : 1,
            repeat_until: form.repeat_kind ? form.repeat_until || null : null,
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
      // Скелет мягкого удаления — useSoftDelete (патч AT): тост глобальный,
      // переживает переход на доску; «Отменить» возвращает задачу из
      // корзины и открывает её снова.
      const taskId = Number(route.params.taskId)
      const title = task.value ? task.value.title : "Задача"
      busy.value = true
      try {
        const ok = await softRemove({
          confirm: "Удалить задачу?",
          url: "/api/projects/" + props.project.id + "/tasks/" + taskId,
          restoreUrl: "/api/trash/tasks/" + taskId + "/restore",
          doneText: "Задача «" + title + "» удалена в корзину",
          restoredText: "Задача «" + title + "» восстановлена",
          restoreFailText: "Не удалось восстановить задачу. ",
          afterRestore: () => {
            router.push("/projects/" + props.project.id + "/tasks/" + taskId)
          },
          onError: (err) => {
            formError.value = err.message || "Не удалилось"
          },
        })
        if (ok) router.push("/projects/" + props.project.id)
      } finally {
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
        notice.show("Метка «" + name + "» создана", { kind: "success" })
      } catch (err) {
        formError.value = err.message || "Метка не создана"
      } finally {
        busy.value = false
      }
    }

    watch(() => route.params.taskId, load)
    onMounted(load)
    return {
      task, statuses, tags, users, error, formError, unavailable, busy, newTag,
      priorities, progressMax, repeatMax, repeatLabel, form, tab, pageTabs,
      save, remove, refreshTask, createTag,
    }
  },
}
</script>
