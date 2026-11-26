<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ApiError, ApiNetworkError } from '../api/client'
import { PathSegmentError } from '../api/paths'

// An error of the API, as the page shows every one: its class and message,
// the request's id; a request that never reached the API, or no answer; a
// request the page did not make, its address not being of its form (DM-210).
defineProps<{ error: unknown }>()
const { t } = useI18n()
</script>

<template>
  <section role="alert" data-test="api-error">
    <template v-if="error instanceof ApiError">
      <code data-test="error-class">{{ error.errorClass }}</code>
      <span data-test="error-message"> {{ error.message }}</span>
      <span v-if="error.requestId"> ({{ t('error.request_id') }} {{ error.requestId }})</span>
    </template>
    <span v-else-if="error instanceof ApiNetworkError">{{ t('error.network') }}</span>
    <span v-else-if="error instanceof PathSegmentError" data-test="error-path">{{
      t('error.path')
    }}</span>
    <span v-else>{{ t('error.timeout') }}</span>
  </section>
</template>
