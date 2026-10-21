<template>
  <div class="ui-grid" :class="{ 'ui-editing': editing }">
    <div
      v-for="item in renderItems"
      :key="item.element"
      :data-element="item.element"
      class="ui-item"
      :class="itemClasses(item)"
      @click="onItemClick(item)"
    >
      <template v-if="editing">
        <span class="ui-item-badge">{{ badgeTitle(item) }}</span>
        <span v-if="item.hidden" class="ui-item-flag">скрыт</span>
      </template>
      <component :is="componentOf(item)" v-if="componentOf(item)" :item="item" :context="context" />
      <!-- Неизвестный элемент — заглушка в стиле Home Assistant
           «card not found»: конфиг сохранён, страница живая. -->
      <section v-else class="card ui-stub">
        <h2>{{ badgeTitle(item) }}</h2>
        <p class="muted">
          Элемент «{{ item.element }}» не найден — обновите приложение
          или уберите его в редакторе.
        </p>
      </section>
      <!-- Плёнка режима правки: ссылки и кнопки внутри карточек не
           срабатывают, клик выделяет элемент. -->
      <div v-if="editing" class="ui-item-cover"></div>
    </div>
  </div>
</template>

<script>
import { computed } from "vue"
import { getElement } from "../../ui/elements.js"
import { catalogMap, spanClass } from "../../ui/items.js"

// Рендерер редактируемой страницы (патч AW): сетка из элементов реестра,
// ширина — span-классами из конфига. В режиме правки добавляет селекцию
// и плёнку поверх содержимого; вне его — рисует только видимые элементы.
export default {
  name: "PageRenderer",
  props: {
    items: { type: Array, required: true },
    catalog: { type: Object, required: true },
    context: { type: Object, required: true },
    editing: { type: Boolean, default: false },
    selected: { type: String, default: null },
  },
  emits: ["select"],
  setup(props, { emit }) {
    const renderItems = computed(() =>
      props.editing ? props.items : props.items.filter((item) => !item.hidden)
    )
    const byName = computed(() => catalogMap(props.catalog))

    function componentOf(item) {
      const element = getElement(item.element)
      return element ? element.component : null
    }

    function badgeTitle(item) {
      const def = byName.value.get(item.element)
      return (def && def.title) || item.element
    }

    function itemClasses(item) {
      return [
        spanClass(item.span),
        {
          "ui-selected": props.editing && props.selected === item.element,
          "ui-hidden-item": props.editing && item.hidden,
        },
      ]
    }

    function onItemClick(item) {
      if (props.editing) emit("select", item.element)
    }

    return { renderItems, componentOf, badgeTitle, itemClasses, onItemClick }
  },
}
</script>
