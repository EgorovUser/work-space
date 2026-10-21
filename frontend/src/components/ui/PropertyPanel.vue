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

    <!-- Две вкладки: раскладка элементов и настройки самой страницы
         (максимум высоты блоков). Инспектор один — как в дизайнерах
         WinForms/Delphi, страница тоже «объект» со свойствами. -->
    <div class="designer-tabs" role="tablist">
      <button type="button" class="designer-tab" :class="{ active: view === 'elements' }" @click="view = 'elements'">Элементы</button>
      <button type="button" class="designer-tab" :class="{ active: view === 'page' }" @click="view = 'page'">Страница</button>
    </div>

    <template v-if="view === 'elements'">
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
          <PropertyField
            v-for="prop in group.props"
            :key="prop.key"
            :prop="prop"
            :value="selectedItem[prop.key]"
            @change="onPropChange"
          />
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
    </template>

    <div v-else class="designer-props designer-page">
      <div class="designer-props-head"><strong>Страница</strong></div>
      <div v-for="group in pageGroups" :key="group.name" class="designer-group">
        <div class="designer-group-name">{{ group.name }}</div>
        <PropertyField
          v-for="prop in group.props"
          :key="prop.key"
          :prop="prop"
          :value="pageValue(prop)"
          @change="onPageChange"
        />
      </div>
      <p class="muted designer-note">
        «Высокий» блок равен выбранному максимуму, «низкий» — половине, «средний» — трём
        четвертям. Если содержимое не влезает, карточка не растёт: оно прокручивается
        внутри блока. Сброс возвращает и эти настройки.
      </p>
    </div>
  </aside>
</template>

<script>
import { computed, ref } from "vue"
import ElementPicker from "./ElementPicker.vue"
import PropertyField from "./PropertyField.vue"
import { catalogMap, findItem, missingElements } from "../../ui/items.js"

// Инспектор свойств страницы (патч AW) — один на все элементы: рендерится
// по схеме из каталога бэкенда (как инспектор SurveyJS — «форма из схемы»),
// рукописных редакторов под каждую карточку нет. Плюс порядок, удаление,
// добавление, сброс и история с откатом; вкладка «Страница» — настройки
// самой страницы (максимум высоты блоков).
export default {
  name: "PropertyPanel",
  components: { ElementPicker, PropertyField },
  props: {
    items: { type: Array, required: true },
    catalog: { type: Object, required: true },
    settings: { type: Object, default: null },
    selected: { type: String, default: null },
    busy: { type: Boolean, default: false },
    saveError: { type: String, default: "" },
    isDefault: { type: Boolean, default: true },
    revisions: { type: Array, required: true },
  },
  emits: ["close", "select", "update-prop", "update-setting", "move", "remove", "add", "reset", "restore", "retry-save", "refresh-revisions"],
  setup(props, { emit }) {
    const pickerOpen = ref(false)
    const view = ref("elements")
    const byName = computed(() => catalogMap(props.catalog))
    const selectedDef = computed(() => (props.selected ? byName.value.get(props.selected) || null : null))
    const selectedItem = computed(() => (props.selected ? findItem(props.items, props.selected) : null))
    const missing = computed(() => missingElements(props.items, props.catalog))

    // Свойства по группам («Раскладка», «Вид», «Внутренние элементы») —
    // как секции инспектора.
    function groupBy(propsList) {
      const groups = []
      for (const prop of propsList || []) {
        let group = groups.find((item) => item.name === prop.group)
        if (!group) {
          group = { name: prop.group, props: [] }
          groups.push(group)
        }
        group.props.push(prop)
      }
      return groups
    }

    const groupedProps = computed(() => groupBy(selectedDef.value && selectedDef.value.props))
    const pageGroups = computed(() => groupBy(props.catalog && props.catalog.settings))

    // Значение настройки страницы: фолбэк — дефолт схемы (например,
    // конфиг ещё не грузился), чтобы поля не показывали пустоту.
    function pageValue(prop) {
      const current = props.settings || {}
      const value = current[prop.key]
      return value === undefined || value === null ? prop.default : value
    }

    function titleOf(item) {
      const def = byName.value.get(item.element)
      return (def && def.title) || item.element
    }

    function onPropChange(prop, value) {
      if (props.selected) emit("update-prop", props.selected, prop.key, value)
    }

    function onPageChange(prop, value) {
      emit("update-setting", prop.key, value)
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
      view,
      selectedDef,
      selectedItem,
      missing,
      groupedProps,
      pageGroups,
      titleOf,
      pageValue,
      onPropChange,
      onPageChange,
      onAdd,
      confirmRemove,
      confirmReset,
      onToggleHistory,
      formatRev,
    }
  },
}
</script>
