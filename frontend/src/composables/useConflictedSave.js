// Конфликт версий при сохранении (патч AD): 409 «запись меняли после вас»
// на трёх экранах правки обрабатывался копией одного блока — теперь одним
// хелпером. Всё, что не 409, уходит в обработчик экрана.

export function useConflictedSave() {
  async function onConflict(err, reload, onError) {
    if (err && err.status === 409) {
      if (window.confirm(err.message + "\n\nЗагрузить свежую версию? Несохранённые правки будут потеряны.")) {
        await reload()
      }
      return true
    }
    if (onError) onError(err)
    return false
  }

  return { onConflict }
}
