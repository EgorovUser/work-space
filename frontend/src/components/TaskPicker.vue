<template>
  <div class="task-picker" ref="root">
    <input
      v-model="query"
      type="text"
      :placeholder="placeholder"
      aria-label="Поиск задачи для фокуса"
      autocomplete="off"
      @input="onInput"
      @focus="onFocus"
      @keydown="onKeydown"
    />
    <div v-if="open" class="task-picker-drop" role="listbox" aria-label="Найденные задачи">
      <div v-if="!results.length" class="task-picker-empty muted">
        {{ query.trim().length < 2 ? "Введите минимум две буквы" : searching ? "Ищем…" : "Открытых задач не нашлось" }}
      </div>
      <button
        v-for="(item, index) in results"
        :key="item.id"
        type="button"
        class="task-picker-item"
        :class="{ active: index === activeIndex }"
        role="option"
        :aria-selected="index === activeIndex"
        @mouseenter="activeIndex = index"
        @click="choose(item)"
      >
        <span class="task-picker-title">{{ item.title }}</span>
        <span class="task-picker-proj">{{ item.project_name }} · {{ item.status_name }}</span>
      </button>
    </div>
  </div>
</template>

<script>
import { onBeforeUnmount, onMounted, ref } from "vue"
import { api } from "../api"

// Выбор задачи поиском (патч AF): вместо селекта из тридцати задач со
// сроками — живой FTS5-поиск по всем открытым задачам всех проектов.
// Скелет как у командной палитры: дебаунс, защита от поздних ответов,
// стрелки и Enter, закрытие по Esc и клику мимо.
export default {
  props: {
    placeholder: { type: String, default: "Задача для фокуса: поиск…" },
  },
  emits: ["select"],
  setup(props, { emit }) {
    const root = ref(null)
    const query = ref("")
    const results = ref([])
    const open = ref(false)
    const searching = ref(false)
    const activeIndex = ref(0)
    let timer = null
    let requestId = 0

    function onInput() {
      if (timer) clearTimeout(timer)
      const value = query.value.trim()
      activeIndex.value = 0
      if (value.length < 2) {
        results.value = []
        return
      }
      searching.value = true
      timer = setTimeout(run, 250)
    }

    function onFocus() {
      open.value = true
    }

    async function run() {
      const value = query.value.trim()
      if (value.length < 2) return
      const id = ++requestId
      try {
        const data = await api("/api/tasks/search?q=" + encodeURIComponent(value))
        if (id !== requestId) return // пришёл ответ более позднего запроса
        results.value = data.items || []
      } catch {
        if (id === requestId) results.value = []
      } finally {
        if (id === requestId) searching.value = false
      }
    }

    function choose(item) {
      if (!item) return
      close()
      emit("select", {
        id: item.id,
        project_id: item.project_id,
        project_name: item.project_name,
        title: item.title,
      })
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault()
        close()
        return
      }
      if (!open.value || !results.value.length) return
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault()
        const total = results.value.length
        const delta = event.key === "ArrowDown" ? 1 : -1
        activeIndex.value = (activeIndex.value + delta + total) % total
        return
      }
      if (event.key === "Enter") {
        event.preventDefault()
        choose(results.value[activeIndex.value])
      }
    }

    function close() {
      open.value = false
      activeIndex.value = 0
    }

    function onDocClick(event) {
      if (root.value && !root.value.contains(event.target)) close()
    }

    onMounted(() => document.addEventListener("click", onDocClick))
    onBeforeUnmount(() => {
      document.removeEventListener("click", onDocClick)
      if (timer) clearTimeout(timer)
    })

    return {
      root,
      query,
      results,
      open,
      searching,
      activeIndex,
      placeholder: props.placeholder,
      onInput,
      onFocus,
      onKeydown,
      choose,
    }
  },
}
</script>
