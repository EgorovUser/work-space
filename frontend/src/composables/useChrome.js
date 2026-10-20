import { ref } from "vue"

// Заголовок шапки для вложенных экранов (например, имя проекта).
// Проектные ссылки больше не живут в рельсе — они рисуются табами в
// ProjectLayout, так что хранить здесь нечего, кроме подписи.
const caption = ref("")

export function useChrome() {
  function setProject(name) {
    caption.value = name || "Проект"
  }

  function clear() {
    caption.value = ""
  }

  return { caption, setProject, clear }
}
