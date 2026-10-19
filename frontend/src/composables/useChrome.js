import { ref } from "vue"

const caption = ref("")
const extra = ref([])

export function useChrome() {
  function setProject(name, links) {
    caption.value = name || "Проект"
    extra.value = links || []
  }

  function clear() {
    caption.value = ""
    extra.value = []
  }

  return { caption, extra, setProject, clear }
}
