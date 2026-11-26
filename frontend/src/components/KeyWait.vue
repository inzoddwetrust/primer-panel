<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { waitsUntil, type KeyWait } from '../run'

// A run waiting for a key to a repository (DM-159): the public key -- no
// secret, shown to everybody who sees the server -- the page of the
// repository's deploy keys when the machine named one (a GitHub address), with
// which rights, until when; and how it stands. The box goes on by itself once
// the key works: nothing here sends anything. With `serverId` (the card) it
// leads to its run.
const props = defineProps<{ wait: KeyWait; serverId?: string }>()
const { t } = useI18n()
const until = computed(() => waitsUntil(props.wait))

async function copy(): Promise<void> {
  await navigator.clipboard.writeText(props.wait.key)
}
</script>

<template>
  <section class="key-wait" data-test="key-wait">
    <h2>{{ t(`key.state.${wait.state}`) }}</h2>
    <p data-test="key-repo">
      {{ wait.write ? t('key.write') : t('key.read') }} <code>{{ wait.repo }}</code>
    </p>
    <p v-if="wait.write && wait.why" data-test="key-why">{{ wait.why }}</p>
    <pre data-test="key-key">{{ wait.key }}</pre>
    <button type="button" data-test="key-copy" @click="copy">{{ t('key.copy') }}</button>
    <p v-if="wait.page">
      <a :href="wait.page" target="_blank" rel="noopener noreferrer" data-test="key-page">{{
        t('key.page')
      }}</a>
    </p>
    <template v-if="wait.state === 'waiting'">
      <p v-if="until" data-test="key-until">{{ t('key.until') }} {{ until }}</p>
      <p v-else data-test="key-no-wait">{{ t('key.no_wait') }}</p>
      <p v-if="wait.again" data-test="key-again">{{ t('key.again') }}</p>
    </template>
    <p v-if="wait.state === 'not_granted' && wait.reason" data-test="key-reason">
      {{ wait.reason }}
    </p>
    <p v-if="serverId">
      <RouterLink
        :to="{ name: 'run', params: { serverId, runId: wait.run_id } }"
        data-test="key-run"
        >{{ t('key.run') }}</RouterLink
      >
    </p>
  </section>
</template>

<style scoped>
.key-wait {
  border: 1px solid var(--color-brand-primary);
  padding: 0.5rem;
}
.key-wait pre {
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
