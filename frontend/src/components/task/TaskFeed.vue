<template>
  <section class="card">
    <form class="stack" @submit.prevent="comment">
      <textarea v-model="commentBody" placeholder="Комментарий" rows="3" />
      <div>
        <button class="btn secondary" type="submit" :disabled="busy">Написать</button>
      </div>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <article v-for="item in task.events" :key="item.id" class="setting">
      <p>
        <strong>{{ kindLabel(item.kind) }}</strong>
        <span class="muted"> · {{ when(item.created_at) }}</span>
        <span v-if="personName(item.user_id)" class="muted"> · {{ personName(item.user_id) }}</span>
      </p>
      <p v-if="item.body">{{ item.body }}</p>
    </article>
  </section>
</template>

<script>
import { ref } from "vue"
import { useRoute } from "vue-router"
import { api } from "../../api"
import { useNotice } from "../../composables/useNotice"
import { useWhen } from "../../composables/useWhen"

const KINDS = {
  created: "Создана",
  status: "Колонка",
  assigned: "Исполнитель",
  comment: "Комментарий",
  checklist: "Чеклист",
  deadline: "Дедлайн",
  attachment: "Файл",
  updated: "Правка",
  recur: "Повтор",
}

// Вкладка «Лента» задачи (патч X): комментарии и история событий.
// Новый комментарий возвращает всю задачу — родитель обновляет её
// (emit refresh), не трогая несохранённые правки в форме «О задаче».
export default {
  props: {
    project: { type: Object, required: true },
    task: { type: Object, required: true },
    users: { type: Array, default: () => [] },
  },
  emits: ["refresh"],
  setup(props, { emit }) {
    const route = useRoute()
    const notice = useNotice()
    const { when } = useWhen()
    const busy = ref(false)
    const commentBody = ref("")
    const error = ref("")

    function kindLabel(kind) {
      return KINDS[kind] || kind
    }

    function personName(id) {
      const person = props.users.find((item) => item.id === id)
      return person ? person.display_name || person.username : ""
    }

    async function comment() {
      if (busy.value) return
      const text = commentBody.value.trim()
      if (!text) {
        error.value = "Комментарий пустой"
        return
      }
      error.value = ""
      busy.value = true
      try {
        const saved = await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/comments", {
          method: "POST",
          body: { body: text },
        })
        commentBody.value = ""
        // Сервер возвращает всю задачу; форму не трогаем — там могут быть
        // несохранённые правки.
        emit("refresh", saved)
        notice.show("Комментарий добавлен", { kind: "success" })
      } catch (err) {
        error.value = err.message || "Комментарий не сохранён"
      } finally {
        busy.value = false
      }
    }

    return { busy, commentBody, error, when, kindLabel, personName, comment }
  },
}
</script>
