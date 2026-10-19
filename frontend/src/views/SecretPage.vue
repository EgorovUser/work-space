<template>
  <div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="!record" class="muted">Загрузка…</p>
    <template v-else>
      <p class="crumbs"><router-link :to="'/projects/' + project.id + '/secrets'">← Секреты</router-link> / {{ form.title || "Секрет" }}</p>
      <h1>{{ form.title || "Секрет" }}</h1>
      <form class="card stack" @submit.prevent="save">
      <label>
        Название
        <input v-model="form.title" type="text" required autocomplete="off" />
      </label>
      <label>
        Вид
        <select v-model="form.kind">
          <option v-if="form.kind && !knownKind" :value="form.kind">{{ form.kind }}</option>
          <option v-for="item in record.kinds || []" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
      </label>
      <label>
        Логин
        <input v-model="form.username" type="text" autocomplete="off" />
      </label>
      <label>
        Ссылка
        <input v-model="form.url" type="text" autocomplete="off" />
      </label>
      <label>
        Заметка
        <textarea v-model="form.note" />
      </label>
      <label>
        Секрет
        <input
          v-model="form.secret"
          :type="visible ? 'text' : 'password'"
          autocomplete="new-password"
          :placeholder="record.has_secret ? 'Не менять, если пусто' : ''"
          @input="touched = true"
        />
      </label>
      <p v-if="record.has_secret && !visible" class="muted">Секрет задан и скрыт.</p>
      <p v-if="formError" class="error">{{ formError }}</p>
      <p v-if="copied" class="ok-text">Скопировано. Буфер очистится через {{ clipSeconds }} с.</p>
      <div class="row-actions">
        <button class="btn" type="submit" :disabled="busy">Сохранить</button>
        <button class="btn secondary" type="button" :disabled="busy" @click="reveal">
          {{ visible ? "Скрыть" : "Показать" }}
        </button>
        <button class="btn secondary" type="button" :disabled="busy" @click="copySecret">Копировать секрет</button>
        <button class="btn secondary" type="button" :disabled="busy" @click="generate">Сгенерировать</button>
        <button class="btn secondary" type="button" :disabled="busy" @click="clearSecret">Очистить секрет</button>
        <button class="btn secondary" type="button" :disabled="busy" @click="toggleArchive">
          {{ record.archived ? "Вернуть из архива" : "В архив" }}
        </button>
        <button class="btn secondary" type="button" :disabled="busy" @click="remove">Удалить</button>
      </div>
      </form>
    </template>
  </div>
</template>

<script>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"

const CLIPBOARD_TTL = 30

export default {
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const router = useRouter()
    const record = ref(null)
    const error = ref("")
    const formError = ref("")
    const busy = ref(false)
    const copied = ref(false)
    const visible = ref(false)
    const touched = ref(false)
    const clipSeconds = ref(CLIPBOARD_TTL)
    const form = ref({ title: "", kind: "", username: "", url: "", note: "", secret: "" })
    const notice = useNotice()
    let clipTimer = null
    let clearTimer = null

    const knownKind = computed(() => {
      const list = (record.value && record.value.kinds) || []
      return list.some((item) => item.id === form.value.kind)
    })

    function apply(data) {
      record.value = data
      form.value = {
        title: data.title,
        kind: data.kind || "",
        username: data.username || "",
        url: data.url || "",
        note: data.note || "",
        secret: "",
      }
      visible.value = false
      touched.value = false
      copied.value = false
    }

    async function load() {
      error.value = ""
      try {
        apply(await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId))
      } catch (err) {
        record.value = null
        error.value = err.message || "Секрет недоступен"
      }
    }

    function armClipboard() {
      clearInterval(clipTimer)
      clearTimeout(clearTimer)
      copied.value = true
      clipSeconds.value = CLIPBOARD_TTL
      // Обратный отсчёт в подсказке + очистка буфера: пароль не остаётся
      // в системе на неопределённый срок после копирования.
      clipTimer = setInterval(() => {
        clipSeconds.value -= 1
        if (clipSeconds.value <= 0) clearInterval(clipTimer)
      }, 1000)
      clearTimer = setTimeout(async () => {
        copied.value = false
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText("")
          }
        } catch {
          // Буфер мог быть перезаписан другой вкладкой — это нормальный исход.
        }
      }, CLIPBOARD_TTL * 1000)
    }

    onBeforeUnmount(() => {
      clearInterval(clipTimer)
      clearTimeout(clearTimer)
    })

    async function save() {
      formError.value = ""
      busy.value = true
      const body = {
        title: form.value.title,
        kind: form.value.kind,
        username: form.value.username,
        url: form.value.url,
        note: form.value.note,
        updated_at: record.value.updated_at,
      }
      if (touched.value) body.secret = form.value.secret
      try {
        apply(await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId, {
          method: "PATCH",
          body,
        }))
        notice.show("Сохранено", { kind: "success" })
      } catch (err) {
        if (err.status === 409) {
          if (window.confirm(err.message + "\n\nЗагрузить свежую версию? Несохранённые правки будут потеряны.")) {
            await load()
          }
        } else {
          formError.value = err.message || "Не сохранилось"
        }
      } finally {
        busy.value = false
      }
    }

    async function reveal() {
      if (visible.value) {
        visible.value = false
        if (!touched.value) form.value.secret = ""
        return
      }
      formError.value = ""
      busy.value = true
      try {
        const data = await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId + "/reveal", {
          method: "POST",
        })
        if (!touched.value) form.value.secret = data.secret || ""
        visible.value = true
      } catch (err) {
        formError.value = err.message || "Не удалось показать"
      } finally {
        busy.value = false
      }
    }

    async function copySecret() {
      copied.value = false
      formError.value = ""
      busy.value = true
      try {
        const value = touched.value
          ? form.value.secret
          : (await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId + "/reveal", {
            method: "POST",
          })).secret || ""
        await writeClipboard(value)
        armClipboard()
      } catch (err) {
        formError.value = err.message || "Не удалось скопировать"
      } finally {
        busy.value = false
      }
    }

    async function writeClipboard(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text)
        return
      }
      const area = document.createElement("textarea")
      area.value = text
      document.body.appendChild(area)
      area.select()
      document.execCommand("copy")
      area.remove()
    }

    async function generate() {
      formError.value = ""
      busy.value = true
      try {
        const data = await api("/api/projects/" + props.project.id + "/secrets/generate", { method: "POST" })
        form.value.secret = data.secret || ""
        touched.value = true
        visible.value = true
      } catch (err) {
        formError.value = err.message || "Не удалось сгенерировать"
      } finally {
        busy.value = false
      }
    }

    function clearSecret() {
      form.value.secret = ""
      touched.value = true
      visible.value = true
    }

    async function toggleArchive() {
      formError.value = ""
      busy.value = true
      try {
        apply(await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId, {
          method: "PATCH",
          body: { archived: !record.value.archived },
        }))
      } catch (err) {
        formError.value = err.message || "Не получилось"
      } finally {
        busy.value = false
      }
    }

    async function remove() {
      if (!window.confirm("Удалить секрет?")) return
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId, { method: "DELETE" })
        router.push("/projects/" + props.project.id + "/secrets")
      } catch (err) {
        formError.value = err.message || "Не удалось удалить"
        busy.value = false
      }
    }

    watch(() => [props.project && props.project.id, route.params.secretId], load, { immediate: true })

    return {
      record, error, formError, busy, copied, visible, touched, form, knownKind, clipSeconds,
      save, reveal, copySecret, generate, clearSecret, toggleArchive, remove,
    }
  },
}
</script>
