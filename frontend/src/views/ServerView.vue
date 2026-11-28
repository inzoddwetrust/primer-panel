<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, useApi } from '../api/client'
import { apiPath } from '../api/paths'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import ConfirmBox from '../components/ConfirmBox.vue'
import KeyWaitNote from '../components/KeyWait.vue'
import SchemaForm from '../components/SchemaForm.vue'
import type { FleetServer } from '../fleet'
import type { KeyWait } from '../run'
import {
  argsFrom,
  emptyForm,
  label,
  missing,
  needsName,
  rollsBack,
  type Button,
  type FormValues,
  type RunRow,
} from '../server'

// A server's card (DM-155): the head (the fleet's row), what stands on it --
// as the box measured it; what is recorded has no source -- its runs, and
// the verbs of the machine the person may queue, as buttons. Each button is
// data of the API: its form, its presets and how it is confirmed -- the
// server's name typed exactly for the destructive, "are you sure?" on prod
// (R-18). Read again every REFRESH_MS while the page is open.
const props = defineProps<{ serverId: string }>()
const REFRESH_MS = 30_000

const { t } = useI18n()
const api = useApi()
const head = ref<FleetServer | null>(null)
const runs = ref<RunRow[]>([])
const keyWait = ref<KeyWait | null>(null)
const buttons = ref<Button[]>([])
const missingServer = ref(false)
const error = ref<unknown>(null)
const chosen = ref<Button | null>(null)
const values = ref<FormValues>(emptyForm())
const asked = ref(false)
const pending = ref<{ expected: string | null; args: Record<string, unknown> } | null>(null)
const queued = ref<string | null>(null)
const busy = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

const base = () => apiPath`/api/v1/servers/${props.serverId}`

async function load(): Promise<void> {
  try {
    const [found, history] = await Promise.all([
      api.get<FleetServer>(base()),
      api.get<RunRow[]>(apiPath`${base()}/runs`),
    ])
    head.value = found
    runs.value = history
  } catch (failure: unknown) {
    if (failure instanceof ApiError && failure.status === 404) {
      missingServer.value = true
      return
    }
    error.value = failure
  }
}

// The wait for a key of the server's running run (DM-159); a server not seen
// is the head's to say, as for the buttons.
async function loadKey(): Promise<void> {
  try {
    keyWait.value = await api.get<KeyWait | null>(apiPath`${base()}/key-wait`)
  } catch (failure: unknown) {
    if (!(failure instanceof ApiError && failure.status === 404)) error.value = failure
  }
}

async function loadButtons(): Promise<void> {
  try {
    buttons.value = await api.get<Button[]>(apiPath`${base()}/verbs`)
  } catch (failure: unknown) {
    if (!(failure instanceof ApiError && failure.status === 404)) error.value = failure
  }
}

function choose(button: Button): void {
  chosen.value = button
  values.value = emptyForm()
  asked.value = false
  queued.value = null
  error.value = null
}

async function send(args: Record<string, unknown>, confirmed: boolean): Promise<void> {
  if (!chosen.value) return
  busy.value = true
  pending.value = null
  try {
    await api.post(apiPath`${base()}/commands`, { verb: chosen.value.verb, args, confirmed })
    queued.value = label(chosen.value)
    error.value = null
  } catch (failure: unknown) {
    error.value = failure
  } finally {
    busy.value = false
  }
}

function submit(): void {
  if (!chosen.value || !head.value) return
  let args: Record<string, unknown>
  try {
    args = argsFrom(chosen.value, values.value)
  } catch {
    error.value = new ApiError(0, 'invalid', t('server.bad_json'), null)
    return
  }
  if (missing(chosen.value, args).length > 0) {
    error.value = new ApiError(0, 'invalid', t('server.required'), null)
    return
  }
  if (needsName(chosen.value, args, asked.value)) {
    pending.value = { expected: head.value.name, args }
  } else if (chosen.value.sure || rollsBack(chosen.value, args, head.value.machine_version)) {
    pending.value = { expected: null, args }
  } else {
    void send(args, false)
  }
}

function confirm(): void {
  if (!pending.value || !head.value) return
  const args = { ...pending.value.args }
  if (pending.value.expected !== null) {
    args['confirm'] = pending.value.expected
  }
  void send(args, true)
}

onMounted(() => {
  void load()
  void loadButtons()
  void loadKey()
  timer = setInterval(() => {
    void load()
    void loadKey()
  }, REFRESH_MS)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <main class="server">
    <p v-if="missingServer" data-test="not-found">{{ t('common.not_found') }}</p>
    <template v-else>
      <ApiErrorNote v-if="error" :error="error" />
      <template v-if="head">
        <h1 data-test="server-name">{{ head.name }}</h1>
        <p>
          <RouterLink :to="{ name: 'passport', params: { serverId } }" data-test="to-passport">{{
            t('passport.title')
          }}</RouterLink>
        </p>
        <p data-test="head">
          {{ head.project.name }} · {{ head.role }} · {{ t('fleet.heartbeat') }}:
          {{ head.heartbeat_at ?? t('fleet.no_data') }} · {{ t('fleet.machine') }}:
          {{ head.machine_version ?? t('fleet.no_data') }} ({{ head.machine_release }}) ·
          {{ t('fleet.ssl') }}:
          {{ head.ssl ? `${head.ssl.mode}, ${head.ssl.expires}` : t('fleet.no_data') }}
        </p>
        <p v-if="head.reasons.length" data-test="reasons">
          <span v-for="reason in head.reasons" :key="reason"
            >{{ t(`fleet.reason.${reason}`) }}
          </span>
        </p>
        <KeyWaitNote v-if="keyWait" :wait="keyWait" :server-id="serverId" />
        <h2>{{ t('server.stands') }}</h2>
        <p v-if="head.stacks === null" data-test="stands">{{ t('fleet.no_data') }}</p>
        <ul v-else data-test="stands">
          <li v-for="part in head.stacks" :key="part.stack">
            {{ part.stack }}@{{ part.release ?? t('fleet.no_data') }}
          </li>
        </ul>
      </template>

      <h2>{{ t('server.actions') }}</h2>
      <p v-if="buttons.length === 0" data-test="no-buttons">{{ t('server.no_actions') }}</p>
      <div class="buttons" data-test="buttons">
        <button
          v-for="button in buttons"
          :key="label(button)"
          type="button"
          :data-test="`button-${label(button)}`"
          @click="choose(button)"
        >
          {{ label(button) }}
        </button>
      </div>
      <form v-if="chosen" data-test="command" @submit.prevent="submit">
        <h3>{{ label(chosen) }}</h3>
        <SchemaForm v-model:values="values" :button="chosen" />
        <label v-if="chosen.name === 'ask'" data-test="ask">
          <input v-model="asked" type="checkbox" /> {{ t('server.ask_destructive') }}
        </label>
        <button type="submit" :disabled="busy" data-test="queue">{{ t('server.queue') }}</button>
      </form>
      <ConfirmBox
        v-if="pending"
        :message="pending.expected !== null ? t('server.type_name') : t('server.sure')"
        :expected="pending.expected"
        @confirm="confirm"
        @cancel="pending = null"
      />
      <p v-if="queued" data-test="queued">{{ t('server.queued') }} {{ queued }}</p>

      <h2>{{ t('server.runs') }}</h2>
      <p v-if="runs.length === 0" data-test="no-runs">{{ t('server.no_runs') }}</p>
      <ul data-test="runs">
        <li v-for="run in runs" :key="run.run_id" :data-test="`run-${run.run_id}`">
          <RouterLink :to="{ name: 'run', params: { serverId, runId: run.run_id } }">
            {{ run.verb ?? t('fleet.no_data') }} · {{ run.started_at ?? t('fleet.no_data') }}
          </RouterLink>
          ·
          <span v-if="run.running" data-test="running">{{ t('server.running') }}</span>
          <span v-else-if="run.verdict">
            {{ run.verdict.result }}
            <span v-if="!run.verdict.verified">— {{ t('fleet.unverified') }}</span>
          </span>
          <span v-else>{{ run.outcome ?? t('fleet.no_data') }}</span>
        </li>
      </ul>
    </template>
  </main>
</template>

<style scoped>
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>
