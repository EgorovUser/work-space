import { createRouter, createWebHistory } from "vue-router"
import { useAuth } from "./composables/useAuth"

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: () => import("./views/Login.vue") },
    { path: "/", component: () => import("./views/ProjectList.vue"), meta: { auth: true } },
    { path: "/mail", component: () => import("./views/Mailbox.vue"), meta: { auth: true } },
    { path: "/mail/:messageId", component: () => import("./views/MailLetter.vue"), meta: { auth: true } },
    { path: "/system", component: () => import("./views/Home.vue"), meta: { auth: true } },
    { path: "/settings", component: () => import("./views/Settings.vue"), meta: { auth: true } },
    { path: "/notifications", component: () => import("./views/Notifications.vue"), meta: { auth: true } },
    {
      path: "/projects/:projectId",
      component: () => import("./views/ProjectLayout.vue"),
      meta: { auth: true },
      children: [
        { path: "", component: () => import("./views/ProjectBoard.vue") },
        { path: "tasks/:taskId", component: () => import("./views/TaskPage.vue") },
        { path: "documents", component: () => import("./views/Documents.vue") },
        { path: "documents/:documentId", component: () => import("./views/DocumentPage.vue") },
        { path: "examples", component: () => import("./views/Examples.vue") },
        { path: "examples/:exampleId", component: () => import("./views/ExamplePage.vue") },
        { path: "secrets", component: () => import("./views/Secrets.vue") },
        { path: "secrets/:secretId", component: () => import("./views/SecretPage.vue") },
        { path: "mail", component: () => import("./views/Mail.vue") },
        { path: "mail/:messageId", component: () => import("./views/MailPage.vue") },
        { path: "time", component: () => import("./views/Time.vue") },
        { path: "settings", component: () => import("./views/ProjectSettings.vue") },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.ready.value) {
    await auth.refresh()
  }
  if (to.meta.auth && !auth.user.value) {
    return "/login"
  }
  if (to.path === "/login" && auth.user.value) {
    return "/"
  }
  return true
})

export default router
