<template>
  <div>
    <h1>Секреты</h1>
    <Tabs v-model="tab" :tabs="pageTabs" />
    <div v-show="tab === 'add'">
    <p class="muted">В поиске участвует только название. Логин, ссылка, заметка и сам секрет в базе зашифрованы.</p>
    <form class="card stack" @submit.prevent="create">
      <label>
        Название
        <input v-model="form.title" type="text" required autocomplete="off" />
      </label>
      <label>
        Вид
        <select v-model="form.kind">
          <option v-for="item in kinds" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
      </label>
      <label>
        Логин
        <input v-model="form.username" type="text" autocomplete="off" />
      </label>
      <label>
        Ссылка
        <input v-model="form.url" type="text" autocomplete="off" />
      </label>
      <label>
        Секрет
        <input v-model="form.secret" :type="showSecret ? 'text' : 'password'" autocomplete="new-password" />
      </label>
      <label>
        Заметка
        <textarea v-model="form.note" />
      </label>
      <p v-if="formError" class="error">{{ formError }}</p>
      <div class="row-actions">
        <button class="btn" type="submit" :disabled="busy">Добавить</button>
        <button class="btn secondary" type="button" :disabled="busy" @click="generate">Сгенерировать</button>
        <button class="btn secondary" type="button" @click="showSecret = !showSecret">
          {{ showSecret ? "Скрыть" : "Показать" }}
        </button>
      </div>
    </form>
    </div>

    <div v-show="tab === 'list'">
    <form class="row-actions" @submit.prevent="load">
      <input v-model="query" type="text" placeholder="Название" />
      <button class="btn secondary" type="submit">Показать</button>
    </form>
    <label class="check">
      <input v-model="includeArchived" type="checkbox" @change="load" />
      <span>Показать архив</span>
    </label>

    <p v-if="error" class="error">{{ error }}</p>
    <SkeletonList v-else-if="loading" :rows="4" />
    <div v-else-if="!items.length" class="empty">
      <strong>Секретов пока нет</strong>
      <span>Пароли, ключи и заметки для доступа появятся здесь — добавьте первый формой выше.</span>
    </div>
    <div v-else class="card">
      <div v-for="item in items" :key="item.id" class="status-row">
        <div>
          <router-link :to="'/projects/' + project.id + '/secrets/' + item.id">{{ item.title }}</router-link>
          <div class="muted">
            {{ item.kind_label || item.kind }}
            <span v-if="item.has_secret"> · секрет задан</span>
            <span v-else> · секрета нет</span>
            <span v-if="item.archived"> · архив</span>
            · {{ when(item.updated_at) }}
          </div>
        </div>
        <ActionMenu :actions="rowActions" @choose="onAction($event, item)" />
      </div>
    </div>
    </div>
  </div>
</template>

<script>
import { ref, watch } from "vue"
import { useRouter } from "vue-router"
import { api } from "../api"
import ActionMenu from "../components/ActionMenu.vue"
import SkeletonList from "../components/SkeletonList.vue"
import Tabs from "../components/Tabs.vue"
import { useWhen } from "../composables/useWhen"
import { useNotice } from "../composables/useNotice"
import { useSoftDelete } from "../composables/useSoftDelete"

export default {
  components: { ActionMenu, Tabs, SkeletonList },
  props: {
    project: { type: Object, required: true },
  },
  setup(props) {
    const items = ref([])
    const kinds = ref([])
    const error = ref("")
    const formError = ref("")
    const loading = ref(true)
    const busy = ref(false)
    const query = ref("")
    const includeArchived = ref(false)
    const tab = ref("list")
    const pageTabs = [
      { id: "list", label: "Список" },
      { id: "add", label: "Новый" },
    ]
    const showSecret = ref(false)
    const form = ref({ title: "", kind: "", username: "", url: "", note: "", secret: "" })
    const { settings, when } = useWhen()
    const notice = useNotice()
    const { softRemove } = useSoftDelete()
    const router = useRouter()
    const rowActions = [
      { id: "open", label: "Открыть" },
      { id: "delete", label: "Удалить", danger: true },
    ]

    function onAction(action, item) {
      if (action === "open") router.push("/projects/" + props.project.id + "/secrets/" + item.id)
      if (action === "delete") remove(item)
    }

    async function remove(item) {
      // Секреты удаляются мягко — «Отменить» достаёт из корзины.
      const snapshot = items.value.slice()
      items.value = items.value.filter((row) => row.id !== item.id)
      const ok = await softRemove({
        confirm: "Удалить секрет «" + item.title + "»?",
        url: "/api/projects/" + props.project.id + "/secrets/" + item.id,
        restoreUrl: "/api/trash/secrets/" + item.id + "/restore",
        doneText: "Секрет «" + item.title + "» удалён в корзину",
        restoredText: "Секрет «" + item.title + "» восстановлен",
        restoreFailText: "Не удалось восстановить секрет. ",
        afterRestore: load,
      })
      if (!ok) items.value = snapshot
    }

    function applyKinds(list) {
      kinds.value = Array.isArray(list) ? list : []
      if (!form.value.kind && kinds.value.length) {
        const fallback = settings.get("secrets", "kind.default")
        const known = kinds.value.some((item) => item.id === fallback)
        form.value.kind = known ? fallback : kinds.value[0].id
      }
    }

    async function load() {
      loading.value = true
      error.value = ""
      try {
        const params = new URLSearchParams()
        if (includeArchived.value) params.set("include_archived", "true")
        if (query.value) params.set("q", query.value)
        const data = await api("/api/projects/" + props.project.id + "/secrets?" + params.toString())
        items.value = data.items || []
        applyKinds(data.kinds)
      } catch (err) {
        items.value = []
        error.value = err.message || "Список недоступен"
      } finally {
        loading.value = false
      }
    }

    async function create() {
      formError.value = ""
      busy.value = true
      try {
        await api("/api/projects/" + props.project.id + "/secrets", {
          method: "POST",
          body: {
            title: form.value.title,
            kind: form.value.kind,
            username: form.value.username,
            url: form.value.url,
            note: form.value.note,
            secret: form.value.secret,
          },
        })
        const title = form.value.title
        const keepKind = form.value.kind
        form.value = { title: "", kind: keepKind, username: "", url: "", note: "", secret: "" }
        showSecret.value = false
        // Прежде форма молча сбрасывалась — было не понять, добавился секрет
        // или нет. Тост подтверждает, поле готово к следующему секрету.
        notice.show("Секрет «" + title + "» добавлен", { kind: "success" })
        await load()
      } catch (err) {
        formError.value = err.message || "Не удалось добавить"
      } finally {
        busy.value = false
      }
    }

    async function generate() {
      formError.value = ""
      busy.value = true
      try {
        const data = await api("/api/projects/" + props.project.id + "/secrets/generate", { method: "POST" })
        form.value.secret = data.secret || ""
        showSecret.value = true
      } catch (err) {
        formError.value = err.message || "Не удалось сгенерировать"
      } finally {
        busy.value = false
      }
    }

    watch(() => props.project && props.project.id, () => {
      settings.load(props.project.id).catch(() => {}).finally(load)
    }, { immediate: true })

    return {
      items, kinds, error, formError, loading, busy, query, includeArchived, showSecret, form, tab, pageTabs,
      when, rowActions, load, create, generate, onAction,
    }
  },
}
</script>
