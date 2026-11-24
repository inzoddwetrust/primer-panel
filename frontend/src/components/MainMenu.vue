<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useMeStore } from '../stores/me'

// The menu of the Panel (DM-154): the fleet, the projects, the superadmin's
// admins, the person.
const { t } = useI18n()
const { me } = storeToRefs(useMeStore())
</script>

<template>
  <nav class="menu" data-test="menu">
    <RouterLink :to="{ name: 'fleet' }">{{ t('menu.fleet') }}</RouterLink>
    <RouterLink :to="{ name: 'projects' }">{{ t('menu.projects') }}</RouterLink>
    <RouterLink v-if="me?.is_superadmin" :to="{ name: 'admins' }" data-test="menu-admins">
      {{ t('menu.admins') }}
    </RouterLink>
    <RouterLink :to="{ name: 'me' }">{{ t('menu.me') }}</RouterLink>
  </nav>
</template>

<style scoped>
.menu {
  display: flex;
  gap: 1rem;
}
</style>
