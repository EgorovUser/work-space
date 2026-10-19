export class ApiError extends Error {
  constructor(message, status, moduleName) {
    super(message)
    this.status = status
    this.moduleName = moduleName
  }
}

let onUnauthorized = null

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

export function downloadFile(fileId) {
  if (!fileId) return
  window.location.assign("/api/files/" + fileId)
}

// Загрузка с прогрессом: fetch не отдаёт прогресс отправки, поэтому XHR.
export function uploadApi(path, body, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", path)
    xhr.withCredentials = true
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        onProgress(event.loaded, event.total)
      }
    }
    xhr.onload = () => {
      let data = null
      if (xhr.responseText) {
        try {
          data = JSON.parse(xhr.responseText)
        } catch {
          data = { detail: xhr.responseText }
        }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data)
        return
      }
      const detail = data && data.detail
      let message
      if (typeof detail === "string" && detail.trim()) message = detail
      else if (xhr.status === 429) message = "Слишком много попыток. Подождите немного и попробуйте снова."
      else if (xhr.status === 422) message = "Проверьте заполнение полей."
      else message = "Запрос не выполнен"
      reject(new ApiError(message, xhr.status, data && data.module))
    }
    xhr.onerror = () => {
      reject(new ApiError("Нет связи с сервером. Проверьте сеть и попробуйте снова.", 0))
    }
    xhr.send(body)
  })
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  let body = options.body
  if (body !== undefined && !(body instanceof FormData) && typeof body !== "string") {
    headers["Content-Type"] = "application/json"
    body = JSON.stringify(body)
  }
  let response
  try {
    response = await fetch(path, {
      credentials: "include",
      ...options,
      headers,
      body,
    })
  } catch {
    // fetch бросает TypeError("Failed to fetch") при лежащем сервере и обрывах сети —
    // пользователь не должен видеть английский текст браузера.
    throw new ApiError("Нет связи с сервером. Проверьте сеть и попробуйте снова.", 0)
  }
  const text = await response.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }
  if (!response.ok) {
    const detail = data && data.detail
    let message
    if (typeof detail === "string" && detail.trim()) {
      message = detail
    } else if (response.status === 429) {
      message = "Слишком много попыток. Подождите немного и попробуйте снова."
    } else if (response.status === 422) {
      message = "Проверьте заполнение полей."
    } else {
      message = "Запрос не выполнен"
    }
    const moduleName = data && data.module
    const quiet = path.startsWith("/api/auth/login") || path.startsWith("/api/auth/me")
    if (response.status === 401 && !quiet && onUnauthorized) {
      onUnauthorized()
    }
    throw new ApiError(message, response.status, moduleName)
  }
  return data
}
