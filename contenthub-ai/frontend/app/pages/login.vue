<script setup lang="ts">
import { Eye, EyeOff, Lock, Terminal } from 'lucide-vue-next'

definePageMeta({
  layout: 'auth',
})

const route = useRoute()
const authStore = useAuthStore()
const toast = useToast()

const email = ref('')
const password = ref('')
const showPassword = ref(false)
const formError = ref<string | null>(null)

const { data: statusData, pending: statusLoading } = await useAsyncData(
  'auth-status',
  () => authStore.fetchAuthStatus(),
)

const isDbUnavailable = computed(() => Boolean(statusData.value && !statusData.value.database_connected))
const isUninitialized = computed(
  () => Boolean(statusData.value && statusData.value.database_connected && !statusData.value.admin_initialized),
)

function resolveSafeRedirect(): string {
  const raw = route.query.redirect
  if (typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//') && raw !== '/login') {
    return raw
  }
  return '/'
}

async function handleSubmit() {
  formError.value = null
  const trimmedEmail = email.value.trim()
  if (!trimmedEmail || !password.value) {
    formError.value = 'Enter both your administrator email and password.'
    return
  }

  const ok = await authStore.login(trimmedEmail, password.value)
  if (!ok) {
    formError.value = authStore.errorMessage || 'Authentication failed.'
    return
  }

  password.value = ''
  toast.add({
    title: 'Signed in',
    description: `Welcome back, ${authStore.user?.display_name || 'Administrator'}.`,
    color: 'success',
  })
  await navigateTo(resolveSafeRedirect())
}
</script>

<template>
  <div class="w-full max-w-md space-y-4">
    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div class="mb-6">
        <div class="flex items-center gap-2 text-teal-700 dark:text-teal-400">
          <Lock
            class="h-4 w-4"
            aria-hidden="true"
          />
          <span class="text-xs font-semibold tracking-wide uppercase">Private Administrator Access</span>
        </div>
        <h1 class="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
          Sign in to ContentHub AI
        </h1>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Single-administrator self-hosted dashboard. Public registration is disabled.
        </p>
      </div>

      <UAlert
        v-if="isDbUnavailable"
        color="warning"
        variant="soft"
        title="MySQL database is not connected"
        description="Configure DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD in .env, run Alembic migrations, and initialize the administrator account."
        class="mb-4"
      />

      <div
        v-if="isUninitialized"
        class="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3.5 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
      >
        <div class="flex items-center gap-2 font-semibold">
          <Terminal class="h-4 w-4 shrink-0" />
          <span>Administrator account not initialized</span>
        </div>
        <p class="mt-1.5 leading-relaxed">
          No default password exists. Run the CLI command below in <code>backend/</code> after applying
          Alembic migrations:
        </p>
        <pre class="mt-2 overflow-x-auto rounded bg-slate-900 px-2.5 py-2 text-[11px] text-slate-100">python -m app.cli init-admin --email admin@example.com --name "Administrator"</pre>
      </div>

      <UAlert
        v-if="formError"
        color="error"
        variant="soft"
        :title="formError"
        class="mb-4"
      />

      <form
        class="space-y-4"
        @submit.prevent="handleSubmit"
      >
        <UFormField
          label="Administrator Email"
          name="email"
          required
        >
          <UInput
            v-model="email"
            type="email"
            autocomplete="username"
            placeholder="admin@example.com"
            class="w-full"
            :disabled="authStore.loading"
          />
        </UFormField>

        <UFormField
          label="Password"
          name="password"
          required
        >
          <div class="relative">
            <UInput
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="Enter administrator password"
              class="w-full pr-10"
              :disabled="authStore.loading"
            />
            <button
              type="button"
              class="absolute top-1/2 right-2.5 -translate-y-1/2 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
              :aria-label="showPassword ? 'Hide password' : 'Show password'"
              @click="showPassword = !showPassword"
            >
              <EyeOff
                v-if="showPassword"
                class="h-4 w-4"
              />
              <Eye
                v-else
                class="h-4 w-4"
              />
            </button>
          </div>
        </UFormField>

        <UButton
          type="submit"
          color="primary"
          block
          :loading="authStore.loading"
          :disabled="statusLoading"
        >
          Sign In
        </UButton>
      </form>
    </div>

    <p class="text-center text-[11px] text-slate-500 dark:text-slate-400">
      Sessions use HTTP-only cookies with server-side revocation and CSRF protection.
    </p>
  </div>
</template>
