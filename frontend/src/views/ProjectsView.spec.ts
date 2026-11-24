import { describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import ProjectsView from './ProjectsView.vue'
import { page } from '../testing'

const ME = (superadmin: boolean) => ({
  user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
  is_superadmin: superadmin,
  projects: [],
  panel_grants: [],
})
const A = { id: 'pa', slug: 'a', name: 'A', kind: 'service', repo: 'r', archived_at: null }

describe('the projects', () => {
  it('lists the projects the API gives; the form is the superadmin’s', async () => {
    const plain = await page(ProjectsView, {}, ME(false), { 'GET /api/v1/projects': [A] })
    expect(plain.wrapper.get('[data-test="projects"]').text()).toContain('A')
    expect(plain.wrapper.get('[data-test="projects"]').text()).toContain('service')
    expect(plain.wrapper.find('[data-test="new-project"]').exists()).toBe(false)
    const none = await page(ProjectsView, {}, ME(false), { 'GET /api/v1/projects': [] })
    expect(none.wrapper.find('[data-test="no-projects"]').exists()).toBe(true)
  })

  it('makes a project through the API and shows its refusal', async () => {
    const { wrapper, asked } = await page(ProjectsView, {}, ME(true), {
      'GET /api/v1/projects': [],
      'POST /api/v1/projects': () =>
        new Response('{"error":{"class":"conflict","message":"The project a exists"}}', {
          status: 409,
        }),
    })
    await wrapper.get('[data-test="slug"]').setValue('a')
    await wrapper.get('[data-test="name"]').setValue('A')
    await wrapper.get('[data-test="repo"]').setValue('git@github.com:o/a.git')
    await wrapper.get('[data-test="new-project"]').trigger('submit')
    await flushPromises()
    expect(asked.find((a) => a.method === 'POST')?.body).toEqual({
      slug: 'a',
      name: 'A',
      kind: 'product',
      repo: 'git@github.com:o/a.git',
    })
    expect(wrapper.get('[data-test="error-class"]').text()).toBe('conflict')
  })
})
