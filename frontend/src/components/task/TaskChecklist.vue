<template>
  <section class="card">
    <form class="row-actions" @submit.prevent="addCheck">
      <input v-model="checkTitle" type="text" placeholder="Пункт" />
      <button class="btn secondary" type="submit" :disabled="busy">Добавить</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <div v-for="item in task.checklist" :key="item.id" class="check check-row">
      <input :checked="item.done" type="checkbox" @change="toggleCheck(item, $event)" />
      <span>{{ item.title }}</span>
      <button class="btn secondary" type="button" :disabled="busy" @click="removeCheck(item)">Убрать</button>
    </div>
    <p v-if="!(task.checklist && task.checklist.length)" class="muted">Пунктов нет. Пустой чеклист даёт прогресс 0 в автоматическом режиме.</p>
  </section>
</template>

<script>
import { ref } from "vue"
import { useRoute } from "vue-router"
import { api } from "../../api"
import { useNotice } from "../../composables/useNotice"

// Вкладка «Чеклист» задачи (патч X): вынесена из TaskPage.vue. Список
// пунктов живёт в объекте задачи родителя и меняется на месте — форма
// «О задаче» не перезатирается побочными действиями. Ошибка показывается
// здесь же, а не на соседней вкладке.
export default {
  props: {
    project: { type: Object, required: true },
    task: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const notice = useNotice()
    const busy = ref(false)
    const checkTitle = ref("")
    const error = ref("")

    async function addCheck() {
      if (busy.value) return
      const title = checkTitle.value.trim()
      if (!title) {
        error.value = "Введите текст пункта"
        return
      }
      error.value = ""
      busy.value = true
      try {
        const item = await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/checklist", {
          method: "POST",
          body: { title },
        })
        checkTitle.value = ""
        props.task.checklist = (props.task.checklist || []).concat([item])
        notice.show("Пункт «" + title + "» добавлен", { kind: "success" })
      } catch (err) {
        error.value = err.message || "Пункт не добавлен"
      } finally {
        busy.value = false
      }
    }

    async function toggleCheck(item, event) {
      const previous = item.done
      item.done = event.target.checked
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/checklist/" + item.id, {
          method: "PATCH",
          body: { done: item.done },
        })
      } catch (err) {
        item.done = previous
        event.target.checked = previous
        notice.show("Не удалось отметить пункт. " + (err.message || "Ошибка"))
      }
    }

    async function removeCheck(item) {
      const list = props.task.checklist || []
      const snapshot = list.slice()
      props.task.checklist = list.filter((row) => row.id !== item.id)
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/checklist/" + item.id, {
          method: "DELETE",
        })
        notice.show("Пункт «" + item.title + "» убран", { kind: "success" })
      } catch (err) {
        props.task.checklist = snapshot
        notice.show("Не удалось убрать пункт. " + (err.message || "Ошибка"))
      }
    }

    return { busy, checkTitle, error, addCheck, toggleCheck, removeCheck }
  },
}
</script>
