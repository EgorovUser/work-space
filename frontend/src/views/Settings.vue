<template>
  <AppShell>
    <h1>Настройки</h1>
    <p class="muted">Токен бота и SMTP — в уведомлениях, туда же галочки «куда слать». Здесь остальные параметры.</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">Загрузка…</p>
    <template v-else>
      <Tabs v-model="tab" :tabs="pageTabs" />
      <div v-if="tab === 'core'" class="card stack">
        <h2>Смена пароля</h2>
        <form class="stack" @submit.prevent="changePassword">
          <label class="tight">
            Текущий пароль
            <input v-model="password.old" type="password" autocomplete="current-password" required />
          </label>
          <label class="tight">
            Новый пароль
            <input v-model="password.new" type="password" autocomplete="new-password" required minlength="8" />
          </label>
          <p v-if="passwordError" class="error">{{ passwordError }}</p>
          <p v-if="passwordOk" class="muted">Пароль изменён. Войдите заново.</p>
          <button class="btn" type="submit" :disabled="passwordBusy">Сменить пароль</button>
        </form>
      </div>
      <div v-if="current" class="settings-grid">
        <section v-for="card in cards" :key="card.name" class="card">
          <h2>{{ card.label }}</h2>
          <template v-if="hasScope(card.items, 'global')">
            <h3 v-if="hasScope(card.items, 'user')" class="muted">Общие</h3>
            <SettingsForm :items="card.items" scope="global" @changed="load" />
            <DbTools v-if="card.name === 'db'" />
          </template>
          <template v-if="hasScope(card.items, 'user')">
            <h3 v-if="hasScope(card.items, 'global')" class="muted">Только для меня</h3>
            <SettingsForm :items="card.items" scope="user" @changed="load" />
          </template>
        </section>
      </div>
    </template>
  </AppShell>
</template>

<script>
import { computed, onMounted, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import AppShell from "../components/AppShell.vue"
import SettingsForm from "../components/SettingsForm.vue"
import DbTools from "../components/DbTools.vue"
import Tabs from "../components/Tabs.vue"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"
import { useSettings } from "../composables/useSettings"
import { useAuth } from "../composables/useAuth"

const NAMES = {
  core: "Общие",
  projects: "Проекты",
  tasks: "Задачи",
  documents: "Документы",
  examples: "Примеры",
  secrets: "Секреты",
  timetracking: "Время",
  mail: "Почта",
  notifications: "Уведомления",
}

const GROUPS = {
  account: "Ящик",
  imap: "Сервер",
  fetch: "Выгрузка",
  filters: "Фильтры",
  message: "Письмо",
  events: "События из почты",
  body: "Текст",
  list: "Списки",
  search: "Поиск",
  rules: "Поля фильтров",
  rule: "Фильтр",
  job: "Автозабор",
  title: "Названия",
  name: "Названия",
  description: "Описания",
  dashboard: "Главная проекта",
  home: "Главный экран",
  card: "Карточка",
  ui: "Интерфейс",
  http: "Сеть",
  files: "Файлы",
  auth: "Вход",
  log: "Журнал",
  logs: "Журнал",
  comment: "Комментарии",
  checklist: "Чеклист",
  deadline: "Сроки",
  deadlines: "Сроки",
  priority: "Приоритет",
  priorities: "Приоритеты",
  progress: "Прогресс",
  status: "Колонки",
  tag: "Метки",
  preview: "Просмотр",
  version: "Версии",
  versions: "Версии",
  extract: "Разбор файла",
  language: "Язык",
  languages: "Языки",
  note: "Заметки",
  generator: "Генератор",
  kind: "Виды",
  kinds: "Виды",
  timer: "Таймер",
  report: "Отчёт",
  week: "Неделя",
  channels: "Каналы",
  matrix: "Куда слать",
  audience: "Кому",
  delivery: "Доставка",
  bell: "Колокольчик",
  db: "База",
  watch: "Следить за состоянием",
  link: "Ссылки",
  error: "Ошибки",
  statuses: "Статусы",
  outbox: "Очередь",
  scheduler: "Планировщик",
  entry: "Запись",
  manual: "Вручную",
  board: "Доска",
  secret: "Секрет",
  username: "Логин",
  url: "Адрес",
  smtp: "Почта уведомлений",
  telegram: "Telegram",
}

const HIDDEN = new Set([
  "notifications.events",
  "notifications.channels",
  "notifications.statuses",
  "notifications.matrix",
  "mail.rules.actions",
  "mail.rules.default_action",
  "mail.rules.notify_actions",
  "mail.fetch.initial_limit",
])

export default {
  components: { AppShell, DbTools, SettingsForm, Tabs },
  setup() {
    const items = ref([])
    const error = ref("")
    const loading = ref(true)
    const tab = ref("core")
    const settings = useSettings()
    const auth = useAuth()
    const notice = useNotice()
    const router = useRouter()
    const password = reactive({ old: "", new: "" })
    const passwordError = ref("")
    const passwordOk = ref(false)
    const passwordBusy = ref(false)

    const groups = computed(() => {
      const map = new Map()
      for (const item of items.value) {
        if (item.module === "notifications" && (item.key.startsWith("telegram.") || item.key.startsWith("smtp."))) {
          continue
        }
        if (HIDDEN.has(item.module + "." + item.key)) continue
        if (!map.has(item.module)) map.set(item.module, [])
        map.get(item.module).push(item)
      }
      return Array.from(map, ([name, groupItems]) => ({ name, items: groupItems })).filter(
        (group) => hasScope(group.items, "global") || hasScope(group.items, "user")
      )
    })

    const pageTabs = computed(() => groups.value.map((group) => ({ id: group.name, label: NAMES[group.name] || group.name })))
    const current = computed(() => groups.value.find((group) => group.name === tab.value) || groups.value[0] || null)
    const cards = computed(() => {
      const source = (current.value && current.value.items) || []
      const map = new Map()
      for (const item of source) {
        const prefix = item.key.split(".")[0]
        if (!map.has(prefix)) map.set(prefix, [])
        map.get(prefix).push(item)
      }
      return Array.from(map, ([name, groupItems]) => ({ name, label: GROUPS[name] || name, items: groupItems })).filter(
        (card) => hasScope(card.items, "global") || hasScope(card.items, "user")
      )
    })

    function hasScope(groupItems, scope) {
      return groupItems.some((item) => item.allowed_scopes.includes(scope) && item.values && item.values[scope])
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const data = await api("/api/settings")
        items.value = data.items || []
        await settings.load()
        if (!groups.value.some((group) => group.name === tab.value) && groups.value.length) {
          tab.value = groups.value[0].name
        }
      } catch (err) {
        error.value = err.message || "Настройки недоступны"
      } finally {
        loading.value = false
      }
    }

    async function changePassword() {
      passwordError.value = ""
      passwordOk.value = false
      passwordBusy.value = true
      try {
        await api("/api/auth/password", {
          method: "POST",
          body: { old_password: password.old, new_password: password.new },
        })
        password.old = ""
        password.new = ""
        passwordOk.value = true
        // Тост глобальный — переживёт выход на экран входа.
        notice.show("Пароль изменён — войдите с новым", { kind: "success" })
        await auth.logout()
        router.push("/login")
      } catch (err) {
        passwordError.value = err.message || "Не удалось сменить пароль"
      } finally {
        passwordBusy.value = false
      }
    }

    onMounted(load)
    return {
      error,
      loading,
      tab,
      pageTabs,
      current,
      cards,
      hasScope,
      load,
      password,
      passwordError,
      passwordOk,
      passwordBusy,
      changePassword,
    }
  },
}
</script>
