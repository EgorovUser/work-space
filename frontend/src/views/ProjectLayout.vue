<template>
  <AppShell bare>
    <div class="project-wrap" :class="{ 'board-page': isBoard }">
      <header v-if="project && (project.description || project.archived)" class="project-bar">
        <p v-if="project.description" class="muted clip">{{ project.description }}</p>
        <span v-if="project.archived" class="pill warn">Архив</span>
      </header>
      <p v-if="unavailable" class="banner">Модуль недоступен</p>
      <p v-else-if="error" class="error">{{ error }}</p>
      <div v-else-if="project" class="project-body">
        <router-view v-slot="{ Component }">
          <component :is="Component" :project="project" @changed="load" />
        </router-view>
      </div>
      <p v-else class="muted">Загрузка…</p>
    </div>
  </AppShell>
</template>

<script>
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from "vue"
import { useRoute } from "vue-router"
import AppShell from "../components/AppShell.vue"
import { api } from "../api"
import { useChrome } from "../composables/useChrome"

export default {
  components: { AppShell },
  setup() {
    const route = useRoute()
    const chrome = useChrome()
    const project = ref(null)
    const error = ref("")
    const unavailable = ref(false)
    const projectId = computed(() => route.params.projectId)
    const isBoard = computed(() => route.path === "/projects/" + projectId.value)

    const links = computed(() => {
      const id = projectId.value
      return [
        { to: "/projects/" + id, label: "Доска", exact: true },
        { to: "/projects/" + id + "/documents", label: "Документы" },
        { to: "/projects/" + id + "/examples", label: "Примеры" },
        { to: "/projects/" + id + "/secrets", label: "Секреты" },
        { to: "/projects/" + id + "/mail", label: "Почта" },
        { to: "/projects/" + id + "/time", label: "Учёт времени" },
        { to: "/projects/" + id + "/notes", label: "Заметки" },
        { to: "/projects/" + id + "/settings", label: "Настройки" },
      ]
    })

    async function load() {
      error.value = ""
      unavailable.value = false
      try {
        project.value = await api("/api/projects/" + projectId.value)
      } catch (err) {
        project.value = null
        if (err.status === 503) unavailable.value = true
        else error.value = err.message || "Проект недоступен"
      }
    }

    provide("reloadProject", load)
    watch([project, links], () => {
      if (project.value) chrome.setProject(project.value.name, links.value)
    })
    watch(projectId, load)
    onMounted(load)
    onBeforeUnmount(() => chrome.clear())
    return { route, project, error, unavailable, links, load, isBoard }
  },
}
</script>

