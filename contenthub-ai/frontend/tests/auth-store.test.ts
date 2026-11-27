import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '~/stores/auth'

describe('auth store', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock.mockReset()
    vi.stubGlobal('$fetch', fetchMock)
  })

  it('populates user and CSRF token on login and sends X-CSRF-Token on logout', async () => {
    fetchMock.mockResolvedValueOnce({
      user: {
        id: 1,
        email: 'admin@contenthub.local',
        display_name: 'Site Admin',
        is_active: true,
        last_login_at: null,
        created_at: '2026-11-26T00:00:00Z',
      },
      csrf_token: 'csrf-token-123',
      expires_at: '2026-11-26T12:00:00Z',
    })

    const store = useAuthStore()
    const ok = await store.login('admin@contenthub.local', 'StrongAdmin#2026!')
    expect(ok).toBe(true)
    expect(store.isAuthenticated).toBe(true)
    expect(store.csrfToken).toBe('csrf-token-123')

    fetchMock.mockResolvedValueOnce({ message: 'Signed out successfully.' })
    await store.logout()

    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/auth/logout', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRF-Token': 'csrf-token-123' },
    })
    expect(store.isAuthenticated).toBe(false)
    expect(store.csrfToken).toBeNull()
  })

  it('captures error detail when login fails', async () => {
    fetchMock.mockRejectedValueOnce({ data: { detail: 'Invalid email or password.' } })

    const store = useAuthStore()
    const ok = await store.login('admin@contenthub.local', 'wrong')
    expect(ok).toBe(false)
    expect(store.isAuthenticated).toBe(false)
    expect(store.errorMessage).toBe('Invalid email or password.')
  })
})
