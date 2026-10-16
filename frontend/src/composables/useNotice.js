import { ref } from "vue"

const message = ref("")

export function useNotice() {
  function show(text) {
    message.value = text || "Не получилось"
  }

  function close() {
    message.value = ""
  }

  return { message, show, close }
}
