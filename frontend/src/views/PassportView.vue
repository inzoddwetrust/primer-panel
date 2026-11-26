<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, useApi } from '../api/client'
import { apiPath } from '../api/paths'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import ConfirmBox from '../components/ConfirmBox.vue'
import type { FleetServer } from '../fleet'
import {
  dotted,
  kindOf,
  mayEdit,
  ruleOf,
  short,
  shown,
  textOf,
  valueOf,
  type Edited,
  type Field,
  type Kind,
  type Passport,
} from '../passport'
import { useMeStore } from '../stores/me'

// A server's passport (DM-158): read from primer-ops, the secrets by name and
// state only. With the permission `passport` a field is changed, a secret
// typed in, and "apply" queues `update` ("are you sure?" on prod). Read
// once, after an action that went, and by "read again": every reading is a
// fetch of primer-ops. A refusal stays on the screen (no reading after it).
// A secret's value is wiped from the page as its request leaves -- whatever
// the answer, the person types it again.
const props = defineProps<{ serverId: string }>()

const { t } = useI18n()
const api = useApi()
const me = useMeStore()
const head = ref<FleetServer | null>(null)
const passport = ref<Passport | null>(null)
const missingServer = ref(false)
const error = ref<unknown>(null)
const busy = ref(false)
const saved = ref<Edited | null>(null)
const queued = ref(false)
const asking = ref(false)

interface FieldEdit {
  path: string[]
  kind: Kind
  text: string
  checked: boolean
}
const editing = ref<FieldEdit | null>(null)

interface SecretEdit {
  stack: string
  key: string
  tls: 'cert' | 'key' | null
  known: boolean
  value: string
}
const secret = ref<SecretEdit | null>(null)

const base = () => apiPath`/api/v1/servers/${props.serverId}`
const editable = computed(() => head.value !== null && mayEdit(me.me, head.value.project.id))

async function act(run: () => Promise<unknown>): Promise<void> {
  busy.value = true
  error.value = null
  try {
    await run()
  } catch (failure: unknown) {
    error.value = failure
  } finally {
    busy.value = false
  }
}

async function load(): Promise<void> {
  await act(async () => {
    try {
      const [found, read] = await Promise.all([
        api.get<FleetServer>(base()),
        api.get<Passport>(apiPath`${base()}/passport`),
      ])
      head.value = found
      passport.value = read
    } catch (failure: unknown) {
      if (failure instanceof ApiError && failure.status === 404) {
        missingServer.value = true
        return
      }
      throw failure
    }
  })
}

async function actThenLoad(run: () => Promise<unknown>): Promise<void> {
  await act(run)
  if (!error.value) await load()
}

function startField(field: Field): void {
  saved.value = null
  editing.value = {
    path: field.path,
    kind: kindOf(field.value),
    text: textOf(field.value),
    checked: field.value === true,
  }
}

function saveField(): void {
  const edit = editing.value
  if (!edit || !shown(passport.value)) return
  let value: unknown
  try {
    // v-model of an input of type number gives a number: the text, always
    value = valueOf(edit.kind, String(edit.text), edit.checked)
  } catch {
    error.value = new ApiError(0, 'invalid', t('passport.bad_json'), null)
    return
  }
  const body = { base: passport.value.base, path: edit.path, value }
  void actThenLoad(async () => {
    saved.value = await api.put<Edited>(apiPath`${base()}/passport/field`, body)
    editing.value = null
  })
}

function startSecret(stack: string, key: string, tls: 'cert' | 'key' | null): void {
  saved.value = null
  secret.value = { stack, key, tls, known: stack !== '' || tls !== null, value: '' }
}

function saveSecret(): void {
  const edit = secret.value
  if (!edit || !shown(passport.value) || edit.value === '') return
  const body: Record<string, unknown> = { base: passport.value.base, value: edit.value }
  if (edit.tls !== null) body['tls'] = edit.tls
  else Object.assign(body, { stack: edit.stack, key: edit.key })
  // the value leaves the page with this request: wiped after any answer
  edit.value = ''
  void actThenLoad(async () => {
    saved.value = await api.put<Edited>(apiPath`${base()}/passport/secret`, body)
    secret.value = null
  })
}

function apply(): void {
  if (head.value?.role === 'prod') {
    asking.value = true
  } else {
    void send(false)
  }
}

async function send(confirmed: boolean): Promise<void> {
  asking.value = false
  queued.value = false
  await actThenLoad(async () => {
    await api.post(apiPath`${base()}/passport/apply`, { confirmed })
    queued.value = true
  })
}

async function copyKey(key: string): Promise<void> {
  await navigator.clipboard.writeText(key)
}

onMounted(() => void load())
</script>

<template>
  <main class="passport">
    <p v-if="missingServer" data-test="not-found">{{ t('common.not_found') }}</p>
    <template v-else>
      <h1>
        {{ t('passport.title') }}<template v-if="head"> · {{ head.name }}</template>
      </h1>
      <p>
        <RouterLink :to="{ name: 'server', params: { serverId } }" data-test="to-server">{{
          t('passport.to_server')
        }}</RouterLink>
        ·
        <button type="button" :disabled="busy" data-test="reread" @click="load">
          {{ t('passport.reread') }}
        </button>
      </p>
      <ApiErrorNote v-if="error" :error="error" />
      <p v-if="saved" data-test="saved">{{ t('passport.saved') }} {{ saved.version }}</p>
      <p v-if="queued" data-test="queued">{{ t('passport.queued') }}</p>

      <template v-if="passport">
        <p v-if="passport.state === 'absent'" data-test="state-absent">
          {{ t('passport.absent') }}
        </p>
        <p v-else-if="passport.state === 'file'" data-test="state-file">
          {{ t('passport.file') }}
        </p>
        <p v-else-if="passport.state === 'damaged'" data-test="state-damaged">
          {{ t(`passport.damaged.${passport.reason}`) }}
        </p>
        <div v-else-if="passport.state === 'not-recipient'" data-test="state-not-recipient">
          <p>{{ t('passport.not_recipient') }}</p>
          <code data-test="panel-key">{{ passport.panel_key }}</code>
          <button type="button" data-test="copy-key" @click="copyKey(passport.panel_key)">
            {{ t('passport.copy_key') }}
          </button>
        </div>

        <template v-else>
          <p data-test="version">
            {{ t('passport.version') }} {{ passport.version }} · {{ t('passport.base') }}
            {{ short(passport.base) }}
          </p>
          <div v-if="passport.problems.length" role="alert" data-test="problems">
            <p>{{ t('passport.problems') }}</p>
            <ul>
              <li v-for="problem in passport.problems" :key="problem">{{ problem }}</li>
            </ul>
          </div>

          <h2>{{ t('passport.apply') }}</h2>
          <p data-test="apply-state">
            {{ t(`passport.apply_state.${passport.apply.state}`) }}
            <template v-if="passport.apply.commit"> · {{ short(passport.apply.commit) }} </template>
          </p>
          <button v-if="editable" type="button" :disabled="busy" data-test="apply" @click="apply">
            {{ t('passport.apply') }}
          </button>
          <ConfirmBox
            v-if="asking"
            :message="t('passport.sure')"
            @confirm="send(true)"
            @cancel="asking = false"
          />

          <h2>{{ t('passport.fields') }}</h2>
          <table data-test="fields">
            <tbody>
              <tr
                v-for="field in passport.fields"
                :key="dotted(field.path)"
                :data-test="`field-${dotted(field.path)}`"
              >
                <th>{{ dotted(field.path) }}</th>
                <td>{{ textOf(field.value) }}</td>
                <td>
                  <span v-if="ruleOf(passport, field.path)" data-test="rule">{{
                    t(`passport.rule.${ruleOf(passport, field.path)}`)
                  }}</span>
                </td>
                <td>
                  <button v-if="editable" type="button" data-test="edit" @click="startField(field)">
                    {{ t('passport.edit') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <form v-if="editing" data-test="field-form" @submit.prevent="saveField">
            <h3>{{ dotted(editing.path) }}</h3>
            <input
              v-if="editing.kind === 'boolean'"
              v-model="editing.checked"
              type="checkbox"
              data-test="field-checked"
            />
            <textarea
              v-else-if="editing.kind === 'json'"
              v-model="editing.text"
              data-test="field-json"
            ></textarea>
            <input
              v-else
              v-model="editing.text"
              :type="editing.kind === 'number' ? 'number' : 'text'"
              data-test="field-text"
            />
            <button type="submit" :disabled="busy" data-test="field-save">
              {{ t('common.save') }}
            </button>
            <button type="button" data-test="field-cancel" @click="editing = null">
              {{ t('common.cancel') }}
            </button>
          </form>

          <h2>{{ t('passport.secrets') }}</h2>
          <p v-if="passport.secrets.length === 0" data-test="no-secrets">
            {{ t('passport.no_secrets') }}
          </p>
          <ul data-test="secrets">
            <li
              v-for="item in passport.secrets"
              :key="`${item.stack}.${item.key}`"
              :data-test="`secret-${item.stack}.${item.key}`"
            >
              {{ item.stack }} · {{ item.key }} — {{ t(`passport.state.${item.state}`) }}
              <button
                v-if="editable"
                type="button"
                data-test="replace"
                @click="startSecret(item.stack, item.key, null)"
              >
                {{ t('passport.replace') }}
              </button>
            </li>
            <li
              v-for="part in passport.tls"
              :key="`tls.${part.key}`"
              :data-test="`tls-${part.key}`"
            >
              tls · {{ part.key }} — {{ t(`passport.state.${part.state}`) }}
              <button
                v-if="editable"
                type="button"
                data-test="replace"
                @click="startSecret('', '', part.key)"
              >
                {{ t('passport.replace') }}
              </button>
            </li>
          </ul>
          <button
            v-if="editable"
            type="button"
            data-test="new-secret"
            @click="startSecret('', '', null)"
          >
            {{ t('passport.new_secret') }}
          </button>
          <form v-if="secret" data-test="secret-form" @submit.prevent="saveSecret">
            <h3 v-if="secret.tls">tls · {{ secret.tls }}</h3>
            <h3 v-else-if="secret.known">{{ secret.stack }} · {{ secret.key }}</h3>
            <template v-else>
              <input v-model="secret.stack" :placeholder="t('passport.stack')" data-test="stack" />
              <input v-model="secret.key" :placeholder="t('passport.key')" data-test="key" />
            </template>
            <textarea
              v-if="secret.tls"
              v-model="secret.value"
              autocomplete="off"
              spellcheck="false"
              data-test="secret-value"
            ></textarea>
            <input
              v-else
              v-model="secret.value"
              type="password"
              autocomplete="new-password"
              data-test="secret-value"
            />
            <button type="submit" :disabled="busy || secret.value === ''" data-test="secret-save">
              {{ t('common.save') }}
            </button>
            <button type="button" data-test="secret-cancel" @click="secret = null">
              {{ t('common.cancel') }}
            </button>
          </form>
        </template>
      </template>
    </template>
  </main>
</template>
