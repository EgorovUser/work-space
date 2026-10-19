<template>
  <AppShell>
    <div class="home-grid">
      <section v-if="sections.events" class="card">
        <h2>Сегодня</h2>
        <p v-if="!events.length" class="muted">Событий из почты на сегодня нет</p>
        <div v-for="item in events" :key="item.id" class="status-row">
          <div>
            <router-link :to="'/mail/' + item.message_id">{{ item.summary }}</router-link>
            <div v-if="item.location" class="muted">{{ item.location }}</div>
          </div>
          <span class="muted">{{ when(item.starts_at) }}</span>
        </div>
      </section>
      <section v-if="sections.tasks" class="card">
        <h2>Горящие задачи</h2>
        <p v-if="!hot.length" class="muted">Нет задач со сроком</p>
        <div v-for="item in hot" :key="item.id" class="status-row">
          <div>
            <router-link :to="'/projects/' + item.project_id + '/tasks/' + item.id">{{ item.title }}</router-link>
            <div class="muted">{{ item.project_name }}</div>
          </div>
          <span :class="item.overdue ? 'bad-text' : 'muted'">{{ when(item.deadline) }}</span>
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
    </div>
    <div class="page-head">
      <h1>Проекты</h1>
      <label class="check">
        <input v-model="includeArchived" type="checkbox" @change="load" />
        <span>Архив</span>
      </label>
    </div>
    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <template v-else>
      <form class="composer" @submit.prevent="create">
        <input v-model="name" type="text" placeholder="Новый проект" required />
        <input v-model="description" type="text" placeholder="Описание, можно пустым" />
        <button class="btn" type="submit" :disabled="busy">Создать</button>
      </form>
      <p v-if="createError" class="error">{{ createError }}</p>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!items.length" class="muted">Проектов пока нет.</p>
      <div v-else class="list">
        <router-link v-for="project in items" :key="project.id" class="list-row" :to="'/projects/' + project.id">
          <strong>{{ project.name }} <span v-if="project.archived" class="muted">· архив</span></strong>
          <span v-if="project.description" class="muted">{{ project.description }}</span>
          <span class="stats">
            <span v-if="project.card.show_open_tasks">Открытые {{ stat(project.open_tasks) }}</span>
            <span v-if="project.card.show_overdue">Просроченные {{ stat(project.overdue_tasks) }}</span>
            <span v-if="project.card.show_nearest_deadline">Дедлайн {{ project.nearest_deadline ? when(project.nearest_deadline) : stat(null) }}</span>
            <span v-if="project.card.show_hours_week">Неделя {{ stat(project.hours_week) }}</span>
            <span v-if="project.card.show_new_mail">Письма {{ stat(project.new_mail) }}</span>
          </span>
        </router-link>
      </div>
    </template>
  </AppShell>
</template>

<script>
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import AppShell from "../components/AppShell.vue"
import { api } from "../api"
import { useWhen } from "../composables/useWhen"

export default {
  components: { AppShell },
  setup() {
    const items = ref([])
    const hot = ref([])
    const letters = ref([])
    const events = ref([])
    const sections = ref({ tasks: true, mail: true, events: true })
    const name = ref("")
    const description = ref("")
    const error = ref("")
    const createError = ref("")
    const unavailable = ref(false)
    const includeArchived = ref(false)
    const busy = ref(false)
    const { settings, when } = useWhen()
    const router = useRouter()

    function stat(value) {
      if (value === null || value === undefined) return "недоступно"
      return value
    }

    async function load() {
      error.value = ""
      unavailable.value = false
      try {
        const [data, home] = await Promise.all([
          api("/api/projects?include_archived=" + (includeArchived.value ? "true" : "false")),
          api("/api/home"),
        ])
        items.value = data.items || []
        hot.value = home.tasks || []
        letters.value = home.mail || []
        events.value = home.events || []
        sections.value = home.sections || { tasks: true, mail: true, events: true }
      } catch (err) {
        if (err.status === 503) unavailable.value = true
        else error.value = err.message || "Не удалось загрузить проекты"
      }
    }

    async function create() {
      createError.value = ""
      busy.value = true
      try {
        const project = await api("/api/projects", {
          method: "POST",
          body: { name: name.value, description: description.value },
        })
        router.push("/projects/" + project.id)
      } catch (err) {
        createError.value = err.message || "Не удалось создать"
      } finally {
        busy.value = false
      }
    }

    onMounted(load)
    return { items, hot, letters, events, sections, name, description, error, createError, unavailable, includeArchived, busy, when, stat, load, create }
  },
}
</script>
