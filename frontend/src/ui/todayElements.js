// Элементы страницы «Сегодня» (патч AW): каждая секция хаба стала
// самостоятельным элементом реестра. Порядок и дефолтные ширины здесь —
// аварийный фолбэк на случай, когда /api/ui недоступен: страница всё
// равно рендерится (кривой конфиг не ломает страницу). Настоящие
// дефолты отдаёт каталог бэкенда — там же схема свойств для инспектора.

import { defineElement, allElements } from "./elements.js"
import OverdueTasks from "../components/today/OverdueTasks.vue"
import UpcomingTasks from "../components/today/UpcomingTasks.vue"
import PomodoroCard from "../components/today/PomodoroCard.vue"
import MailEvents from "../components/today/MailEvents.vue"
import NewMail from "../components/today/NewMail.vue"
import NotificationsCard from "../components/today/NotificationsCard.vue"
import ProjectsCard from "../components/today/ProjectsCard.vue"

defineElement({ name: "overdue-tasks", title: "Просроченные", span: 4, component: OverdueTasks })
defineElement({ name: "upcoming-tasks", title: "Ближайшие сроки", span: 2, component: UpcomingTasks })
defineElement({ name: "pomodoro", title: "Помодоро", span: 2, component: PomodoroCard })
defineElement({ name: "mail-events", title: "События на сегодня", span: 2, component: MailEvents })
defineElement({ name: "new-mail", title: "Новые письма", span: 2, component: NewMail })
defineElement({ name: "notifications", title: "Уведомления", span: 2, component: NotificationsCard })
defineElement({ name: "projects", title: "Проекты", span: 4, component: ProjectsCard })

// Аварийная раскладка: реестр знает имена, подписи и ширины — этого
// хватает, чтобы страница жила без сервера конфигураций. Высота «авто»:
// без конфига фиксировать нечего, карточки растут по содержимому.
export function fallbackItems() {
  return allElements().map((element) => ({
    element: element.name,
    span: element.span,
    height: "auto",
    hidden: false,
    title: "",
  }))
}
