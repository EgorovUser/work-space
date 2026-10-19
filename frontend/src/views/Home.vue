<template>
  <AppShell>
    <div class="page-head">
      <h1>Состояние</h1>
      <button class="btn" type="button" :disabled="busy" @click="check">{{ busy ? "Проверяю…" : "Проверить" }}</button>
    </div>
    <p v-if="checkedAt" class="muted">Проверено {{ when(checkedAt) }}. Кнопка заново открывает базу, файлы, почту, бота и почту уведомлений. Если сломалось что-то кроме самих уведомлений, сообщение придёт само.</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="busy && !checks.length" class="muted">Проверяю…</p>

    <section v-if="checks.length" class="card">
      <div class="status-row">
        <strong>Итог</strong>
        <span class="pill" :class="report.status">{{ statusLabel(report.status) }}</span>
      </div>
      <div v-for="item in checks" :key="item.id" class="status-row">
        <div>
          <div>{{ item.label }}</div>
          <div v-if="item.detail" class="muted">{{ item.detail }}</div>
          <div v-for="sub in item.items || []" :key="sub.name" class="muted">{{ sub.name }}: {{ sub.detail }}</div>
        </div>
        <span class="pill" :class="item.status">{{ statusLabel(item.status) }}</span>
      </div>
    </section>

    <section v-if="schedule.length" class="card">
      <h2>Расписание</h2>
      <div v-for="item in schedule" :key="item.id" class="status-row">
        <div>
          <div>{{ item.title }}</div>
          <div class="muted">{{ item.every }} — {{ item.action }}</div>
          <div v-if="item.next || item.finished_at || item.error" class="muted">
            <template v-if="item.next">{{ item.next }}</template>
            <template v-if="item.finished_at"> · последний {{ when(item.finished_at) }}</template>
            <span v-if="item.error"> — {{ item.error }}</span>
          </div>
        </div>
        <span class="pill" :class="item.status">{{ statusLabel(item.status) }}</span>
      </div>
    </section>
  </AppShell>
</template>

<script>
import { onMounted, ref } from "vue"
import AppShell from "../components/AppShell.vue"
import { api } from "../api"
import { useWhen } from "../composables/useWhen"

export default {
  components: { AppShell },
  setup() {
    const report = ref({ status: "" })
    const checks = ref([])
    const schedule = ref([])
    const checkedAt = ref("")
    const error = ref("")
    const busy = ref(false)
    const { settings, when } = useWhen()

    function statusLabel(status) {
      if (status === "ok") return "Ок"
      if (status === "warn") return "Внимание"
      if (status === "bad") return "Ошибка"
      if (status === "off") return "Выкл"
      return status || "…"
    }

    async function check() {
      busy.value = true
      error.value = ""
      try {
        const data = await api("/api/system/check", { method: "POST" })
        report.value = data
        checks.value = data.checks || []
        schedule.value = data.schedule || []
        checkedAt.value = data.checked_at || ""
      } catch (err) {
        error.value = err.message || "Проверка не выполнилась"
      } finally {
        busy.value = false
      }
    }

    onMounted(() => {
      settings.load().catch(() => {})
      check()
    })

    return { report, checks, schedule, checkedAt, error, busy, when, statusLabel, check }
  },
}
</script>
