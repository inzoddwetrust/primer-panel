<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

// A confirmation (R-18): with `expected` the person types it -- a slug, a
// Telegram id -- before the action goes; without it, yes or no.
const props = defineProps<{ message: string; expected?: string | null }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { t } = useI18n()
const typed = ref('')
const ready = computed(() => !props.expected || typed.value === props.expected)
</script>

<template>
  <div role="dialog" class="confirm" data-test="confirm">
    <p data-test="confirm-message">{{ message }}</p>
    <input v-if="expected" v-model="typed" data-test="confirm-input" />
    <button type="button" :disabled="!ready" data-test="confirm-yes" @click="emit('confirm')">
      {{ t('common.yes') }}
    </button>
    <button type="button" data-test="confirm-no" @click="emit('cancel')">
      {{ t('common.no') }}
    </button>
  </div>
</template>

<style scoped>
.confirm {
  border: 1px solid var(--color-brand-primary);
  padding: 0.5rem;
}
</style>
