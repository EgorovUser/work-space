<template>
  <div>
    <p class="muted">Хештег ставится сам, если подошли все условия сразу. Снять его с конкретного письма можно внутри письма. Дата — день получения в вашем часовом поясе.</p>
    <form class="card stack" @submit.prevent="createTag">
      <h2>Хештег</h2>
      <label>Название <input v-model="tagForm.name" type="text" required /></label>
      <label class="tight">Цвет <input v-model="tagForm.color" type="color" /></label>
      <div v-for="(row, index) in conditions" :key="index" class="row-actions">
        <select v-model="row.field" @change="syncOp(row)">
          <option v-for="item in fields" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <select v-model="row.op">
          <option v-for="item in opsFor(row.field)" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <input v-if="row.field === 'received'" v-model="row.value" type="date" />
        <input v-else v-model="row.value" type="text" placeholder="Значение" />
        <button class="text-btn" type="button" @click="conditions.splice(index, 1)">Убрать</button>
      </div>
      <div class="row-actions">
        <button class="btn secondary" type="button" @click="conditions.push(blankCondition())">Ещё условие</button>
      </div>
      <p v-if="!conditions.length" class="muted">Без условия хештег некуда поставить.</p>
      <p v-if="tagError" class="error">{{ tagError }}</p>
      <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Добавить хештег</button></div>
    </form>
    <article v-for="tag in tags" :key="tag.id" class="card stack">
      <div class="tag-row">
        <span class="mail-tag on" :style="tagStyle(tag, true)">{{ tag.name }}</span>
        <button class="text-btn" type="button" :disabled="busy" @click="removeTag(tag)">Удалить</button>
      </div>
      <p v-if="!tag.rules.length" class="muted">Только вручную</p>
      <p v-for="(rule, index) in tag.rules" :key="index" class="muted">{{ ruleText(rule) }}</p>
    </article>
  </div>
</template>

<script>
import { reactive, ref, watch } from "vue"
import { api } from "../../api"
import { tagStyle } from "../../composables/mailTagStyle"
import { useNotice } from "../../composables/useNotice"

// Вкладка «Хештеги» почты (патч X): вынесена из Mailbox.vue вместе со всей
// своей логикой. Разметка и классы не менялись — на них держатся стили и e2e.
// Каталоги полей/операций приходят пропсами из общего ответа /api/mail,
// мутации просят родителя перезагрузить список (emit changed), создание
// переключает на письма (emit done).
export default {
  props: {
    tags: { type: Array, default: () => [] },
    fields: { type: Array, default: () => [] },
    ops: { type: Array, default: () => [] },
    defaultColor: { type: String, default: "" },
  },
  emits: ["changed", "done"],
  setup(props, { emit }) {
    const notice = useNotice()
    const busy = ref(false)
    const tagError = ref("")
    const conditions = ref([])
    const tagForm = reactive({ name: "", color: "#3a6ea5" })

    watch(
      () => props.defaultColor,
      (value) => {
        if (value && tagForm.color === "#3a6ea5") tagForm.color = value
      },
      { immediate: true }
    )
    watch(
      () => props.fields,
      (value) => {
        if (!conditions.value.length && value.length) conditions.value = [blankCondition()]
      },
      { immediate: true }
    )

    function opsFor(field) {
      const dateOps = new Set(["before", "after", "on"])
      const items = props.ops || []
      if (field === "received") return items.filter((item) => dateOps.has(item.id))
      return items.filter((item) => !dateOps.has(item.id))
    }

    function blankCondition() {
      const field = (props.fields[0] && props.fields[0].id) || "from"
      const ops = opsFor(field)
      return { field, op: (ops[0] && ops[0].id) || "contains", value: "" }
    }

    function syncOp(row) {
      const ops = opsFor(row.field)
      if (!ops.some((item) => item.id === row.op)) row.op = ops[0] ? ops[0].id : ""
    }

    function ruleText(rule) {
      const field = props.fields.find((item) => item.id === rule.field)
      const op = props.ops.find((item) => item.id === rule.op)
      return (field ? field.label : rule.field) + " " + (op ? op.label : rule.op) + " «" + rule.value + "»"
    }

    async function createTag() {
      tagError.value = ""
      for (const row of conditions.value) {
        if (!(row.value || "").trim()) {
          tagError.value = "Укажите значение условия или уберите пустую строку"
          return
        }
      }
      if (!conditions.value.length) {
        tagError.value = "Нужно хотя бы одно условие"
        return
      }
      busy.value = true
      try {
        await api("/api/mail/tags", {
          method: "POST",
          body: {
            name: tagForm.name,
            color: tagForm.color,
            rules: conditions.value.map((row) => ({ field: row.field, op: row.op, value: row.value })),
          },
        })
        const name = tagForm.name
        tagForm.name = ""
        conditions.value = [blankCondition()]
        notice.show("Хештег «" + name + "» создан", { kind: "success" })
        emit("changed")
        emit("done")
      } catch (err) {
        tagError.value = err.message || "Хештег не сохранился"
      } finally {
        busy.value = false
      }
    }

    async function removeTag(tag) {
      if (!window.confirm("Удалить хештег «" + tag.name + "» и его условия? Письма останутся.")) return
      busy.value = true
      tagError.value = ""
      try {
        await api("/api/mail/tags/" + tag.id, { method: "DELETE" })
        notice.show("Хештег «" + tag.name + "» удалён", { kind: "success" })
        emit("changed")
      } catch (err) {
        tagError.value = err.message || "Хештег не удалён"
      } finally {
        busy.value = false
      }
    }

    return { busy, tagError, conditions, tagForm, tagStyle, opsFor, blankCondition, syncOp, ruleText, createTag, removeTag }
  },
}
</script>
