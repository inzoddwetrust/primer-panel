<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError, ApiNetworkError, useApi } from '../api/client'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import { useMeStore } from '../stores/me'

const { t } = useI18n()
const api = useApi()
const router = useRouter()
const store = useMeStore()
const { me, error } = storeToRefs(store)

// A refused sign-out stays on the screen: the person is still signed in,
// the store is kept and the page stays (DM-212).
const logoutError = ref<unknown>(null)

async function logout(): Promise<void> {
  logoutError.value = null
  try {
    await api.post('/auth/logout')
  } catch (failure: unknown) {
    logoutError.value = failure
    return
  }
  store.clear()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <main class="me">
    <h1>{{ t('me.heading') }}</h1>
    <section v-if="error" role="alert" data-test="api-error">
      <template v-if="error instanceof ApiError">
        <p>
          <code data-test="error-class">{{ error.errorClass }}</code>
          <span data-test="error-message"> {{ error.message }}</span>
        </p>
        <p v-if="error.requestId" data-test="request-id">
          {{ t('error.request_id') }} {{ error.requestId }}
        </p>
      </template>
      <p v-else-if="error instanceof ApiNetworkError">{{ t('error.network') }}</p>
      <p v-else>{{ t('error.timeout') }}</p>
    </section>
    <section v-else-if="me" data-test="me">
      <p data-test="name">{{ me.user.first_name ?? me.user.username }}</p>
      <p data-test="telegram-id">{{ t('me.telegram_id') }} {{ me.user.telegram_id }}</p>
      <p v-if="me.is_superadmin" data-test="superadmin">{{ t('me.superadmin') }}</p>
      <h2>{{ t('me.projects') }}</h2>
      <ul v-if="me.projects.length" data-test="projects">
        <li v-for="access in me.projects" :key="access.project.id">
          {{ access.project.name }}
          <span v-if="access.is_admin">({{ t('me.admin') }})</span>
          <code>{{ access.permissions.join(', ') }}</code>
        </li>
      </ul>
      <p v-else data-test="no-projects">{{ t('me.no_projects') }}</p>
      <RouterLink :to="{ name: 'projects' }" data-test="projects-link">
        {{ t('me.projects_link') }}
      </RouterLink>
      <button type="button" data-test="logout" @click="logout">{{ t('me.logout') }}</button>
      <ApiErrorNote v-if="logoutError" :error="logoutError" />
    </section>
    <p v-else>{{ t('me.loading') }}</p>
  </main>
</template>
