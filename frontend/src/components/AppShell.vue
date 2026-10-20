<template>
  <div class="app">
    <aside class="rail">
      <div class="brand">{{ title || "Рабочее пространство" }}</div>
      <nav class="rail-nav">
        <router-link to="/">Сегодня</router-link>
        <router-link to="/projects">Проекты</router-link>
        <router-link v-for="item in railBadges" :key="item.to" :to="item.to"
          >{{ item.label }}<span
            v-if="railBadge(item.key)"
            class="rail-badge"
            :class="badgeClass(item)"
            >{{ railBadge(item.key) }}</span
          ></router-link
        >
        <router-link to="/settings">Настройки</router-link>
        <router-link to="/system">Состояние</router-link>
      </nav>
      <!-- Патч AL: активный фокус — над именем пользователя, только когда
           что-то идёт. Помодоро приоритетнее (он клиентский и всегда свежий);
           иначе — серверный таймер. Ссылка ведёт к источнику, кнопка — стоп. -->
      <div v-if="focusLine" class="rail-focus" :class="focusLine.kind">
        <router-link class="rail-focus-link" :to="focusLine.to" :title="focusLine.hint">
          <strong class="rail-focus-clock">{{ focusLine.clock }}</strong>
          <span v-if="focusLine.sub" class="rail-focus-sub">{{ focusLine.sub }}</span>
        </router-link>
        <button class="rail-focus-stop" type="button" :title="focusLine.stopTitle" @click="focusLine.onStop">
          ⏹
        </button>
      </div>
      <div class="rail-foot">
        <div v-if="user" class="rail-user">{{ user.display_name || user.username }}</div>
        <button class="btn secondary" type="button" @click="onLogout">Выйти</button>
        <div v-if="build" class="rail-build" :title="'Сборка патча ' + build">сборка {{ build }}</div>
      </div>
    </aside>
    <main class="app-main">
      <header class="topbar">
        <div class="topbar-title">{{ heading }}</div>
        <GlobalSearch />
        <div class="topbar-tools">
          <router-link v-if="pomo.state.running" to="/" class="pomo-chip" :class="{ break: pomo.state.phase === 'break' }" title="Идёт помодоро — вернуться на «Сегодня»">
            {{ pomo.label() }}
          </router-link>
          <router-link
            v-else-if="focusTimer.running"
            :to="focusTimer.to"
            class="pomo-chip timer"
            title="Идёт таймер — открыть учёт времени проекта"
          >
            {{ focusTimer.clock }}
          </router-link>
          <ThemeToggle />
          <Bell />
        </div>
      </header>
      <div class="app-body" :class="bare ? 'bare' : 'page'">
        <slot />
      </div>
    </main>
    <!-- Нижняя навигация для телефонов: CSS прячет её на широких экранах. -->
    <BottomNav />
  </div>
</template>

<script>
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import Bell from "./Bell.vue"
import BottomNav from "./BottomNav.vue"
import ThemeToggle from "./ThemeToggle.vue"
import GlobalSearch from "./GlobalSearch.vue"
import { api } from "../api"
import { useAuth } from "../composables/useAuth"
import { useChrome } from "../composables/useChrome"
import { railCount } from "../composables/countFormat"
import { useCounters } from "../composables/useCounters"
import { useEvents } from "../composables/useEvents"
import { usePomodoro } from "../composables/usePomodoro"
import { useRunningTimer } from "../composables/useRunningTimer"
import { useSettings } from "../composables/useSettings"

// Рельса несёт только глобальные разделы. Навигация внутри проекта живёт
// в горизонтальных табах под шапкой (ProjectLayout) — раньше ссылки
// проекта сваливались в этот же столбец, и в нём было 13 строк.
export default {
  props: {
    bare: { type: Boolean, default: false },
  },
  components: { Bell, BottomNav, ThemeToggle, GlobalSearch },
  setup(props) {
    const auth = useAuth()
    const settings = useSettings()
    const chrome = useChrome()
    const events = useEvents()
    const router = useRouter()
    const route = useRoute()

    const heading = computed(() => {
      if (chrome.caption.value) return chrome.caption.value
      if (route.path === "/") return "Сегодня"
      if (route.path.startsWith("/projects")) return "Проекты"
      if (route.path.startsWith("/mail")) return "Почта"
      if (route.path.startsWith("/time")) return "Учёт времени"
      if (route.path.startsWith("/secrets")) return "Секреты"
      if (route.path.startsWith("/trash")) return "Корзина"
      if (route.path.startsWith("/notifications")) return "Уведомления"
      if (route.path.startsWith("/settings")) return "Настройки"
      if (route.path.startsWith("/system")) return "Состояние"
      return settings.title.value || "Сегодня"
    })

    const pomo = usePomodoro()
    const counters = useCounters()
    const globalCounts = counters.globalCounts
    const focus = useRunningTimer()

    // Активный фокус в рельсе (патч AL): помодоро или серверный таймер.
    // Часы тикают сами (state.remaining у помодоро, now у таймера),
    // вычисляемое свойство пересобирается каждую секунду.
    const focusLine = computed(() => {
      if (pomo.state.running) {
        const rest = pomo.state.phase === "break"
        return {
          kind: rest ? "pomo break" : "pomo",
          clock: pomo.label(),
          sub: pomo.state.task ? pomo.state.task.title : "",
          to: "/",
          hint: "Идёт помодоро — вернуться на «Сегодня»",
          stopTitle: "Остановить помодоро",
          onStop: () => pomo.stop(),
        }
      }
      const row = focus.running.value
      if (row) {
        return {
          kind: "timer",
          clock: focus.elapsed.value || "0:00",
          sub: focus.sub.value,
          to: "/projects/" + row.project_id + "/time",
          hint: "Идёт таймер — открыть учёт времени",
          stopTitle: "Остановить таймер",
          onStop: () => {
            focus.stop().catch(() => {})
          },
        }
      }
      return null
    })

    // Чип в шапке — тот же фокус для узких экранов, где рельсы нет.
    const focusTimer = computed(() => {
      const row = focus.running.value
      if (!row) return { running: null }
      return {
        running: row,
        clock: focus.elapsed.value || "0:00",
        to: "/projects/" + row.project_id + "/time",
      }
    })

    // Числа рельсы (патч U): 0–99 числом, дальше 99+. Источник — хаб
    // счётчиков: SSE применяет живые обновления, навигация и опрос —
    // запасные пути. Ноль показываем приглушённым. Патч AH: красным
    // кружком горят только непрочитанные уведомления — остальные счётчики
    // спокойные, они сообщают, а не требуют внимания.
    const railBadges = [
      { to: "/mail", label: "Почта", key: "mail_unread" },
      { to: "/time", label: "Время", key: null },
      { to: "/secrets", label: "Секреты", key: "secrets_total" },
      { to: "/trash", label: "Корзина", key: "trash_total" },
      { to: "/notifications", label: "Уведомления", key: "notifications_unread", alert: true },
    ]

    function railBadge(key) {
      return railCount(globalCounts.value ? globalCounts.value[key] : null)
    }

    function railZero(key) {
      return !globalCounts.value || !globalCounts.value[key]
    }

    function badgeClass(item) {
      const empty = railZero(item.key)
      return { zero: empty, alert: Boolean(item.alert) && !empty }
    }

    const build = ref("")

    onMounted(() => {
      settings.load().catch(() => {})
      events.start()
      counters.start()
      counters.refresh()
      focus.start()
      // Сборка приходит от работающего бэкенда, а не зашита в бандл: если
      // надписи нет — оболочка устарела; если есть — ровно эта версия и
      // крутится (сверяется с curl /healthz).
      api("/healthz")
        .then((data) => {
          build.value = data && data.build ? String(data.build) : ""
        })
        .catch(() => {})
    })

    onBeforeUnmount(() => {
      counters.stop()
      focus.stopPolling()
    })

    async function onLogout() {
      events.stop()
      counters.reset()
      focus.reset()
      pomo.stop()
      await auth.logout()
      router.push("/login")
    }

    return {
      user: auth.user,
      title: settings.title,
      build,
      bare: computed(() => props.bare),
      caption: chrome.caption,
      heading,
      railBadges,
      railBadge,
      railZero,
      badgeClass,
      pomo,
      focusLine,
      focusTimer,
      route,
      onLogout,
    }
  },
}
</script>
