<template>
  <div>
    <p class="muted">Здесь решается, какое новое письмо вообще поднимает уведомление. Куда его слать — колокольчик, Telegram или почта — на странице «Уведомления». Старая докачка молчит в любом режиме.</p>
    <form class="card stack" @submit.prevent="saveNotify">
      <label>
        О чём писать
        <select v-model="notify.mode">
          <option v-for="item in modes" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
      </label>
      <label v-if="notify.mode === 'filter'">
        Как совмещать условия
        <select v-model="notify.match">
          <option v-for="item in matches" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
      </label>
      <label class="check">
        <input v-model="notify.gate_filed" type="checkbox" :disabled="notify.mode !== 'filter'" />
        <span>Тот же фильтр и для «письмо ушло в проект»</span>
      </label>
      <p v-if="notifyError" class="error">{{ notifyError }}</p>
      <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Сохранить</button></div>
    </form>
    <form v-if="notify.mode === 'filter'" class="card stack" @submit.prevent="addNotifyRule">
      <h2>Условие</h2>
      <div class="row-actions">
        <select v-model="notifyForm.field" @change="syncNotifyOp">
          <option v-for="item in fields" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <select v-model="notifyForm.op">
          <option v-for="item in opsFor(notifyForm.field)" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <select v-if="notifyForm.field === 'tag'" v-model="notifyForm.value">
          <option value="">Хештег</option>
          <option v-for="tag in tags" :key="tag.id" :value="String(tag.id)">{{ tag.name }}</option>
        </select>
        <input v-else v-model="notifyForm.value" type="text" placeholder="Например ivanov или aeroflot" />
      </div>
      <p v-if="notifyForm.field === 'tag' && !tags.length" class="muted">Сначала создайте хештег на соседней вкладке.</p>
      <p v-if="notify.mode === 'filter' && !rules.length" class="muted">Пока условий нет, о новых письмах тихо.</p>
      <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Добавить условие</button></div>
    </form>
    <template v-if="notify.mode === 'filter'">
      <article v-for="rule in rules" :key="rule.id" class="card">
        <div class="status-row">
          <span>{{ rule.text }}</span>
          <button class="text-btn" type="button" :disabled="busy" @click="removeNotifyRule(rule)">Удалить</button>
        </div>
      </article>
    </template>
  </div>
</template>

<script>
import { reactive, ref, watch } from "vue"
import { api } from "../../api"

// Вкладка «Уведомления» почты (патч X): фильтр «какое письмо поднимает
// уведомление». Вынесена из Mailbox.vue; состояние применяет блок notify
// из общего ответа /api/mail (пропс meta), мутации перечитывают его же.
export default {
  props: {
    tags: { type: Array, default: () => [] },
    meta: { type: Object, default: null },
  },
  emits: [],
  setup(props, { emit }) {
    const busy = ref(false)
    const notifyError = ref("")
    const notify = reactive({ mode: "all", match: "any", gate_filed: true })
    const modes = ref([])
    const matches = ref([])
    const fields = ref([])
    const ops = ref([])
    const rules = ref([])
    const notifyForm = reactive({ field: "from", op: "contains", value: "" })

    watch(
      () => props.meta,
      (data) => applyMeta(data),
      { immediate: true, deep: true }
    )

    function applyMeta(data) {
      if (!data || typeof data !== "object") return
      notify.mode = data.mode || "all"
      notify.match = data.match || "any"
      notify.gate_filed = data.gate_filed !== false
      modes.value = data.modes || modes.value
      matches.value = data.matches || matches.value
      fields.value = data.fields || fields.value
      ops.value = data.ops || ops.value
      rules.value = data.rules || []
      if (!notifyForm.field && fields.value.length) notifyForm.field = fields.value[0].id
    }

    function opsFor(field) {
      const items = ops.value || []
      if (field === "tag") return items.filter((item) => item.id === "equals")
      return items
    }

    function syncNotifyOp() {
      const items = opsFor(notifyForm.field)
      if (!items.some((item) => item.id === notifyForm.op)) notifyForm.op = items[0] ? items[0].id : ""
      notifyForm.value = ""
    }

    function applyResult(data) {
      applyMeta(data)
    }

    async function saveNotify() {
      notifyError.value = ""
      busy.value = true
      try {
        applyResult(await api("/api/mail/notify", {
          method: "PUT",
          body: { mode: notify.mode, match: notify.match, gate_filed: !!notify.gate_filed },
        }))
      } catch (err) {
        notifyError.value = err.message || "Фильтр не сохранился"
      } finally {
        busy.value = false
      }
    }

    async function addNotifyRule() {
      notifyError.value = ""
      if (!(notifyForm.value || "").trim()) {
        notifyError.value = notifyForm.field === "tag" ? "Выберите хештег" : "Укажите значение"
        return
      }
      busy.value = true
      try {
        applyResult(await api("/api/mail/notify", {
          method: "PUT",
          body: { mode: notify.mode, match: notify.match, gate_filed: !!notify.gate_filed },
        }))
        applyResult(await api("/api/mail/notify/rules", {
          method: "POST",
          body: { field: notifyForm.field, op: notifyForm.op, value: notifyForm.value },
        }))
        notifyForm.value = ""
      } catch (err) {
        notifyError.value = err.message || "Условие не добавилось"
      } finally {
        busy.value = false
      }
    }

    async function removeNotifyRule(rule) {
      notifyError.value = ""
      busy.value = true
      try {
        applyResult(await api("/api/mail/notify/rules/" + rule.id, { method: "DELETE" }))
      } catch (err) {
        notifyError.value = err.message || "Условие не удалилось"
      } finally {
        busy.value = false
      }
    }

    return {
      busy, notifyError, notify, modes, matches, fields, rules, notifyForm,
      opsFor, syncNotifyOp, saveNotify, addNotifyRule, removeNotifyRule,
    }
  },
}
</script>
