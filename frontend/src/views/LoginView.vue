<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useRuntimeConfig } from '../config-key'
import { parseRefusal, startUrl } from '../login'

const route = useRoute()
const { t } = useI18n()
const config = useRuntimeConfig()

const invite = computed(() => {
  const value = route.query.invite
  return typeof value === 'string' && value !== '' ? value : null
})
const href = computed(() => startUrl(config.apiOrigin, invite.value))
const refusal = computed(() => parseRefusal(route.hash))
</script>

<template>
  <main class="login">
    <h1 data-test="login-heading">{{ t('login.heading') }}</h1>
    <section v-if="refusal" role="alert" data-test="refusal">
      <p v-if="refusal.reason" data-test="refusal-text">{{ t(`refusal.${refusal.reason}`) }}</p>
      <p v-else data-test="refusal-text">{{ t('refusal.unknown') }} {{ refusal.given }}</p>
      <p v-if="refusal.telegramId" data-test="telegram-id">
        {{ t('refusal.your_id') }} <strong>{{ refusal.telegramId }}</strong>
      </p>
    </section>
    <p v-if="invite" data-test="invite-note">{{ t('login.invite') }}</p>
    <a class="button" :href="href" data-test="login-button">{{ t('login.button') }}</a>
  </main>
</template>

<style scoped>
/* Colors and fonts come only from the theme's custom properties
   (src/theme.css): no literal here. */
.button {
  display: inline-block;
  padding: 0.5rem 1rem;
  background: var(--color-brand-primary);
  color: var(--color-brand-on-primary);
  text-decoration: none;
}
</style>
