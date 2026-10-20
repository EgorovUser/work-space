<template>
  <section class="card stack tp-time">
    <div class="row-actions tp-time-head">
      <h2>Списать время</h2>
      <span class="muted" title="Все записи по этой задаче">Всего: {{ formatHoursCompact(task.spent_minutes) }}</span>
    </div>
    <div class="row-actions">
      <label class="tight">
        Часы
        <input v-model.number="spent.hours" type="number" min="0" step="0.25" inputmode="decimal" required />
      </label>
      <label class="tight">
        Дата
        <input v-model="spent.day" type="date" />
      </label>
      <label class="tight tp-time-note">
        Заметка
        <input v-model="spent.note" type="text" />
      </label>
    </div>
    <p v-if="timeError" class="error">{{ timeError }}</p>
    <div class="row-actions">
      <button class="btn" type="button" :disabled="busy" @click="logTime">Списать</button>
      <button class="btn secondary" type="button" :disabled="busy" @click="startOnTask">Старт таймера</button>
    </div>
    <p v-if="!timeEntries.length" class="muted">По этой задаче записей пока нет — списанное время появится здесь и в разделе «Учёт времени».</p>
    <div v-for="item in timeEntries" :key="item.id" class="inbox-row">
      <div>{{ item.running ? "Идёт" : formatDuration(item.minutes) }}<span v-if="item.note"> · {{ item.note }}</span></div>
      <span class="when">{{ when(item.started_at) }}</span>
      <span></span>
    </div>
  </section>
</template>

<script>
import { reactive, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { api } from "../../api"
import { formatDuration, formatHoursCompact, hoursToMinutes } from "../../composables/timeFormat"
import { useNotice } from "../../composables/useNotice"
import { usePomodoro } from "../../composables/usePomodoro"
import { useRunningTimer } from "../../composables/useRunningTimer"
import { useWhen } from "../../composables/useWhen"

// Блок «Списать время» на вкладке «О задаче» (патч R, вынесен из TaskPage
// в патче X). Меняет переданный объект задачи на месте — это элемент
// реактивного массива родителя, итог «Всего» растёт сразу после списания.
export default {
  props: {
    project: { type: Object, required: true },
    task: { type: Object, required: true },
  },
  setup(props) {
    const route = useRoute()
    const notice = useNotice()
    const { when, localDay } = useWhen()
    const busy = ref(false)
    const timeEntries = ref([])
    const timeError = ref("")
    // Один активный фокус (патч AL): таймер по задаче тоже гасит помодоро
    // и сообщает рельсе о себе сразу.
    const pomo = usePomodoro()
    const focus = useRunningTimer()
    // Ввод в часах (патч R): «1.5» — полтора часа; в API уходят минуты.
    const spent = reactive({ day: localDay(), hours: 1, note: "" })

    async function loadTime() {
      timeError.value = ""
      try {
        const data = await api("/api/projects/" + props.project.id + "/time")
        const id = Number(route.params.taskId)
        timeEntries.value = (data.entries || []).filter((item) => Number(item.task_id) === id)
      } catch (err) {
        timeError.value = err.message || "Время недоступно"
      }
    }

    async function logTime() {
      if (busy.value) return
      const minutes = hoursToMinutes(spent.hours)
      if (!minutes) {
        timeError.value = "Введите часы, например 1.5 — полтора часа"
        return
      }
      busy.value = true
      timeError.value = ""
      try {
        const entry = await api("/api/projects/" + props.project.id + "/time/entries", {
          method: "POST",
          body: {
            task_id: Number(route.params.taskId),
            minutes,
            day: spent.day,
            note: spent.note,
          },
        })
        const logged = Number(entry && entry.minutes) || minutes
        props.task.spent_minutes = (Number(props.task.spent_minutes) || 0) + logged
        spent.note = ""
        notice.show("Списано " + formatHoursCompact(logged) + " · «" + props.task.title + "»", { kind: "success" })
        await loadTime()
      } catch (err) {
        timeError.value = err.message || "Не записалось"
      } finally {
        busy.value = false
      }
    }

    async function startOnTask() {
      busy.value = true
      timeError.value = ""
      pomo.stop()
      try {
        await api("/api/projects/" + props.project.id + "/time/start", {
          method: "POST",
          body: { task_id: Number(route.params.taskId), note: spent.note },
        })
        notice.show("Таймер запущен по этой задаче", { kind: "success" })
        focus.refresh()
        await loadTime()
      } catch (err) {
        timeError.value = err.message || "Таймер не запустился"
      } finally {
        busy.value = false
      }
    }

    watch(
      () => route.params.taskId,
      () => {
        loadTime()
      },
      { immediate: true }
    )
    return { busy, timeEntries, timeError, spent, when, logTime, startOnTask, formatDuration, formatHoursCompact }
  },
}
</script>
