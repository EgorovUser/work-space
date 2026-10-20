import { ref } from "vue"

// Охрана буфера обмена (патч X): «Скопировано. Буфер очистится через N с.»
// Один экземпляр на страницу секрета: индикатор живёт в форме, а копируют
// и текущий секрет, и прежние версии из истории — состояние общее.
const CLIPBOARD_TTL = 30

const copied = ref(false)
const clipSeconds = ref(CLIPBOARD_TTL)
let clipTimer = null
let clearTimer = null

export function useClipboard() {
  function stop() {
    clearInterval(clipTimer)
    clearTimeout(clearTimer)
  }

  async function write(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
      return
    }
    const area = document.createElement("textarea")
    area.value = text
    document.body.appendChild(area)
    area.select()
    document.execCommand("copy")
    area.remove()
  }

  function arm() {
    stop()
    copied.value = true
    clipSeconds.value = CLIPBOARD_TTL
    // Обратный отсчёт в подсказке + очистка буфера: пароль не остаётся
    // в системе на неопределённый срок после копирования.
    clipTimer = setInterval(() => {
      clipSeconds.value -= 1
      if (clipSeconds.value <= 0) clearInterval(clipTimer)
    }, 1000)
    clearTimer = setTimeout(async () => {
      copied.value = false
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText("")
        }
      } catch {
        // Буфер мог быть перезаписан другой вкладкой — это нормальный исход.
      }
    }, CLIPBOARD_TTL * 1000)
  }

  return { copied, clipSeconds, write, arm, stop, CLIPBOARD_TTL }
}
