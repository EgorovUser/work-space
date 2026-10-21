import { computed, ref } from "vue"
import { api } from "../api"
import { useEvents } from "./useEvents"
import { addItem, moveItem, removeItem, sameItems, setItemProp } from "../ui/items"

// Конфигурация редактируемой страницы (патч AW): состояние + каталог
// свойств с бэкенда, правки с автосохранением (дебаунс), живая
// синхронизация вкладок через SSE ui.changed.
//
// Инспектор свойств не захардкожен: панель рендерится по каталогу, как
// инспектор SurveyJS. Конфликт двух вкладок решается просто: пока у
// этой вкладки несохранённые правки, входящее состояние не применяется
// (последнее сохранение выигрывает) — для личного приложения честно и
// предсказуемо.

const SAVE_DEBOUNCE_MS = 700

export function useUiConfig(page, { fallback = [] } = {}) {
  const items = ref([...fallback])
  const catalog = ref({ elements: [] })
  const isDefault = ref(true)
  const loaded = ref(false)
  const error = ref("")
  const editing = ref(false)
  const selected = ref(null)
  const saving = ref(false)
  const saveError = ref("")
  const revisions = ref([])
  const revisionsLoaded = ref(false)

  let saveTimer = null
  // JSON последнего состояния, подтверждённого сервером (реактивен —
  // от него считается pending).
  const lastAck = ref(null)
  let remoteOff = null

  const events = useEvents()

  function dirty() {
    return saveTimer !== null || saving.value
  }

  async function load() {
    error.value = ""
    try {
      const data = await api("/api/ui/" + page)
      applyRemote(data)
      loaded.value = true
    } catch (err) {
      // Страница живёт на аварийной раскладке из реестра — как HA
      // показывает «card not found», только тут весь конфиг.
      error.value = err.message || "Не удалось загрузить конфигурацию страницы"
      loaded.value = true
      // Аварийная раскладка считается «подтверждённой»: без правок
      // пользователя никаких сохранений не будет.
      lastAck.value = JSON.stringify(items.value)
    }
  }

  function applyRemote(data) {
    const next = data.items || []
    if (data.catalog) catalog.value = data.catalog
    if (data.is_default !== undefined) isDefault.value = !!data.is_default
    // Локальные несохранённые правки не затираем: подтверждённое
    // состояние доедет следующим сохранением.
    if (!dirty()) items.value = next
    lastAck.value = JSON.stringify(next)
  }

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(flush, SAVE_DEBOUNCE_MS)
  }

  async function flush() {
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
    const payload = items.value
    const acked = lastAck.value ? JSON.parse(lastAck.value) : null
    if (sameItems(payload, acked)) return
    saving.value = true
    saveError.value = ""
    try {
      const data = await api("/api/ui/" + page, { method: "PUT", body: { items: payload } })
      applyRemote(data)
    } catch (err) {
      saveError.value = "Не сохранилось: " + (err.message || "ошибка сети")
      scheduleSave()
    } finally {
      saving.value = false
    }
  }

  // Правки: локально сразу (страница откликается мгновенно), на сервер —
  // с дебаунсом, чтобы серия движений ручки не плодила запросы.
  function updateProp(element, key, value) {
    items.value = setItemProp(items.value, element, key, value)
    scheduleSave()
  }

  function addElement(element) {
    const def = (catalog.value.elements || []).find((item) => item.name === element)
    const defaults = {}
    for (const prop of (def && def.props) || []) defaults[prop.key] = prop.default
    items.value = addItem(items.value, element, defaults)
    selected.value = element
    scheduleSave()
  }

  function removeElement(element) {
    items.value = removeItem(items.value, element)
    if (selected.value === element) selected.value = null
    scheduleSave()
  }

  function moveElement(element, delta) {
    items.value = moveItem(items.value, element, delta)
    scheduleSave()
  }

  async function reset() {
    const data = await api("/api/ui/" + page + "/reset", { method: "POST" })
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
    applyRemote(data)
    if (selected.value && !items.value.some((item) => item.element === selected.value)) {
      selected.value = null
    }
    refreshRevisions()
  }

  async function restore(revisionId) {
    const data = await api("/api/ui/" + page + "/revisions/" + revisionId + "/restore", { method: "POST" })
    applyRemote(data)
    refreshRevisions()
  }

  async function refreshRevisions() {
    try {
      const data = await api("/api/ui/" + page + "/revisions")
      revisions.value = data.items || []
      revisionsLoaded.value = true
    } catch {
      revisions.value = []
    }
  }

  // Есть несохранённые изменения: правка ещё в дебаунсе или запрос уже
  // летит. Индикатор в панели живёт от ручки до подтверждения, а не
  // мигает на время полёта — и человеку, и e2e видно честное «Сохраняем…».
  const pending = computed(() => !sameItems(items.value, lastAck.value ? JSON.parse(lastAck.value) : null))

  function start() {
    // ui.changed от другой вкладки (или от этой — SSE-эхо нашего же
    // сохранения): перечитать конфиг, если локальных правок в полёте нет.
    remoteOff = events.on((type, payload) => {
      if (type === "ui.changed" && payload && payload.page === page && !dirty()) {
        load()
      }
    })
    load()
  }

  function stop() {
    if (remoteOff) {
      remoteOff()
      remoteOff = null
    }
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  }

  return {
    items,
    catalog,
    isDefault,
    loaded,
    error,
    editing,
    selected,
    saving,
    pending,
    saveError,
    revisions,
    revisionsLoaded,
    start,
    stop,
    load,
    flush,
    updateProp,
    addElement,
    removeElement,
    moveElement,
    reset,
    restore,
    refreshRevisions,
  }
}
