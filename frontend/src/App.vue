<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import MainMenu from './components/MainMenu.vue'

defineProps<{ error: string | null }>()
const { t } = useI18n()
</script>

<template>
  <div class="app">
    <header>
      <span class="logo" role="img" :aria-label="t('title')" data-test="logo"></span>
      <span data-test="title">{{ t('title') }}</span>
    </header>
    <p v-if="error" role="alert" data-test="config-error">{{ t('config_error') }} {{ error }}</p>
    <template v-else>
      <MainMenu />
      <RouterView />
    </template>
  </div>
</template>

<style scoped>
/* Colors, fonts and the logo come only from the theme's custom properties
   (src/theme.css): no literal here. */
header {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.logo {
  width: 2rem;
  height: 2rem;
  background-image: var(--asset-logo);
  background-repeat: no-repeat;
  background-size: contain;
}

header span[data-test='title'] {
  color: var(--color-brand-primary);
  font-weight: var(--font-weight-heading);
}
</style>
