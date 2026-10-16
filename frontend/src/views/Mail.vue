<template>
  <div>
    <p class="muted">Ящик общий на все проекты. Здесь только письма, которые подходят под фильтры этого проекта.</p>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'letters'">
        <form class="row-actions" @submit.prevent="load">
          <input v-model="query" type="text" placeholder="Тема или отправитель" />
          <button class="btn secondary" type="submit">Показать</button>
        </form>
        <label class="check"><input v-model="unreadOnly" type="checkbox" @change="load" /><span>Только непрочитанные</span></label>
        <label class="check"><input v-model="includeArchived" type="checkbox" @change="load" /><span>Показать архив</span></label>
        <p v-if="error" class="error">{{ error }}</p>
        <p v-else-if="loading" class="muted">Загрузка…</p>
        <p v-else-if="!rules.length" class="muted">Фильтров нет, поэтому писем здесь не видно. Добавьте фильтр на вкладке «Фильтры» — в список попадут только подходящие.</p>
        <p v-else-if="!messages.length" class="muted">Под текущие фильтры ничего не попало</p>
        <div v-else class="card">
          <div v-for="item in messages" :key="item.id" class="status-row">
            <div>
              <router-link :class="{ unread: !item.read }" :to="'/projects/' + project.id + '/mail/' + item.id">{{ item.title }}</router-link>
              <span v-if="item.thread_count > 1" class="muted"> · {{ item.thread_count }} в переписке</span>
              <div class="muted">{{ fromLine(item) }} · {{ when(item.received_at) }}<span v-if="item.attachment_count"> · вложения {{ item.attachment_count }}</span></div>
              <div v-if="item.preview" class="snippet">{{ item.preview }}</div>
            </div>
          </div>
        </div>
      </div>
      <div v-show="tab === 'rules'">
        <p class="muted">Письмо сохраняется всегда, само, порциями. Фильтр решает только одно: это письмо этого проекта, и его надо перенести в папку «{{ project.name }}».</p>
        <form class="card stack" @submit.prevent="createRule">
          <h2>Фильтр</h2>
          <label>Название <input v-model="rule.name" type="text" required /></label>
          <label>
            Поле
            <select v-model="rule.field">
              <option v-for="item in fields" :key="item.id" :value="item.id">{{ item.label }}</option>
            </select>
          </label>
          <label>
            Условие
            <select v-model="rule.op">
              <option v-for="item in ops" :key="item.id" :value="item.id">{{ item.label }}</option>
            </select>
          </label>
          <label>Значение <input v-model="rule.value" type="text" required /></label>
          <p v-if="ruleError" class="error">{{ ruleError }}</p>
          <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Добавить фильтр</button></div>
        </form>
        <div v-if="rules.length" class="card">
          <div v-for="item in rules" :key="item.id" class="status-row">
            <div>
              <strong>{{ item.name }}</strong>
              <div class="muted">{{ item.field_label }} {{ item.op_label }} «{{ item.value }}»</div>
            </div>
            <button class="btn secondary" type="button" :disabled="busy" @click="removeRule(item)">Удалить</button>
          </div>
        </div>
        <form class="card stack" @submit.prevent="importFile">
          <h2>Файл письма</h2>
          <label>Файл .eml <input type="file" @change="onFile" /></label>
          <p v-if="importError" class="error">{{ importError }}</p>
          <p v-if="importNote" class="ok-text">{{ importNote }}</p>
          <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Загрузить</button></div>
        </form>
      </div>
  </div>
</template>

<script>
import { ref, watch } from "vue"
import { api } from "../api"
import Tabs from "../components/Tabs.vue"
import { useSettings } from "../composables/useSettings"
import { formatWhen } from "../composables/formatDate"

export default {
  components: { Tabs },
  props: { project: { type: Object, required: true } },
  setup(props) {
    const accounts = ref([])
    const rules = ref([])
    const messages = ref([])
    const fields = ref([])
    const ops = ref([])
    const actions = ref([])
    const error = ref("")
    const accountError = ref("")
    const ruleError = ref("")
    const importError = ref("")
    const importNote = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const query = ref("")
    const unreadOnly = ref(false)
    const includeArchived = ref(false)
    const tab = ref("letters")
    const pageTabs = [
      { id: "letters", label: "Письма" },
      { id: "rules", label: "Фильтры" },
    ]
    const file = ref(null)
    const account = ref({ name: "", host: "", port: 993, use_ssl: true, username: "", password: "", folder: "INBOX" })
    const rule = ref({ name: "", field: "from", op: "contains", value: "", action: "keep" })
    const settings = useSettings()

    function when(value) {
      return formatWhen(value, settings.get("core", "ui.date_format"), settings.get("core", "ui.timezone") || undefined)
    }

    function fromLine(item) {
      if (item.from_name && item.from_addr) return item.from_name + " <" + item.from_addr + ">"
      return item.from_addr || item.from_name || ""
    }

    function applyChoices(data) {
      fields.value = data.fields || []
      ops.value = data.ops || []
      actions.value = data.actions || []
      if (!fields.value.some((item) => item.id === rule.value.field) && fields.value.length) rule.value.field = fields.value[0].id
      if (!ops.value.some((item) => item.id === rule.value.op) && ops.value.length) rule.value.op = ops.value[0].id
      if (!actions.value.some((item) => item.id === rule.value.action) && actions.value.length) rule.value.action = actions.value[0].id
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const params = new URLSearchParams()
        if (unreadOnly.value) params.set("unread", "true")
        if (includeArchived.value) params.set("include_archived", "true")
        if (query.value) params.set("q", query.value)
        const data = await api("/api/projects/" + props.project.id + "/mail?" + params.toString())
        accounts.value = data.accounts || []
        rules.value = data.rules || []
        messages.value = data.messages || []
        applyChoices(data)
      } catch (err) {
        error.value = err.message || "Почта недоступна"
      } finally {
        loading.value = false
      }
    }

    async function createAccount() {
      accountError.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/accounts", { method: "POST", body: { ...account.value } })
        account.value.password = ""
        account.value.name = ""
        await load()
      } catch (err) {
        accountError.value = err.message || "Не удалось добавить"
      } finally {
        busy.value = false
      }
    }

    async function check(item) {
      error.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/accounts/" + item.id + "/check", { method: "POST" })
        await load()
      } catch (err) {
        error.value = err.message || "Проверка не удалась"
      } finally {
        busy.value = false
      }
    }

    async function fetchMail(item) {
      error.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/accounts/" + item.id + "/fetch", { method: "POST" })
        await load()
      } catch (err) {
        error.value = err.message || "Не удалось забрать"
      } finally {
        busy.value = false
      }
    }

    async function removeAccount(item) {
      if (!window.confirm("Удалить ящик? Письма останутся.")) return
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/accounts/" + item.id, { method: "DELETE" })
        await load()
      } catch (err) {
        error.value = err.message || "Не удалось удалить"
      } finally {
        busy.value = false
      }
    }

    async function createRule() {
      ruleError.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/rules", { method: "POST", body: { ...rule.value } })
        rule.value.name = ""
        rule.value.value = ""
        await load()
      } catch (err) {
        ruleError.value = err.message || "Не удалось добавить"
      } finally {
        busy.value = false
      }
    }

    async function removeRule(item) {
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/rules/" + item.id, { method: "DELETE" })
        await load()
      } catch (err) {
        error.value = err.message || "Не удалось удалить"
      } finally {
        busy.value = false
      }
    }

    function onFile(event) {
      file.value = event.target.files && event.target.files[0]
    }

    async function importFile() {
      importError.value = ""
      importNote.value = ""
      if (!file.value) {
        importError.value = "Выберите файл"
        return
      }
      busy.value = true
      const body = new FormData()
      body.append("file", file.value)
      try {
        const data = await api("/api/projects/" + props.project.id + "/mail/import", { method: "POST", body })
        if (data.status === "duplicate") importNote.value = "Такое письмо уже есть"
        else importNote.value = "Письмо сохранено"
        await load()
      } catch (err) {
        importError.value = err.message || "Не загрузилось"
      } finally {
        busy.value = false
      }
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).catch(() => {}).finally(load)
    }, { immediate: true })

    return {
      accounts, rules, messages, fields, ops, actions, error, accountError, ruleError, importError, importNote,
      loading, busy, query, unreadOnly, includeArchived, account, rule, tab, pageTabs,
      when, fromLine, load, createAccount, check, fetchMail, removeAccount, createRule, removeRule, onFile, importFile,
    }
  },
}
</script>
