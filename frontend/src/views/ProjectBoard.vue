<template>
  <div>
    <Tabs v-model="tab" :tabs="pageTabs" />

    <TaskBoard v-if="tab === 'tasks'" :project="project" />

    <div v-else-if="tab === 'summary'">
      <p v-if="error" class="error">{{ error }}</p>
      <div v-else class="split">
        <section class="card">
          <h2>Ближайшие дедлайны</h2>
          <p v-if="!board" class="muted">Загрузка…</p>
          <p v-else-if="board.upcoming_deadlines == null" class="banner">Модуль недоступен</p>
          <p v-else-if="!board.upcoming_deadlines.length" class="muted">Нет дедлайнов</p>
          <ul v-else class="plain-list">
            <li v-for="item in board.upcoming_deadlines" :key="item.id">
              <router-link :to="'/projects/' + project.id + '/tasks/' + item.id">{{ item.title }}</router-link>
              — {{ when(item.deadline) }}
            </li>
          </ul>
        </section>
        <section class="card">
          <h2>Часы</h2>
          <p v-if="!board" class="muted">Загрузка…</p>
          <template v-else>
            <ModuleNote :value="board.hours" empty="Нет записей" />
            <p v-if="Array.isArray(board.hours)">
              <router-link :to="'/projects/' + project.id + '/time'">Открыть учёт</router-link>
            </p>
          </template>
        </section>
        <section class="card">
          <h2>Создание и закрытие</h2>
          <p v-if="!board" class="muted">Загрузка…</p>
          <p v-else-if="board.chart == null" class="banner">Модуль недоступен</p>
          <div v-else class="chart-box"><TrendChart :chart="board.chart" /></div>
        </section>
        <section class="card">
          <h2>Последние документы</h2>
          <p v-if="!board" class="muted">Загрузка…</p>
          <p v-else-if="board.recent_documents == null" class="banner">Модуль недоступен</p>
          <p v-else-if="!board.recent_documents.length" class="muted">Нет документов</p>
          <ul v-else class="plain-list">
            <li v-for="item in board.recent_documents" :key="item.id">
              <router-link :to="'/projects/' + project.id + '/documents/' + item.id">{{ item.title }}</router-link>
            </li>
          </ul>
          <p><router-link :to="'/projects/' + project.id + '/documents'">Все документы</router-link></p>
        </section>
        <section class="card">
          <h2>Последние письма</h2>
          <p v-if="!board" class="muted">Загрузка…</p>
          <p v-else-if="board.recent_mail == null" class="banner">Модуль недоступен</p>
          <p v-else-if="!board.recent_mail.length" class="muted">Нет писем</p>
          <ul v-else class="plain-list">
            <li v-for="item in board.recent_mail" :key="item.id">
              <router-link :to="'/projects/' + project.id + '/mail/' + item.id">{{ item.title }}</router-link>
              <span v-if="item.thread_count > 1" class="muted"> · {{ item.thread_count }}</span>
            </li>
          </ul>
          <p><router-link :to="'/projects/' + project.id + '/mail'">Вся почта</router-link></p>
        </section>
      </div>
    </div>

    <section v-else class="card">
      <h2>Поиск по проекту</h2>
      <form class="row-actions" @submit.prevent="runSearch">
        <input v-model="query" type="text" placeholder="Слово в названии или тексте" />
        <button class="btn" type="submit">Найти</button>
      </form>
      <p v-if="searchError" class="error">{{ searchError }}</p>
      <div v-if="groups" class="split tight">
        <div v-for="group in groupList" :key="group.key">
          <h3>{{ group.label }}</h3>
          <p v-if="group.items === null" class="banner">Модуль недоступен</p>
          <p v-else-if="!group.items.length" class="muted">Ничего не найдено</p>
          <ul v-else class="plain-list">
            <li v-for="item in group.items" :key="item.id">
              <router-link v-if="group.key === 'tasks'" :to="'/projects/' + project.id + '/tasks/' + item.id">{{ item.title }}</router-link>
              <router-link v-else-if="group.key === 'documents'" :to="'/projects/' + project.id + '/documents/' + item.id">{{ item.title }}</router-link>
              <router-link v-else-if="group.key === 'examples'" :to="'/projects/' + project.id + '/examples/' + item.id">{{ item.title }}</router-link>
              <router-link v-else-if="group.key === 'secrets'" :to="'/projects/' + project.id + '/secrets/' + item.id">{{ item.title }}</router-link>
              <router-link v-else-if="group.key === 'mail'" :to="'/projects/' + project.id + '/mail/' + item.id">{{ item.title }}</router-link>
              <span v-else>{{ item.title }}</span>
              <span v-if="item.snippet" class="muted"> — {{ item.snippet }}</span>
            </li>
          </ul>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import { computed, ref, watch } from "vue"
import { api } from "../api"
import { useSettings } from "../composables/useSettings"
import { formatWhen } from "../composables/formatDate"
import TaskBoard from "../components/TaskBoard.vue"
import TrendChart from "../components/TrendChart.vue"
import ModuleNote from "../components/ModuleNote.vue"
import Tabs from "../components/Tabs.vue"

const LABELS = [
  ["tasks", "Задачи"],
  ["documents", "Документы"],
  ["examples", "Примеры"],
  ["mail", "Письма"],
  ["secrets", "Секреты"],
]

export default {
  components: { ModuleNote, Tabs, TaskBoard, TrendChart },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const board = ref(null)
    const error = ref("")
    const query = ref("")
    const groups = ref(null)
    const searchError = ref("")
    const tab = ref("tasks")
    const pageTabs = [
      { id: "tasks", label: "Задачи" },
      { id: "summary", label: "Сводка" },
      { id: "search", label: "Поиск" },
    ]
    const settings = useSettings()

    const groupList = computed(() => {
      if (!groups.value) return []
      return LABELS.map(([key, label]) => ({ key, label, items: groups.value[key] }))
    })

    function when(value) {
      return formatWhen(value, settings.get("core", "ui.date_format"), settings.get("core", "ui.timezone") || undefined)
    }

    async function load() {
      error.value = ""
      try {
        board.value = await api("/api/projects/" + props.project.id + "/dashboard")
      } catch (err) {
        if (err.status === 503) error.value = "Модуль недоступен"
        else error.value = err.message || "Доска недоступна"
      }
    }

    async function runSearch() {
      searchError.value = ""
      groups.value = null
      try {
        const data = await api("/api/projects/" + props.project.id + "/search?q=" + encodeURIComponent(query.value))
        groups.value = data.groups
      } catch (err) {
        searchError.value = err.message || "Поиск не выполнен"
      }
    }

    watch(() => props.project && props.project.id, load, { immediate: true })
    return { board, error, query, groups, groupList, searchError, tab, pageTabs, runSearch, when }
  },
}
</script>
