<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, useApi } from '../api/client'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import ConfirmBox from '../components/ConfirmBox.vue'
import KeyWaitNote from '../components/KeyWait.vue'
import { useRuntimeConfig } from '../config-key'
import {
  ladder,
  logLines,
  useStream,
  type KeyWait,
  type Line,
  type RunPage,
  type StreamSource,
} from '../run'

// A run (DM-156): its ladder of steps live, its log, its verdict, "repeat"
// and "copy for an LLM". The lines come by the stream as the box sends them;
// the state, the report and what "repeat" queues are the API's.
const props = defineProps<{ serverId: string; runId: string }>()
const { t } = useI18n()
const api = useApi()
const open = useStream()
const config = useRuntimeConfig()
const run = ref<RunPage | null>(null)
const lines = ref<Line[]>([])
const status = ref<string | null>(null)
const missing = ref(false)
const error = ref<unknown>(null)
const all = ref(false)
const pending = ref<{ expected: string | null } | null>(null)
const queued = ref(false)
const keyWait = ref<KeyWait | null>(null)
let stream: StreamSource | undefined

const steps = computed(() => ladder(lines.value))
const log = computed(() => logLines(lines.value, all.value))
const more = computed(() => lines.value.filter((l) => l.event === 'log').length > log.value.length)
const base = () => `/api/v1/servers/${props.serverId}/runs/${props.runId}`

async function load(): Promise<void> {
  try {
    run.value = await api.get<RunPage>(base())
    status.value = run.value.status
    keyWait.value = run.value.key_wait
  } catch (failure: unknown) {
    if (failure instanceof ApiError && failure.status === 404) {
      missing.value = true
      return
    }
    error.value = failure
  }
}

function listen(): void {
  stream = open(`${config.apiOrigin}/api/v1/streams/servers/${props.serverId}/runs/${props.runId}`)
  stream.addEventListener('line', (event) => {
    lines.value = [...lines.value, JSON.parse(event.data) as Line]
  })
  stream.addEventListener('key', (event) => {
    keyWait.value = JSON.parse(event.data) as KeyWait | null
  })
  stream.addEventListener('status', (event) => {
    const next = (JSON.parse(event.data) as { status: string }).status
    status.value = next
    if (next === 'finished' || next === 'abandoned') {
      stream?.close()
      void load()
    }
  })
}

async function copy(): Promise<void> {
  if (run.value?.report_llm != null) {
    await navigator.clipboard.writeText(run.value.report_llm)
  }
}

async function send(confirmed: boolean, name: string | null): Promise<void> {
  const repeat = run.value?.repeat
  if (!repeat) return
  pending.value = null
  const args = name === null ? { ...repeat.args } : { ...repeat.args, confirm: name }
  try {
    await api.post(`/api/v1/servers/${props.serverId}/commands`, {
      verb: repeat.verb,
      args,
      confirmed,
    })
    queued.value = true
    error.value = null
  } catch (failure: unknown) {
    error.value = failure
  }
}

function again(): void {
  const repeat = run.value?.repeat
  if (!repeat || !run.value) return
  if (repeat.name) {
    pending.value = { expected: run.value.server_name }
  } else if (repeat.sure) {
    pending.value = { expected: null }
  } else {
    void send(false, null)
  }
}

onMounted(async () => {
  await load()
  if (!missing.value) listen()
})
onBeforeUnmount(() => stream?.close())
</script>

<template>
  <main class="run">
    <p v-if="missing" data-test="not-found">{{ t('common.not_found') }}</p>
    <template v-else>
      <ApiErrorNote v-if="error" :error="error" />
      <h1>{{ run?.verb ?? t('fleet.no_data') }} · {{ runId }}</h1>
      <p data-test="status">{{ status ? t(`run.status.${status}`) : t('common.loading') }}</p>
      <KeyWaitNote v-if="keyWait" :wait="keyWait" />
      <p v-if="run?.verdict" data-test="verdict">
        {{ run.verdict.result }} ({{ run.verdict.exit_code }}, {{ run.verdict.finished }})
        <span v-if="!run.verdict.verified">— {{ t('fleet.unverified') }}</span>
      </p>
      <div class="actions">
        <button v-if="run?.repeat" type="button" data-test="repeat" @click="again">
          {{ t('run.repeat') }}
        </button>
        <span v-else-if="run" data-test="no-repeat">{{ t('run.repeat_from_card') }}</span>
        <button v-if="run?.report_llm != null" type="button" data-test="copy" @click="copy">
          {{ t('run.copy') }}
        </button>
      </div>
      <ConfirmBox
        v-if="pending"
        :message="pending.expected !== null ? t('server.type_name') : t('server.sure')"
        :expected="pending.expected"
        @confirm="send(true, pending?.expected ?? null)"
        @cancel="pending = null"
      />
      <p v-if="queued" data-test="queued">{{ t('server.queued') }} {{ run?.repeat?.verb }}</p>

      <h2>{{ t('run.steps') }}</h2>
      <ol data-test="ladder">
        <li v-for="step in steps" :key="step.key" :data-test="`step-${step.name}`">
          {{ step.phase }} / {{ step.stack }} / {{ step.name }} —
          <span data-test="step-status">{{ step.status }}</span>
          <span v-if="step.duration_s !== null"> ({{ step.duration_s }} s)</span>
          <code v-if="step.reason">{{ JSON.stringify(step.reason) }}</code>
        </li>
      </ol>

      <h2>{{ t('run.log') }}</h2>
      <p v-if="log.length === 0" data-test="no-log">{{ t('run.no_log') }}</p>
      <pre
        v-else
        data-test="log"
      ><span v-for="entry in log" :key="String(entry.seq)" :class="String(entry['stream'])">{{ String(entry['at']) }} {{ String(entry['stack']) }}/{{ String(entry['name']) }} {{ String(entry['line']) }}
</span></pre>
      <button v-if="more" type="button" data-test="show-all" @click="all = true">
        {{ t('run.show_all') }}
      </button>
    </template>
  </main>
</template>

<style scoped>
pre {
  overflow-x: auto;
}

.stderr {
  color: var(--color-brand-primary);
}
</style>
