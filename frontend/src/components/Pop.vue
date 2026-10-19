<template>
  <div ref="root" class="pop">
    <slot name="trigger" :open="open" :toggle="toggle" />
    <Teleport to="body">
      <div v-if="open" ref="panel" class="pop-panel" :class="{ wide }" :style="style">
        <slot :close="close" />
      </div>
    </Teleport>
  </div>
</template>

<script>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { usePop } from "../composables/usePop"

export default {
  props: {
    align: { type: String, default: "start" },
    wide: { type: Boolean, default: false },
  },
  setup(props) {
    const root = ref(null)
    const panel = ref(null)
    const style = ref({})
    const pop = usePop(root, panel)

    function place() {
      const trigger = root.value && (root.value.querySelector("button, a") || root.value)
      if (!trigger) return
      const rect = trigger.getBoundingClientRect()
      const width = props.wide ? 340 : Math.max(180, rect.width)
      let left = props.align === "end" ? rect.right - width : rect.left
      left = Math.max(8, Math.min(left, window.innerWidth - width - 8))
      let top = rect.bottom + 6
      const estimated = panel.value ? panel.value.offsetHeight : 240
      if (top + estimated > window.innerHeight - 8) top = Math.max(8, rect.top - estimated - 6)
      style.value = { left: left + "px", top: top + "px", width: width + "px" }
    }

    watch(pop.open, async (value) => {
      if (!value) return
      await nextTick()
      place()
    })

    onMounted(() => {
      window.addEventListener("resize", place)
      window.addEventListener("scroll", place, true)
    })
    onBeforeUnmount(() => {
      window.removeEventListener("resize", place)
      window.removeEventListener("scroll", place, true)
    })

    return { root, panel, style, ...pop }
  },
}
</script>
