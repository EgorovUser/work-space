import { ref } from "vue"
import { api } from "../api"

const values = ref({})
const title = ref("")

export function useSettings() {
  async function load(projectId) {
    const query = projectId ? "?project_id=" + encodeURIComponent(projectId) : ""
    values.value = await api("/api/settings/effective" + query)
    const nextTitle = values.value.core && values.value.core["ui.app_title"]
    if (nextTitle) {
      title.value = nextTitle
      document.title = nextTitle
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
