<template>
  <router-view />
  <NoticeDialog />
</template>

<script>
import NoticeDialog from "./components/NoticeDialog.vue"

export default {
  components: { NoticeDialog },
}
</script>
