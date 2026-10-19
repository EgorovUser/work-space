<template>
  <div v-if="message.text" class="toast" :class="{ success: message.kind === 'success' }" role="status">
    <p>{{ message.text }}</p>
    <div class="toast-actions">
      <button v-if="message.action" class="text-btn" type="button" @click="runAction">{{ message.action.label }}</button>
      <button class="text-btn" type="button" @click="close">Закрыть</button>
    </div>
  </div>
</template>

<script>
import { useNotice } from "../composables/useNotice"

export default {
  setup() {
    const notice = useNotice()
    return { message: notice.message, close: notice.close, runAction: notice.runAction }
  },
}
</script>
