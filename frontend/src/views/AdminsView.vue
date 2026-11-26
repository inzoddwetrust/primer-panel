<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApi } from '../api/client'
import { apiPath } from '../api/paths'
import { cell, columnTargets, personName, staffTouched, type Member, type Project } from '../access'
import ApiErrorNote from '../components/ApiErrorNote.vue'
import ConfirmBox from '../components/ConfirmBox.vue'

// The superadmin's screen: every admin of every project × every permission
// of the API's list (gate DM-152, R2): the projects, then their people, all at
// once. A new permission is a column off in every row. A cell is on by what
// the admin may do; `people` of an admin is the API's, not a checkbox. "On
// for all" goes row by row, one request each, stopping at an error; each row
// is read back from the API.
interface Row {
  project: Project
  member: Member
  staff: Member[]
}

const { t } = useI18n()
const api = useApi()
const permissions = ref<string[]>([])
const rows = ref<Row[]>([])
const error = ref<unknown>(null)
const pending = ref<{ message: string; run: () => Promise<void> } | null>(null)

async function projectRows(project: Project): Promise<Row[]> {
  const members = await api.get<Member[]>(apiPath`/api/v1/projects/${project.id}/members`)
  const staff = members.filter((member) => !member.is_admin)
  return members.filter((member) => member.is_admin).map((member) => ({ project, member, staff }))
}

async function load(): Promise<void> {
  error.value = null
  try {
    const [list, projects] = await Promise.all([
      api.get<{ permissions: string[] }>('/api/v1/permissions'),
      api.get<Project[]>('/api/v1/projects'),
    ])
    permissions.value = list.permissions
    rows.value = (await Promise.all(projects.map(projectRows))).flat()
  } catch (failure: unknown) {
    error.value = failure
  }
}

async function put(row: Row, sent: string[]): Promise<void> {
  const base = apiPath`/api/v1/projects/${row.project.id}`
  await api.put(apiPath`${base}/members/${row.member.user.id}/permissions`, {
    permissions: sent,
  })
  const fresh = await projectRows(row.project)
  rows.value = rows.value.flatMap((each) =>
    each.project.id !== row.project.id
      ? [each]
      : each.member.user.id === row.member.user.id
        ? fresh.filter((r) => r.member.user.id === row.member.user.id)
        : [each],
  )
}

function toggle(row: Row, permission: string): void {
  const stored = row.member.permissions
  if (!stored.includes(permission)) {
    void run(() =>
      put(
        row,
        permissions.value.filter((p) => p === permission || stored.includes(p)),
      ),
    )
    return
  }
  const sent = stored.filter((p) => p !== permission)
  const count = staffTouched(row.staff, [permission])
  pending.value = {
    message: t('project.take_confirm', { count }),
    run: () => run(() => put(row, sent)),
  }
}

async function run(step: () => Promise<void>): Promise<void> {
  pending.value = null
  error.value = null
  try {
    await step()
  } catch (failure: unknown) {
    error.value = failure
  }
}

async function onForAll(permission: string): Promise<void> {
  error.value = null
  for (const target of columnTargets(rows.value, permission)) {
    const row = rows.value.find(
      (each) =>
        each.project.id === target.project.id && each.member.user.id === target.member.user.id,
    )
    if (!row) continue
    const stored = row.member.permissions
    try {
      await put(
        row,
        permissions.value.filter((p) => p === permission || stored.includes(p)),
      )
    } catch (failure: unknown) {
      error.value = failure
      return
    }
  }
}

onMounted(load)
</script>

<template>
  <main class="admins">
    <h1>{{ t('admins.heading') }}</h1>
    <ApiErrorNote v-if="error" :error="error" />
    <ConfirmBox
      v-if="pending"
      :message="pending.message"
      @confirm="pending.run()"
      @cancel="pending = null"
    />
    <p v-if="rows.length === 0" data-test="no-admins">{{ t('admins.none') }}</p>
    <div class="scroll">
      <table data-test="matrix">
        <thead>
          <tr>
            <th>{{ t('admins.project') }}</th>
            <th>{{ t('admins.person') }}</th>
            <th
              v-for="permission in permissions"
              :key="permission"
              :data-test="`col-${permission}`"
            >
              {{ permission }}
              <button type="button" :data-test="`all-${permission}`" @click="onForAll(permission)">
                {{ t('admins.all_on') }}
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="`${row.project.id}-${row.member.user.id}`"
            :data-test="`row-${row.project.slug}-${row.member.user.telegram_id}`"
          >
            <td>{{ row.project.name }}</td>
            <td>{{ personName(row.member.user) }}</td>
            <td v-for="permission in permissions" :key="permission">
              <input
                type="checkbox"
                :data-test="`cell-${permission}`"
                :checked="cell(row.member, permission).on"
                :disabled="cell(row.member, permission).fixed"
                @change="toggle(row, permission)"
              />
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
</style>
