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

      <section class="card stack">
        <h2>История значений</h2>
        <p class="muted">
          Снимок создаётся, когда меняются пароль, логин или ссылка. Откат не
          разрушающий: текущие значения тоже попадают в историю.
        </p>
        <p v-if="historyError" class="error">{{ historyError }}</p>
        <p v-else-if="!history.length" class="muted">Пока пусто — важные поля ещё не менялись.</p>
        <div v-for="item in history" :key="item.id" class="status-row">
          <div>
            <strong>{{ when(item.created_at) }}</strong>
            <div class="muted">изменялись: {{ changedText(item) }}</div>
          </div>
          <div class="rdp-tools">
            <button
              class="btn secondary"
              type="button"
              :disabled="busy || !item.has_secret"
              :title="item.has_secret ? '' : 'В этой версии значения нет'"
              @click="copyRevision(item)"
            >Скопировать</button>
            <button class="btn secondary" type="button" :disabled="busy" @click="restoreRevision(item)">Вернуть</button>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"
import { useWhen } from "../composables/useWhen"

const CLIPBOARD_TTL = 30

// Метки важных полей — язык пользователя: пароль, логин, ссылка.
const FIELD_LABELS = { secret: "пароль", username: "логин", url: "ссылка" }

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
    const history = ref([])
    const historyError = ref("")
    const notice = useNotice()
    const { settings, when } = useWhen()
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
        await loadHistory()
      } catch (err) {
        record.value = null
        error.value = err.message || "Секрет недоступен"
      }
    }

    async function loadHistory() {
      historyError.value = ""
      try {
        const data = await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId + "/revisions")
        history.value = data.items || []
      } catch (err) {
        history.value = []
        historyError.value = err.message || "История недоступна"
      }
    }

    function changedText(item) {
      const labels = (item.changed || []).map((code) => FIELD_LABELS[code] || code)
      return labels.length ? labels.join(", ") : "—"
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

    // Какие важные поля уходят в сохранении изменёнными — для текста тоста.
    function changedLabels() {
      const labels = []
      if (touched.value && record.value.has_secret) labels.push("пароль")
      if (record.value.username && form.value.username !== record.value.username) labels.push("логин")
      if (record.value.url && form.value.url !== record.value.url) labels.push("ссылка")
      return labels
    }

    async function save() {
      formError.value = ""
      const labels = changedLabels()
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
        const data = await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId, {
          method: "PATCH",
          body,
        })
        apply(data)
        await loadHistory()
        if (data.revision_id) {
          // Сервер сохранил прежние значения снимком — даём одну кнопку
          // на немедленный откат вместо отдельного похода в историю.
          notice.show(
            labels.length ? "Сохранено: " + labels.join(", ") : "Сохранено",
            { kind: "success", action: { label: "Отменить", run: () => undoRevision(data.revision_id) } },
          )
        } else {
          notice.show("Сохранено", { kind: "success" })
        }
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

    // Откат к снимку без лишних вопросов — вызывается кнопкой «Отменить»
    // у тоста (намерение уже выражено) и из «Вернуть» после подтверждения.
    async function undoRevision(revisionId) {
      formError.value = ""
      busy.value = true
      try {
        const data = await api(
          "/api/projects/" + props.project.id + "/secrets/" + route.params.secretId + "/revisions/" + revisionId + "/restore",
          { method: "POST" },
        )
        apply(data)
        await loadHistory()
        if (data.revision_id) {
          notice.show("Возвращены прежние значения", {
            kind: "success",
            action: { label: "Отменить", run: () => undoRevision(data.revision_id) },
          })
        } else {
          notice.show("Версия совпадает с текущей", { kind: "success" })
        }
      } catch (err) {
        formError.value = err.message || "Не удалось вернуть версию"
      } finally {
        busy.value = false
      }
    }

    async function restoreRevision(item) {
      const ok = window.confirm(
        "Вернуть прежние значения ("
        + changedText(item)
        + ")? Текущие тоже сохранятся в истории — откат можно отменить.",
      )
      if (!ok) return
      await undoRevision(item.id)
    }

    async function copyRevision(item) {
      copied.value = false
      formError.value = ""
      busy.value = true
      try {
        const data = await api(
          "/api/projects/" + props.project.id + "/secrets/" + route.params.secretId + "/revisions/" + item.id + "/reveal",
          { method: "POST" },
        )
        await writeClipboard(data.secret || "")
        armClipboard()
      } catch (err) {
        formError.value = err.message || "Не удалось скопировать"
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
      // Слепая перезапись: поле может держать текущий (или ещё не
      // сохранённый) пароль — спрашиваем, прежде чем затирать.
      if ((form.value.secret || "") !== "" || record.value.has_secret) {
        const ok = window.confirm(
          "Заменить текущий секрет? Прежнее значение останется в истории после сохранения.",
        )
        if (!ok) return
      }
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
      if ((form.value.secret || "") !== "" || record.value.has_secret) {
        const ok = window.confirm(
          "Убрать значение секрета? Прежнее можно будет вернуть из истории после сохранения.",
        )
        if (!ok) return
      }
      form.value.secret = ""
      touched.value = true
      visible.value = true
    }

    async function toggleArchive() {
      formError.value = ""
      busy.value = true
      try {
        const previous = record.value.archived
        apply(await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId, {
          method: "PATCH",
          body: { archived: !previous },
        }))
        notice.show(previous ? "Секрет возвращён из архива" : "Секрет в архиве", { kind: "success" })
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
        const secretId = Number(route.params.secretId)
        const title = record.value ? record.value.title : "Секрет"
        // Удаление мягкое: «Отменить» достаёт секрет из корзины и открывает
        // его страницу снова. История значений сохраняется до purge.
        notice.show("Секрет «" + title + "» удалён в корзину", {
          kind: "success",
          timeout: 9000,
          action: {
            label: "Отменить",
            run: async () => {
              try {
                await api("/api/trash/secrets/" + secretId + "/restore", { method: "POST" })
                notice.show("Секрет «" + title + "» восстановлен", { kind: "success" })
                router.push("/projects/" + props.project.id + "/secrets/" + secretId)
              } catch (err) {
                notice.show("Не удалось восстановить секрет. " + (err.message || "Ошибка"))
              }
            },
          },
        })
        router.push("/projects/" + props.project.id + "/secrets")
      } catch (err) {
        formError.value = err.message || "Не удалось удалить"
        busy.value = false
      }
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).catch(() => {})
    }, { immediate: true })

    watch(() => [props.project && props.project.id, route.params.secretId], load, { immediate: true })

    return {
      record, error, formError, busy, copied, visible, touched, form, knownKind, clipSeconds,
      history, historyError, when, changedText,
      save, reveal, copySecret, generate, clearSecret, toggleArchive, remove,
      copyRevision, restoreRevision,
    }
  },
}
</script>
