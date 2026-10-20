<template>
  <AppShell>
    <div class="page-head">
      <h1>Сегодня</h1>
      <span class="muted today-date">{{ todayLabel }}</span>
    </div>

    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="6" />

    <template v-else>
      <div class="today-grid">
        <section v-if="sections.tasks" class="card">
          <h2>Просроченные <span v-if="overdue.length" class="pill warn">{{ overdue.length }}</span></h2>
          <p v-if="!overdue.length" class="muted">Просроченных нет — можно выдыхать</p>
          <div v-for="item in overdue" :key="item.id" class="status-row">
            <div>
              <router-link :to="'/projects/' + item.project_id + '/tasks/' + item.id">{{ item.title }}</router-link>
              <span v-if="priorityLabel(item.priority)" class="pill" :class="priorityClass(item.priority)">{{ priorityLabel(item.priority) }}</span>
              <div class="muted">{{ item.project_name }}</div>
            </div>
            <span class="bad-text">{{ when(item.deadline) }}</span>
          </div>
        </section>

        <section v-if="sections.tasks" class="card">
          <h2>Ближайшие сроки</h2>
          <p v-if="!upcoming.length" class="muted">Открытых задач со сроком нет</p>
          <div v-for="item in upcoming" :key="item.id" class="status-row">
            <div>
              <router-link :to="'/projects/' + item.project_id + '/tasks/' + item.id">{{ item.title }}</router-link>
              <span v-if="priorityLabel(item.priority)" class="pill" :class="priorityClass(item.priority)">{{ priorityLabel(item.priority) }}</span>
              <div class="muted">{{ item.project_name }}</div>
            </div>
            <span class="muted">{{ when(item.deadline) }}</span>
          </div>
          <button
            v-if="moreTasks"
            class="btn secondary today-more"
            type="button"
            :disabled="moreBusy"
            @click="loadMoreTasks"
          >{{ moreBusy ? "Загружаем…" : "Показать ещё задачи" }}</button>
        </section>

        <section class="card today-pomo">
          <h2>Помодоро</h2>
          <template v-if="pomo.state.running">
            <div class="pomo-clock" :class="{ break: pomo.state.phase === 'break' }">{{ pomo.label() }}</div>
            <p class="muted">
              <template v-if="pomo.state.task">{{ pomo.state.task.title }} · после фокуса запишется в «Время»</template>
              <template v-else>Фокус без задачи — просто таймер</template>
            </p>
            <div class="row-actions">
              <button v-if="pomo.state.phase === 'break'" class="btn secondary" type="button" @click="pomo.skipBreak()">Закончить перерыв</button>
              <button class="btn secondary" type="button" @click="pomo.stop()">Стоп</button>
            </div>
          </template>
          <template v-else>
            <p class="muted">
              {{ pomo.state.settings.workMinutes }} минут фокуса, {{ pomo.state.settings.breakMinutes }} отдыха.
              <span v-if="pomo.state.sessions">Завершено на этой вкладке: {{ pomo.state.sessions }}.</span>
            </p>
            <label class="check">
              <input v-model.number="workMinutes" class="pomo-input" type="number" min="1" max="120" />
              <span>мин фокуса</span>
            </label>
            <label class="check">
              <input v-model.number="breakMinutes" class="pomo-input" type="number" min="1" max="60" />
              <span>мин перерыва</span>
            </label>
            <label class="check">
              <input v-model="autoBreak" type="checkbox" />
              <span>перерыв стартует сам</span>
            </label>
            <div class="row-actions">
              <select v-model="pomoTaskId" class="pomo-task">
                <option value="">Без задачи (просто таймер)</option>
                <option v-for="item in pomoTasks" :key="item.id" :value="String(item.id)">
                  {{ item.title }} · {{ item.project_name }}
                </option>
              </select>
              <button class="btn" type="button" @click="startPomo()">Старт</button>
            </div>
          </template>
        </section>

        <section v-if="sections.events" class="card">
          <h2>События на сегодня</h2>
          <p v-if="!events.length" class="muted">Событий из почты на сегодня нет</p>
          <div v-for="item in events" :key="item.id" class="status-row">
            <div>
              <router-link :to="'/mail/' + item.message_id">{{ item.summary }}</router-link>
              <div v-if="item.location" class="muted">{{ item.location }}</div>
            </div>
            <span class="muted">{{ when(item.starts_at) }}</span>
          </div>
        </section>

        <section v-if="sections.mail" class="card">
          <h2>Новые письма</h2>
          <p v-if="!letters.length" class="muted">Непрочитанных нет</p>
          <div v-for="item in letters" :key="item.id" class="status-row">
            <div>
              <router-link :to="'/mail/' + item.id">{{ item.title }}</router-link>
              <span v-if="item.thread_count > 1" class="muted"> · {{ item.thread_count }} в переписке</span>
              <div class="muted">
                {{ item.project_name }}
                <span v-if="item.attachment_count"> · вложения {{ item.attachment_count }}</span>
              </div>
            </div>
            <span class="muted">{{ when(item.received_at) }}</span>
          </div>
        </section>

        <section v-if="sections.notifications" class="card">
          <h2>Уведомления</h2>
          <p v-if="!notifications.length" class="muted">Уведомлений нет</p>
          <div v-for="item in notifications" :key="item.id" class="status-row">
            <div>
              <router-link v-if="item.link" :to="item.link">{{ item.title }}</router-link>
              <strong v-else :class="{ unread: !item.read }">{{ item.title }}</strong>
              <div v-if="item.body" class="muted clip">{{ item.body }}</div>
            </div>
            <span class="muted">{{ when(item.created_at) }}</span>
          </div>
        </section>
      </div>

      <section class="card">
        <div class="page-head">
          <h2>Проекты</h2>
          <router-link to="/projects" class="text-btn">Все проекты →</router-link>
        </div>
        <p v-if="!projects.length" class="muted">
          Проектов пока нет —
          <router-link to="/projects">создайте первый</router-link>.
        </p>
        <div v-else class="list">
          <router-link v-for="project in projects" :key="project.id" class="list-row" :to="'/projects/' + project.id">
            <strong>{{ project.name }}</strong>
            <span v-if="project.description" class="muted clip">{{ project.description }}</span>
            <span class="stats">
              <span v-if="project.card.show_open_tasks">Открытые {{ project.open_tasks ?? "—" }}</span>
              <span v-if="project.card.show_overdue && project.overdue_tasks">Просроченные {{ project.overdue_tasks }}</span>
              <span v-if="project.card.show_new_mail && project.new_mail">Письма {{ project.new_mail }}</span>
            </span>
          </router-link>
        </div>
      </section>
    </template>
  </AppShell>
</template>

<script>
import { computed, onMounted, ref, watch } from "vue"
import AppShell from "../components/AppShell.vue"
import SkeletonList from "../components/SkeletonList.vue"
import { api } from "../api"
import { usePomodoro } from "../composables/usePomodoro"
import { useWhen } from "../composables/useWhen"

// Хаб «Сегодня»: один экран вместо утреннего обхода разделов. Данные —
// агрегат /api/home по всем проектам; ленты второстепенные, падение блока
// не должно ронять остальные.
//
// Патч N: приоритетные метки у задач (важное видно сразу), «Показать ещё»
// для задач и карточка помодоро — фокус по задаче из списка дня.
const PRIORITIES = {
  high: "важная",
  normal: "обычная",
  low: "низкая",
}

export default {
  components: { AppShell, SkeletonList },
  setup() {
    const projects = ref([])
    const tasks = ref([])
    const letters = ref([])
    const events = ref([])
    const notifications = ref([])
    const sections = ref({ tasks: true, mail: true, events: true, notifications: true })
    const error = ref("")
    const unavailable = ref(false)
    const loading = ref(true)
    const moreTasks = ref(false)
    const moreBusy = ref(false)
    const { when } = useWhen()
    const pomo = usePomodoro()

    const overdue = computed(() => tasks.value.filter((item) => item.overdue))
    const upcoming = computed(() => tasks.value.filter((item) => !item.overdue))

    // Задачи для помодоро: всё со сроком, что уже показано на экране.
    const pomoTasks = computed(() => tasks.value.slice(0, 30))
    const pomoTaskId = ref("")
    const workMinutes = ref(pomo.state.settings.workMinutes)
    const breakMinutes = ref(pomo.state.settings.breakMinutes)
    const autoBreak = ref(pomo.state.settings.autoBreak)

    watch(workMinutes, (value) => pomo.updateSettings({ workMinutes: value }))
    watch(breakMinutes, (value) => pomo.updateSettings({ breakMinutes: value }))
    watch(autoBreak, (value) => pomo.updateSettings({ autoBreak: value }))

    function startPomo() {
      const chosen = pomoTasks.value.find((item) => String(item.id) === pomoTaskId.value)
      pomo.start(chosen || null)
    }

    function priorityLabel(value) {
      return PRIORITIES[value] || ""
    }

    function priorityClass(value) {
      if (value === "high") return "warn"
      if (value === "low") return "low"
      return ""
    }

    const todayLabel = computed(() => {
      const now = new Date()
      return now.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" })
    })

    let taskLimit = 10

    async function load(taskOffset = 0, append = false) {
      if (taskOffset === 0) {
        loading.value = true
        error.value = ""
        unavailable.value = false
      } else {
        moreBusy.value = true
      }
      try {
        const params = taskOffset ? "?task_offset=" + taskOffset : ""
        const data = await api("/api/home" + params)
        projects.value = data.projects || []
        if (append) {
          const seen = new Set(tasks.value.map((item) => item.id))
          tasks.value = tasks.value.concat((data.tasks || []).filter((item) => !seen.has(item.id)))
        } else {
          tasks.value = data.tasks || []
        }
        letters.value = data.mail || []
        events.value = data.events || []
        notifications.value = data.notifications || []
        sections.value = data.sections || sections.value
        taskLimit = Number(data.task_limit) || taskLimit
        moreTasks.value = (data.tasks || []).length >= taskLimit
      } catch (err) {
        if (err.status === 503) unavailable.value = true
        else error.value = err.message || "Не удалось загрузить сводку"
      } finally {
        loading.value = false
        moreBusy.value = false
      }
    }

    function loadMoreTasks() {
      if (moreBusy.value) return
      load(tasks.value.length, true)
    }

    onMounted(() => load())
    return {
      projects, overdue, upcoming, letters, events, notifications, sections,
      error, unavailable, loading, when, todayLabel, load,
      moreTasks, moreBusy, loadMoreTasks,
      pomo, pomoTasks, pomoTaskId, workMinutes, breakMinutes, autoBreak, startPomo,
      priorityLabel, priorityClass,
    }
  },
}
</script>
