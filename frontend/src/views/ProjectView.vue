<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { ApiError, useApi } from '../api/client'
import {
  cell,
  inviteLink,
  inviteState,
  mayChange,
  personName,
  setToSend,
  staffTouched,
  visiblePermissions,
  type Invite,
  type Member,
  type Person,
  type Project,
} from '../access'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import ConfirmBox from '../components/ConfirmBox.vue'
import { useMeStore } from '../stores/me'

// A project: its people and their permissions, the superadmin's admin, the
// invites. Every action goes through the API, which checks it again
// (DM-149); the page shows only what the person may do (gate DM-152).
const props = defineProps<{ projectId: string }>()
const { t } = useI18n()
const api = useApi()
const { me } = storeToRefs(useMeStore())

const project = ref<Project | null>(null)
const members = ref<Member[]>([])
const all = ref<string[]>([])
const invites = ref<Invite[]>([])
const users = ref<Person[]>([])
const error = ref<unknown>(null)
const missing = ref(false)

const superadmin = computed(() => me.value?.is_superadmin === true)
const held = computed(
  () =>
    me.value?.projects.find((access) => access.project.id === props.projectId)?.permissions ?? [],
)
const visible = computed(() => visiblePermissions(all.value, held.value, superadmin.value))
const givesPeople = computed(() => superadmin.value || held.value.includes('people'))
const hasAdmin = computed(() => members.value.some((member) => member.is_admin))
const strangers = computed(() =>
  users.value.filter((user) => !members.value.some((member) => member.user.id === user.id)),
)

interface Pending {
  message: string
  expected: string | null
  run: () => Promise<void>
}
const pending = ref<Pending | null>(null)
const editing = ref<Member | null>(null)
const chosen = ref<string[]>([])
const appoint = reactive({ userId: '', permissions: [] as string[] })
const invite = reactive({ isAdmin: false, permissions: [] as string[], ttlHours: 168 })
const link = ref<string | null>(null)

const base = computed(() => `/api/v1/projects/${props.projectId}`)

async function act(run: () => Promise<unknown>): Promise<void> {
  error.value = null
  try {
    await run()
  } catch (failure: unknown) {
    error.value = failure
  }
}

// An action, then the page read again -- only when it went: a refusal stays
// on the screen (a reload would clear it).
async function actThenLoad(run: () => Promise<unknown>): Promise<void> {
  await act(run)
  if (!error.value) {
    await load()
  }
}

async function load(): Promise<void> {
  await act(async () => {
    try {
      const [found, people, list] = await Promise.all([
        api.get<Project>(base.value),
        api.get<Member[]>(`${base.value}/members`),
        api.get<{ permissions: string[] }>('/api/v1/permissions'),
      ])
      project.value = found
      members.value = people
      all.value = list.permissions
    } catch (failure: unknown) {
      if (failure instanceof ApiError && failure.status === 404) {
        missing.value = true
        return
      }
      throw failure
    }
    if (givesPeople.value) {
      invites.value = await api.get<Invite[]>(`${base.value}/invites`)
    }
    if (superadmin.value) {
      users.value = await api.get<Person[]>('/api/v1/users')
    }
  })
}

function ask(message: string, expected: string | null, run: () => Promise<unknown>): void {
  pending.value = {
    message,
    expected,
    run: async () => {
      pending.value = null
      await actThenLoad(run)
    },
  }
}

function edit(member: Member): void {
  editing.value = member
  const shown = member.is_admin ? all.value : visible.value
  chosen.value = member.permissions.filter((permission) => shown.includes(permission))
}

function save(member: Member): void {
  const shown = member.is_admin ? all.value : visible.value
  const sent = setToSend(all.value, chosen.value, member.permissions, shown)
  const put = async () => {
    await api.put(`${base.value}/members/${member.user.id}/permissions`, { permissions: sent })
    editing.value = null
  }
  const taken = member.permissions.filter((permission) => !sent.includes(permission))
  if (member.is_admin && taken.length > 0) {
    const count = staffTouched(members.value, taken)
    ask(t('project.take_confirm', { count }), null, put)
    return
  }
  void actThenLoad(put)
}

function revoke(member: Member): void {
  const run = () => api.post(`${base.value}/members/${member.user.id}/revoke`)
  if (member.is_admin) {
    ask(t('project.revoke_admin_confirm'), String(member.user.telegram_id), run)
  } else {
    ask(t('project.revoke_staff_confirm'), null, run)
  }
}

function archive(): void {
  if (project.value) {
    ask(t('project.archive_confirm'), project.value.slug, () => api.post(`${base.value}/archive`))
  }
}

async function appointAdmin(): Promise<void> {
  await actThenLoad(() =>
    api.post(`${base.value}/admins`, {
      user_id: appoint.userId,
      permissions: appoint.permissions,
    }),
  )
}

async function createInvite(): Promise<void> {
  await act(async () => {
    const made = await api.post<{ token: string }>(`${base.value}/invites`, {
      permissions: invite.permissions,
      is_admin: superadmin.value && invite.isAdmin,
      ttl_hours: invite.ttlHours,
    })
    link.value = inviteLink(window.location.origin, made.token)
  })
  invites.value = givesPeople.value ? await api.get<Invite[]>(`${base.value}/invites`) : []
}

function revokeInvite(item: Invite): void {
  ask(t('invites.revoke_confirm'), null, () => api.post(`${base.value}/invites/${item.id}/revoke`))
}

async function copy(): Promise<void> {
  if (link.value) {
    await navigator.clipboard.writeText(link.value)
  }
}

onMounted(load)
</script>

<template>
  <main class="project">
    <p v-if="missing" data-test="not-found">{{ t('common.not_found') }}</p>
    <template v-else>
      <ApiErrorNote v-if="error" :error="error" />
      <ConfirmBox
        v-if="pending"
        :message="pending.message"
        :expected="pending.expected"
        @confirm="pending.run()"
        @cancel="pending = null"
      />
      <h1 v-if="project" data-test="project-name">{{ project.name }}</h1>
      <button
        v-if="superadmin && project && !project.archived_at"
        type="button"
        data-test="archive"
        @click="archive"
      >
        {{ t('project.archive') }}
      </button>

      <RouterLink
        v-if="superadmin || held.includes('servers')"
        :to="{ name: 'add-server', params: { projectId } }"
        data-test="add-server"
      >
        {{ t('add_server.link') }}
      </RouterLink>
      <h2>{{ t('project.members') }}</h2>
      <p v-if="!hasAdmin" data-test="no-admin">{{ t('project.no_admin') }}</p>
      <p v-if="members.length === 0">{{ t('project.nobody') }}</p>
      <ul data-test="members">
        <li
          v-for="member in members"
          :key="member.user.id"
          :data-test="`member-${member.user.telegram_id}`"
        >
          {{ personName(member.user) }} ({{ member.user.telegram_id }})
          <span v-if="member.is_admin">— {{ t('project.admin') }}</span>
          <code data-test="effective">{{ member.effective.join(', ') }}</code>
          <template v-if="mayChange(member, held, superadmin)">
            <button type="button" data-test="edit" @click="edit(member)">
              {{ t('project.edit') }}
            </button>
            <button type="button" data-test="revoke" @click="revoke(member)">
              {{ t('project.revoke') }}
            </button>
          </template>
          <form
            v-if="editing?.user.id === member.user.id"
            data-test="editor"
            @submit.prevent="save(member)"
          >
            <label
              v-for="permission in member.is_admin ? all : visible"
              :key="permission"
              :data-test="`perm-${permission}`"
            >
              <input
                type="checkbox"
                :value="permission"
                :checked="cell(member, permission).fixed || chosen.includes(permission)"
                :disabled="cell(member, permission).fixed"
                @change="
                  chosen = chosen.includes(permission)
                    ? chosen.filter((p) => p !== permission)
                    : [...chosen, permission]
                "
              />
              {{ permission }}
            </label>
            <button type="submit" data-test="save">{{ t('common.save') }}</button>
            <button type="button" @click="editing = null">{{ t('common.cancel') }}</button>
          </form>
        </li>
      </ul>

      <form v-if="superadmin" data-test="appoint" @submit.prevent="appointAdmin">
        <h3>{{ t('project.appoint') }}</h3>
        <select v-model="appoint.userId" data-test="appoint-person">
          <option v-for="user in strangers" :key="user.id" :value="user.id">
            {{ personName(user) }} ({{ user.telegram_id }})
          </option>
        </select>
        <label v-for="permission in all" :key="permission">
          <input v-model="appoint.permissions" type="checkbox" :value="permission" />
          {{ permission }}
        </label>
        <button type="submit">{{ t('project.appoint') }}</button>
      </form>

      <section v-if="givesPeople" data-test="invites">
        <h2>{{ t('invites.heading') }}</h2>
        <p v-if="invites.length === 0">{{ t('invites.none') }}</p>
        <ul>
          <li v-for="item in invites" :key="item.id" :data-test="`invite-${item.id}`">
            <code>{{ item.permissions.join(', ') }}</code>
            <span v-if="item.is_admin">— {{ t('invites.is_admin') }}</span>
            <span data-test="invite-state">{{
              t(`invites.state_${inviteState(item, new Date())}`)
            }}</span>
            <button
              v-if="inviteState(item, new Date()) === 'active'"
              type="button"
              data-test="invite-revoke"
              @click="revokeInvite(item)"
            >
              {{ t('invites.revoke') }}
            </button>
          </li>
        </ul>
        <form data-test="invite-form" @submit.prevent="createInvite">
          <label
            v-for="permission in visible"
            :key="permission"
            :data-test="`invite-perm-${permission}`"
          >
            <input v-model="invite.permissions" type="checkbox" :value="permission" />
            {{ permission }}
          </label>
          <label v-if="superadmin" data-test="invite-admin">
            <input v-model="invite.isAdmin" type="checkbox" /> {{ t('invites.is_admin') }}
          </label>
          <label>
            {{ t('invites.ttl') }}
            <input v-model.number="invite.ttlHours" type="number" min="1" max="720" />
          </label>
          <button type="submit" data-test="invite-create">{{ t('invites.create') }}</button>
        </form>
        <div v-if="link" data-test="invite-link">
          <p>{{ t('invites.link') }}</p>
          <code data-test="invite-link-text">{{ link }}</code>
          <button type="button" data-test="invite-copy" @click="copy">
            {{ t('invites.copy') }}
          </button>
          <button type="button" data-test="invite-close" @click="link = null">
            {{ t('common.close') }}
          </button>
        </div>
      </section>
    </template>
  </main>
</template>
