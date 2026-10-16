<template>
  <form class="stack" @submit.prevent="save">
    <section class="card stack">
      <h2>Telegram</h2>
      <p class="muted">Токен выдаёт @BotFather. В чат впишите числовой id: свой, группы или канала, куда бот может писать.</p>
      <label>
        Токен бота
        <input v-model="form.botToken" class="secret-input" type="text" name="telegram-bot-token" autocomplete="off" spellcheck="false" :placeholder="flags.botToken ? 'Уже задан — введите новый, только если меняете' : ''" />
      </label>
      <p v-if="flags.botToken && flags.botTokenOk" class="ok-text">Токен сохранён. Поле пустое специально: обратно он не показывается и пустое поле его не стирает.</p>
      <p v-else-if="flags.botToken" class="error">Сохранённый токен не подходит. Telegram на него отвечает Not Found. Вставьте токен из BotFather целиком: число, двоеточие и длинный ключ.</p>
      <p v-else class="muted">Токен ещё не задан.</p>
      <label>
        Id чата
        <input v-model="form.chatId" type="text" autocomplete="off" placeholder="Например 123456789" />
      </label>
      <p v-if="telegramError" class="error">{{ telegramError }}</p>
      <p v-if="telegramNote" class="ok-text">{{ telegramNote }}</p>
      <div class="row-actions">
        <button class="btn secondary" type="button" :disabled="busy" @click="testTelegram">Проверить бота</button>
      </div>
    </section>

    <section class="card stack">
      <h2>Почта для уведомлений</h2>
      <p class="muted">Отправка берёт только эти поля. В общих настройках их больше нет, чтобы не было двух разных адресов.</p>
      <label>Сервер <input v-model="form.host" type="text" autocomplete="off" /></label>
      <label>Порт <input v-model.number="form.port" type="number" min="1" /></label>
      <label class="check"><input v-model="form.ssl" type="checkbox" /><span>SSL</span></label>
      <label class="check"><input v-model="form.starttls" type="checkbox" /><span>STARTTLS</span></label>
      <label>Логин <input v-model="form.username" type="text" autocomplete="off" /></label>
      <label>
        Пароль
        <input v-model="form.password" type="password" autocomplete="new-password" :placeholder="flags.password ? 'Уже задан — введите новый, только если меняете' : ''" />
      </label>
      <p v-if="flags.password" class="ok-text">Пароль сохранён. Поле пустое специально: обратно он не показывается и пустое поле его не стирает.</p>
      <p v-else class="muted">Пароль ещё не задан. Для сервера без авторизации его можно не заполнять.</p>
      <label>От кого <input v-model="form.from" type="text" autocomplete="off" /></label>
      <label>Кому <input v-model="form.to" type="text" autocomplete="off" /></label>
      <p v-if="mailError" class="error">{{ mailError }}</p>
      <p v-if="mailNote" class="ok-text">{{ mailNote }}</p>
      <div class="row-actions">
        <button class="btn secondary" type="button" :disabled="busy" @click="testMail">Проверить почту</button>
      </div>
    </section>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="note" class="ok-text">{{ note }}</p>
    <div class="row-actions">
      <button class="btn" type="submit" :disabled="busy">Сохранить</button>
    </div>
  </form>
</template>

<script>
import { onMounted, reactive, ref } from "vue"
import { api } from "../api"

const TEXT_KEYS = {
  "telegram.chat_id": "chatId",
  "smtp.host": "host",
  "smtp.username": "username",
  "smtp.from": "from",
  "smtp.to": "to",
}

export default {
  setup() {
    const form = reactive({
      botToken: "",
      chatId: "",
      host: "",
      port: 587,
      ssl: false,
      starttls: true,
      username: "",
      password: "",
      from: "",
      to: "",
    })
    const flags = reactive({ botToken: false, botTokenOk: true, password: false })
    const error = ref("")
    const note = ref("")
    const telegramError = ref("")
    const telegramNote = ref("")
    const mailError = ref("")
    const mailNote = ref("")
    const busy = ref(false)

    function chosen(item) {
      const user = item.values && item.values.user
      const global = item.values && item.values.global
      if (user && user.is_override) return user
      if (global && global.is_override) return global
      return user || global || {}
    }

    async function load() {
      const data = await api("/api/settings?module=notifications")
      for (const item of data.items || []) {
        const state = chosen(item)
        if (item.key === "telegram.bot_token") {
          flags.botToken = Boolean(state.is_set)
          flags.botTokenOk = state.usable !== false
        }
        if (item.key === "smtp.password") flags.password = Boolean(state.is_set)
        if (item.key === "smtp.port" && state.value != null) form.port = Number(state.value)
        if (item.key === "smtp.ssl") form.ssl = Boolean(state.value)
        if (item.key === "smtp.starttls") form.starttls = Boolean(state.value)
        const field = TEXT_KEYS[item.key]
        if (field && state.value != null) form[field] = String(state.value)
      }
    }

    async function put(key, value) {
      await api("/api/settings", {
        method: "PUT",
        body: { module: "notifications", key, scope: "user", value },
      })
    }

    async function saveTelegram() {
      const typed = form.botToken.trim()
      if (typed) {
        const token = normalizeToken(typed)
        if (!token) {
          throw new Error("Это не токен бота. Скопируйте его из BotFather целиком: число, двоеточие и длинный ключ.")
        }
        await put("telegram.bot_token", token)
        flags.botToken = true
        flags.botTokenOk = true
        form.botToken = ""
      }
      await put("telegram.chat_id", form.chatId.trim())
    }

    async function saveMail() {
      await put("smtp.host", form.host.trim())
      await put("smtp.port", Number(form.port) || 0)
      await put("smtp.ssl", Boolean(form.ssl))
      await put("smtp.starttls", Boolean(form.starttls))
      await put("smtp.username", form.username.trim())
      if (form.password) {
        await put("smtp.password", form.password)
        flags.password = true
        form.password = ""
      }
      await put("smtp.from", form.from.trim())
      await put("smtp.to", form.to.trim())
    }

    function normalizeToken(raw) {
      let text = String(raw || "").replace(/\s+/g, "")
      const marker = text.toLowerCase().indexOf("/bot")
      if (marker >= 0) text = text.slice(marker + 4).split("/")[0]
      else if (text.toLowerCase().startsWith("bot") && text.slice(3).includes(":")) text = text.slice(3)
      return /^\d{6,}:[A-Za-z0-9_-]{20,}$/.test(text) ? text : ""
    }

    async function persist() {
      await saveTelegram()
      await saveMail()
      await load()
    }

    async function save() {
      error.value = ""
      note.value = ""
      busy.value = true
      try {
        await persist()
        note.value = "Сохранено"
      } catch (err) {
        error.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function testTelegram() {
      telegramError.value = ""
      telegramNote.value = ""
      error.value = ""
      busy.value = true
      try {
        await saveTelegram()
        await load()
        await api("/api/notifications/test/telegram", { method: "POST" })
        telegramNote.value = "Сообщение ушло в чат. Токен на месте, поле очищено только на экране."
      } catch (err) {
        telegramError.value = err.message || "Бот не ответил"
      } finally {
        busy.value = false
      }
    }

    async function testMail() {
      mailError.value = ""
      mailNote.value = ""
      error.value = ""
      busy.value = true
      try {
        await saveMail()
        await load()
        await api("/api/notifications/test/email", { method: "POST" })
        mailNote.value = "Письмо отправлено. Пароль на месте, поле очищено только на экране."
      } catch (err) {
        mailError.value = err.message || "Письмо не ушло"
      } finally {
        busy.value = false
      }
    }

    onMounted(() => {
      load().catch((err) => {
        error.value = err.message || "Настройки недоступны"
      })
    })

    return { form, flags, error, note, telegramError, telegramNote, mailError, mailNote, busy, save, testTelegram, testMail }
  },
}
</script>
