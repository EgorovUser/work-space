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

      <!-- История значений (патч O) — компонент secret/SecretRevisions.vue
           (патч X); откат возвращает карточку сюда событием applied. -->
      <SecretRevisions ref="revisions" :project="project" @applied="apply" />
    </template>
  </div>
</template>

<script>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"
import SecretRevisions from "../components/secret/SecretRevisions.vue"
import { useClipboard } from "../composables/useClipboard"
import { useNotice } from "../composables/useNotice"
import { useWhen } from "../composables/useWhen"

// Страница секрета: форма значений, показ/копирование, генерация, архив,
// удаление. История значений — в secret/SecretRevisions.vue (патч X);
// буфер обмена с автоочисткой — composable useClipboard.
export default {
  components: { SecretRevisions },
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
    const visible = ref(false)
    const touched = ref(false)
    const form = ref({ title: "", kind: "", username: "", url: "", note: "", secret: "" })
    const notice = useNotice()
    const clipboard = useClipboard()
    const { copied, clipSeconds } = clipboard
    const revisions = ref(null)
    const { settings } = useWhen()

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

    // Откат к снимку — руками компонента истории (тот же путь, что и
    // кнопка «Вернуть» в ней), карточка возвращается сюда событием applied.
    function undoRevision(revisionId) {
      if (revisions.value) revisions.value.undoRevision(revisionId)
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
      formError.value = ""
      busy.value = true
      try {
        const value = touched.value
          ? form.value.secret
          : (await api("/api/projects/" + props.project.id + "/secrets/" + route.params.secretId + "/reveal", {
            method: "POST",
          })).secret || ""
        await clipboard.write(value)
        clipboard.arm()
      } catch (err) {
        formError.value = err.message || "Не удалось скопировать"
      } finally {
        busy.value = false
      }
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

    onBeforeUnmount(() => clipboard.stop())

    return {
      record, error, formError, busy, copied, visible, touched, form, knownKind, clipSeconds,
      revisions, apply, save, reveal, copySecret, generate, clearSecret, toggleArchive, remove,
    }
  },
}
</script>
