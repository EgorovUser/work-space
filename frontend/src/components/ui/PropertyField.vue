<template>
  <label class="designer-field">
    <span class="designer-field-label">{{ prop.label }}</span>
    <select v-if="prop.type === 'enum'" :value="value" @change="onChange($event.target.value)">
      <option v-for="option in prop.options" :key="String(option)" :value="option">
        {{ optionLabel(prop, option) }}
      </option>
    </select>
    <input
      v-else-if="prop.type === 'bool'"
      type="checkbox"
      :checked="!!value"
      @change="$emit('change', prop, $event.target.checked)"
    />
    <input
      v-else
      type="text"
      :value="value || ''"
      :maxlength="prop.max_length || 80"
      :placeholder="placeholderFor(prop)"
      @input="$emit('change', prop, $event.target.value)"
    />
  </label>
</template>

<script>
// Одно поле инспектора (патч AW): рендер по схеме каталога, без рукописных
// форм. Используется и для свойств элемента, и для настроек страницы —
// интерфейс не знает, чья это схема.
const OPTION_LABELS = {
  span: { 1: "четверть ширины", 2: "половина", 3: "три четверти", 4: "вся ширина" },
  density: { normal: "обычная", compact: "плотная" },
  height: {
    auto: "как обычно",
    low: "низкий (половина максимума)",
    medium: "средний (три четверти)",
    tall: "высокий (максимум)",
  },
  columns: { 1: "одна колонка", 2: "две колонки", 3: "три колонки" },
  items_align: { stretch: "растянуть на всю ширину", center: "по центру", start: "по левому краю" },
  gap: { normal: "обычный", compact: "плотный", spacious: "свободный" },
  height_max: { 360: "360 px", 420: "420 px", 480: "480 px", 560: "560 px", 640: "640 px", 720: "720 px" },
}

export default {
  name: "PropertyField",
  props: {
    prop: { type: Object, required: true },
    value: { type: null, default: null },
  },
  emits: ["change"],
  methods: {
    // select всегда отдаёт строки: числовые перечисления (ширина, колонки,
    // максимум высоты) конвертируем обратно в числа, чтобы конфиг
    // не расползался типами.
    onChange(raw) {
      let value = raw
      if (this.prop.type === "enum" && (this.prop.options || []).some((option) => typeof option === "number")) {
        value = Number(raw)
      }
      this.$emit("change", this.prop, value)
    },
    optionLabel(prop, option) {
      const labels = OPTION_LABELS[prop.ui_hint]
      return (labels && labels[option]) || String(option)
    },
    placeholderFor(prop) {
      return prop.key === "title" ? "как обычно" : ""
    },
  },
}
</script>
