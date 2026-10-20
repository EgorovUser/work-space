<template>
  <AppShell>
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
      <SkeletonList v-else-if="loading" :rows="5" />
      <div v-else-if="!items.length" class="empty">
        <strong>Проектов пока нет</strong>
        <span>Создайте первый формой выше — он появится здесь сразу.</span>
      </div>
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
import SkeletonList from "../components/SkeletonList.vue"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"
import { useWhen } from "../composables/useWhen"

// Чистый список проектов. Сводка «что горит» переехала на главную «Сегодня»,
// здесь осталась только работа с самими проектами.
export default {
  components: { AppShell, SkeletonList },
  setup() {
    const items = ref([])
    const name = ref("")
    const description = ref("")
    const error = ref("")
    const createError = ref("")
    const unavailable = ref(false)
    const includeArchived = ref(false)
    const busy = ref(false)
    const loading = ref(true)
    const { when } = useWhen()
    const notice = useNotice()
    const router = useRouter()

    function stat(value) {
      if (value === null || value === undefined) return "недоступно"
      return value
    }

    async function load() {
      loading.value = true
      error.value = ""
      unavailable.value = false
      try {
        const data = await api("/api/projects?include_archived=" + (includeArchived.value ? "true" : "false"))
        items.value = data.items || []
      } catch (err) {
        if (err.status === 503) unavailable.value = true
        else error.value = err.message || "Не удалось загрузить проекты"
      } finally {
        loading.value = false
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
        notice.show("Проект «" + project.name + "» создан", { kind: "success" })
        router.push("/projects/" + project.id)
      } catch (err) {
        createError.value = err.message || "Не удалось создать"
      } finally {
        busy.value = false
      }
    }

    onMounted(load)
    return { items, name, description, error, createError, unavailable, includeArchived, busy, loading, when, stat, load, create }
  },
}
</script>
