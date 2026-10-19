import { reactive } from "vue"

// Один слот уведомлений на приложение. Кроме ошибок умеет успех (зелёный)
// и действие («Отменить»): тост с кнопкой живёт дольше обычного.
const state = reactive({ text: "", kind: "error", action: null })
let timer = null

export function useNotice() {
  function close() {
    clearTimeout(timer)
    state.text = ""
    state.kind = "error"
    state.action = null
  }

  function show(text, options = {}) {
    state.text = text || "Не получилось"
    state.kind = options.kind === "success" ? "success" : "error"
    state.action = options.action && typeof options.action.run === "function" ? options.action : null
    clearTimeout(timer)
    const timeout = Number(options.timeout) || (state.kind === "success" ? (state.action ? 7000 : 3500) : 7000)
    timer = setTimeout(close, timeout)
  }

  function runAction() {
    const action = state.action
    close()
    if (action) action.run()
  }

  return { message: state, show, close, runAction }
}
