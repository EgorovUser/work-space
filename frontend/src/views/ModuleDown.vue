<template>
  <div>
    <h1>{{ title }}</h1>
    <p class="banner">Модуль недоступен</p>
  </div>
</template>

<script>
export default {
  inheritAttrs: false,
  props: {
    title: { type: String, required: true },
    project: { type: Object, default: null },
  },
}
</script>
