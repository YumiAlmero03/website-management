export default defineNuxtRouteMiddleware(async (to) => {
  const authStore = useAuthStore()
  const isLoginRoute = to.path === '/login'

  if (!authStore.sessionChecked) {
    await authStore.fetchSession()
  }

  if (!authStore.isAuthenticated && !isLoginRoute) {
    return navigateTo({
      path: '/login',
      query: to.fullPath && to.fullPath !== '/' ? { redirect: to.fullPath } : undefined,
    })
  }

  if (authStore.isAuthenticated && isLoginRoute) {
    const redirectTarget = typeof to.query.redirect === 'string' && to.query.redirect.startsWith('/')
      ? to.query.redirect
      : '/'
    return navigateTo(redirectTarget)
  }
})
