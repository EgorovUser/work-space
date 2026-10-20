<template>
  <div>
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
      <p v-if="itemErrors[item.id]" class="error">{{ itemErrors[item.id] }}</p>
    </article>
  </div>
</template>

<script>
import { reactive, ref } from "vue"
import { api } from "../../api"
import { useNotice } from "../../composables/useNotice"

// Вкладка «Ящик» почты (патч X): подключение IMAP, смена пароля, проверка,
// забор порции. Вынесена из Mailbox.vue; после любой мутации просит родителя
// перезагрузить почту (emit changed) — как раньше делал общий load().
export default {
  props: {
    accounts: { type: Array, default: () => [] },
  },
  emits: ["changed"],
  setup(props, { emit }) {
    const notice = useNotice()
    const busy = ref(false)
    const accountError = ref("")
    const passwords = reactive({})
    const notes = reactive({})
    const itemErrors = reactive({})
    const account = ref({ name: "", host: "", port: 993, use_ssl: true, username: "", password: "", folder: "INBOX" })

    async function createAccount() {
      accountError.value = ""
      busy.value = true
      try {
        await api("/api/mail/accounts", { method: "POST", body: { ...account.value } })
        account.value.password = ""
        notice.show("Ящик «" + (account.value.username || "") + "» подключён", { kind: "success" })
        emit("changed")
      } catch (err) {
        accountError.value = err.message || "Ящик не подключился"
      } finally {
        busy.value = false
      }
    }

    async function savePassword(item) {
      notes[item.id] = ""
      itemErrors[item.id] = ""
      const password = passwords[item.id] || ""
      if (!password) {
        itemErrors[item.id] = "Введите новый пароль"
        return
      }
      busy.value = true
      try {
        await api("/api/mail/accounts/" + item.id, { method: "PATCH", body: { password } })
        passwords[item.id] = ""
        notes[item.id] = "Пароль сохранён, забрана первая порция."
        emit("changed")
      } catch (err) {
        itemErrors[item.id] = err.message || "Пароль не сохранился"
      } finally {
        busy.value = false
      }
    }

    async function test(item) {
      notes[item.id] = ""
      itemErrors[item.id] = ""
      busy.value = true
      try {
        const data = await api("/api/mail/accounts/" + item.id + "/test", { method: "POST" })
        notes[item.id] = data.ok ? "Проверка прошла. " + (data.subject || "") : ""
        if (!data.ok) itemErrors[item.id] = data.error || "Пароль не подошёл"
        emit("changed")
      } catch (err) {
        itemErrors[item.id] = err.message || "Проверка не удалась"
      } finally {
        busy.value = false
      }
    }

    async function fetchMail(item) {
      notes[item.id] = ""
      itemErrors[item.id] = ""
      busy.value = true
      try {
        const data = await api("/api/mail/accounts/" + item.id + "/fetch", { method: "POST" })
        if (data.blocked) itemErrors[item.id] = data.error || "Пароль не подошёл"
        else notes[item.id] = "Забрали " + (data.fetched || 0) + ". " + (data.backfill === "done" ? "Старые письма уже все здесь." : "Следующая порция придёт сама или по кнопке.")
        emit("changed")
      } catch (err) {
        itemErrors[item.id] = err.message || "Порция не забралась"
      } finally {
        busy.value = false
      }
    }

    async function removeAccount(item) {
      if (!window.confirm("Удалить ящик «" + item.name + "»? Настройки (сервер, логин, пароль) будут потеряны; сохранённые письма останутся.")) return
      busy.value = true
      itemErrors[item.id] = ""
      try {
        await api("/api/mail/accounts/" + item.id, { method: "DELETE" })
        notice.show("Ящик «" + item.name + "» удалён", { kind: "success" })
        emit("changed")
      } catch (err) {
        itemErrors[item.id] = err.message || "Ящик не удалён"
      } finally {
        busy.value = false
      }
    }

    return { busy, accountError, passwords, notes, itemErrors, account, createAccount, savePassword, test, fetchMail, removeAccount }
  },
}
</script>
