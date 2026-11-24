<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useApi } from '../api/client'
import type { Project } from '../access'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import { useMeStore } from '../stores/me'

// The projects a person sees (the API answers only theirs; the superadmin's,
// all), and the superadmin's form of a new project.
const { t } = useI18n()
const api = useApi()
const { me } = storeToRefs(useMeStore())
const projects = ref<Project[] | null>(null)
const error = ref<unknown>(null)
const form = reactive({ slug: '', name: '', kind: 'product', repo: '' })

async function load(): Promise<void> {
  try {
    projects.value = await api.get<Project[]>('/api/v1/projects')
  } catch (failure: unknown) {
    error.value = failure
  }
}

async function create(): Promise<void> {
  error.value = null
  try {
    await api.post('/api/v1/projects', { ...form })
    Object.assign(form, { slug: '', name: '', kind: 'product', repo: '' })
    await load()
  } catch (failure: unknown) {
    error.value = failure
  }
}

onMounted(load)
</script>

<template>
  <main class="projects">
    <h1>{{ t('projects.heading') }}</h1>
    <ApiErrorNote v-if="error" :error="error" />
    <p v-if="projects === null">{{ t('common.loading') }}</p>
    <p v-else-if="projects.length === 0" data-test="no-projects">{{ t('projects.none') }}</p>
    <ul v-else data-test="projects">
      <li v-for="project in projects" :key="project.id">
        <RouterLink :to="{ name: 'project', params: { projectId: project.id } }">
          {{ project.name }}
        </RouterLink>
        ({{ t(`projects.kind_${project.kind}`) }})
        <span v-if="project.archived_at">— {{ t('projects.archived') }}</span>
      </li>
    </ul>
    <form v-if="me?.is_superadmin" data-test="new-project" @submit.prevent="create">
      <h2>{{ t('projects.new') }}</h2>
      <label>{{ t('projects.slug') }} <input v-model="form.slug" data-test="slug" /></label>
      <label>{{ t('projects.name') }} <input v-model="form.name" data-test="name" /></label>
      <label>
        {{ t('projects.kind') }}
        <select v-model="form.kind" data-test="kind">
          <option value="product">{{ t('projects.kind_product') }}</option>
          <option value="service">{{ t('projects.kind_service') }}</option>
        </select>
      </label>
      <label>{{ t('projects.repo') }} <input v-model="form.repo" data-test="repo" /></label>
      <button type="submit" data-test="create">{{ t('projects.create') }}</button>
    </form>
  </main>
</template>
