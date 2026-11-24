// The person signed in: /api/v1/me of the Panel's API (DM-149, DM-150).

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError, ApiNetworkError, ApiTimeoutError, type ApiClient } from '../api/client'

export interface ProjectAccess {
  project: { id: string; slug: string; name: string; kind: string }
  is_admin: boolean
  permissions: string[]
}

export interface Me {
  user: {
    id: string
    telegram_id: number
    first_name: string | null
    username: string | null
  }
  is_superadmin: boolean
  projects: ProjectAccess[]
  panel_grants: string[]
}

export type LoadResult = 'signed_in' | 'unauthorized' | 'failed'

export const useMeStore = defineStore('me', () => {
  const me = ref<Me | null>(null)
  const error = ref<ApiError | ApiNetworkError | ApiTimeoutError | null>(null)

  async function load(api: ApiClient): Promise<LoadResult> {
    error.value = null
    try {
      me.value = await api.get<Me>('/api/v1/me')
      return 'signed_in'
    } catch (failure: unknown) {
      me.value = null
      if (failure instanceof ApiError && failure.status === 401) {
        return 'unauthorized'
      }
      if (
        failure instanceof ApiError ||
        failure instanceof ApiNetworkError ||
        failure instanceof ApiTimeoutError
      ) {
        error.value = failure
        return 'failed'
      }
      throw failure
    }
  }

  function clear(): void {
    me.value = null
    error.value = null
  }

  return { me, error, load, clear }
})
