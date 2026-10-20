<template>
  <div>
    <h1>Учёт времени</h1>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <section v-show="tab === 'timer'" class="card stack">
      <div class="timer-line">
        <strong v-if="running" class="timer-elapsed">{{ elapsed(running.started_at) }}</strong>
        <strong v-else>Таймер остановлен</strong>
        <span v-if="running && running.task_title" class="muted">{{ running.task_title }}</span>
        <span v-if="running && running.note" class="muted">{{ running.note }}</span>
      </div>
      <p v-if="elsewhere" class="banner">
        Таймер уже идёт в другом проекте. Новый старт остановит его, если это разрешено настройкой.
      </p>
      <label>
        Задача
        <select v-model="draft.task_id">
          <option value="">Без задачи</option>
          <option v-for="task in tasks" :key="task.id" :value="String(task.id)">{{ task.title }}</option>
        </select>
      </label>
      <label>
        Заметка
        <input v-model="draft.note" type="text" />
      </label>
      <p v-if="timerError" class="error">{{ timerError }}</p>
      <div class="row-actions">
        <button v-if="!running" class="btn" type="button" :disabled="busy" @click="start">Старт</button>
        <button v-else class="btn" type="button" :disabled="busy" @click="stop">Стоп</button>
      </div>
    </section>

    <section v-show="tab === 'report'" class="card">
      <div class="row-actions">
        <label class="tight">
          Период
          <select v-model="days" @change="load">
            <option value="7">Неделя</option>
            <option value="14">Две недели</option>
            <option value="30">Месяц</option>
            <option value="90">Квартал</option>
          </select>
        </label>
        <p class="muted">Сегодня {{ report ? formatDuration(report.today_minutes) : "—" }}, неделя {{ report ? formatDuration(report.week_minutes) : "—" }}</p>
      </div>
      <div v-if="report && report.chart" class="chart-box">
        <TimeChart :chart="report.chart" />
      </div>
      <p v-if="report && isEmptyPeriod" class="muted">За выбранный период записей нет. Запустите таймер на вкладке «Таймер» или добавьте запись вручную на вкладке «Записи».</p>
      <ul v-if="report && report.by_task.length" class="plain-list">
        <li v-for="item in report.by_task" :key="item.task_id || 'none'">
          {{ item.title }} — {{ formatDuration(item.minutes) }}
        </li>
      </ul>
    </section>

    <div v-show="tab === 'log'">
    <form class="card stack" @submit.prevent="addManual">
      <h2>Записать вручную</h2>
      <label>
        Дата
        <input v-model="manual.day" type="date" required />
      </label>
      <label>
        Часы
        <input v-model.number="manual.hours" type="number" min="0" step="0.25" inputmode="decimal" required />
      </label>
      <label>
        Задача
        <select v-model="manual.task_id">
          <option value="">Без задачи</option>
          <option v-for="task in tasks" :key="task.id" :value="String(task.id)">{{ task.title }}</option>
        </select>
      </label>
      <label>
        Заметка
        <input v-model="manual.note" type="text" />
      </label>
      <p v-if="formError" class="error">{{ formError }}</p>
      <div class="row-actions">
        <button class="btn" type="submit" :disabled="busy">Добавить</button>
      </div>
    </form>

    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="4" />
    <div v-else-if="!entries.length" class="empty">
      <strong>Записей за период нет</strong>
      <span>Измените период выше или добавьте первую запись формой.</span>
    </div>
    <div v-else class="stack">
      <article v-for="item in entries" :key="item.id" class="card">
        <div class="status-row">
          <div>
            <strong>{{ item.running ? "Идёт" : formatDuration(item.minutes) }}</strong>
            <div class="muted">
              {{ when(item.started_at) }}<span v-if="item.ended_at"> — {{ when(item.ended_at) }}</span>
            </div>
            <div v-if="item.task_title">{{ item.task_title }}</div>
            <div v-if="item.note">{{ item.note }}</div>
          </div>
          <div class="row-actions">
            <button class="btn secondary" type="button" :disabled="busy" @click="beginEdit(item)">Изменить</button>
            <button class="btn secondary" type="button" :disabled="busy" @click="remove(item)">Удалить</button>
          </div>
        </div>
        <form v-if="edit && edit.id === item.id" class="stack" @submit.prevent="saveEdit">
          <label v-if="!item.running">
            Часы
            <input v-model.number="edit.hours" type="number" min="0" step="0.25" inputmode="decimal" />
          </label>
          <label>
            Заметка
            <input v-model="edit.note" type="text" />
          </label>
          <label>
            Задача
            <select v-model="edit.task_id">
              <option value="">Без задачи</option>
              <option v-for="task in tasks" :key="task.id" :value="String(task.id)">{{ task.title }}</option>
            </select>
          </label>
          <p v-if="editError" class="error">{{ editError }}</p>
          <div class="row-actions">
            <button class="btn" type="submit" :disabled="busy">Сохранить</button>
            <button class="btn secondary" type="button" @click="edit = null">Отмена</button>
          </div>
        </form>
      </article>
    </div>
    </div>
  </div>
</template>

<script>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import TimeChart from "../components/TimeChart.vue"
import SkeletonList from "../components/SkeletonList.vue"
import Tabs from "../components/Tabs.vue"
import { api } from "../api"
import { formatDuration, hoursToMinutes } from "../composables/timeFormat"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { useSoftDelete } from "../composables/useSoftDelete"
import { usePomodoro } from "../composables/usePomodoro"
import { useRunningTimer } from "../composables/useRunningTimer"

export default {
  components: { Tabs, TimeChart, SkeletonList },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const running = ref(null)
    const elsewhere = ref(null)
    const entries = ref([])
    const report = ref(null)
    const tasks = ref([])
    const error = ref("")
    const timerError = ref("")
    const formError = ref("")
    const editError = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const tick = ref(0)
    const { settings, when, localDay } = useWhen()
    const draft = ref({ note: "", task_id: "" })
    // Ручная запись вводится в часах (патч R): «1.5» превращается в 90 минут.
    const manual = ref({ day: localDay(), hours: 1, note: "", task_id: "" })
    const edit = ref(null)
    const notice = useNotice()
    const { softRemove } = useSoftDelete()
    // Один активный фокус (патч AL): старт серверного таймера гасит
    // помодоро, а рельса узнаёт о новом таймере сразу, не дожидаясь опроса.
    const pomo = usePomodoro()
    const focus = useRunningTimer()
    const tab = ref("timer")
    const days = ref(14)
    const pageTabs = [
      { id: "timer", label: "Таймер" },
      { id: "report", label: "Отчёт" },
      { id: "log", label: "Записи" },
    ]
    let clock = null
    let refreshTimer = null

    const isEmptyPeriod = computed(() => {
      const rep = report.value
      if (!rep) return false
      const hasHours = rep.chart && Array.isArray(rep.chart.hours) && rep.chart.hours.some((value) => Number(value) > 0)
      return !hasHours && !(rep.by_task && rep.by_task.length)
    })

    function elapsed(started) {
      tick.value
      const sec = Math.max(0, Math.floor((Date.now() - new Date(started).getTime()) / 1000))
      const hours = String(Math.floor(sec / 3600)).padStart(2, "0")
      const mins = String(Math.floor((sec % 3600) / 60)).padStart(2, "0")
      const secs = String(sec % 60).padStart(2, "0")
      return hours + ":" + mins + ":" + secs
    }

    function taskBody(value) {
      if (!value) return null
      const number = Number(value)
      return Number.isFinite(number) ? number : null
    }

    async function loadTasks() {
      try {
        const data = await api("/api/projects/" + props.project.id + "/tasks")
        tasks.value = data.items || []
      } catch {
        tasks.value = []
      }
    }

    async function load() {
      error.value = ""
      try {
        const data = await api("/api/projects/" + props.project.id + "/time?days=" + days.value)
        running.value = data.running
        elsewhere.value = data.running_elsewhere
        entries.value = data.entries || []
        report.value = data.report
      } catch (err) {
        error.value = err.message || "Учёт недоступен"
      } finally {
        loading.value = false
        arm()
      }
    }

    function arm() {
      clearInterval(refreshTimer)
      refreshTimer = null
      const seconds = Number(settings.get("timetracking", "timer.page_refresh_seconds")) || 0
      if (seconds > 0 && running.value) {
        refreshTimer = setInterval(load, seconds * 1000)
      }
    }

    async function start() {
      const previous = running.value
      const note = draft.value.note
      const task = tasks.value.find((item) => String(item.id) === String(draft.value.task_id))
      pomo.stop()
      running.value = {
        started_at: new Date().toISOString(),
        note,
        task_title: task ? task.title : "",
      }
      draft.value.note = ""
      try {
        await api("/api/projects/" + props.project.id + "/time/start", {
          method: "POST",
          body: { note, task_id: taskBody(draft.value.task_id) },
        })
        notice.show("Таймер запущен" + (task ? " · " + task.title : ""), { kind: "success" })
      } catch (err) {
        running.value = previous
        draft.value.note = note
        notice.show("Не удалось запустить таймер. " + (err.message || "Ошибка"))
        return
      }
      focus.refresh()
      try {
        await load()
      } catch {
        // таймер уже запущен, список подтянется следующим обновлением
      }
    }

    async function stop() {
      const previous = running.value
      running.value = null
      try {
        const stopped = await api("/api/projects/" + props.project.id + "/time/stop", { method: "POST" })
        notice.show("Таймер остановлен · " + formatDuration(stopped.minutes), { kind: "success" })
      } catch (err) {
        running.value = previous
        notice.show("Не удалось остановить таймер. " + (err.message || "Ошибка"))
        return
      }
      focus.refresh()
      try {
        await load()
      } catch {
        // таймер уже остановлен
      }
    }

    async function addManual() {
      formError.value = ""
      const minutes = hoursToMinutes(manual.value.hours)
      if (!minutes) {
        formError.value = "Введите часы, например 1.5 — полтора часа"
        return
      }
      busy.value = true
      try {
        const entry = await api("/api/projects/" + props.project.id + "/time/entries", {
          method: "POST",
          body: {
            day: manual.value.day,
            minutes,
            note: manual.value.note,
            task_id: taskBody(manual.value.task_id),
          },
        })
        manual.value.note = ""
        const logged = Number(entry && entry.minutes) || minutes
        notice.show("Запись добавлена · " + formatDuration(logged), { kind: "success" })
        await load()
      } catch (err) {
        formError.value = err.message || "Не записалось"
      } finally {
        busy.value = false
      }
    }

    function beginEdit(item) {
      editError.value = ""
      edit.value = {
        id: item.id,
        // Правка тоже в часах: минуты записи возвращаются в поле дробью.
        hours: Math.round((Number(item.minutes) / 60) * 100) / 100,
        note: item.note,
        task_id: item.task_id ? String(item.task_id) : "",
        running: item.running,
      }
    }

    async function saveEdit() {
      editError.value = ""
      const body = { note: edit.value.note, task_id: taskBody(edit.value.task_id) }
      if (!edit.value.running) {
        const minutes = hoursToMinutes(edit.value.hours)
        if (!minutes) {
          editError.value = "Введите часы, например 1.5 — полтора часа"
          return
        }
        body.minutes = minutes
      }
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/time/entries/" + edit.value.id, {
          method: "PATCH",
          body,
        })
        edit.value = null
        notice.show("Запись сохранена", { kind: "success" })
        await load()
      } catch (err) {
        editError.value = err.message || "Не сохранилось"
      } finally {
        busy.value = false
      }
    }

    async function remove(item) {
      // Записи времени удаляются окончательно — без корзины и отката.
      await softRemove({
        confirm: "Удалить запись?",
        url: "/api/projects/" + props.project.id + "/time/entries/" + item.id,
        doneText: "Запись " + (item.running ? "таймера" : formatDuration(item.minutes)) + " удалена",
        onDone: load,
        onError: (err) => {
          error.value = err.message || "Не удалось удалить"
        },
      })
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).catch(() => {}).finally(() => {
        loadTasks()
        load()
      })
    }, { immediate: true })

    clock = setInterval(() => { tick.value += 1 }, 1000)
    onBeforeUnmount(() => {
      clearInterval(clock)
      clearInterval(refreshTimer)
    })

    return {
      running, elsewhere, entries, report, tasks, error, timerError, formError, editError,
      loading, busy, draft, manual, edit, tab, days, pageTabs, isEmptyPeriod,
      when, formatDuration, elapsed, start, stop, addManual, beginEdit, saveEdit, remove,
    }
  },
}
</script>
