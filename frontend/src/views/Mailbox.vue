<template>
  <AppShell>
    <div class="page-head">
      <h1>Почта</h1>
      <p class="muted">
        <template v-if="sync && sync.automatic">Новые письма забираются сами, каждые {{ sync.every_seconds }} с.</template>
        <template v-else>Автозабор выключен. Порцию можно забрать у ящика.</template>
      </p>
    </div>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'letters'">
      <form class="row-actions" @submit.prevent="load">
        <input v-model="query" type="text" placeholder="Тема или отправитель" />
        <button class="btn secondary" type="submit">Показать</button>
      </form>
      <div v-if="tags.length" class="tag-row">
        <button type="button" class="mail-tag" :class="{ on: !activeTag }" @click="setTag(0)">Все</button>
        <button
          v-for="tag in tags"
          :key="tag.id"
          type="button"
          class="mail-tag"
          :class="{ on: activeTag === tag.id }"
          :style="tagStyle(tag, activeTag === tag.id)"
          @click="setTag(tag.id)"
        >{{ tag.name }}</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!messages.length" class="muted">{{ activeTag ? "Под этот хештег ничего не попало" : "Писем нет" }}</p>
      <div v-else class="list">
        <article v-for="item in messages" :key="item.id" class="list-row">
          <router-link :class="{ unread: !item.read }" :to="'/mail/' + item.id">{{ item.title }}</router-link>
          <span v-if="item.thread_count > 1" class="muted"> · {{ item.thread_count }} в переписке</span>
          <div class="muted">{{ fromLine(item) }} · {{ when(item.received_at) }}<span v-if="item.thread_unread"> · непрочитанных {{ item.thread_unread }}</span><span v-if="item.attachment_count"> · вложения {{ item.attachment_count }}</span></div>
          <div v-if="item.tags && item.tags.length" class="tag-row">
            <span v-for="tag in item.tags" :key="tag.id" class="mail-tag on" :style="tagStyle(tag, true)">{{ tag.name }}</span>
          </div>
        </article>
      </div>
    </div>
    <div v-show="tab === 'tags'">
      <p class="muted">Хештег ставится сам, если подошли все условия сразу. Снять его с конкретного письма можно внутри письма. Дата — день получения в вашем часовом поясе.</p>
      <form class="card stack" @submit.prevent="createTag">
        <h2>Хештег</h2>
        <label>Название <input v-model="tagForm.name" type="text" required /></label>
        <label class="tight">Цвет <input v-model="tagForm.color" type="color" /></label>
        <div v-for="(row, index) in conditions" :key="index" class="row-actions">
          <select v-model="row.field" @change="syncOp(row)">
            <option v-for="item in tagFields" :key="item.id" :value="item.id">{{ item.label }}</option>
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
    <div v-show="tab === 'notify'">
      <p class="muted">Здесь решается, какое новое письмо вообще поднимает уведомление. Куда его слать — колокольчик, Telegram или почта — на странице «Уведомления». Старая докачка молчит в любом режиме.</p>
      <form class="card stack" @submit.prevent="saveNotify">
        <label>
          О чём писать
          <select v-model="notify.mode">
            <option v-for="item in notifyModes" :key="item.id" :value="item.id">{{ item.label }}</option>
          </select>
        </label>
        <label v-if="notify.mode === 'filter'">
          Как совмещать условия
          <select v-model="notify.match">
            <option v-for="item in notifyMatches" :key="item.id" :value="item.id">{{ item.label }}</option>
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
            <option v-for="item in notifyFields" :key="item.id" :value="item.id">{{ item.label }}</option>
          </select>
          <select v-model="notifyForm.op">
            <option v-for="item in notifyOpsFor(notifyForm.field)" :key="item.id" :value="item.id">{{ item.label }}</option>
          </select>
          <select v-if="notifyForm.field === 'tag'" v-model="notifyForm.value">
            <option value="">Хештег</option>
            <option v-for="tag in tags" :key="tag.id" :value="String(tag.id)">{{ tag.name }}</option>
          </select>
          <input v-else v-model="notifyForm.value" type="text" placeholder="Например ivanov или aeroflot" />
        </div>
        <p v-if="notifyForm.field === 'tag' && !tags.length" class="muted">Сначала создайте хештег на соседней вкладке.</p>
        <p v-if="notify.mode === 'filter' && !notifyRules.length" class="muted">Пока условий нет, о новых письмах тихо.</p>
        <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Добавить условие</button></div>
      </form>
      <template v-if="notify.mode === 'filter'">
        <article v-for="rule in notifyRules" :key="rule.id" class="card">
          <div class="status-row">
            <span>{{ rule.text }}</span>
            <button class="text-btn" type="button" :disabled="busy" @click="removeNotifyRule(rule)">Удалить</button>
          </div>
        </article>
      </template>
    </div>
    <div v-show="tab === 'accounts'">
      <form class="card stack" @submit.prevent="createAccount">
        <h2>Ящик IMAP</h2>
        <label>Название <input v-model="account.name" type="text" required /></label>
        <label>Сервер <input v-model="account.host" type="text" required autocomplete="off" /></label>
        <label>Порт <input v-model.number="account.port" type="number" min="1" /></label>
        <label class="check"><input v-model="account.use_ssl" type="checkbox" /><span>SSL</span></label>
        <label>Логин <input v-model="account.username" type="text" autocomplete="off" /></label>
        <label>Пароль <input v-model="account.password" type="password" autocomplete="new-password" /></label>
        <label>Папка <input v-model="account.folder" type="text" placeholder="INBOX" /></label>
        <p v-if="accountError" class="error">{{ accountError }}</p>
        <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Подключить</button></div>
      </form>
      <article v-for="item in accounts" :key="item.id" class="card stack">
        <strong>{{ item.name }}</strong>
        <div class="muted">{{ item.username }} · {{ item.host }}:{{ item.port }} · {{ item.folder }}</div>
        <p v-if="item.auth_blocked" class="error">Пароль не подошёл. Повторных попыток нет, пока не смените пароль.</p>
        <p v-else-if="item.last_error" class="error">{{ item.last_error }}</p>
        <p v-if="item.backfill_uid > 0" class="muted">Старые письма ещё докачиваются порциями.</p>
        <p v-else-if="item.backfill_uid < 0" class="muted">Папка забрана, дальше только новые письма.</p>
        <label>Новый пароль <input v-model="passwords[item.id]" type="password" autocomplete="new-password" /></label>
        <div class="row-actions">
          <button class="btn" type="button" :disabled="busy" @click="savePassword(item)">Сменить пароль</button>
          <button class="btn secondary" type="button" :disabled="busy" @click="test(item)">Проверить</button>
          <button class="btn secondary" type="button" :disabled="busy || item.auth_blocked" @click="fetchMail(item)">Забрать порцию</button>
          <button class="text-btn" type="button" :disabled="busy" @click="removeAccount(item)">Удалить</button>
        </div>
        <p v-if="notes[item.id]" class="ok-text">{{ notes[item.id] }}</p>
      </article>
    </div>
  </AppShell>
</template>

<script>
import { reactive, ref, onMounted } from "vue"
import AppShell from "../components/AppShell.vue"
import Tabs from "../components/Tabs.vue"
import { api } from "../api"
import { useWhen } from "../composables/useWhen"

export default {
  components: { AppShell, Tabs },
  setup() {
    const accounts = ref([])
    const messages = ref([])
    const error = ref("")
    const accountError = ref("")
    const sync = ref(null)
    const busy = ref(false)
    const query = ref("")
    const tab = ref("accounts")
    const activeTag = ref(0)
    const tags = ref([])
    const tagFields = ref([])
    const tagOps = ref([])
    const conditions = ref([])
    const tagError = ref("")
    const tagForm = reactive({ name: "", color: "#3a6ea5" })
    const notify = reactive({ mode: "all", match: "any", gate_filed: true })
    const notifyModes = ref([])
    const notifyMatches = ref([])
    const notifyFields = ref([])
    const notifyOps = ref([])
    const notifyRules = ref([])
    const notifyError = ref("")
    const notifyForm = reactive({ field: "from", op: "contains", value: "" })
    const passwords = reactive({})
    const notes = reactive({})
    const account = ref({ name: "", host: "", port: 993, use_ssl: true, username: "", password: "", folder: "INBOX" })
    const pageTabs = [
      { id: "letters", label: "Письма" },
      { id: "tags", label: "Хештеги" },
      { id: "notify", label: "Уведомления" },
      { id: "accounts", label: "Ящик" },
    ]
    const { settings, when } = useWhen()
    let opened = false

    function fromLine(item) {
      if (item.from_name && item.from_addr) return item.from_name + " <" + item.from_addr + ">"
      return item.from_addr || item.from_name || ""
    }

    function tagStyle(tag, active) {
      return {
        color: active ? "#fff" : tag.color,
        borderColor: tag.color,
        background: active ? tag.color : "transparent",
      }
    }

    function opsFor(field) {
      const dateOps = new Set(["before", "after", "on"])
      const items = tagOps.value || []
      if (field === "received") return items.filter((item) => dateOps.has(item.id))
      return items.filter((item) => !dateOps.has(item.id))
    }

    function blankCondition() {
      const field = (tagFields.value[0] && tagFields.value[0].id) || "from"
      const ops = opsFor(field)
      return { field, op: (ops[0] && ops[0].id) || "contains", value: "" }
    }

    function syncOp(row) {
      const ops = opsFor(row.field)
      if (!ops.some((item) => item.id === row.op)) row.op = ops[0] ? ops[0].id : ""
    }

    function ruleText(rule) {
      const field = tagFields.value.find((item) => item.id === rule.field)
      const op = tagOps.value.find((item) => item.id === rule.op)
      return (field ? field.label : rule.field) + " " + (op ? op.label : rule.op) + " «" + rule.value + "»"
    }

    function applyMeta(data) {
      tags.value = data.tags || []
      tagFields.value = data.tag_fields || []
      tagOps.value = data.tag_ops || []
      if (data.tag_default_color && tagForm.color === "#3a6ea5") tagForm.color = data.tag_default_color
      if (!conditions.value.length && tagFields.value.length) conditions.value = [blankCondition()]
      const note = data.notify || {}
      notify.mode = note.mode || "all"
      notify.match = note.match || "any"
      notify.gate_filed = note.gate_filed !== false
      notifyModes.value = note.modes || []
      notifyMatches.value = note.matches || []
      notifyFields.value = note.fields || []
      notifyOps.value = note.ops || []
      notifyRules.value = note.rules || []
      if (!notifyForm.field && notifyFields.value.length) notifyForm.field = notifyFields.value[0].id
    }

    async function load() {
      error.value = ""
      const params = new URLSearchParams()
      if (query.value.trim()) params.set("q", query.value.trim())
      if (activeTag.value) params.set("tag", String(activeTag.value))
      const data = await api("/api/mail?" + params.toString())
      accounts.value = data.accounts || []
      messages.value = data.messages || []
      sync.value = data.sync || null
      applyMeta(data)
      if (!opened) {
        opened = true
        if (accounts.value.length) tab.value = "letters"
      }
    }

    function setTag(id) {
      activeTag.value = id
      load().catch((err) => {
        error.value = err.message || "Почта недоступна"
      })
    }

    function notifyOpsFor(field) {
      const items = notifyOps.value || []
      if (field === "tag") return items.filter((item) => item.id === "equals")
      return items
    }

    function syncNotifyOp() {
      const ops = notifyOpsFor(notifyForm.field)
      if (!ops.some((item) => item.id === notifyForm.op)) notifyForm.op = ops[0] ? ops[0].id : ""
      notifyForm.value = ""
    }

    function applyNotify(data) {
      notify.mode = data.mode || notify.mode
      notify.match = data.match || notify.match
      notify.gate_filed = data.gate_filed !== false
      notifyRules.value = data.rules || []
      notifyModes.value = data.modes || notifyModes.value
      notifyMatches.value = data.matches || notifyMatches.value
      notifyFields.value = data.fields || notifyFields.value
      notifyOps.value = data.ops || notifyOps.value
    }

    async function saveNotify() {
      notifyError.value = ""
      busy.value = true
      try {
        applyNotify(await api("/api/mail/notify", {
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
        applyNotify(await api("/api/mail/notify", {
          method: "PUT",
          body: { mode: notify.mode, match: notify.match, gate_filed: !!notify.gate_filed },
        }))
        applyNotify(await api("/api/mail/notify/rules", {
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
        applyNotify(await api("/api/mail/notify/rules/" + rule.id, { method: "DELETE" }))
      } catch (err) {
        notifyError.value = err.message || "Условие не удалилось"
      } finally {
        busy.value = false
      }
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
        tagForm.name = ""
        conditions.value = [blankCondition()]
        tab.value = "letters"
        await load()
      } catch (err) {
        tagError.value = err.message || "Хештег не сохранился"
      } finally {
        busy.value = false
      }
    }

    async function removeTag(tag) {
      busy.value = true
      tagError.value = ""
      try {
        await api("/api/mail/tags/" + tag.id, { method: "DELETE" })
        if (activeTag.value === tag.id) activeTag.value = 0
        await load()
      } catch (err) {
        tagError.value = err.message || "Хештег не удалён"
      } finally {
        busy.value = false
      }
    }

    async function createAccount() {
      accountError.value = ""
      busy.value = true
      try {
        await api("/api/mail/accounts", { method: "POST", body: { ...account.value } })
        account.value.password = ""
        await load()
      } catch (err) {
        accountError.value = err.message || "Ящик не подключился"
      } finally {
        busy.value = false
      }
    }

    async function savePassword(item) {
      notes[item.id] = ""
      const password = passwords[item.id] || ""
      if (!password) {
        notes[item.id] = ""
        error.value = "Введите новый пароль"
        return
      }
      busy.value = true
      error.value = ""
      try {
        await api("/api/mail/accounts/" + item.id, { method: "PATCH", body: { password } })
        passwords[item.id] = ""
        notes[item.id] = "Пароль сохранён, забрана первая порция."
        await load()
      } catch (err) {
        error.value = err.message || "Пароль не сохранился"
      } finally {
        busy.value = false
      }
    }

    async function test(item) {
      notes[item.id] = ""
      busy.value = true
      error.value = ""
      try {
        const data = await api("/api/mail/accounts/" + item.id + "/test", { method: "POST" })
        notes[item.id] = data.ok ? "Проверка прошла. " + (data.subject || "") : ""
        if (!data.ok) error.value = data.error || "Пароль не подошёл"
        await load()
      } catch (err) {
        error.value = err.message || "Проверка не удалась"
      } finally {
        busy.value = false
      }
    }

    async function fetchMail(item) {
      notes[item.id] = ""
      busy.value = true
      error.value = ""
      try {
        const data = await api("/api/mail/accounts/" + item.id + "/fetch", { method: "POST" })
        if (data.blocked) error.value = data.error || "Пароль не подошёл"
        else notes[item.id] = "Забрали " + (data.fetched || 0) + ". " + (data.backfill === "done" ? "Старые письма уже все здесь." : "Следующая порция придёт сама или по кнопке.")
        await load()
      } catch (err) {
        error.value = err.message || "Порция не забралась"
      } finally {
        busy.value = false
      }
    }

    async function removeAccount(item) {
      busy.value = true
      try {
        await api("/api/mail/accounts/" + item.id, { method: "DELETE" })
        await load()
      } catch (err) {
        error.value = err.message || "Ящик не удалён"
      } finally {
        busy.value = false
      }
    }

    onMounted(() => {
      settings.load().catch(() => {})
      load().catch((err) => {
        error.value = err.message || "Почта недоступна"
      })
    })

    return {
      accounts, messages, sync, error, accountError, busy, query, tab, passwords, notes, account, pageTabs,
      tags, tagFields, tagOps, conditions, tagError, tagForm, activeTag,
      notify, notifyModes, notifyMatches, notifyFields, notifyForm, notifyRules, notifyError,
      when, fromLine, load, createAccount, savePassword, test, fetchMail, removeAccount,
      tagStyle, opsFor, blankCondition, syncOp, ruleText, setTag, createTag, removeTag,
      notifyOpsFor, syncNotifyOp, saveNotify, addNotifyRule, removeNotifyRule,
    }
  },
}
</script>
