<template>
  <div>
    <p v-if="error" class="error">{{ error }}</p>
    <article v-else-if="message" class="card stack">
      <h1>{{ message.title }}</h1>
      <p class="muted">{{ fromLine }} → {{ message.to_addr || "—" }} · {{ when(message.received_at) }}</p>
      <div v-if="message.tags && message.tags.length" class="tag-row">
        <button
          v-for="tag in message.tags"
          :key="tag.id"
          type="button"
          class="mail-tag on"
          :style="tagStyle(tag, true)"
          :disabled="busy"
          @click="toggleTag(tag, false)"
        >{{ tag.name }} ×</button>
      </div>
      <section v-if="message.thread && message.thread.length > 1" class="stack">
        <h2>Переписка</h2>
        <div v-for="item in message.thread" :key="item.id" class="status-row">
          <div>
            <strong v-if="item.id === message.id">{{ item.title }}</strong>
            <router-link v-else :class="{ unread: !item.read }" :to="threadLink(item)">{{ item.title }}</router-link>
            <div class="muted">{{ fromLineOf(item) }} · {{ when(item.received_at) }}<span v-if="item.archived"> · архив</span></div>
          </div>
        </div>
        <p v-if="message.thread_total > message.thread.length" class="muted">Показаны последние {{ message.thread.length }} из {{ message.thread_total }}</p>
      </section>
      <p v-if="message.events && message.events.length" class="muted">
        События:
        <span v-for="item in message.events" :key="item.id"> {{ item.summary }} · {{ when(item.starts_at) }}</span>
      </p>
      <iframe v-if="message.html" class="mail-frame" sandbox="" referrerpolicy="no-referrer" :srcdoc="frameHtml"></iframe>
      <pre v-else class="text-block">{{ message.body || "Текста нет" }}</pre>
      <ul v-if="message.attachments && message.attachments.length" class="plain-list">
        <li v-for="item in message.attachments" :key="item.section || item.filename">
          <a v-if="item.file_id" :href="'/api/files/' + item.file_id">{{ item.filename }}</a>
          <template v-else>
            <span>{{ item.filename }}</span>
            <button class="btn secondary" type="button" :disabled="busy || !item.section" @click="pullFile(item)">Скачать вложение</button>
          </template>
        </li>
      </ul>
      <div class="composer">
        <select v-model="folderProject">
          <option value="">Папка проекта</option>
          <option v-for="item in projects" :key="item.id" :value="String(item.id)">{{ item.name }}</option>
        </select>
        <button class="btn secondary" type="button" :disabled="busy || !folderProject" @click="place(false)">Копировать</button>
        <button class="btn secondary" type="button" :disabled="busy || !folderProject" @click="place(true)">Переместить</button>
      </div>
      <p class="muted">Если папки с именем проекта на сервере нет, она создаётся.</p>
      <p v-if="formError" class="error">{{ formError }}</p>
      <div class="row-actions">
        <button class="btn secondary" type="button" :disabled="busy" @click="toggleRead">
          {{ message.read ? "Пометить непрочитанным" : "Пометить прочитанным" }}
        </button>
        <button class="btn secondary" type="button" :disabled="busy" @click="toggleArchive">
          {{ message.archived ? "Вернуть из архива" : "В архив" }}
        </button>
        <button class="btn secondary" type="button" :disabled="busy" @click="remove">Удалить</button>
      </div>
    </article>
    <p v-else class="muted">Загрузка…</p>
  </div>
</template>

<script>
import { computed, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api, downloadFile } from "../api"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"

export default {
  props: { project: { type: Object, default: null } },
  setup(props) {
    const route = useRoute()
    const router = useRouter()
    const message = ref(null)
    const projects = ref([])
    const folderProject = ref("")
    const error = ref("")
    const formError = ref("")
    const busy = ref(false)
    const { settings, when } = useWhen()
    const notice = useNotice()

    const fromLine = computed(() => {
      const item = message.value
      if (!item) return ""
      if (item.from_name && item.from_addr) return item.from_name + " <" + item.from_addr + ">"
      return item.from_addr || item.from_name || ""
    })

    const frameHtml = computed(() => {
      const html = message.value && message.value.html
      if (!html) return ""
      return "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>" + html + "</body></html>"
    })

    function fromLineOf(item) {
      if (!item) return ""
      if (item.from_name && item.from_addr) return item.from_name + " <" + item.from_addr + ">"
      return item.from_addr || item.from_name || ""
    }

    function threadLink(item) {
      if (props.project && props.project.id) return "/projects/" + props.project.id + "/mail/" + item.id
      return "/mail/" + item.id
    }

    function tagStyle(tag, active) {
      return {
        color: active ? "#fff" : tag.color,
        borderColor: tag.color,
        background: active ? tag.color : "transparent",
      }
    }

    function path() {
      if (props.project && props.project.id) {
        return "/api/projects/" + props.project.id + "/mail/messages/" + route.params.messageId
      }
      return "/api/mail/messages/" + route.params.messageId
    }

    async function pullFile(item) {
      formError.value = ""
      busy.value = true
      try {
        const saved = await api(
          path() + "/attachments/" + encodeURIComponent(item.section),
          { method: "POST" }
        )
        item.file_id = saved.file_id
        downloadFile(saved.file_id)
      } catch (err) {
        formError.value = err.message || "Вложение не скачалось"
      } finally {
        busy.value = false
      }
    }

    async function load() {
      error.value = ""
      try {
        await settings.load(props.project && props.project.id).catch(() => {})
        const data = await api("/api/projects?include_archived=false")
        projects.value = data.items || []
        if (props.project && props.project.id) folderProject.value = String(props.project.id)
        message.value = await api(path())
      } catch (err) {
        message.value = null
        error.value = err.message || "Письмо недоступно"
      }
    }

    async function patch(body) {
      const previous = { ...message.value }
      message.value = { ...message.value, ...body }
      try {
        message.value = await api(path(), {
          method: "PATCH",
          body,
        })
      } catch (err) {
        message.value = previous
        notice.show("Не удалось изменить письмо. " + (err.message || "Ошибка"))
      }
    }

    function toggleRead() {
      patch({ read: !message.value.read })
    }

    function toggleArchive() {
      patch({ archived: !message.value.archived })
    }

    async function toggleTag(tag, on) {
      const previous = ((message.value && message.value.tags) || []).slice()
      if (on) message.value.tags = previous.concat([{ id: tag.id, name: tag.name, color: tag.color }])
      else message.value.tags = previous.filter((row) => row.id !== tag.id)
      formError.value = ""
      try {
        const updated = await api("/api/mail/messages/" + message.value.id + "/tags", {
          method: "POST",
          body: { tag_id: tag.id, on },
        })
        message.value = { ...message.value, tags: updated.tags || [] }
      } catch (err) {
        message.value.tags = previous
        formError.value = err.message || "Хештег не изменился"
      }
    }

    async function remove() {
      if (!window.confirm("Удалить письмо?")) return
      busy.value = true
      try {
        await api(path(), { method: "DELETE" })
        router.push(props.project ? "/projects/" + props.project.id + "/mail" : "/mail")
      } catch (err) {
        formError.value = err.message || "Не удалось удалить"
        busy.value = false
      }
    }

    async function place(move) {
      formError.value = ""
      busy.value = true
      try {
        const data = await api(path() + "/folder", { method: "POST", body: { project_id: Number(folderProject.value), move } })
        notice.show((move ? "Переместили в папку " : "Скопировали в папку ") + (data.folder || ""))
      } catch (err) {
        formError.value = err.message || "Папка не обновилась"
      } finally {
        busy.value = false
      }
    }

    watch(() => [props.project && props.project.id, route.params.messageId], load, { immediate: true })

    return { message, projects, folderProject, error, formError, busy, fromLine, fromLineOf, frameHtml, tagStyle, threadLink, when, toggleRead, toggleArchive, toggleTag, remove, pullFile, place }
  },
}
</script>
