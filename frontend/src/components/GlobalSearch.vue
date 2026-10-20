<template>
  <div class="topbar-search" :class="{ 'search-idle': !query }" ref="root">
    <input
      ref="input"
      v-model="query"
      type="search"
      :placeholder="placeholder"
      aria-label="Поиск по всему workspace"
      @input="onInput"
      @focus="onFocus"
      @keydown="onKeydown"
    />
    <span v-if="!query" class="search-kbd" aria-hidden="true">Ctrl K</span>
    <div v-if="open" class="search-drop" role="listbox" aria-label="Результаты поиска">
      <div class="search-filters" role="group" aria-label="Фильтр по типам">
        <button
          type="button"
          class="search-chip"
          :class="{ on: !filter }"
          @click="setFilter('')"
        >Все</button>
        <button
          v-for="type in TYPES"
          :key="type.id"
          type="button"
          class="search-chip"
          :class="{ on: filter === type.id }"
          @click="setFilter(type.id)"
        >{{ type.label }}</button>
      </div>

      <template v-if="flat.length">
        <section v-for="section in visibleSections" :key="section.key" class="search-group">
          <div class="search-group-label">{{ section.label }}</div>
          <div
            v-for="entry in section.entries"
            :key="section.key + '-' + entry.key"
            class="search-item"
            :class="{ active: entry.flatIndex === activeIndex }"
            role="option"
            :aria-selected="entry.flatIndex === activeIndex"
            @mouseenter="activeIndex = entry.flatIndex"
            @click="activate(entry)"
          >
            <template v-if="entry.kind === 'command'">
              <span class="search-item-title">{{ entry.item.label }}</span>
              <span class="muted search-item-snip">{{ entry.item.hint }}</span>
            </template>
            <template v-else>
              <span class="search-item-head">
                <span class="search-item-title">
                  {{ entry.item.title }}<span v-if="entry.item.archived" class="muted"> · архив</span>
                </span>
                <span v-if="entry.item.project_name" class="search-item-proj" :title="entry.item.project_name">{{ entry.item.project_name }}</span>
              </span>
              <span v-if="entry.item.snippet" class="search-item-snip">
                <template v-for="(part, index) in parts(entry.item.snippet)" :key="index">
                  <mark v-if="part.mark">{{ part.text }}</mark>
                  <template v-else>{{ part.text }}</template>
                </template>
              </span>
            </template>
          </div>
          <button
            v-if="section.kind === 'group' && !expanded[section.id] && section.entries.length >= 5"
            class="search-more"
            type="button"
            @click="expand(section.id)"
          >Ещё в разделе…</button>
        </section>
      </template>
      <div v-else class="search-empty muted">
        {{ searching ? "Ищем…" : "Ничего не нашлось" }}
      </div>

      <div v-if="recents.length && !query" class="search-recents">
        <span class="search-group-label">Недавние запросы</span>
        <button
          v-for="item in recents"
          :key="item"
          type="button"
          class="search-chip"
          @click="runRecent(item)"
        >{{ item }}</button>
      </div>

      <div class="search-hints muted">
        <span>↑↓ выбор</span><span>Enter открыть</span><span>Esc закрыть</span>
      </div>
    </div>
  </div>
</template>

<script>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"

const LINKS = {
  tasks: (item) => `/projects/${item.project_id}/tasks/${item.id}`,
  notes: (item) => `/projects/${item.project_id}/notes`,
  mail: (item) => `/mail/${item.id}`,
  documents: (item) => `/projects/${item.project_id}/documents/${item.id}`,
  examples: (item) => `/projects/${item.project_id}/examples/${item.id}`,
  secrets: (item) => `/projects/${item.project_id}/secrets/${item.id}`,
  rdp: (item) => `/projects/${item.project_id}/rdp`,
}

const TYPES = [
  { id: "tasks", label: "Задачи" },
  { id: "mail", label: "Письма" },
  { id: "documents", label: "Документы" },
  { id: "secrets", label: "Секреты" },
  { id: "rdp", label: "RDP" },
  { id: "notes", label: "Заметки" },
  { id: "examples", label: "Примеры" },
]

const COMMANDS = [
  { label: "Сегодня", to: "/", hint: "сводка по всем проектам" },
  { label: "Проекты", to: "/projects", hint: "список и доски" },
  { label: "Почта", to: "/mail", hint: "общий ящик" },
  { label: "Секреты", to: "/secrets", hint: "хранилище всех проектов" },
  { label: "Корзина", to: "/trash", hint: "удалённое и восстановление" },
  { label: "Уведомления", to: "/notifications", hint: "лента событий" },
  { label: "Настройки", to: "/settings", hint: "модули и значения" },
  { label: "Состояние", to: "/system", hint: "диагностика" },
]

const RECENTS_KEY = "ws.search.recents"
const FILTER_KEY = "ws.search.filter"
const RECENTS_MAX = 8

function loadRecents() {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENTS_KEY) || "[]")
    return Array.isArray(raw) ? raw.filter((item) => typeof item === "string").slice(0, RECENTS_MAX) : []
  } catch {
    return []
  }
}

// Палитра (патч N): поиск вырос в командную — Ctrl+K открывает, фильтры
// по типам, стрелки и Enter, недавние запросы и быстрые команды разделов.
// Патч P: у каждого результата виден проект — до перехода, не после.
export default {
  setup() {
    const router = useRouter()
    const route = useRoute()
    const root = ref(null)
    const input = ref(null)
    const query = ref("")
    const groups = ref([])
    const open = ref(false)
    const searching = ref(false)
    const activeIndex = ref(0)
    const filter = ref("")
    const recents = ref(loadRecents())
    const expanded = ref({})
    let timer = null
    let requestId = 0

    const placeholder = computed(() => (open.value ? "Поиск или команда…" : "Поиск: задачи, письма, заметки… Ctrl+K"))

    function parts(snippet) {
      // Сниппет приходит с маркерами \x01/\x02 вокруг совпадений — режем
      // на куски и рендерим <mark> без v-html.
      const out = []
      for (const chunk of String(snippet || "").split("\x01")) {
        const closing = chunk.indexOf("\x02")
        if (closing === -1) {
          if (chunk) out.push({ text: chunk, mark: false })
        } else {
          if (closing) out.push({ text: chunk.slice(0, closing), mark: true })
          const rest = chunk.slice(closing + 1)
          if (rest) out.push({ text: rest, mark: false })
        }
      }
      return out
    }

    const commandEntries = computed(() => {
      const needle = query.value.trim().toLowerCase()
      const list = needle
        ? COMMANDS.filter((item) => item.label.toLowerCase().includes(needle))
        : COMMANDS
      return list.map((item) => ({ kind: "command", item }))
    })

    // Плоский список: команды сверху, дальше группы результатов.
    const flat = computed(() => {
      const entries = []
      for (const entry of commandEntries.value) {
        entries.push({ ...entry, key: "cmd-" + entry.item.to })
      }
      for (const group of groups.value) {
        for (const item of group.items) {
          entries.push({ kind: "result", group: group.id, item, key: group.id + "-" + item.id })
        }
      }
      entries.forEach((entry, index) => {
        entry.flatIndex = index
      })
      return entries
    })

    const visibleSections = computed(() => {
      const sections = []
      if (commandEntries.value.length) {
        sections.push({ key: "commands", kind: "commands", label: "Разделы", entries: flat.value.slice(0, commandEntries.value.length) })
      }
      for (const group of groups.value) {
        const entries = flat.value.filter((entry) => entry.kind === "result" && entry.group === group.id)
        sections.push({ key: group.id, kind: "group", id: group.id, label: group.label, entries })
      }
      return sections
    })

    function onInput() {
      if (timer) clearTimeout(timer)
      const value = query.value.trim()
      if (value.length < 2) {
        groups.value = []
        open.value = isPaletteWanted()
        activeIndex.value = 0
        return
      }
      open.value = true
      searching.value = true
      timer = setTimeout(run, 250)
    }

    function onFocus() {
      focusedRecently = true
      if (query.value.trim().length >= 2) open.value = true
      else onInput()
    }

    async function run(limit = 5, types = null) {
      const value = query.value.trim()
      if (value.length < 2) return
      const id = ++requestId
      const params = new URLSearchParams({ q: value, limit: String(limit) })
      const chosen = types === null ? filter.value : types
      if (chosen) params.set("types", chosen)
      try {
        const data = await api("/api/search?" + params.toString())
        if (id !== requestId) return // пришёл ответ более позднего запроса
        if (types === null) {
          groups.value = data.groups || []
          expanded.value = {}
        } else {
          const fresh = (data.groups || []).find((group) => group.id === types)
          groups.value = groups.value.map((group) => (group.id === types && fresh ? { ...fresh } : group))
        }
      } catch {
        if (id === requestId && types === null) groups.value = []
      } finally {
        if (id === requestId) searching.value = false
      }
    }

    async function expand(groupId) {
      expanded.value = { ...expanded.value, [groupId]: true }
      await run(20, groupId)
    }

    function setFilter(value) {
      filter.value = value
      try {
        localStorage.setItem(FILTER_KEY, value)
      } catch {
        /* приватный режим — просто не запомним */
      }
      if (query.value.trim().length >= 2) {
        searching.value = true
        run()
      }
    }

    function runRecent(value) {
      query.value = value
      onInput()
      nextTick(() => input.value && input.value.focus())
    }

    function remember(value) {
      const text = value.trim()
      if (text.length < 2) return
      const next = [text, ...recents.value.filter((item) => item !== text)].slice(0, RECENTS_MAX)
      recents.value = next
      try {
        localStorage.setItem(RECENTS_KEY, JSON.stringify(next))
      } catch {
        /* не критично */
      }
    }

    function activate(entry) {
      if (!entry) return
      if (entry.kind === "command") {
        close()
        router.push(entry.item.to)
        return
      }
      remember(query.value)
      close()
      const link = LINKS[entry.group]
      if (link) router.push(link(entry.item))
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault()
        close()
        return
      }
      if (!open.value) return
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault()
        const total = flat.value.length
        if (!total) return
        const delta = event.key === "ArrowDown" ? 1 : -1
        activeIndex.value = (activeIndex.value + delta + total) % total
        scrollToActive()
        return
      }
      if (event.key === "Enter") {
        const entry = flat.value[activeIndex.value]
        if (entry) {
          event.preventDefault()
          activate(entry)
        }
      }
    }

    function scrollToActive() {
      nextTick(() => {
        const el = root.value && root.value.querySelector(".search-item.active")
        if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" })
      })
    }

    function openPalette() {
      open.value = true
      activeIndex.value = 0
      nextTick(() => input.value && input.value.focus())
    }

    function onHotkey(event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        if (open.value) close()
        else openPalette()
      }
    }

    function isPaletteWanted() {
      // Короткий запрос не ищет, но палитра (команды и недавние) остаётся
      // открытой, пока поле в фокусе — его трогали мышью или Ctrl+K.
      return open.value || focusedRecently
    }

    let focusedRecently = false

    function close() {
      open.value = false
      activeIndex.value = 0
      focusedRecently = false
      if (input.value) input.value.blur()
    }

    function onDocClick(event) {
      if (root.value && !root.value.contains(event.target)) close()
    }

    watch(
      () => route.fullPath,
      () => close()
    )

    watch(query, () => {
      activeIndex.value = 0
    })

    onMounted(() => {
      document.addEventListener("click", onDocClick)
      document.addEventListener("keydown", onHotkey)
      try {
        const saved = localStorage.getItem(FILTER_KEY)
        if (saved && TYPES.some((type) => type.id === saved)) filter.value = saved
      } catch {
        /* нет доступа к localStorage — фильтр просто не восстановится */
      }
    })
    onBeforeUnmount(() => {
      document.removeEventListener("click", onDocClick)
      document.removeEventListener("keydown", onHotkey)
      if (timer) clearTimeout(timer)
    })

    return {
      root, input, query, groups, open, searching, activeIndex, filter, recents, expanded,
      TYPES, placeholder, flat, visibleSections,
      parts, onInput, onFocus, onKeydown, setFilter, runRecent, expand, activate,
    }
  },
}
</script>
