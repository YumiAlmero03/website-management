type HttpMethod = 'GET' | 'HEAD' | 'PATCH' | 'POST' | 'PUT' | 'DELETE' | 'OPTIONS'

interface ApiRequestOptions {
  method?: HttpMethod
  query?: Record<string, string | number | boolean | undefined>
  body?: BodyInit | Record<string, unknown> | null
  headers?: HeadersInit
}

const MUTATING_METHODS = new Set<HttpMethod>(['POST', 'PUT', 'PATCH', 'DELETE'])

export function useApiClient() {
  const authStore = useAuthStore()

  async function request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    const method: HttpMethod = options.method || 'GET'
    const headers: Record<string, string> = {}

    if (options.headers) {
      const incoming = new Headers(options.headers)
      incoming.forEach((value, key) => {
        headers[key] = value
      })
    }

    if (import.meta.server) {
      const reqHeaders = useRequestHeaders(['cookie'])
      if (reqHeaders.cookie && !headers.cookie) {
        headers.cookie = reqHeaders.cookie
      }
    }

    if (MUTATING_METHODS.has(method) && authStore.csrfToken) {
      headers['X-CSRF-Token'] = authStore.csrfToken
    }

    return await $fetch<T>(path, {
      method,
      query: options.query,
      body: options.body,
      credentials: 'include',
      headers,
    })
  }

  return { request }
}
