<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApi } from '../api/client'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import { useRuntimeConfig } from '../config-key'

// A new server of a project (DM-157): a one-time registration token -- shown
// once, here, never again -- the command a box registers with, and the wait
// for it. The token goes into the box's environment, never its arguments
// (DM-139); the command starts with a space, which keeps it out of bash's
// history for root on Ubuntu (ignorespace) -- the screen promises no more.
// What a box may answer and the release are the API's.
interface Issued {
  id: string
  token: string
  expires_at: string
  release: string
  install_url: string
  box_refusals: string[]
}
interface State {
  used_at: string | null
  expires_at: string
  server: { id: string; name: string } | null
}

const props = defineProps<{ projectId: string }>()
const POLL_MS = 5_000
const { t, te } = useI18n()
const api = useApi()
const config = useRuntimeConfig()
const issued = ref<Issued | null>(null)
const state = ref<State | null>(null)
const expired = ref(false)
const error = ref<unknown>(null)
let timer: ReturnType<typeof setInterval> | undefined

const command = computed(() =>
  issued.value
    ? ` PRIDEM_REGISTER_TOKEN=${issued.value.token} pridem register --panel ${config.apiOrigin}`
    : '',
)

function stop(): void {
  clearInterval(timer)
  timer = undefined
}

async function poll(): Promise<void> {
  if (!issued.value) return
  try {
    state.value = await api.get<State>(
      `/api/v1/projects/${props.projectId}/registration-tokens/${issued.value.id}`,
    )
    expired.value = !state.value.used_at && new Date(state.value.expires_at) <= new Date()
    if (state.value.used_at || expired.value) stop()
  } catch (failure: unknown) {
    error.value = failure
    stop()
  }
}

async function issue(): Promise<void> {
  stop()
  error.value = null
  state.value = null
  expired.value = false
  try {
    issued.value = await api.post<Issued>(`/api/v1/projects/${props.projectId}/registration-tokens`)
    timer = setInterval(() => void poll(), POLL_MS)
  } catch (failure: unknown) {
    error.value = failure
  }
}

onBeforeUnmount(stop)
</script>

<template>
  <main class="add-server">
    <h1>{{ t('add_server.heading') }}</h1>
    <ApiErrorNote v-if="error" :error="error" />
    <button type="button" data-test="issue" @click="issue">{{ t('add_server.issue') }}</button>
    <template v-if="issued">
      <p data-test="once">{{ t('add_server.once') }}</p>
      <h2>{{ t('add_server.box') }}</h2>
      <p data-test="needs">{{ t('add_server.needs', { release: issued.release }) }}</p>
      <pre data-test="command">{{ command }}</pre>
      <p data-test="warning">{{ t('add_server.warning') }}</p>
      <h2>{{ t('add_server.vps') }}</h2>
      <ol data-test="vps">
        <li>
          {{ t('add_server.step_machine', { release: issued.release }) }}
          <pre data-test="install">curl -fsSLO {{ issued.install_url }} && bash install.sh</pre>
        </li>
        <li>{{ t('add_server.step_product') }}</li>
        <li>{{ t('add_server.step_register') }}</li>
      </ol>
      <p v-if="state?.server" data-test="registered">
        {{ t('add_server.used') }}
        <RouterLink :to="{ name: 'server', params: { serverId: state.server.id } }">
          {{ state.server.name }}
        </RouterLink>
      </p>
      <p v-else-if="expired" data-test="expired">{{ t('add_server.expired') }}</p>
      <p v-else data-test="waiting">{{ t('add_server.waiting') }}</p>
      <h3>{{ t('add_server.refusals') }}</h3>
      <ul data-test="refusals">
        <li v-for="code in issued.box_refusals" :key="code">
          <code>{{ code }}</code>
          — {{ te(`add_server.refusal.${code}`) ? t(`add_server.refusal.${code}`) : code }}
        </li>
      </ul>
    </template>
  </main>
</template>
