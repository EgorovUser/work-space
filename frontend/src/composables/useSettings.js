import { ref } from "vue"
import { api } from "../api"

const values = ref({})
const title = ref("")
// In-flight запрос /api/settings/effective: несколько view на одной
// навигации зовут load() параллельно — дедупим одинаковые запросы.
let inflight = null

export function useSettings() {
  async function load(projectId) {
    const query = projectId ? "?project_id=" + encodeURIComponent(projectId) : ""
    const url = "/api/settings/effective" + query
    if (inflight && inflight.url === url) {
      return inflight.promise
    }
    const promise = api(url).then((data) => {
      values.value = data
      const nextTitle = data.core && data.core["ui.app_title"]
      if (nextTitle) {
        title.value = nextTitle
        document.title = nextTitle
      }
    })
    inflight = { url, promise }
    try {
      await promise
    } finally {
      if (inflight && inflight.promise === promise) {
        inflight = null
      }
    }
  }

  async function loadPublicTitle() {
    const data = await api("/api/settings/bootstrap")
    const nextTitle = data.values && data.values["core.ui.app_title"]
    if (nextTitle) {
      title.value = nextTitle
      document.title = nextTitle
    }
  }

  function get(moduleName, key) {
    const bucket = values.value[moduleName]
    if (!bucket) {
      return undefined
    }
    return bucket[key]
  }

  return { values, title, load, loadPublicTitle, get }
}
