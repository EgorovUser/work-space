<template>
  <AppShell>
    <div class="page-head">
      <div>
        <h1>Корзина</h1>
        <p class="muted">Удалённое хранится {{ retentionDays }} дней, потом чистится окончательно.</p>
      </div>
      <button v-if="groups.length" class="btn danger" type="button" :disabled="busy === 'all'" @click="purgeAll">
        Очистить всё
      </button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="4" />
    <div v-else-if="!groups.length" class="empty">
      <strong>Корзина пуста</strong>
      <span>Удалите задачу, документ, секрет или RDP-подключение — оно появится здесь.</span>
    </div>

    <template v-else>
      <section v-for="group in groups" :key="group.id" class="card">
        <h2>{{ group.label }} <span class="pill">{{ group.items.length }}</span></h2>
        <div v-for="item in group.items" :key="group.id + '-' + item.id" class="status-row">
          <div>
            <strong>{{ item.title }}</strong>
            <div class="muted">
              {{ item.project_name || "без проекта" }} · {{ when(item.deleted_at) }}
            </div>
          </div>
          <div class="row-actions">
            <span class="pill" :class="item.days_left <= 7 ? 'warn' : ''" :title="'Хранится ещё ' + item.days_left + ' дн.'">осталось {{ item.days_left }} дн.</span>
            <button class="btn secondary" type="button" :disabled="busy === group.id + '-' + item.id" @click="restore(group, item)">
              Восстановить
            </button>
            <button class="btn danger" type="button" :disabled="busy === group.id + '-' + item.id" @click="purge(group, item)">
              Удалить навсегда
            </button>
          </div>
        </div>
      </section>
    </template>
  </AppShell>
</template>

<script>
import { onMounted, ref } from "vue"
import AppShell from "../components/AppShell.vue"
import SkeletonList from "../components/SkeletonList.vue"
import { api } from "../api"
import { useNotice } from "../composables/useNotice"
import { useWhen } from "../composables/useWhen"

// Корзина (патч N): мягко удалённые записи всех модулей одним экраном.
// Восстановление возвращает запись в её модуль; «Удалить навсегда»
// вычищает безвозвратно — с подтверждением. Патч P: у каждой записи —
// сколько дней осталось до автоочистки, и «Очистить всё» одним махом.
export default {
  components: { AppShell, SkeletonList },
  setup() {
    const groups = ref([])
    const retentionDays = ref(30)
    const loading = ref(true)
    const error = ref("")
    const busy = ref("")
    const notice = useNotice()
    const { when } = useWhen()

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const data = await api("/api/trash")
        groups.value = data.groups || []
        retentionDays.value = Number(data.retention_days) || 30
      } catch (err) {
        groups.value = []
        error.value = err.message || "Корзина недоступна"
      } finally {
        loading.value = false
      }
    }

    function drop(group, item) {
      group.items = group.items.filter((row) => row.id !== item.id)
      if (!group.items.length) {
        groups.value = groups.value.filter((row) => row.id !== group.id)
      }
    }

    async function restore(group, item) {
      busy.value = group.id + "-" + item.id
      try {
        await api("/api/trash/" + group.id + "/" + item.id + "/restore", { method: "POST" })
        drop(group, item)
        notice.show("Восстановлено: " + item.title)
      } catch (err) {
        notice.show((err.message || "Ошибка") + " — обновите список")
        await load()
      } finally {
        busy.value = ""
      }
    }

    async function purge(group, item) {
      if (!window.confirm("Удалить «" + item.title + "» навсегда? Восстановить будет нельзя.")) return
      busy.value = group.id + "-" + item.id
      try {
        await api("/api/trash/" + group.id + "/" + item.id, { method: "DELETE" })
        drop(group, item)
        notice.show("Удалено навсегда")
      } catch (err) {
        notice.show((err.message || "Ошибка") + " — обновите список")
        await load()
      } finally {
        busy.value = ""
      }
    }

    async function purgeAll() {
      const total = groups.value.reduce((sum, group) => sum + group.items.length, 0)
      if (!window.confirm("Очистить корзину целиком — " + total + " записей? Восстановить будет нельзя.")) return
      busy.value = "all"
      try {
        const data = await api("/api/trash", { method: "DELETE" })
        notice.show("Корзина очищена: " + (data.purged || 0) + " записей")
      } catch (err) {
        notice.show((err.message || "Ошибка") + " — обновите список")
      } finally {
        busy.value = ""
        await load()
      }
    }

    onMounted(load)
    return { groups, retentionDays, loading, error, busy, when, restore, purge, purgeAll }
  },
}
</script>
