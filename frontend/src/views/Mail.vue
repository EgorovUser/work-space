<template>
  <div>
    <p class="muted">Ящик общий на все проекты. Здесь только письма, которые подходят под фильтры этого проекта.</p>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'letters'">
        <form class="row-actions" @submit.prevent="load">
          <input v-model="query" type="text" placeholder="Тема, отправитель или текст письма" />
          <button class="btn secondary" type="submit">Показать</button>
        </form>
        <label class="check"><input v-model="unreadOnly" type="checkbox" @change="load" /><span>Только непрочитанные</span></label>
        <label class="check"><input v-model="includeArchived" type="checkbox" @change="load" /><span>Показать архив</span></label>
        <p v-if="error" class="error">{{ error }}</p>
        <SkeletonList v-else-if="loading" :rows="4" />
        <div v-else-if="!rules.length" class="empty">
          <strong>Писем по фильтрам пока нет</strong>
          <span>Фильтров нет, поэтому письма этого проекта не видны. Добавьте фильтр на вкладке «Фильтры» — в список попадут только подходящие.</span>
        </div>
        <div v-else-if="!messages.length" class="empty">
          <strong>Под текущие фильтры ничего не попало</strong>
          <span>Попробуйте ослабить условия фильтров или снять «Только непрочитанные».</span>
        </div>
        <div v-else class="card">
          <div v-for="item in messages" :key="item.id" class="status-row">
            <div>
              <router-link :class="{ unread: !item.read }" :to="'/projects/' + project.id + '/mail/' + item.id">{{ item.title }}</router-link>
              <span v-if="item.thread_count > 1" class="muted"> · {{ item.thread_count }} в переписке</span>
              <div class="muted">{{ fromLine(item) }} · {{ when(item.received_at) }}<span v-if="item.attachment_count"> · вложения {{ item.attachment_count }}</span></div>
              <div v-if="item.preview" class="snippet">{{ item.preview }}</div>
            </div>
          </div>
        </div>
        <div v-if="messages.length" class="status-row">
          <p class="muted">Показано {{ messages.length }}</p>
          <button v-if="hasMore" class="btn secondary" type="button" :disabled="moreBusy" @click="loadMore">{{ moreBusy ? "Загружаем…" : "Показать ещё" }}</button>
        </div>
      </div>
      <div v-show="tab === 'rules'">
        <p class="muted">Письмо сохраняется всегда, само, порциями. Фильтр решает только одно: это письмо этого проекта, и его надо перенести в папку «{{ project.name }}».</p>
        <form class="card stack" @submit.prevent="createRule">
          <h2>Фильтр</h2>
          <label>Название <input v-model="rule.name" type="text" required /></label>
          <label>
            Поле
            <select v-model="rule.field">
              <option v-for="item in fields" :key="item.id" :value="item.id">{{ item.label }}</option>
            </select>
          </label>
          <label>
            Условие
            <select v-model="rule.op">
              <option v-for="item in ops" :key="item.id" :value="item.id">{{ item.label }}</option>
            </select>
          </label>
          <label>Значение <input v-model="rule.value" type="text" required /></label>
          <p v-if="ruleError" class="error">{{ ruleError }}</p>
          <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Добавить фильтр</button></div>
        </form>
        <div v-if="rules.length" class="card">
          <div v-for="item in rules" :key="item.id" class="status-row">
            <div>
              <strong>{{ item.name }}</strong>
              <div class="muted">{{ item.field_label }} {{ item.op_label }} «{{ item.value }}»</div>
            </div>
            <button class="btn secondary" type="button" :disabled="busy" @click="removeRule(item)">Удалить</button>
          </div>
        </div>
        <form class="card stack" @submit.prevent="importFile">
          <h2>Файл письма</h2>
          <label>Файл .eml <input type="file" @change="onFile" /></label>
          <p v-if="importError" class="error">{{ importError }}</p>
          <p v-if="importNote" class="ok-text">{{ importNote }}</p>
          <div class="row-actions"><button class="btn" type="submit" :disabled="busy">Загрузить</button></div>
        </form>
      </div>
  </div>
</template>

<script>
import { reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { api } from "../api"
import Tabs from "../components/Tabs.vue"
import SkeletonList from "../components/SkeletonList.vue"
import { useNotice } from "../composables/useNotice"
import { useSoftDelete } from "../composables/useSoftDelete"
import { fromLine } from "../composables/mailFormat"
import { useWhen } from "../composables/useWhen"

export default {
  components: { Tabs, SkeletonList },
  props: { project: { type: Object, required: true } },
  setup(props) {
    const route = useRoute()
    const router = useRouter()
    const notice = useNotice()
    const { softRemove } = useSoftDelete()
    const accounts = ref([])
    const rules = ref([])
    const messages = ref([])
    const fields = ref([])
    const ops = ref([])
    const error = ref("")
    const ruleError = ref("")
    const importError = ref("")
    const importNote = ref("")
    const loading = ref(true)
    const busy = ref(false)
    // Поиск и фильтры — в URL: возврат из письма не сбрасывает их.
    const query = ref(typeof route.query.q === "string" ? route.query.q : "")
    const unreadOnly = ref(route.query.unread === "true")
    const includeArchived = ref(route.query.archived === "true")
    const tab = ref(route.query.tab === "rules" ? "rules" : "letters")
    const moreBusy = ref(false)
    const hasMore = ref(false)
    const page = reactive({ offset: 0, limit: 100 })
    const pageTabs = [
      { id: "letters", label: "Письма" },
      { id: "rules", label: "Фильтры" },
    ]
    const file = ref(null)
    const rule = ref({ name: "", field: "from", op: "contains", value: "", action: "keep" })
    const { settings, when } = useWhen()

    function applyChoices(data) {
      fields.value = data.fields || []
      ops.value = data.ops || []
      if (!fields.value.some((item) => item.id === rule.value.field) && fields.value.length) rule.value.field = fields.value[0].id
      if (!ops.value.some((item) => item.id === rule.value.op) && ops.value.length) rule.value.op = ops.value[0].id
    }

    function syncUrl() {
      const next = {}
      if (tab.value !== "letters") next.tab = tab.value
      if (query.value.trim()) next.q = query.value.trim()
      if (unreadOnly.value) next.unread = "true"
      if (includeArchived.value) next.archived = "true"
      router.replace({ query: next }).catch(() => {})
    }

    async function load(append) {
      append = append === true
      loading.value = true
      error.value = ""
      try {
        const params = new URLSearchParams()
        if (unreadOnly.value) params.set("unread", "true")
        if (includeArchived.value) params.set("include_archived", "true")
        if (query.value) params.set("q", query.value)
        if (append) params.set("offset", String(page.offset))
        const data = await api("/api/projects/" + props.project.id + "/mail?" + params.toString())
        accounts.value = data.accounts || []
        rules.value = data.rules || []
        if (append) {
          const seen = new Set(messages.value.map((item) => item.id))
          messages.value = messages.value.concat((data.messages || []).filter((item) => !seen.has(item.id)))
        } else {
          messages.value = data.messages || []
        }
        if (data.page) {
          page.offset = Number(data.page.offset) || 0
          page.limit = Number(data.page.limit) || page.limit
        }
        hasMore.value = (data.messages || []).length >= page.limit
        applyChoices(data)
      } catch (err) {
        error.value = err.message || "Почта недоступна"
      } finally {
        loading.value = false
      }
    }

    async function loadMore() {
      if (moreBusy.value) return
      page.offset += page.limit
      moreBusy.value = true
      try {
        await load(true)
      } finally {
        moreBusy.value = false
      }
    }

    watch(tab, syncUrl)





    async function createRule() {
      ruleError.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/rules", { method: "POST", body: { ...rule.value } })
        rule.value.name = ""
        rule.value.value = ""
        notice.show("Правило добавлено", { kind: "success" })
        await load()
      } catch (err) {
        ruleError.value = err.message || "Не удалось добавить"
      } finally {
        busy.value = false
      }
    }

    async function removeRule(item) {
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/mail/rules/" + item.id, { method: "DELETE" })
        notice.show("Правило удалено", { kind: "success" })
        await load()
      } catch (err) {
        error.value = err.message || "Не удалось удалить"
      } finally {
        busy.value = false
      }
    }

    function onFile(event) {
      file.value = event.target.files && event.target.files[0]
    }

    async function importFile() {
      importError.value = ""
      importNote.value = ""
      if (!file.value) {
        importError.value = "Выберите файл"
        return
      }
      busy.value = true
      const body = new FormData()
      body.append("file", file.value)
      try {
        const data = await api("/api/projects/" + props.project.id + "/mail/import", { method: "POST", body })
        if (data.status === "duplicate") importNote.value = "Такое письмо уже есть"
        else importNote.value = "Письмо сохранено"
        await load()
      } catch (err) {
        importError.value = err.message || "Не загрузилось"
      } finally {
        busy.value = false
      }
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).catch(() => {}).finally(load)
    }, { immediate: true })

    return {
      accounts, rules, messages, fields, ops, error, ruleError, importError, importNote,
      loading, busy, query, unreadOnly, includeArchived, rule, tab, pageTabs, moreBusy, hasMore,
      when, fromLine, load, loadMore, createRule, removeRule, onFile, importFile,
    }
  },
}
</script>
