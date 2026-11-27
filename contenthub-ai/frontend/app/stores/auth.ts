import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { AdminUser, AuthSession, AuthStatus } from '~/types/api'
import { extractErrorMessage } from '~/utils/format'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AdminUser | null>(null)
  const csrfToken = ref<string | null>(null)
  const expiresAt = ref<string | null>(null)
  const sessionChecked = ref(false)
  const loading = ref(false)
  const errorMessage = ref<string | null>(null)
  const authStatus = ref<AuthStatus | null>(null)

  const isAuthenticated = computed(() => user.value !== null)

  function clearSession() {
    user.value = null
    csrfToken.value = null
    expiresAt.value = null
  }

  function applySession(payload: AuthSession) {
    user.value = payload.user
    csrfToken.value = payload.csrf_token
    expiresAt.value = payload.expires_at
    sessionChecked.value = true
    errorMessage.value = null
  }

  async function fetchAuthStatus(): Promise<AuthStatus | null> {
    try {
      const headers = import.meta.server ? useRequestHeaders(['cookie']) : undefined
      const status = await $fetch<AuthStatus>('/api/v1/auth/status', {
        credentials: 'include',
        headers,
      })
      authStatus.value = status
      return status
    }
    catch (err) {
      errorMessage.value = extractErrorMessage(err, 'Unable to reach backend API.')
      return null
    }
  }

  async function fetchSession(force = false): Promise<boolean> {
    if (sessionChecked.value && !force) {
      return isAuthenticated.value
    }
    loading.value = true
    try {
      const headers = import.meta.server ? useRequestHeaders(['cookie']) : undefined
      const data = await $fetch<AuthSession>('/api/v1/auth/me', {
        credentials: 'include',
        headers,
      })
      applySession(data)
      return true
    }
    catch {
      clearSession()
      sessionChecked.value = true
      return false
    }
    finally {
      loading.value = false
    }
  }

  async function login(email: string, password: string): Promise<boolean> {
    loading.value = true
    errorMessage.value = null
    try {
      const data = await $fetch<AuthSession>('/api/v1/auth/login', {
        method: 'POST',
        credentials: 'include',
        body: { email, password },
      })
      applySession(data)
      return true
    }
    catch (err) {
      clearSession()
      errorMessage.value = extractErrorMessage(err, 'Invalid administrator credentials.')
      return false
    }
    finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    loading.value = true
    try {
      const headers: Record<string, string> = {}
      if (csrfToken.value) {
        headers['X-CSRF-Token'] = csrfToken.value
      }
      await $fetch('/api/v1/auth/logout', {
        method: 'POST',
        credentials: 'include',
        headers,
      })
    }
    catch {
      // Clear client state even if server session already expired.
    }
    finally {
      clearSession()
      sessionChecked.value = true
      loading.value = false
    }
  }

  return {
    user,
    csrfToken,
    expiresAt,
    sessionChecked,
    loading,
    errorMessage,
    authStatus,
    isAuthenticated,
    clearSession,
    applySession,
    fetchAuthStatus,
    fetchSession,
    login,
    logout,
  }
})
