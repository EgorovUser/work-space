<template>
  <button
    class="icon-btn theme-btn"
    type="button"
    :title="meta.title"
    :aria-label="meta.title"
    @click="cycle"
  >
    <span class="theme-btn-icon" aria-hidden="true">{{ meta.icon }}</span>
  </button>
</template>

<script>
import { computed } from "vue"
import { useTheme } from "../composables/useTheme"

const META = {
  auto: { icon: "◐", title: "Тема: как в системе" },
  light: { icon: "☀", title: "Тема: светлая" },
  dark: { icon: "☾", title: "Тема: тёмная" },
}

export default {
  setup() {
    const theme = useTheme()
    const meta = computed(() => META[theme.mode.value] || META.auto)
    return { meta, cycle: theme.cycleTheme }
  },
}
</script>
