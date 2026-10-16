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

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  let body = options.body
  if (body !== undefined && !(body instanceof FormData) && typeof body !== "string") {
    headers["Content-Type"] = "application/json"
    body = JSON.stringify(body)
  }
  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers,
    body,
  })
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
    const message = typeof detail === "string" ? detail : "Запрос не выполнен"
    const moduleName = data && data.module
    const quiet = path.startsWith("/api/auth/login") || path.startsWith("/api/auth/me")
    if (response.status === 401 && !quiet && onUnauthorized) {
      onUnauthorized()
    }
    throw new ApiError(message, response.status, moduleName)
  }
  return data
}
