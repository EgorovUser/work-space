<template>
  <div ref="root" class="multi">
    <div class="multi-box">
      <button v-for="id in modelValue" :key="id" class="chip" type="button" @click="remove(id)">
        {{ labelOf(id) }} ×
      </button>
      <input
        v-model="text"
        type="text"
        :placeholder="modelValue.length ? '' : placeholder"
        @focus="show"
        @keydown.enter.prevent="pickFirst"
        @keydown.backspace="onBackspace"
        @keydown.esc="close"
      />
    </div>
    <ul v-if="open && filtered.length" class="multi-menu">
      <li v-for="option in filtered" :key="option.id">
        <button type="button" @mousedown.prevent="add(option.id)">{{ option.label }}</button>
      </li>
    </ul>
    <p v-else-if="open && text && !filtered.length" class="muted">Нет такого варианта</p>
  </div>
</template>

<script>
import { computed, ref } from "vue"
import { usePop } from "../composables/usePop"

export default {
  props: {
    modelValue: { type: Array, default: () => [] },
    options: { type: Array, default: () => [] },
    placeholder: { type: String, default: "Найти и выбрать" },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const root = ref(null)
    const text = ref("")
    const pop = usePop(root)

    const filtered = computed(() => {
      const needle = text.value.trim().toLowerCase()
      const chosen = new Set(props.modelValue)
      return props.options.filter((option) => {
        if (chosen.has(option.id)) return false
        if (!needle) return true
        return String(option.label || option.id).toLowerCase().includes(needle)
      })
    })

    function labelOf(id) {
      const found = props.options.find((option) => option.id === id)
      return found ? found.label : id
    }

    function add(id) {
      if (props.modelValue.includes(id)) return
      emit("update:modelValue", props.modelValue.concat(id))
      text.value = ""
      pop.show()
    }

    function remove(id) {
      emit("update:modelValue", props.modelValue.filter((item) => item !== id))
    }

    function pickFirst() {
      const first = filtered.value[0]
      if (first) add(first.id)
    }

    function onBackspace() {
      if (text.value || !props.modelValue.length) return
      remove(props.modelValue[props.modelValue.length - 1])
    }

    return { root, text, open: pop.open, show: pop.show, close: pop.close, filtered, labelOf, add, remove, pickFirst, onBackspace }
  },
}
</script>
