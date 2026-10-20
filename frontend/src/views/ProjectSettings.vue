<template>
  <div>
    <h1>Настройки</h1>
    <form class="card stack" @submit.prevent="saveProject">
      <label>
        Название
        <input v-model="name" type="text" required />
      </label>
      <label>
        Описание
        <textarea v-model="description" />
      </label>
      <p v-if="formError" class="error">{{ formError }}</p>
      <div class="row-actions">
        <button class="btn" type="submit" :disabled="busy">Сохранить</button>
        <button class="btn secondary" type="button" :disabled="busy" @click="toggleArchive">
          {{ project.archived ? "Вернуть из архива" : "В архив" }}
        </button>
      </div>
    </form>

    <p v-if="settingsError" class="error">{{ settingsError }}</p>
    <section v-else class="card">
      <h2>Параметры проекта</h2>
      <SettingsForm :items="items" scope="project" :project-id="project.id" @changed="loadSettings" />
    </section>
  </div>
</template>

<script>
import { ref, watch } from "vue"
import SettingsForm from "../components/SettingsForm.vue"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"

export default {
  components: { SettingsForm },
  props: {
    project: { type: Object, required: true },
  },
  emits: ["changed"],
  setup(props, { emit }) {
    const name = ref("")
    const description = ref("")
    const formError = ref("")
    const settingsError = ref("")
    const notice = useNotice()
    const items = ref([])
    const busy = ref(false)

    watch(
      () => props.project,
      (project) => {
        name.value = project.name
        description.value = project.description || ""
        loadSettings()
      },
      { immediate: true }
    )

    async function loadSettings() {
      settingsError.value = ""
      try {
        const data = await api("/api/settings?module=projects&project_id=" + props.project.id)
        items.value = data.items || []
      } catch (err) {
        settingsError.value = err.message || "Настройки недоступны"
      }
    }

    async function saveProject() {
      formError.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id, {
          method: "PATCH",
          body: { name: name.value, description: description.value },
        })
        emit("changed")
        notice.show("Проект сохранён", { kind: "success" })
      } catch (err) {
        formError.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function toggleArchive() {
      formError.value = ""
      busy.value = true
      try {
        const previous = props.project.archived
        await api("/api/projects/" + props.project.id + "/archive", {
          method: "POST",
          body: { archived: !previous },
        })
        emit("changed")
        notice.show(previous ? "Проект возвращён из архива" : "Проект в архиве", { kind: "success" })
      } catch (err) {
        formError.value = err.message || "Не изменилось"
      } finally {
        busy.value = false
      }
    }

    return { name, description, formError, settingsError, items, busy, loadSettings, saveProject, toggleArchive }
  },
}
</script>
