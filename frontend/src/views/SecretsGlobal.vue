<template>
  <AppShell>
    <div class="page-head">
      <h1>Секреты</h1>
      <span class="muted">все проекты вместе</span>
    </div>

    <form class="row-actions" @submit.prevent="load">
      <input v-model="query" type="text" placeholder="Название" />
      <button class="btn secondary" type="submit" :disabled="loading">Показать</button>
    </form>
    <label class="check">
      <input v-model="includeArchived" type="checkbox" @change="load" />
      <span>Показать архив</span>
    </label>

    <p v-if="unavailable" class="banner">Модуль недоступен</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="5" />
    <div v-else-if="!groups.length" class="empty">
      <strong>Секретов пока нет</strong>
      <span>Здесь собираются секреты всех проектов. Добавьте первый в разделе «Секреты» любого проекта.</span>
    </div>
    <template v-else>
      <p v-if="truncated" class="muted">
        Показаны не все секреты (лимит {{ limit }}) — сузьте поиск или поднимите лимит в настройках.
      </p>
      <section v-for="group in groups" :key="group.project_id" class="card">
        <h2 class="group-head">
          <router-link :to="'/projects/' + group.project_id + '/secrets'">{{ group.project_name }}</router-link>
          <span class="muted">{{ group.items.length }}</span>
          <span v-if="group.project_archived" class="pill warn">Архив проекта</span>
        </h2>
        <div v-for="item in group.items" :key="item.id" class="status-row">
          <div>
            <router-link :to="'/projects/' + group.project_id + '/secrets/' + item.id">{{ item.title }}</router-link>
            <div class="muted">
              {{ item.kind_label || item.kind }}
              <span v-if="item.has_username"> · логин задан</span>
              <span v-if="item.has_secret"> · секрет задан</span>
              <span v-else> · секрета нет</span>
              <span v-if="item.archived"> · архив</span>
              · {{ when(item.updated_at) }}
            </div>
          </div>
          <ActionMenu :actions="rowActions(item)" @choose="onAction($event, item, group)" />
        </div>
      </section>
    </template>
  </AppShell>
</template>

<script>
import { onBeforeUnmount, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import AppShell from "../components/AppShell.vue"
import ActionMenu from "../components/ActionMenu.vue"
import SkeletonList from "../components/SkeletonList.vue"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"
import { useSettings } from "../composables/useSettings"
import { useWhen } from "../composables/useWhen"

const CLIPBOARD_TTL = 30

// Глобальный раздел «Секреты»: список по всем проектам, сгруппированный
// по проектам. Значения не ходят списком — только маскированные признаки;
// копирование логина и секрета идёт через существующие проектные
// эндпоинты (detail и reveal), буфер очищается через 30 секунд.
export default {
  components: { AppShell, ActionMenu, SkeletonList },
  setup() {
    const groups = ref([])
    const total = ref(0)
    const truncated = ref(false)
    const limit = ref(300)
    const error = ref("")
    const unavailable = ref(false)
    const loading = ref(true)
    const query = ref("")
    const includeArchived = ref(false)
    const router = useRouter()
    const settings = useSettings()
    const notice = useNotice()
    const { when } = useWhen()
    let clearTimer = null

    function rowActions(item) {
      const actions = [{ id: "open", label: "Открыть" }]
      if (item.has_username) actions.push({ id: "copy_login", label: "Копировать логин" })
      if (item.has_secret) actions.push({ id: "copy_secret", label: "Копировать секрет" })
      return actions
    }

    async function writeClipboard(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text)
        return
      }
      const area = document.createElement("textarea")
      area.value = text
      document.body.appendChild(area)
      area.select()
      document.execCommand("copy")
      area.remove()
    }

    async function copyValue(value) {
      await writeClipboard(value)
      notice.show("Скопировано. Буфер очистится через " + CLIPBOARD_TTL + " с.", { kind: "success" })
      clearTimeout(clearTimer)
      clearTimer = setTimeout(async () => {
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText("")
          }
        } catch {
          // Буфер мог быть перезаписан другой вкладкой — это нормальный исход.
        }
      }, CLIPBOARD_TTL * 1000)
    }

    async function copyLogin(item, group) {
      try {
        const data = await api("/api/projects/" + group.project_id + "/secrets/" + item.id)
        if (!data.username) {
          notice.show("У этого секрета нет логина")
          return
        }
        await copyValue(data.username)
      } catch (err) {
        notice.show("Не удалось скопировать логин. " + (err.message || "Ошибка"))
      }
    }

    async function copySecret(item, group) {
      try {
        const data = await api("/api/projects/" + group.project_id + "/secrets/" + item.id + "/reveal", {
          method: "POST",
        })
        await copyValue(data.secret || "")
      } catch (err) {
        notice.show("Не удалось скопировать секрет. " + (err.message || "Ошибка"))
      }
    }

    function onAction(action, item, group) {
      if (action === "open") router.push("/projects/" + group.project_id + "/secrets/" + item.id)
      if (action === "copy_login") copyLogin(item, group)
      if (action === "copy_secret") copySecret(item, group)
    }

    async function load() {
      loading.value = true
      error.value = ""
      unavailable.value = false
      try {
        const params = new URLSearchParams()
        if (includeArchived.value) params.set("include_archived", "true")
        if (query.value) params.set("q", query.value)
        const data = await api("/api/secrets?" + params.toString())
        groups.value = data.groups || []
        total.value = data.total || 0
        truncated.value = Boolean(data.truncated)
        limit.value = Number(settings.get("secrets", "list.global_limit")) || limit.value
      } catch (err) {
        groups.value = []
        if (err.status === 503) unavailable.value = true
        else error.value = err.message || "Список недоступен"
      } finally {
        loading.value = false
      }
    }

    onMounted(() => {
      settings.load().catch(() => {})
      load()
    })
    onBeforeUnmount(() => {
      clearTimeout(clearTimer)
    })
    return {
      groups, total, truncated, limit, error, unavailable, loading, query, includeArchived,
      when, rowActions, onAction, load,
    }
  },
}
</script>
