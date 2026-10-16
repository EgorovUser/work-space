<template>
  <div class="tabs" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      class="tab"
      type="button"
      role="tab"
      :class="{ active: modelValue === tab.id }"
      :aria-selected="modelValue === tab.id"
      @click="$emit('update:modelValue', tab.id)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>

<script>
export default {
  props: {
    tabs: { type: Array, required: true },
    modelValue: { type: String, required: true },
  },
  emits: ["update:modelValue"],
}
</script>
