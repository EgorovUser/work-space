import { ref } from "vue"

const message = ref("")
let timer = null

export function useNotice() {
  function show(text) {
    message.value = text || "Не получилось"
    clearTimeout(timer)
    timer = setTimeout(() => {
      message.value = ""
    }, 7000)
  }

  function close() {
    clearTimeout(timer)
    message.value = ""
  }

  return { message, show, close }
}
