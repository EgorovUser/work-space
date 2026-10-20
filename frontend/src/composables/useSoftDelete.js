import { api } from "../api"
import { useNotice } from "./useNotice"

// Мягкое удаление с «Отменить» — единый блок (патч AD). Семь экранов
// писали этот скелет руками: подтверждение → DELETE → тост с возвратом
// из корзины → восстановление с тостом. Тексты и адреса вариативны,
// поведение — нет.
//
// softRemove возвращает true, если удаление прошло (вызывающий может
// увести пользователя со страницы), и false — если отменили или не
// вышло. Оптимистичное снятие строки (и её откат при ошибке) — на
// стороне экрана: только он знает форму своего списка.

export function useSoftDelete() {
  const notice = useNotice()

  async function softRemove(options) {
    const {
      confirm: confirmText,
      url,
      restoreUrl,
      doneText,
      restoredText,
      restoreFailText,
      afterRestore,
      onDone,
      onError,
    } = options
    if (!window.confirm(confirmText)) return false
    try {
      await api(url, { method: "DELETE" })
    } catch (err) {
      if (onError) onError(err)
      else notice.show("Не удалось удалить. " + (err.message || "Ошибка"))
      return false
    }
    if (onDone) await onDone()
    // Без restoreUrl (запись не в корзине) — простой тост без «Отменить».
    if (!restoreUrl) {
      notice.show(doneText, { kind: "success" })
      return true
    }
    notice.show(doneText, {
      kind: "success",
      timeout: 9000,
      action: {
        label: "Отменить",
        run: async () => {
          try {
            await api(restoreUrl, { method: "POST" })
            notice.show(restoredText, { kind: "success" })
            if (afterRestore) await afterRestore()
          } catch (err) {
            notice.show(restoreFailText + (err.message || "Ошибка"))
          }
        },
      },
    })
    return true
  }

  return { softRemove }
}
