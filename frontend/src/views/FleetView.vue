<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApi } from '../api/client'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import type { FleetServer } from '../fleet'

// The fleet (DM-154): the servers a person sees, in the API's order -- red
// first; the page knows no rule of red and sorts nothing. Every field is
// what the box sent; one with no data says so -- never a zero it did not get.
// Read again every REFRESH_MS while the page is open.
const REFRESH_MS = 30_000

const { t } = useI18n()
const api = useApi()
const servers = ref<FleetServer[] | null>(null)
const error = ref<unknown>(null)
let timer: ReturnType<typeof setInterval> | undefined

async function load(): Promise<void> {
  try {
    servers.value = await api.get<FleetServer[]>('/api/v1/servers')
    error.value = null
  } catch (failure: unknown) {
    error.value = failure
  }
}

onMounted(() => {
  void load()
  timer = setInterval(() => void load(), REFRESH_MS)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <main class="fleet">
    <h1>{{ t('fleet.heading') }}</h1>
    <ApiErrorNote v-if="error" :error="error" />
    <p v-if="servers === null">{{ t('common.loading') }}</p>
    <p v-else-if="servers.length === 0" data-test="no-servers">{{ t('fleet.none') }}</p>
    <div v-else class="scroll">
      <table data-test="fleet">
        <thead>
          <tr>
            <th>{{ t('fleet.server') }}</th>
            <th>{{ t('fleet.project') }}</th>
            <th>{{ t('fleet.role') }}</th>
            <th>{{ t('fleet.red') }}</th>
            <th>{{ t('fleet.stands') }}</th>
            <th>{{ t('fleet.verdict') }}</th>
            <th>{{ t('fleet.health') }}</th>
            <th>{{ t('fleet.heartbeat') }}</th>
            <th>{{ t('fleet.machine') }}</th>
            <th>{{ t('fleet.ssl') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="server in servers"
            :key="server.id"
            :class="{ red: server.reasons.length > 0 }"
            :data-test="`server-${server.name}`"
          >
            <td data-test="name">{{ server.name }}</td>
            <td data-test="project">{{ server.project.name }}</td>
            <td data-test="role">{{ server.role }}</td>
            <td data-test="reasons">
              <span v-for="reason in server.reasons" :key="reason" :data-test="`reason-${reason}`">
                {{ t(`fleet.reason.${reason}`) }}
              </span>
            </td>
            <td data-test="stands">
              <template v-if="server.stacks === null">{{ t('fleet.no_data') }}</template>
              <template v-else-if="server.stacks.length === 0">{{
                t('fleet.nothing_stands')
              }}</template>
              <span v-for="part in server.stacks" v-else :key="part.stack">
                {{ part.stack }}@{{ part.release ?? t('fleet.no_data') }}
              </span>
            </td>
            <td data-test="verdict">
              <template v-if="server.verdict === null">{{ t('fleet.no_data') }}</template>
              <template v-else>
                {{ server.verdict.verb }}: {{ server.verdict.result }} ({{
                  server.verdict.finished
                }})
                <span v-if="!server.verdict.verified">— {{ t('fleet.unverified') }}</span>
              </template>
            </td>
            <td data-test="health">
              <template v-if="server.health === null">{{ t('fleet.no_data') }}</template>
              <template v-else>
                {{ server.health.healthy }} / {{ server.health.unhealthy }} /
                {{ server.health.starting }} / {{ server.health.none }}
              </template>
            </td>
            <td data-test="heartbeat">{{ server.heartbeat_at ?? t('fleet.no_data') }}</td>
            <td data-test="machine">
              {{ server.machine_version ?? t('fleet.no_data') }} ({{ server.machine_release }})
            </td>
            <td data-test="ssl">
              <template v-if="server.ssl === null">{{ t('fleet.no_data') }}</template>
              <template v-else>{{ server.ssl.mode }}, {{ server.ssl.expires }}</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>

<style scoped>
.scroll {
  overflow-x: auto;
}

tr.red td[data-test='reasons'] {
  color: var(--color-brand-primary);
  font-weight: var(--font-weight-heading);
}
</style>
