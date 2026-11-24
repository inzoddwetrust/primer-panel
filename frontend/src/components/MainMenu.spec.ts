import { describe, expect, it } from 'vitest'
import MainMenu from './MainMenu.vue'
import { page } from '../testing'

function me(superadmin: boolean) {
  return {
    user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
    is_superadmin: superadmin,
    projects: [],
    panel_grants: [],
  }
}

describe('the menu', () => {
  it('leads to the fleet, the projects and the person; the admins for the superadmin', async () => {
    const plain = await page(MainMenu, {}, me(false), {})
    expect(plain.wrapper.findAll('a').map((a) => a.attributes('href'))).toEqual([
      '/',
      '/projects',
      '/me',
    ])
    const superadmin = await page(MainMenu, {}, me(true), {})
    expect(superadmin.wrapper.find('[data-test="menu-admins"]').attributes('href')).toBe(
      '/superadmin/admins',
    )
  })
})
