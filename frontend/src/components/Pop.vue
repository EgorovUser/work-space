<template>
  <div ref="root" class="pop" :class="[placement, align]">
    <slot name="trigger" :open="open" :toggle="toggle" />
    <div v-if="open" class="pop-panel">
      <slot :close="close" />
    </div>
  </div>
</template>

<script>
import { ref } from "vue"
import { usePop } from "../composables/usePop"

export default {
  props: {
    placement: { type: String, default: "down" },
    align: { type: String, default: "start" },
  },
  setup() {
    const root = ref(null)
    return { root, ...usePop(root) }
  },
}
</script>
