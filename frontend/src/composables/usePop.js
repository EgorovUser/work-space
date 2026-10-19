import { onBeforeUnmount, ref } from "vue"

export function createPopStore() {
  let current = 0
  const items = new Map()

  function close(id) {
    if (current === id) current = 0
  }

  function open(id) {
    if (current && current !== id) {
      const previous = current
      current = id
      const item = items.get(previous)
      if (item) item.close()
    } else {
      current = id
    }
  }

  function pointer(target) {
    if (!current) return
    const item = items.get(current)
    if (!item || item.contains(target)) return
    item.close()
  }

  function escape() {
    if (!current) return false
    const item = items.get(current)
    if (!item) return false
    item.close()
    return true
  }

  return {
    register(id, item) {
      items.set(id, item)
    },
    unregister(id) {
      items.delete(id)
      if (current === id) current = 0
    },
    open,
    close,
    pointer,
    escape,
    current() {
      return current
    },
  }
}

const store = createPopStore()
let seq = 0
let installed = false

function install() {
  if (installed || typeof document === "undefined") return
  installed = true
  document.addEventListener("pointerdown", (event) => store.pointer(event.target), true)
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return
    if (store.escape()) event.preventDefault()
  }, true)
}

export function usePop(root, panel) {
  install()
  const id = ++seq
  const open = ref(false)

  function close() {
    open.value = false
    store.close(id)
  }

  function show() {
    open.value = true
    store.open(id)
  }

  function toggle() {
    if (open.value) close()
    else show()
  }

  store.register(id, {
    close,
    contains(target) {
      if (!target) return false
      const nodes = [root && root.value, panel && panel.value]
      return nodes.some((node) => node && node.contains(target))
    },
  })
  onBeforeUnmount(() => store.unregister(id))
  return { open, show, close, toggle }
}
