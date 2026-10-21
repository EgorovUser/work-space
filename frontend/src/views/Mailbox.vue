<template>
  <AppShell>
    <div class="page-head">
      <h1>Почта</h1>
      <p class="muted">
        <template v-if="sync && sync.automatic">Новые письма забираются сами, {{ everyLabel }}.</template>
        <template v-else>Автозабор выключен. Порцию можно забрать у ящика.</template>
      </p>
    </div>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'letters'">
      <div class="status-row mail-toolbar">
        <p class="muted">Непрочитанных: {{ unread }}</p>
        <button class="btn secondary" type="button" :disabled="busy || moreBusy" @click="load()">Обновить</button>
      </div>
      <form class="row-actions" @submit.prevent="search">
        <input v-model="query" type="text" placeholder="Тема, отправитель или текст письма" />
        <button class="btn secondary" type="submit">Показать</button>
      </form>
      <div v-if="tags.length" class="tag-row">
        <button type="button" class="mail-tag" :class="{ on: !activeTag }" @click="setTag(0)">Все</button>
        <button
          v-for="tag in tags"
          :key="tag.id"
          type="button"
          class="mail-tag"
          :class="{ on: activeTag === tag.id }"
          :style="tagStyle(tag, activeTag === tag.id)"
          @click="setTag(tag.id)"
        >{{ tag.name }}</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <!-- Список и читалка рядом: письмо открывается без ухода со страницы.
           Узкий экран — читалка занимает экран целиком, «К списку» возвращает. -->
      <div v-else class="mailbox-split" :class="{ 'with-detail': selectedId }">
        <div class="mailbox-list">
          <SkeletonList v-if="loading" :rows="6" />
          <div v-else-if="!messages.length" class="empty">
            <strong>{{ activeTag ? "Под этот хештег ничего не попало" : "Писем пока нет" }}</strong>
            <span v-if="!activeTag">Как только в подключённом ящике появятся письма, они возникнут здесь сами.</span>
          </div>
          <template v-else>
            <div class="list">
              <button
                v-for="item in messages"
                :key="item.id"
                type="button"
                class="mail-row"
                :class="{ active: item.id === selectedId }"
                :aria-current="item.id === selectedId ? 'true' : null"
                @click="openMessage(item)"
              >
                <span class="mail-dot" :class="{ on: !item.read }" aria-hidden="true"></span>
                <span class="mail-row-body">
                  <span class="mail-row-title">
                    <strong :class="{ unread: !item.read }">{{ item.title }}</strong>
                    <span v-if="item.thread_count > 1" class="muted"> · {{ item.thread_count }} в переписке</span>
                  </span>
                  <span class="muted">{{ fromLine(item) }} · {{ when(item.received_at) }}<span v-if="item.thread_unread"> · непрочитанных {{ item.thread_unread }}</span><span v-if="item.attachment_count"> · вложения {{ item.attachment_count }}</span></span>
                  <span v-if="item.preview" class="mail-row-snippet">{{ item.preview }}</span>
                  <span v-if="item.tags && item.tags.length" class="tag-row">
                    <span v-for="tag in item.tags" :key="tag.id" class="mail-tag on" :style="tagStyle(tag, true)">{{ tag.name }}</span>
                  </span>
                </span>
              </button>
            </div>
            <div class="status-row">
              <p class="muted">Показано {{ messages.length }}</p>
              <button v-if="hasMore" class="btn secondary" type="button" :disabled="moreBusy" @click="loadMore">{{ moreBusy ? "Загружаем…" : "Показать ещё" }}</button>
            </div>
          </template>
        </div>
        <section v-if="selectedId" class="mailbox-detail" aria-label="Открытое письмо">
          <MailReader
            :key="selectedId"
            :message-id="selectedId"
            :neighbors="rowNeighbors"
            closable
            @select="openById"
            @close="closeDetail"
            @changed="applyReaderChange"
            @removed="removeSelectedRow"
          />
        </section>
      </div>
    </div>
    <div v-show="tab === 'tags'">
      <MailTags :tags="tags" :fields="tagFields" :ops="tagOps" :default-color="tagDefaultColor" @changed="load" @done="tab = 'letters'" />
    </div>
    <div v-show="tab === 'notify'">
      <MailNotify :tags="tags" :meta="notifyMeta" />
    </div>
    <div v-show="tab === 'accounts'">
      <MailAccounts :accounts="accounts" @changed="load" />
    </div>
  </AppShell>
</template>

<script>
import { computed, reactive, ref, onBeforeUnmount, onMounted, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import AppShell from "../components/AppShell.vue"
import Tabs from "../components/Tabs.vue"
import SkeletonList from "../components/SkeletonList.vue"
import MailReader from "../components/MailReader.vue"
import MailAccounts from "../components/mail/MailAccounts.vue"
import MailNotify from "../components/mail/MailNotify.vue"
import MailTags from "../components/mail/MailTags.vue"
import { api } from "../api"
import { useEvents } from "../composables/useEvents"
import { tagStyle } from "../composables/mailTagStyle"
import { fromLine } from "../composables/mailFormat"
import { neighbors } from "../composables/mailNav"
import { useWhen } from "../composables/useWhen"

// Почта: список слева, читалка справа, письмо — в маршруте. Второстепенные
// вкладки (хештеги, уведомления, ящик) вынесены в компоненты mail/
// (патч X) — этот файл отвечает за список, читалку и живые события.
const TAB_IDS = new Set(["letters", "tags", "notify", "accounts"])

export default {
  components: { AppShell, Tabs, SkeletonList, MailReader, MailAccounts, MailNotify, MailTags },
  setup() {
    const route = useRoute()
    const router = useRouter()
    const accounts = ref([])
    const messages = ref([])
    const error = ref("")
    const sync = ref(null)
    const busy = ref(false)
    const loading = ref(true)
    const unread = ref(0)
    const moreBusy = ref(false)
    const hasMore = ref(false)
    const page = reactive({ offset: 0, limit: 100 })
    // Вкладка/поиск/хештег живут в URL: возврат из письма, F5 и прямые ссылки
    // не сбрасывают то, что пользователь уже настроил.
    const query = ref(typeof route.query.q === "string" ? route.query.q : "")
    const tab = ref(TAB_IDS.has(String(route.query.tab)) ? String(route.query.tab) : "letters")
    const activeTag = ref(Number(route.query.tag) || 0)
    const tags = ref([])
    // Каталоги для вкладок хештегов и уведомлений: приходят с общим ответом
    // /api/mail и раздаются дочерним компонентам пропсами.
    const tagFields = ref([])
    const tagOps = ref([])
    const tagDefaultColor = ref("")
    const notifyMeta = ref(null)
    const pageTabs = [
      { id: "letters", label: "Письма" },
      { id: "tags", label: "Хештеги" },
      { id: "notify", label: "Уведомления" },
      { id: "accounts", label: "Ящик" },
    ]
    const { settings, when } = useWhen()
    let firstLoad = true

    // Выбранное письмо живёт в маршруте /mail/:id — deep-link, «назад» и
    // Esc работают, а список слева никуда не девается.
    const selectedId = computed(() => {
      const value = Number(route.params.messageId)
      return value > 0 ? value : null
    })
    const rowNeighbors = computed(() => neighbors(messages.value, selectedId.value))

    const everyLabel = computed(() => {
      const value = Number(sync.value && sync.value.every_seconds) || 0
      if (!value) return ""
      if (value % 60 === 0) return "каждые " + value / 60 + " мин."
      return "каждые " + value + " с."
    })

    function syncUrl() {
      const next = {}
      if (tab.value !== "letters") next.tab = tab.value
      if (query.value.trim()) next.q = query.value.trim()
      if (activeTag.value) next.tag = String(activeTag.value)
      router.replace({ query: next }).catch(() => {})
    }

    async function load(append = false) {
      if (firstLoad) loading.value = true
      error.value = ""
      const params = new URLSearchParams()
      if (query.value.trim()) params.set("q", query.value.trim())
      if (activeTag.value) params.set("tag", String(activeTag.value))
      if (append) params.set("offset", String(page.offset))
      try {
        const data = await api("/api/mail?" + params.toString())
        accounts.value = data.accounts || []
        if (append) {
          const seen = new Set(messages.value.map((item) => item.id))
          messages.value = messages.value.concat((data.messages || []).filter((item) => !seen.has(item.id)))
        } else {
          messages.value = data.messages || []
        }
        sync.value = data.sync || null
        tags.value = data.tags || []
        tagFields.value = data.tag_fields || []
        tagOps.value = data.tag_ops || []
        tagDefaultColor.value = data.tag_default_color || ""
        notifyMeta.value = data.notify || null
        unread.value = data.unread || 0
        if (data.page) {
          page.offset = Number(data.page.offset) || 0
          page.limit = Number(data.page.limit) || page.limit
        }
        hasMore.value = (data.messages || []).length >= page.limit
        // Патч AI: без подключённых ящиков больше не прыгаем на вкладку
        // «Ящик» — базовое окно почты всегда открывается на «Письма».
        // Подключить ящик можно осознанно: вкладка рядом, и пустое
        // состояние списка само подсказывает, откуда берутся письма.
      } catch (err) {
        error.value = err.message || "Почта недоступна"
      } finally {
        firstLoad = false
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

    function setTag(id) {
      activeTag.value = id
      syncUrl()
      load().catch(() => {})
    }

    async function search() {
      syncUrl()
      await load()
    }

    function openMessage(item) {
      if (item.id === selectedId.value) return
      openById(item.id)
    }

    function openById(id) {
      router.push("/mail/" + id).catch(() => {})
    }

    function closeDetail() {
      if (!route.params.messageId) return
      // Возврат на тот же фильтрованный список, без новой записи в истории.
      router.replace({ path: "/mail", query: route.query }).catch(() => {})
    }

    // Читалка доложила об изменении письма — строка списка обновляется
    // на месте, мгновенно (SSE-пересчёт подтянет остальное чуть позже).
    function applyReaderChange(updated) {
      if (!updated || !updated.id) return
      const row = messages.value.find((item) => item.id === updated.id)
      if (!row) return
      row.read = !!updated.read
      row.archived = !!updated.archived
      if (updated.tags) row.tags = updated.tags
    }

    function removeSelectedRow() {
      const id = selectedId.value
      if (id) messages.value = messages.value.filter((item) => item.id !== id)
      closeDetail()
    }

    // Esc закрывает письмо — но не отбирает его у поиска и полей ввода.
    function onKeydown(event) {
      if (event.key !== "Escape" || !selectedId.value) return
      const target = event.target
      if (target && target.closest && target.closest("input, textarea, select, [contenteditable='true'], .topbar-search")) return
      closeDetail()
    }

    watch(tab, syncUrl)

    // Глубокая ссылка на письмо всегда открывает вкладку писем,
    // даже если до этого открыли настройки ящика.
    watch(() => route.params.messageId, (value) => {
      if (value && tab.value !== "letters") tab.value = "letters"
    })

    // Живые события: счётчик непрочитанных — сразу из состояния канала,
    // а когда серверный забор приносит письма — список обновляется сам,
    // без F5. Изменение письма (прочитано, архив, удаление — в том числе
    // из другой вкладки) приходит событием mail.changed. Обновляем только
    // видимую вкладку: невидимой всё равно свежие данные подтянутся при
    // возврате.
    const events = useEvents()
    let syncTimer = null
    let changedTimer = null
    const offUnread = watch(events.mailUnread, (value) => {
      if (typeof value === "number") unread.value = value
    })
    const offEvents = events.on((type) => {
      if (type === "mail.sync") {
        if (typeof document !== "undefined" && document.visibilityState !== "visible") return
        if (syncTimer) clearTimeout(syncTimer)
        syncTimer = setTimeout(() => {
          syncTimer = null
          if (tab.value === "letters") load()
        }, 800)
        return
      }
      if (type !== "mail.changed") return
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return
      if (changedTimer) clearTimeout(changedTimer)
      changedTimer = setTimeout(() => {
        changedTimer = null
        if (tab.value === "letters") load()
      }, 600)
    })
    onBeforeUnmount(() => {
      offUnread()
      offEvents()
      if (syncTimer) clearTimeout(syncTimer)
      if (changedTimer) clearTimeout(changedTimer)
      window.removeEventListener("keydown", onKeydown)
    })

    onMounted(() => {
      settings.load().catch(() => {})
      load()
      window.addEventListener("keydown", onKeydown)
    })

    return {
      accounts, messages, sync, error, busy, loading, unread, moreBusy, hasMore, everyLabel,
      query, tab, pageTabs,
      tags, tagFields, tagOps, tagDefaultColor, notifyMeta, activeTag,
      when, fromLine, tagStyle, load, loadMore, search, setTag,
      selectedId, rowNeighbors, openMessage, openById, closeDetail, applyReaderChange, removeSelectedRow,
    }
  },
}
</script>
