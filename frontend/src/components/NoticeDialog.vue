<template>
  <div v-if="message" class="modal-back">
    <div class="modal" role="alertdialog">
      <p>{{ message }}</p>
      <button class="btn" type="button" @click="close">Понятно</button>
    </div>
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
