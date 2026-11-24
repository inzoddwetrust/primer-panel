import { describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import AdminsView from './AdminsView.vue'
import { page, person } from '../testing'

const SUPER = {
  user: { id: 's', telegram_id: 1, first_name: 'Super', username: null },
  is_superadmin: true,
  projects: [],
  panel_grants: [],
}
// The API's list, written out, with a permission no admin has yet.
const LIST = { permissions: ['deploy_test', 'seeds', 'people', 'brand_new'] }
const A = { id: 'pa', slug: 'a', name: 'A', kind: 'product', repo: 'r', archived_at: null }
const B = { id: 'pb', slug: 'b', name: 'B', kind: 'product', repo: 'r', archived_at: null }

function admin(id: string, telegramId: number, permissions: string[]) {
  return {
    user: person(id, telegramId, id),
    is_admin: true,
    permissions,
    effective: [...permissions, 'people'],
    granted_by: 's',
    granted_at: '2026-11-24T00:00:00Z',
  }
}

function answers(extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/permissions': LIST,
    'GET /api/v1/projects': [A, B],
    'GET /api/v1/projects/pa/members': [admin('x', 11, ['deploy_test'])],
    'GET /api/v1/projects/pb/members': [admin('y', 21, ['seeds'])],
    ...extra,
  }
}

describe('the superadmin’s admins × permissions', () => {
  it('test_probe_DM_152_new_permission_is_off_in_every_row', async () => {
    // The columns are the API's list: a permission no admin holds is a column,
    // off in every row. The pair: a held one is on where it is held.
    const { wrapper } = await page(AdminsView, {}, SUPER, answers())
    const columns = wrapper.findAll('th[data-test^="col-"]').map((th) => th.attributes('data-test'))
    expect(columns).toEqual(['col-deploy_test', 'col-seeds', 'col-people', 'col-brand_new'])
    for (const row of ['row-a-11', 'row-b-21']) {
      const box = wrapper.get(`[data-test="${row}"] [data-test="cell-brand_new"]`)
      expect((box.element as HTMLInputElement).checked).toBe(false)
    }
    const held = wrapper.get('[data-test="row-a-11"] [data-test="cell-deploy_test"]')
    expect((held.element as HTMLInputElement).checked).toBe(true)
    const people = wrapper.get('[data-test="row-a-11"] [data-test="cell-people"]')
    expect((people.element as HTMLInputElement).checked).toBe(true)
    expect((people.element as HTMLInputElement).disabled).toBe(true)
  })

  it('turns a column on row by row and stops at an error', async () => {
    const { wrapper, asked } = await page(
      AdminsView,
      {},
      SUPER,
      answers({
        'PUT /api/v1/projects/pa/members/x/permissions': () =>
          new Response('{"error":{"class":"conflict","message":"The project is archived"}}', {
            status: 409,
          }),
        'PUT /api/v1/projects/pb/members/y/permissions': [],
      }),
    )
    await wrapper.get('[data-test="all-brand_new"]').trigger('click')
    await flushPromises()
    const puts = asked.filter((a) => a.method === 'PUT')
    expect(puts.map((a) => [a.path, a.body])).toEqual([
      ['/api/v1/projects/pa/members/x/permissions', { permissions: ['deploy_test', 'brand_new'] }],
    ])
    expect(wrapper.get('[data-test="error-class"]').text()).toBe('conflict')
  })

  it('turns a column on in every row where it is off, one request each', async () => {
    const { wrapper, asked } = await page(
      AdminsView,
      {},
      SUPER,
      answers({
        'PUT /api/v1/projects/pa/members/x/permissions': [],
        'PUT /api/v1/projects/pb/members/y/permissions': [],
      }),
    )
    await wrapper.get('[data-test="all-seeds"]').trigger('click')
    await flushPromises()
    const puts = asked.filter((a) => a.method === 'PUT')
    // y holds seeds already: only x is asked
    expect(puts.map((a) => [a.path, a.body])).toEqual([
      ['/api/v1/projects/pa/members/x/permissions', { permissions: ['deploy_test', 'seeds'] }],
    ])
    // the row is read back from the API after its request
    expect(asked.filter((a) => a.path === '/api/v1/projects/pa/members').length).toBe(2)
    // twin REPEAT: with every row on, nothing is asked
    const before = asked.length
    await wrapper.get('[data-test="all-people"]').trigger('click')
    await flushPromises()
    expect(asked.length).toBe(before)
  })

  it('asks before taking a permission from an admin, naming the staff it reaches', async () => {
    const staff = {
      user: person('z', 12, 'z'),
      is_admin: false,
      permissions: ['deploy_test'],
      effective: ['deploy_test'],
      granted_by: 'x',
      granted_at: '2026-11-24T00:00:00Z',
    }
    const { wrapper, asked } = await page(
      AdminsView,
      {},
      SUPER,
      answers({
        'GET /api/v1/projects/pa/members': [admin('x', 11, ['deploy_test']), staff],
        'PUT /api/v1/projects/pa/members/x/permissions': [],
      }),
    )
    await wrapper.get('[data-test="row-a-11"] [data-test="cell-deploy_test"]').trigger('change')
    await flushPromises()
    expect(wrapper.get('[data-test="confirm-message"]').text()).toContain('1')
    expect(asked.some((a) => a.method === 'PUT')).toBe(false)
    await wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    expect(asked.find((a) => a.method === 'PUT')?.body).toEqual({ permissions: [] })
  })
})
