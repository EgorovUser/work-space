<template>
  <div>
    <p class="crumbs"><router-link :to="'/projects/' + project.id + '/mail'">← Письма проекта</router-link></p>
    <MailReader :message-id="messageId" :project="project" @removed="onRemoved" />
  </div>
</template>

<script>
import { computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import MailReader from "../components/MailReader.vue"

// Страница письма внутри проекта: тонкая обёртка вокруг читалки.
// После удаления возвращаемся к списку писем проекта.
export default {
  components: { MailReader },
  props: { project: { type: Object, required: true } },
  setup(props) {
    const route = useRoute()
    const router = useRouter()

    const messageId = computed(() => Number(route.params.messageId) || 0)

    function onRemoved() {
      router.push("/projects/" + props.project.id + "/mail")
    }

    return { messageId, onRemoved }
  },
}
</script>
