<template>
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

<script>
import { ref, watch } from "vue"
import { useRoute } from "vue-router"
import { api } from "../../api"
import { useClipboard } from "../../composables/useClipboard"
import { useNotice } from "../../composables/useNotice"
import { useWhen } from "../../composables/useWhen"

// Метки важных полей — язык пользователя: пароль, логин, ссылка.
const FIELD_LABELS = { secret: "пароль", username: "логин", url: "ссылка" }

// История значений секрета (патч O, вынесена из SecretPage в патче X).
// Откат возвращает всю карточку — родитель обновляет форму (emit applied),
// история перечитывается здесь же. undo() открыт наружу (defineExpose):
// кнопка «Отменить» у тоста после сохранения зовёт тот же откат.
export default {
  props: {
    project: { type: Object, required: true },
  },
  emits: ["applied"],
  setup(props, { emit }) {
    const route = useRoute()
    const notice = useNotice()
    const { when } = useWhen()
    const clipboard = useClipboard()
    const busy = ref(false)
    const history = ref([])
    const historyError = ref("")
    const formError = ref("")

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
        emit("applied", data)
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
      formError.value = ""
      busy.value = true
      try {
        const data = await api(
          "/api/projects/" + props.project.id + "/secrets/" + route.params.secretId + "/revisions/" + item.id + "/reveal",
          { method: "POST" },
        )
        await clipboard.write(data.secret || "")
        clipboard.arm()
      } catch (err) {
        formError.value = err.message || "Не удалось скопировать"
      } finally {
        busy.value = false
      }
    }

    watch(
      () => [props.project && props.project.id, route.params.secretId],
      () => {
        loadHistory()
      },
      { immediate: true }
    )

    return { busy, history, historyError, when, changedText, copyRevision, restoreRevision, undoRevision }
  },

  // Кнопка «Отменить» у тоста сохранения зовёт тот же откат, что и «Вернуть».
  expose: ["undoRevision"],
}
</script>
