<template>
  <p v-if="value === null || value === undefined" class="banner">Модуль недоступен</p>
  <p v-else-if="!rows.length" class="muted">{{ empty }}</p>
  <ul v-else class="plain-list">
    <li v-for="(row, index) in rows" :key="index">{{ row }}</li>
  </ul>
</template>

<script>
export default {
  props: {
    value: { default: null },
    empty: { type: String, default: "Нет данных" },
  },
  computed: {
    rows() {
      if (!Array.isArray(this.value)) return []
      return this.value.map((item) => {
        if (item == null) return ""
        if (typeof item !== "object") return String(item)
        if (item.title && item.deadline) return item.title + " — " + item.deadline
        if (item.name != null && item.count != null) return item.name + ": " + item.count
        if (item.title) return item.title
        if (item.name) return item.name
        return ""
      }).filter(Boolean)
    },
  },
}
</script>
