import { describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import ProjectView from './ProjectView.vue'
import { page, person } from '../testing'

const LIST = {
  permissions: [
    'deploy_test',
    'deploy_prod',
    'seeds',
    'db',
    'passport',
    'destructive',
    'project_verbs',
    'servers',
    'people',
  ],
}
const PROJECT = {
  id: 'pa',
  slug: 'velo',
  name: 'Velo',
  kind: 'product',
  repo: 'r',
  archived_at: null,
}

function me(superadmin: boolean, permissions: string[]) {
  return {
    user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
    is_superadmin: superadmin,
    projects: superadmin ? [] : [{ project: { ...PROJECT }, is_admin: true, permissions }],
    panel_grants: [],
  }
}

function row(id: string, telegramId: number, isAdmin: boolean, permissions: string[]) {
  return {
    user: person(id, telegramId, id),
    is_admin: isAdmin,
    permissions,
    effective: isAdmin ? [...permissions, 'people'] : permissions,
    granted_by: 's',
    granted_at: '2026-11-24T00:00:00Z',
  }
}

const ADMIN = row('me', 99, true, ['deploy_test', 'seeds'])
const STAFF = row('st', 12, false, ['deploy_test', 'db'])

function answers(extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/projects/pa': PROJECT,
    'GET /api/v1/projects/pa/members': [ADMIN, STAFF],
    'GET /api/v1/permissions': LIST,
    'GET /api/v1/projects/pa/invites': [],
    'GET /api/v1/users': [person('n', 50, 'New')],
    ...extra,
  }
}

describe('a project’s people and invites', () => {
  it('test_probe_DM_152_admin_sees_only_own_permissions', async () => {
    // The admin holds deploy_test, seeds and people; the staff member holds db
    // from the superadmin. The admin's editor has no db, and a save keeps it.
    const { wrapper, asked } = await page(
      ProjectView,
      { projectId: 'pa' },
      me(false, ['deploy_test', 'seeds', 'people']),
      answers({ 'PUT /api/v1/projects/pa/members/st/permissions': [] }),
    )
    await wrapper.get('[data-test="member-12"] [data-test="edit"]').trigger('click')
    const shown = wrapper
      .findAll('[data-test="editor"] label')
      .map((label) => label.attributes('data-test'))
    expect(shown).toEqual(['perm-deploy_test', 'perm-seeds', 'perm-people'])
    expect(wrapper.find('[data-test="perm-db"]').exists()).toBe(false)
    await wrapper.get('[data-test="perm-seeds"] input').trigger('change')
    await wrapper.get('[data-test="editor"]').trigger('submit')
    await flushPromises()
    expect(asked.find((a) => a.method === 'PUT')?.body).toEqual({
      permissions: ['deploy_test', 'seeds', 'db'],
    })
    // the admin's own row: no buttons, only the superadmin changes an admin
    expect(wrapper.find('[data-test="member-99"] [data-test="edit"]').exists()).toBe(false)
    // invites: the admin's permissions, no "an admin"
    const offered = wrapper
      .findAll('[data-test="invite-form"] label[data-test^="invite-perm-"]')
      .map((label) => label.attributes('data-test'))
    expect(offered).toEqual(['invite-perm-deploy_test', 'invite-perm-seeds', 'invite-perm-people'])
    expect(wrapper.find('[data-test="invite-admin"]').exists()).toBe(false)
  })

  it('archives only when the slug is typed', async () => {
    const { wrapper, asked } = await page(
      ProjectView,
      { projectId: 'pa' },
      me(true, []),
      answers({ 'POST /api/v1/projects/pa/archive': PROJECT }),
    )
    await wrapper.get('[data-test="archive"]').trigger('click')
    const yes = wrapper.get('[data-test="confirm-yes"]')
    expect((yes.element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.get('[data-test="confirm-input"]').setValue('vel')
    expect((yes.element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.get('[data-test="confirm-input"]').setValue('velo')
    await yes.trigger('click')
    await flushPromises()
    expect(asked.some((a) => a.method === 'POST' && a.path.endsWith('/archive'))).toBe(true)
  })

  it('revokes an admin only when his Telegram id is typed; staff with yes', async () => {
    const { wrapper, asked } = await page(
      ProjectView,
      { projectId: 'pa' },
      me(true, []),
      answers({
        'POST /api/v1/projects/pa/members/me/revoke': [],
        'POST /api/v1/projects/pa/members/st/revoke': [],
      }),
    )
    await wrapper.get('[data-test="member-99"] [data-test="revoke"]').trigger('click')
    expect(wrapper.find('[data-test="confirm-input"]').exists()).toBe(true)
    await wrapper.get('[data-test="confirm-input"]').setValue('99')
    await wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="member-12"] [data-test="revoke"]').trigger('click')
    expect(wrapper.find('[data-test="confirm-input"]').exists()).toBe(false)
    await wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    const revoked = asked.filter((a) => a.path.endsWith('/revoke')).map((a) => a.path)
    expect(revoked).toEqual([
      '/api/v1/projects/pa/members/me/revoke',
      '/api/v1/projects/pa/members/st/revoke',
    ])
  })

  it('shows the invite’s link once, on the page’s own sign-in', async () => {
    const { wrapper } = await page(
      ProjectView,
      { projectId: 'pa' },
      me(true, []),
      answers({ 'POST /api/v1/projects/pa/invites': { token: 'tok-1', invite: {} } }),
    )
    expect(wrapper.find('[data-test="invite-admin"]').exists()).toBe(true)
    await wrapper.get('[data-test="invite-form"]').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[data-test="invite-link-text"]').text()).toBe(
      `${window.location.origin}/login?invite=tok-1`,
    )
    await wrapper.get('[data-test="invite-close"]').trigger('click')
    expect(wrapper.find('[data-test="invite-link"]').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('tok-1')
  })

  it('shows a refusal of the API, never swallows it', async () => {
    const { wrapper } = await page(
      ProjectView,
      { projectId: 'pa' },
      me(false, ['deploy_test', 'seeds', 'people']),
      answers({
        'PUT /api/v1/projects/pa/members/st/permissions': () =>
          new Response('{"error":{"class":"forbidden","message":"The permission db is needed"}}', {
            status: 403,
          }),
      }),
    )
    await wrapper.get('[data-test="member-12"] [data-test="edit"]').trigger('click')
    await wrapper.get('[data-test="editor"]').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[data-test="error-class"]').text()).toBe('forbidden')
    expect(wrapper.get('[data-test="error-message"]').text()).toBe('The permission db is needed')
  })

  it('a project not seen is "not found"; staff without people reads only', async () => {
    const missing = await page(ProjectView, { projectId: 'zz' }, me(false, []), answers())
    expect(missing.wrapper.find('[data-test="not-found"]').exists()).toBe(true)
    const reader = await page(
      ProjectView,
      { projectId: 'pa' },
      me(false, ['deploy_test']),
      answers(),
    )
    expect(reader.wrapper.find('[data-test="edit"]').exists()).toBe(false)
    expect(reader.wrapper.find('[data-test="invites"]').exists()).toBe(false)
    expect(reader.asked.some((a) => a.path.endsWith('/invites'))).toBe(false)
  })

  it('names a project with no admin', async () => {
    const { wrapper } = await page(
      ProjectView,
      { projectId: 'pa' },
      me(true, []),
      answers({ 'GET /api/v1/projects/pa/members': [STAFF] }),
    )
    expect(wrapper.find('[data-test="no-admin"]').exists()).toBe(true)
  })

  it('leads to a new server with the permission servers', async () => {
    const without = await page(
      ProjectView,
      { projectId: 'pa' },
      me(false, ['deploy_test', 'people']),
      answers(),
    )
    expect(without.wrapper.find('[data-test="add-server"]').exists()).toBe(false)
    const holder = await page(
      ProjectView,
      { projectId: 'pa' },
      me(false, ['servers', 'people']),
      answers(),
    )
    expect(holder.wrapper.get('[data-test="add-server"]').attributes('href')).toBe(
      '/projects/pa/servers/new',
    )
  })
})
