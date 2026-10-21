<template>
  <div class="designer-picker">
    <p class="muted">Карточки, которых нет на странице:</p>
    <button
      v-for="option in options"
      :key="option.name"
      class="designer-picker-item"
      type="button"
      @click="$emit('add', option.name)"
    >
      + {{ option.title }}
    </button>
  </div>
</template>

<script>
// Пикер элементов (патч AW): что можно добавить на страницу — всё, чего
// в конфиге ещё нет. Список приходит из каталога, компонент показывает
// подписи и отдаёт имя.
export default {
  name: "ElementPicker",
  props: {
    options: { type: Array, required: true },
  },
  emits: ["add"],
}
</script>
