<template>
  <AppShell bare>
    <div class="project-wrap">
      <header v-if="project" class="project-bar">
        <div class="page-head">
          <h1>{{ project.name }}</h1>
          <router-link to="/">Все проекты</router-link>
        </div>
        <p v-if="project.description" class="muted">{{ project.description }}</p>
        <p v-if="project.archived" class="banner">Проект в архиве</p>
        <nav class="section-nav">
          <router-link
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            :class="{ active: link.exact ? route.path === link.to : route.path.startsWith(link.to) }"
          >
            {{ link.label }}
          </router-link>
        </nav>
      </header>
      <p v-if="unavailable" class="banner">Модуль недоступен</p>
      <p v-else-if="error" class="error">{{ error }}</p>
      <router-view v-else-if="project" v-slot="{ Component }">
        <component :is="Component" :project="project" @changed="load" />
      </router-view>
      <p v-else class="muted">Загрузка…</p>
    </div>
  </AppShell>
</template>

<script>
import { computed, onMounted, provide, ref, watch } from "vue"
import { useRoute } from "vue-router"
import AppShell from "../components/AppShell.vue"
import { api } from "../api"

export default {
  components: { AppShell },
  setup() {
    const route = useRoute()
    const project = ref(null)
    const error = ref("")
    const unavailable = ref(false)
    const projectId = computed(() => route.params.projectId)

    const links = computed(() => {
      const id = projectId.value
      return [
        { to: "/projects/" + id, label: "Доска", exact: true },
        { to: "/projects/" + id + "/documents", label: "Документы" },
        { to: "/projects/" + id + "/examples", label: "Примеры" },
        { to: "/projects/" + id + "/secrets", label: "Секреты" },
        { to: "/projects/" + id + "/mail", label: "Почта" },
        { to: "/projects/" + id + "/time", label: "Учёт времени" },
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
    watch(projectId, load)
    onMounted(load)
    return { route, project, error, unavailable, links, load }
  },
}
</script>

