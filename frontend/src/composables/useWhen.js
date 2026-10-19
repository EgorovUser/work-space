import { useSettings } from "./useSettings"
import { formatWhen } from "./formatDate"

export function useWhen() {
  const settings = useSettings()

  function when(value) {
    return formatWhen(value, settings.get("core", "ui.date_format"), settings.get("core", "ui.timezone") || undefined)
  }

  function localDay() {
    const now = new Date()
    const month = String(now.getMonth() + 1).padStart(2, "0")
    const day = String(now.getDate()).padStart(2, "0")
    return now.getFullYear() + "-" + month + "-" + day
  }

  return { settings, when, localDay }
}
