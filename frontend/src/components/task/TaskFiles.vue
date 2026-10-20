<template>
  <section class="card">
    <p class="muted">Файл создаётся как документ или пример и появляется в их списках. В задаче остаётся только ссылка.</p>
    <form class="composer" @submit.prevent="upload">
      <input ref="fileInput" type="file" />
      <select v-model="fileKind">
        <option value="document">Документ</option>
        <option value="example">Пример</option>
      </select>
      <button class="btn secondary" type="submit" :disabled="busy">Прикрепить</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
    <div v-for="file in task.files" :key="file.kind + '-' + file.id" class="status-row">
      <div>
        <router-link v-if="file.kind === 'document'" :to="'/projects/' + project.id + '/documents/' + file.target_id">{{ file.original_name }}</router-link>
        <router-link v-else-if="file.kind === 'example'" :to="'/projects/' + project.id + '/examples/' + file.target_id">{{ file.original_name }}</router-link>
        <a v-else :href="'/api/files/' + file.file_id">{{ file.original_name }}</a>
        <div class="muted">{{ kindName(file.kind) }}</div>
      </div>
      <button class="text-btn" type="button" @click="removeFile(file)">Убрать ссылку</button>
    </div>
  </section>
</template>

<script>
import { ref } from "vue"
import { useRoute } from "vue-router"
import { api } from "../../api"
import { useNotice } from "../../composables/useNotice"

// Вкладка «Файлы» задачи (патч X): вынесена из TaskPage.vue. Ссылки
// живут в объекте задачи родителя и меняются на месте; ошибка показывается
// здесь же, а не на вкладке «О задаче».
export default {
  props: {
    project: { type: Object, required: true },
    task: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const notice = useNotice()
    const busy = ref(false)
    const fileInput = ref(null)
    const fileKind = ref("document")
    const error = ref("")

    function kindName(kind) {
      if (kind === "document") return "Документ"
      if (kind === "example") return "Пример"
      return "Старый файл"
    }

    async function upload() {
      if (busy.value) return
      const input = fileInput.value
      const file = input && input.files && input.files[0]
      if (!file) {
        error.value = "Выберите файл"
        return
      }
      const body = new FormData()
      body.append("file", file)
      body.append("kind", fileKind.value)
      error.value = ""
      busy.value = true
      try {
        const ref = await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/files", {
          method: "POST",
          body,
        })
        input.value = ""
        props.task.files = (props.task.files || []).concat([ref])
        notice.show("Файл «" + (ref.original_name || "файл") + "» прикреплён", { kind: "success" })
      } catch (err) {
        error.value = err.message || "Файл не прикрепился"
      } finally {
        busy.value = false
      }
    }

    async function removeFile(file) {
      if (busy.value) return
      const snapshot = (props.task.files || []).slice()
      props.task.files = snapshot.filter((row) => !(row.id === file.id && row.kind === file.kind))
      error.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/tasks/" + route.params.taskId + "/files/" + file.id + "?kind=" + encodeURIComponent(file.kind || ""), {
          method: "DELETE",
        })
        notice.show("Ссылка на файл убрана", { kind: "success" })
      } catch (err) {
        props.task.files = snapshot
        error.value = err.message || "Файл не откреплён"
      } finally {
        busy.value = false
      }
    }

    return { busy, fileInput, fileKind, error, kindName, upload, removeFile }
  },
}
</script>
