<template>
  <div>
    <article v-for="item in visible" :key="item.module + ':' + item.key + ':' + scope" class="setting">
      <h3>{{ item.label }}</h3>
      <p v-if="item.description" class="muted hint">{{ item.description }}</p>
      <p v-if="item.restart_required" class="muted hint">Применяется после перезапуска.</p>
      <p v-if="item.secret && state(item).is_set" class="muted hint">Значение уже задано. Пустое поле его не меняет.</p>

      <label v-if="item.value_type === 'bool'" class="check">
        <input v-model="drafts[draftKey(item)]" type="checkbox" />
        <span>Включено</span>
      </label>
      <label v-else>
        <span class="muted">{{ item.key }}</span>
        <textarea
          v-if="item.ui_hint === 'json' || item.ui_hint === 'textarea'"
          v-model="drafts[draftKey(item)]"
        />
        <select v-else-if="item.ui_hint === 'select'" v-model="drafts[draftKey(item)]">
          <option v-for="option in item.options || []" :key="option" :value="option">{{ option }}</option>
        </select>
        <input
          v-else
          v-model="drafts[draftKey(item)]"
          :type="inputType(item)"
          :min="item.min_value"
          :max="item.max_value"
        />
      </label>
      <p v-if="errors[draftKey(item)]" class="error">{{ errors[draftKey(item)] }}</p>
      <div class="row-actions">
        <button class="btn" type="button" :disabled="busy" @click="save(item)">Сохранить</button>
        <button
          v-if="state(item).is_override"
          class="btn secondary"
          type="button"
          :disabled="busy"
          @click="reset(item)"
        >
          Сбросить
        </button>
      </div>
    </article>
  </div>
</template>

<script>
import { computed, reactive, ref, watch } from "vue"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"

export default {
  props: {
    items: { type: Array, required: true },
    scope: { type: String, required: true },
    projectId: { type: [Number, String], default: null },
  },
  emits: ["changed"],
  setup(props, { emit }) {
    const drafts = reactive({})
    const errors = reactive({})
    const busy = ref(false)
    const notice = useNotice()

    const visible = computed(() =>
      props.items.filter((item) => item.allowed_scopes.includes(props.scope) && item.values[props.scope])
    )

    function draftKey(item) {
      return props.scope + ":" + item.module + ":" + item.key
    }

    function state(item) {
      return item.values[props.scope]
    }

    function fill() {
      for (const item of visible.value) {
        const current = state(item)
        const key = draftKey(item)
        if (item.secret) {
          drafts[key] = ""
        } else if (item.value_type === "json") {
          drafts[key] = JSON.stringify(current.value, null, 2)
        } else if (item.value_type === "bool") {
          drafts[key] = Boolean(current.value)
        } else {
          drafts[key] = current.value == null ? "" : String(current.value)
        }
        errors[key] = ""
      }
    }

    watch(visible, fill, { immediate: true })

    function inputType(item) {
      if (item.secret || item.ui_hint === "secret") return "password"
      if (item.ui_hint === "number" || item.value_type === "int" || item.value_type === "float") return "number"
      return "text"
    }

    function parse(item) {
      const raw = drafts[draftKey(item)]
      if (item.secret && raw === "") {
        return undefined
      }
      if (item.value_type === "bool") return Boolean(raw)
      if (item.value_type === "int") return Number.parseInt(raw, 10)
      if (item.value_type === "float") return Number(raw)
      if (item.value_type === "json") return JSON.parse(raw)
      return raw
    }

    async function save(item) {
      const key = draftKey(item)
      errors[key] = ""
      let value
      try {
        value = parse(item)
      } catch {
        errors[key] = "Не получилось разобрать значение"
        return
      }
      if (value === undefined) return
      if ((item.value_type === "int" || item.value_type === "float") && Number.isNaN(value)) {
        errors[key] = "Ожидается число"
        return
      }
      busy.value = true
      try {
        await api("/api/settings", {
          method: "PUT",
          body: bodyOf(item, value),
        })
        emit("changed")
        notice.show("Настройка «" + item.label + "» сохранена", { kind: "success" })
      } catch (error) {
        errors[key] = error.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function reset(item) {
      const key = draftKey(item)
      errors[key] = ""
      busy.value = true
      try {
        await api("/api/settings/reset", {
          method: "POST",
          body: bodyOf(item),
        })
        emit("changed")
        notice.show("Настройка «" + item.label + "» сброшена к значению по умолчанию", { kind: "success" })
      } catch (error) {
        errors[key] = error.message || "Не сбросилось"
      } finally {
        busy.value = false
      }
    }

    function bodyOf(item, value) {
      const body = { module: item.module, key: item.key, scope: props.scope }
      if (value !== undefined) body.value = value
      if (props.scope === "project" && props.projectId) body.project_id = Number(props.projectId)
      return body
    }

    return { visible, drafts, errors, busy, draftKey, state, inputType, save, reset }
  },
}
</script>
