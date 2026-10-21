<template>
  <AppShell>
    <div class="page-head today-head">
      <h1>Сегодня</h1>
      <span class="muted today-date">{{ todayLabel }}</span>
      <button
        v-if="!loading && !unavailable && !error"
        class="btn secondary today-edit-toggle"
        type="button"
        @click="toggleEditing"
      >{{ editing ? "Готово" : "Настроить" }}</button>
    </div>

    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="6" />

    <template v-else>
      <p v-if="uiError" class="banner today-config-error">{{ uiError }}</p>

      <!-- Патч AW: страница собрана из элементов реестра — сеткой рулит
           конфигурация (ui_configs на бэкене), правится визуальным
           редактором. Данные страницы прежние: один агрегат /api/home. -->
      <div class="today-designer" :class="{ editing }">
        <div class="today-canvas">
          <PageRenderer
            :items="items"
            :catalog="catalog"
            :context="context"
            :editing="editing"
            :selected="selected"
            :settings="settings"
            @select="onSelect"
          />
        </div>
        <PropertyPanel
          v-if="editing"
          :items="items"
          :catalog="catalog"
          :settings="settings"
          :selected="selected"
          :busy="pending"
          :save-error="saveError"
          :is-default="isDefault"
          :revisions="revisions"
          @close="toggleEditing"
          @select="onSelect"
          @update-prop="updateProp"
          @update-setting="updateSetting"
          @move="moveElement"
          @remove="removeElement"
          @add="addElement"
          @reset="onReset"
          @restore="onRestore"
          @retry-save="flush"
          @refresh-revisions="refreshRevisions"
        />
      </div>
    </template>
  </AppShell>
</template>

<script>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import AppShell from "../components/AppShell.vue"
import SkeletonList from "../components/SkeletonList.vue"
import PageRenderer from "../components/ui/PageRenderer.vue"
import PropertyPanel from "../components/ui/PropertyPanel.vue"
import { api } from "../api"
import { useUiConfig } from "../composables/useUiConfig"
import { fallbackItems } from "../ui/todayElements.js"

// Хаб «Сегодня»: один экран вместо утреннего обхода разделов. Данные —
// агрегат /api/home по всем проектам.
//
// Патч AW: секции хаба стали элементами реестра (components/today/),
// порядок и видимость — персональная конфигурация страницы
// (useUiConfig + визуальный редактор с панелью свойств). Кто ни разу
// не открывал редактор, видит прежнюю раскладку: дефолт конфига
// повторяет каталог и уважает старые настройки home.show_*.
export default {
  components: { AppShell, SkeletonList, PageRenderer, PropertyPanel },
  setup() {
    const projects = ref([])
    const tasks = ref([])
    const letters = ref([])
    const events = ref([])
    const notifications = ref([])
    const error = ref("")
    const unavailable = ref(false)
    const loading = ref(true)
    const moreTasks = ref(false)
    const moreBusy = ref(false)

    const route = useRoute()
    const router = useRouter()

    const ui = useUiConfig("today", { fallback: fallbackItems() })
    const {
      items, settings, catalog, isDefault, loaded, error: uiError, editing, selected,
      pending, saveError, revisions, updateProp, updateSetting, addElement, removeElement,
      moveElement, reset, restore, flush, refreshRevisions,
    } = ui

    const overdue = computed(() => tasks.value.filter((item) => item.overdue))
    const upcoming = computed(() => tasks.value.filter((item) => !item.overdue))

    // Элементы «Сегодня» питаются контекстом страницы: данными сводки
    // и колбэками пагинации. Помодоро — самостоятельный синглтон.
    const context = computed(() => ({
      projects: projects.value,
      overdue: overdue.value,
      upcoming: upcoming.value,
      letters: letters.value,
      events: events.value,
      notifications: notifications.value,
      moreTasks: moreTasks.value,
      moreBusy: moreBusy.value,
      loadMoreTasks,
    }))

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

    // Режим правки живёт в адресе (?edit=1): глубокая ссылка, e2e и
    // честная кнопка «назад» без магии.
    watch(
      () => route.query.edit,
      (value) => {
        editing.value = value === "1"
        if (editing.value) refreshRevisions()
      },
      { immediate: true }
    )

    function toggleEditing() {
      const next = !editing.value
      const query = { ...route.query }
      if (next) query.edit = "1"
      else delete query.edit
      router.replace({ query })
    }

    function onSelect(element) {
      selected.value = element
    }

    async function onReset() {
      try {
        await reset()
      } catch (err) {
        saveError.value = "Не получилось: " + (err.message || "ошибка")
      }
    }

    async function onRestore(revisionId) {
      try {
        await restore(revisionId)
      } catch (err) {
        saveError.value = "Не получилось: " + (err.message || "ошибка")
      }
    }

    // Esc выходит из редактора — как из палитры.
    function onKeydown(event) {
      if (event.key === "Escape" && editing.value) toggleEditing()
    }

    const loadingAll = computed(() => loading.value || !loaded.value)

    onMounted(() => {
      window.addEventListener("keydown", onKeydown)
      ui.start()
      load()
    })
    onBeforeUnmount(() => {
      window.removeEventListener("keydown", onKeydown)
      ui.stop()
    })

    return {
      projects, overdue, upcoming, letters, events, notifications,
      error, unavailable, loading: loadingAll, todayLabel,
      moreTasks, moreBusy, loadMoreTasks, context,
      items, settings, catalog, isDefault, uiError, editing, selected, pending, saveError, revisions,
      updateProp, updateSetting, addElement, removeElement, moveElement,
      toggleEditing, onSelect, onReset, onRestore, flush, refreshRevisions,
    }
  },
}
</script>
