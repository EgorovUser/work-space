<template>
  <aside class="card designer-panel">
    <div class="designer-head">
      <h2>Редактор страницы</h2>
      <button class="btn secondary" type="button" @click="$emit('close')">Готово</button>
    </div>

    <p v-if="saveError" class="banner designer-error">
      {{ saveError }}
      <button class="text-btn" type="button" @click="$emit('retry-save')">Повторить</button>
    </p>
    <p v-else-if="busy" class="muted designer-saving">Сохраняем…</p>

    <div class="designer-list">
      <button
        v-for="(item, index) in items"
        :key="item.element"
        class="designer-row"
        :class="{ active: item.element === selected }"
        type="button"
        @click="$emit('select', item.element)"
      >
        <span class="designer-row-title">
          {{ titleOf(item) }}
          <span v-if="item.hidden" class="muted">· скрыт</span>
        </span>
        <span class="designer-row-tools" @click.stop>
          <button
            class="text-btn"
            type="button"
            title="Выше"
            :disabled="index === 0"
            @click="$emit('move', item.element, -1)"
          >↑</button>
          <button
            class="text-btn"
            type="button"
            title="Ниже"
            :disabled="index === items.length - 1"
            @click="$emit('move', item.element, 1)"
          >↓</button>
        </span>
      </button>
    </div>

    <div v-if="selectedDef && selectedItem" class="designer-props">
      <div class="designer-props-head">
        <strong>{{ selectedDef.title }}</strong>
        <button class="text-btn designer-remove" type="button" @click="confirmRemove">Убрать</button>
      </div>
      <div v-for="group in groupedProps" :key="group.name" class="designer-group">
        <div class="designer-group-name">{{ group.name }}</div>
        <label v-for="prop in group.props" :key="prop.key" class="designer-field">
          <span class="designer-field-label">{{ prop.label }}</span>
          <select
            v-if="prop.type === 'enum'"
            :value="selectedItem[prop.key]"
            @change="emitProp(prop, $event.target.value)"
          >
            <option v-for="option in prop.options" :key="String(option)" :value="option">
              {{ optionLabel(prop, option) }}
            </option>
          </select>
          <input
            v-else-if="prop.type === 'bool'"
            type="checkbox"
            :checked="!!selectedItem[prop.key]"
            @change="emitProp(prop, $event.target.checked)"
          />
          <input
            v-else
            type="text"
            :value="selectedItem[prop.key] || ''"
            :maxlength="prop.max_length || 80"
            :placeholder="placeholderFor(prop)"
            @input="emitProp(prop, $event.target.value)"
          />
        </label>
      </div>
    </div>
    <p v-else class="muted designer-hint">Выберите элемент — на странице или в списке выше.</p>

    <div class="designer-actions">
      <button v-if="missing.length" class="btn secondary" type="button" @click="pickerOpen = !pickerOpen">
        {{ pickerOpen ? "Скрыть список" : "+ Добавить элемент" }}
      </button>
      <ElementPicker v-if="pickerOpen && missing.length" :options="missing" @add="onAdd" />
      <button class="btn secondary" type="button" :disabled="isDefault" @click="confirmReset">
        Сбросить к стандартной
      </button>
    </div>

    <details class="designer-history" @toggle="onToggleHistory">
      <summary>История изменений</summary>
      <p v-if="!revisions.length" class="muted">
        Пока пусто — снимки прежней раскладки появляются после первого изменения.
      </p>
      <div v-for="rev in revisions" :key="rev.id" class="designer-rev">
        <span class="designer-rev-info">{{ formatRev(rev) }}</span>
        <button class="text-btn" type="button" @click="$emit('restore', rev.id)">Вернуть</button>
      </div>
    </details>
  </aside>
</template>

<script>
import { computed, ref } from "vue"
import ElementPicker from "./ElementPicker.vue"
import { catalogMap, findItem, missingElements } from "../../ui/items.js"

// Инспектор свойств страницы (патч AW) — один на все элементы: рендерится
// по схеме из каталога бэкенда (как инспектор SurveyJS — «форма из схемы»),
// рукописных редакторов под каждую карточку нет. Плюс порядок, удаление,
// добавление, сброс и история с откатом.
const OPTION_LABELS = {
  span: { 1: "четверть ширины", 2: "половина", 3: "три четверти", 4: "вся ширина" },
  density: { normal: "обычная", compact: "плотная" },
}

export default {
  name: "PropertyPanel",
  components: { ElementPicker },
  props: {
    items: { type: Array, required: true },
    catalog: { type: Object, required: true },
    selected: { type: String, default: null },
    busy: { type: Boolean, default: false },
    saveError: { type: String, default: "" },
    isDefault: { type: Boolean, default: true },
    revisions: { type: Array, required: true },
  },
  emits: ["close", "select", "update-prop", "move", "remove", "add", "reset", "restore", "retry-save", "refresh-revisions"],
  setup(props, { emit }) {
    const pickerOpen = ref(false)
    const byName = computed(() => catalogMap(props.catalog))
    const selectedDef = computed(() => (props.selected ? byName.value.get(props.selected) || null : null))
    const selectedItem = computed(() => (props.selected ? findItem(props.items, props.selected) : null))
    const missing = computed(() => missingElements(props.items, props.catalog))

    // Свойства по группам («Раскладка», «Вид») — как секции инспектора.
    const groupedProps = computed(() => {
      const groups = []
      for (const prop of (selectedDef.value && selectedDef.value.props) || []) {
        let group = groups.find((item) => item.name === prop.group)
        if (!group) {
          group = { name: prop.group, props: [] }
          groups.push(group)
        }
        group.props.push(prop)
      }
      return groups
    })

    function titleOf(item) {
      const def = byName.value.get(item.element)
      return (def && def.title) || item.element
    }

    function optionLabel(prop, option) {
      const labels = OPTION_LABELS[prop.ui_hint]
      return (labels && labels[option]) || String(option)
    }

    function placeholderFor(prop) {
      return prop.key === "title" ? "как обычно" : ""
    }

    function emitProp(prop, rawValue) {
      // select всегда отдаёт строки: числовые перечисления (ширина)
      // конвертируем обратно в числа, чтобы конфиг не расползался.
      let value = rawValue
      if (prop.type === "enum" && prop.options.some((option) => typeof option === "number")) {
        value = Number(rawValue)
      }
      if (props.selected) emit("update-prop", props.selected, prop.key, value)
    }

    function onAdd(element) {
      pickerOpen.value = false
      emit("add", element)
    }

    function confirmRemove() {
      const title = selectedDef.value ? selectedDef.value.title : props.selected
      if (window.confirm("Убрать «" + title + "» со страницы? Вернуть можно кнопкой «Добавить элемент».")) {
        emit("remove", props.selected)
      }
    }

    function confirmReset() {
      if (window.confirm("Вернуть стандартную раскладку? Текущая сохранится в истории изменений.")) {
        emit("reset")
      }
    }

    function onToggleHistory(event) {
      if (event.target.open) emit("refresh-revisions")
    }

    function formatRev(rev) {
      const when = new Date(rev.created_at)
      const stamp = isNaN(when.getTime())
        ? ""
        : when.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      const count = rev.items_count || (rev.elements || []).length
      return stamp + " · " + count + " " + plural(count, ["элемент", "элемента", "элементов"])
    }

    function plural(count, forms) {
      const mod10 = count % 10
      const mod100 = count % 100
      if (mod10 === 1 && mod100 !== 11) return forms[0]
      if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1]
      return forms[2]
    }

    return {
      pickerOpen,
      selectedDef,
      selectedItem,
      missing,
      groupedProps,
      titleOf,
      optionLabel,
      placeholderFor,
      emitProp,
      onAdd,
      confirmRemove,
      confirmReset,
      onToggleHistory,
      formatRev,
    }
  },
}
</script>
