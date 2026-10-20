<template>
  <div class="topbar-search">
    <input
      v-model="query"
      type="search"
      placeholder="Поиск: задачи, письма, заметки…"
      aria-label="Поиск по всему workspace"
      @input="onInput"
      @focus="onInput"
      @keydown.escape="close"
      @keydown.enter="jumpFirst"
    />
    <div v-if="open" class="search-drop" role="listbox">
      <div v-if="!groups.length" class="search-empty muted">
        {{ searching ? "Ищем…" : "Ничего не нашлось" }}
      </div>
      <section v-for="group in groups" :key="group.id" class="search-group">
        <div class="search-group-label">{{ group.label }}</div>
        <button
          v-for="item in group.items"
          :key="group.id + '-' + item.id"
          class="search-item"
          type="button"
          role="option"
          @click="go(group, item)"
        >
          <span class="search-item-title">
            {{ item.title }}<span v-if="item.archived" class="muted"> · архив</span>
          </span>
          <span v-if="item.snippet" class="search-item-snip">
            <template v-for="(part, index) in parts(item.snippet)" :key="index">
              <mark v-if="part.mark">{{ part.text }}</mark>
              <template v-else>{{ part.text }}</template>
            </template>
          </span>
        </button>
      </section>
    </div>
  </div>
</template>

<script>
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"

const LINKS = {
  tasks: (item) => `/projects/${item.project_id}/tasks/${item.id}`,
  notes: (item) => `/projects/${item.project_id}/notes`,
  mail: (item) => `/mail/${item.id}`,
  documents: (item) => `/projects/${item.project_id}/documents/${item.id}`,
  examples: (item) => `/projects/${item.project_id}/examples/${item.id}`,
  secrets: (item) => `/projects/${item.project_id}/secrets/${item.id}`,
}

export default {
  setup() {
    const router = useRouter()
    const route = useRoute()
    const query = ref("")
    const groups = ref([])
    const open = ref(false)
    const searching = ref(false)
    let timer = null
    let requestId = 0

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

    function onInput() {
      if (timer) clearTimeout(timer)
      const value = query.value.trim()
      if (value.length < 2) {
        groups.value = []
        open.value = false
        return
      }
      open.value = true
      searching.value = true
      timer = setTimeout(run, 250)
    }

    async function run() {
      const value = query.value.trim()
      if (value.length < 2) return
      const id = ++requestId
      try {
        const data = await api("/api/search?q=" + encodeURIComponent(value) + "&limit=5")
        if (id !== requestId) return // пришёл ответ более позднего запроса
        groups.value = data.groups || []
      } catch {
        if (id === requestId) groups.value = []
      } finally {
        if (id === requestId) searching.value = false
      }
    }

    function go(group, item) {
      close()
      const link = LINKS[group.id]
      if (link) router.push(link(item))
    }

    function jumpFirst() {
      for (const group of groups.value) {
        if (group.items.length) {
          go(group, group.items[0])
          return
        }
      }
    }

    function close() {
      open.value = false
    }

    function onDocClick(event) {
      if (!event.target.closest(".topbar-search")) close()
    }

    watch(
      () => route.fullPath,
      () => close()
    )

    onMounted(() => document.addEventListener("click", onDocClick))
    onBeforeUnmount(() => {
      document.removeEventListener("click", onDocClick)
      if (timer) clearTimeout(timer)
    })

    return { query, groups, open, searching, parts, onInput, go, jumpFirst, close }
  },
}
</script>
