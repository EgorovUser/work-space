<template>
  <article v-if="message" class="card stack mail-reader">
    <div v-if="closable" class="mail-back-row">
      <button class="btn secondary mail-back" type="button" @click="emit('close')">← К списку писем</button>
    </div>
    <div v-if="neighbors && (neighbors.prev || neighbors.next)" class="mail-nav-row">
      <button
        class="btn secondary"
        type="button"
        :disabled="!neighbors.prev"
        :title="neighbors.prev ? neighbors.prev.title : ''"
        @click="neighbors.prev && emit('select', neighbors.prev.id)"
      >← Новее</button>
      <button
        class="btn secondary"
        type="button"
        :disabled="!neighbors.next"
        :title="neighbors.next ? neighbors.next.title : ''"
        @click="neighbors.next && emit('select', neighbors.next.id)"
      >Старее →</button>
    </div>
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
    <div v-if="message.html && hasImages" class="row-actions">
      <button class="btn secondary" type="button" @click="showImages = !showImages">
        {{ showImages ? "Скрыть картинки" : "Показать картинки" }}
      </button>
      <span class="muted">По умолчанию внешние картинки не грузятся: так письмо не сообщает отправителю, что вы его открыли.</span>
    </div>
    <iframe v-if="message.html" class="mail-frame" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" :srcdoc="frameHtml"></iframe>
    <pre v-else class="text-block">{{ message.body || "Текста нет" }}</pre>
    <ul v-if="message.attachments && message.attachments.length" class="plain-list">
      <li v-for="item in message.attachments" :key="item.section || item.filename">
        <a v-if="item.file_id" :href="'/api/files/' + item.file_id" download>{{ item.filename }}</a>
        <template v-else>
          <span>{{ item.filename }}</span>
          <button class="btn secondary" type="button" :disabled="busy || !item.section" @click="pullFile(item)">Скачать вложение</button>
        </template>
        <button
          class="btn secondary"
          type="button"
          :disabled="busy || savingDoc || !documentTarget"
          :title="documentTarget ? 'Документ создастся в проекте «' + documentTargetName + '»' : 'Выберите папку проекта ниже'"
          @click="saveToDocuments(item)"
        >→ В документы</button>
        <span v-if="item.size" class="muted"> · {{ formatSize(item.size) }}</span>
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
  <SkeletonList v-else-if="!error" :rows="4" />
  <p v-else class="error">{{ error }}</p>
</template>

<script>
import { computed, ref, watch } from "vue"
import { api, downloadFile } from "../api"
import SkeletonList from "./SkeletonList.vue"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { formatSize } from "../composables/formatBytes"

// Читалка письма. Живёт в двух местах: правая панель «Почты» (master-detail,
// там есть сосед-навигация и «К списку») и отдельная страница письма проекта.
// Навигацию после удаления решает родитель: читалка только сообщает
// («removed»), а сама никуда не уходит.
export default {
  components: { SkeletonList },
  props: {
    messageId: { type: Number, required: true },
    project: { type: Object, default: null },
    closable: { type: Boolean, default: false },
    neighbors: { type: Object, default: null },
  },
  emits: ["changed", "removed", "select", "close"],
  setup(props, { emit }) {
    const message = ref(null)
    const projects = ref([])
    const folderProject = ref("")
    const error = ref("")
    const formError = ref("")
    const busy = ref(false)
    const savingDoc = ref(false)
    const showImages = ref(false)
    const { settings, when } = useWhen()
    const notice = useNotice()

    const fromLine = computed(() => {
      const item = message.value
      if (!item) return ""
      if (item.from_name && item.from_addr) return item.from_name + " <" + item.from_addr + ">"
      return item.from_addr || item.from_name || ""
    })

    // Внешние картинки в письме — источник трекинг-пикселей: пока кнопка не
    // нажата, src вырезается и заменяется нейтральным заполнителем. Ссылки
    // открываются в новой вкладке (<base target="_blank"> + allow-popups),
    // иначе они заменяли письмо внутри рамки без пути назад.
    const hasImages = computed(() => {
      const html = message.value && message.value.html
      return Boolean(html && /<img\b/i.test(html))
    })

    const frameHtml = computed(() => {
      const html = message.value && message.value.html
      if (!html) return ""
      const style =
        "<style>img[data-blocked-src]{display:inline-block;min-width:28px;min-height:28px;background:#eef1f4;border:1px dashed #b7c0c8;border-radius:4px;vertical-align:middle}</style>"
      const head = '<!doctype html><html><head><meta charset="utf-8"><base target="_blank" rel="noopener noreferrer">' + style + "</head><body>"
      const body = showImages.value ? html : html.replace(/(<img\b[^>]*?)\ssrc\s*=\s*(["'])(https?:\/\/[^"']*)\2/gi, "$1 data-blocked-src=$2$3$2")
      return head + body + "</body></html>"
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
        return "/api/projects/" + props.project.id + "/mail/messages/" + props.messageId
      }
      return "/api/mail/messages/" + props.messageId
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

    // Куда ляжет документ из вложения: проект письма или выбранная папка.
    const documentTarget = computed(() => {
      if (props.project && props.project.id) return Number(props.project.id)
      const raw = message.value && message.value.project_id
      if (raw) return Number(raw)
      const picked = Number(folderProject.value)
      return picked || null
    })

    const documentTargetName = computed(() => {
      const id = documentTarget.value
      const found = projects.value.find((item) => item.id === id)
      return found ? found.name : ""
    })

    async function saveToDocuments(item) {
      if (!documentTarget.value) {
        formError.value = "Сначала выберите папку проекта для документа"
        return
      }
      formError.value = ""
      savingDoc.value = true
      try {
        let sectionPath = ""
        if (item.section) {
          sectionPath = "/attachments/" + encodeURIComponent(item.section)
        }
        const url =
          (props.project && props.project.id
            ? "/api/projects/" + props.project.id + "/mail/messages/" + props.messageId
            : "/api/mail/messages/" + props.messageId) + sectionPath + "/document"
        const body = props.project && props.project.id ? {} : { project_id: documentTarget.value }
        const created = await api(url, { method: "POST", body })
        notice.show("Документ создан: " + created.title)
        emit("changed")
      } catch (err) {
        formError.value = err.message || "Документ не создался"
      } finally {
        savingDoc.value = false
      }
    }

    async function load() {
      error.value = ""
      message.value = null
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
        emit("changed", message.value)
      } catch (err) {
        message.value = previous
        notice.show("Не удалось изменить письмо. " + (err.message || "Ошибка"))
      }
    }

    function toggleRead() {
      patch({ read: !message.value.read })
    }

    async function toggleArchive() {
      const before = message.value.archived
      await patch({ archived: !before })
      if (message.value.archived === before) return
      notice.show(before ? "Письмо возвращено из архива" : "Письмо в архиве", {
        kind: "success",
        action: { label: "Отменить", run: () => patch({ archived: before }) },
      })
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
        emit("changed", message.value)
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
        emit("removed", message.value && message.value.id)
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

    watch(() => [props.project && props.project.id, props.messageId], () => {
      showImages.value = false
      formError.value = ""
      load()
    }, { immediate: true })

    return { message, projects, folderProject, error, formError, busy, savingDoc, showImages, hasImages, fromLine, fromLineOf, frameHtml, tagStyle, threadLink, when, formatSize, toggleRead, toggleArchive, toggleTag, remove, pullFile, saveToDocuments, documentTarget, documentTargetName, place, emit }
  },
}
</script>
