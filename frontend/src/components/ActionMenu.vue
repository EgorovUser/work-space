<template>
  <Pop align="end">
    <template #trigger="{ toggle }">
      <button class="text-btn" type="button" @click="toggle">Действия</button>
    </template>
    <template #default="{ close }">
      <button
        v-for="action in actions"
        :key="action.id"
        type="button"
        :class="{ danger: action.danger }"
        @click="choose(action, close)"
      >
        {{ action.label }}
      </button>
    </template>
  </Pop>
</template>

<script>
import Pop from "./Pop.vue"

export default {
  components: { Pop },
  props: {
    actions: { type: Array, required: true },
  },
  emits: ["choose"],
  setup(_, { emit }) {
    function choose(action, close) {
      close()
      emit("choose", action.id)
    }
    return { choose }
  },
}
</script>
