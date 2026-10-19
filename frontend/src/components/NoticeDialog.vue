<template>
  <div v-if="message" class="toast" role="status">
    <p>{{ message }}</p>
    <button class="text-btn" type="button" @click="close">Закрыть</button>
  </div>
</template>

<script>
import { useNotice } from "../composables/useNotice"

export default {
  setup() {
    const notice = useNotice()
    return { message: notice.message, close: notice.close }
  },
}
</script>
