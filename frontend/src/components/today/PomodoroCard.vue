<template>
  <section class="card today-pomo">
    <h2>{{ item.title || "Помодоро" }}</h2>
    <template v-if="pomo.state.running">
      <div class="pomo-clock" :class="{ break: pomo.state.phase === 'break' }">{{ pomo.label() }}</div>
      <p class="muted">
        <template v-if="pomo.state.task">{{ pomo.state.task.title }} · после фокуса запишется в «Время»</template>
        <template v-else>Фокус без задачи — просто таймер</template>
      </p>
      <div class="row-actions">
        <button v-if="pomo.state.phase === 'break'" class="btn secondary" type="button" @click="pomo.skipBreak()">Закончить перерыв</button>
        <button class="btn secondary" type="button" @click="pomo.stop()">Стоп</button>
      </div>
    </template>
    <template v-else>
      <p class="muted">
        {{ pomo.state.settings.workMinutes }} минут фокуса, {{ pomo.state.settings.breakMinutes }} отдыха.
        <span v-if="pomo.state.sessions">Завершено на этой вкладке: {{ pomo.state.sessions }}.</span>
      </p>
      <label class="check">
        <input v-model.number="workMinutes" class="pomo-input" type="number" min="1" max="120" />
        <span>мин фокуса</span>
      </label>
      <label class="check">
        <input v-model.number="breakMinutes" class="pomo-input" type="number" min="1" max="60" />
        <span>мин перерыва</span>
      </label>
      <label class="check">
        <input v-model="autoBreak" type="checkbox" />
        <span>перерыв стартует сам</span>
      </label>
      <!-- Патч AM: подписка на системные уведомления о смене фаз —
           работают и в фоновой вкладке; включение спрашивает
           разрешение браузера. -->
      <label class="check">
        <input v-model="phaseNotify" type="checkbox" />
        <span>уведомлять о смене фаз</span>
      </label>
      <div class="row-actions pomo-pick">
        <TaskPicker v-if="!pomoTask" @select="pomoTask = $event" />
        <span v-else class="pomo-task-chip" :title="pomoTask.title + ' · ' + pomoTask.project_name">
          <strong>{{ pomoTask.title }}</strong>
          <span class="muted">{{ pomoTask.project_name }}</span>
          <button
            class="text-btn pomo-task-clear"
            type="button"
            title="Сбросить: фокус без задачи"
            @click="pomoTask = null"
          >✕</button>
        </span>
        <button class="btn" type="button" @click="startPomo()">Старт</button>
      </div>
    </template>
  </section>
</template>

<script>
import { ref, watch } from "vue"
import TaskPicker from "../TaskPicker.vue"
import { usePomodoro } from "../../composables/usePomodoro"

// Элемент «Сегодня» — помодоро. Таймер один на приложение (composable
// держит состояние в модуле), карточка целиком переехала из Today.vue
// (патч AW) — поведение не менялось, только адрес прописки.
export default {
  name: "TodayPomodoro",
  components: { TaskPicker },
  props: {
    item: { type: Object, required: true },
    context: { type: Object, required: true },
  },
  setup() {
    const pomo = usePomodoro()
    // Патч AF: задача для помодоро выбирается живым поиском по всем
    // открытым задачам (TaskPicker + /api/tasks/search).
    const pomoTask = ref(null)
    const workMinutes = ref(pomo.state.settings.workMinutes)
    const breakMinutes = ref(pomo.state.settings.breakMinutes)
    const autoBreak = ref(pomo.state.settings.autoBreak)
    const phaseNotify = ref(pomo.state.settings.notify)

    watch(workMinutes, (value) => pomo.updateSettings({ workMinutes: value }))
    watch(breakMinutes, (value) => pomo.updateSettings({ breakMinutes: value }))
    watch(autoBreak, (value) => pomo.updateSettings({ autoBreak: value }))
    // Включение подписки спрашивает разрешение браузера один раз; отказ
    // не мешает — останутся звук и заголовок вкладки.
    watch(phaseNotify, (value) => {
      pomo.updateSettings({ notify: value })
      if (value && typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {})
      }
    })

    function startPomo() {
      pomo.start(pomoTask.value)
    }

    return { pomo, pomoTask, workMinutes, breakMinutes, autoBreak, phaseNotify, startPomo }
  },
}
</script>
