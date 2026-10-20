<template>
  <AppShell bare>
    <div class="project-wrap" :class="{ 'board-page': isBoard }">
      <nav v-if="project" class="project-tabs" aria-label="Разделы проекта">
        <!-- Свои <a> вместо дефолтных router-link: vue-router считает ссылку
             на индекс-маршрут (/projects/N) активной на ЛЮБОМ дочернем
             разделе — и «Доска» подсвечивалась рядом с текущей вкладкой.
             Активность считаем сами (isTabActive). -->
        <template v-for="link in links" :key="link.to">
          <router-link :to="link.to" custom v-slot="{ href, navigate }">
            <a
              :href="href"
              :class="{ 'router-link-active': isTabActive(link) }"
              :aria-current="isTabActive(link) ? 'page' : null"
              @click="navigate"
            >{{ link.label }}<span
              v-if="link.badge && tabCount(badges[link.badge])"
              class="tab-badge"
              :class="{ zero: !badges[link.badge] }"
            >{{ tabCount(badges[link.badge]) }}</span></a>
          </router-link>
        </template>
      </nav>
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
import { tabCount } from "../composables/countFormat"
import { useChrome } from "../composables/useChrome"
import { useCounters } from "../composables/useCounters"

// Разделы проекта — горизонтальная лента табов под шапкой. Раньше они
// уезжали вторым блоком в рельсу и смешивались с глобальной навигацией;
// теперь у проекта своё жильё, у приложения — своё.
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
        { to: "/projects/" + id + "/documents", label: "Документы", badge: "documents" },
        { to: "/projects/" + id + "/examples", label: "Примеры", badge: "examples" },
        { to: "/projects/" + id + "/secrets", label: "Секреты", badge: "secrets" },
        { to: "/projects/" + id + "/rdp", label: "RDP", badge: "rdp" },
        { to: "/projects/" + id + "/mail", label: "Почта", badge: "mail" },
        { to: "/projects/" + id + "/time", label: "Учёт времени" },
        { to: "/projects/" + id + "/notes", label: "Заметки", badge: "notes" },
        { to: "/projects/" + id + "/settings", label: "Настройки" },
      ]
    })

    // Бейджи разделов (патч U): числа активного — документы, примеры,
    // секреты, RDP, письма по правилам, заметки. Подписаны на хаб
    // счётчиков: навигация и мутации обновляют, опрос страхует.
    const counters = useCounters()
    const badges = computed(() => counters.projectCounts.value || {})

    // «Доска» горит только на самой доске — и на страницах её задач
    // (/tasks/:id открываются с доски). Остальные разделы — на своём корне
    // и на подстраницах: документ, письмо, секрет.
    function isTabActive(link) {
      if (link.exact) {
        return route.path === link.to || route.path.startsWith(link.to + "/tasks/")
      }
      return route.path === link.to || route.path.startsWith(link.to + "/")
    }

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
    watch([project, projectId], () => {
      if (project.value) chrome.setProject(project.value.name)
    })
    watch(projectId, (id) => {
      load()
      counters.bindProject(id)
    })
    onMounted(() => {
      load()
      counters.bindProject(projectId.value)
    })
    onBeforeUnmount(() => chrome.clear())
    return { route, project, error, unavailable, links, load, isBoard, isTabActive, badges, tabCount }
  },
}
</script>
