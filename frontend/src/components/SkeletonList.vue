<template>
  <div class="skel-list" aria-hidden="true">
    <div v-for="row in rows" :key="row" class="skel-row">
      <span class="skel skel-title"></span>
      <span class="skel skel-meta"></span>
      <span class="skel skel-meta skel-meta--short"></span>
    </div>
  </div>
</template>

<script>
// Серые заглушки на время загрузки списка: показывают форму будущих строк
// вместо мигания «пусто → загрузилось». Высота строк похожа на .list-row.
export default {
  props: {
    rows: { type: Number, default: 4 },
  },
}
</script>
