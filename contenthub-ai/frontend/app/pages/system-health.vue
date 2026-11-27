<script setup lang="ts">
import { Database, HardDrive, RefreshCw, ShieldAlert } from 'lucide-vue-next'
import type { SystemHealth } from '~/types/api'
import { extractErrorMessage, formatDateTime, formatMegabytes } from '~/utils/format'

const { request } = useApiClient()
const toast = useToast()

const health = ref<SystemHealth | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const errorMessage = ref<string | null>(null)

async function loadHealth(showToast = false) {
  if (health.value) {
    refreshing.value = true
  }
  else {
    loading.value = true
  }
  errorMessage.value = null

  try {
    health.value = await request<SystemHealth>('/api/v1/health/system')
    if (showToast) {
      toast.add({
        title: 'Health diagnostics updated',
        color: 'success',
      })
    }
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to fetch system health diagnostics.')
  }
  finally {
    loading.value = false
    refreshing.value = false
  }
}

function progressBarClass(percent: number, warn: number, critical?: number): string {
  if (critical !== undefined && percent >= critical) {
    return 'bg-red-500'
  }
  if (percent >= warn) {
    return 'bg-amber-500'
  }
  return 'bg-teal-600'
}

onMounted(() => {
  void loadHealth(false)
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          System Health & Resource Guardian
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Live MySQL diagnostics, server resource utilization via psutil, and persistent storage checks.
        </p>
      </div>
      <UButton
        color="neutral"
        variant="outline"
        size="sm"
        :loading="refreshing"
        @click="loadHealth(true)"
      >
        <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
        Re-check Now
      </UButton>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Unable to load system health"
      :message="errorMessage"
      retryable
      @retry="loadHealth(false)"
    />

    <div
      v-if="loading"
      class="space-y-4"
    >
      <USkeleton class="h-24 w-full" />
      <USkeleton class="h-48 w-full" />
    </div>

    <template v-else-if="health">
      <!-- Overall status -->
      <div class="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div class="flex items-center gap-3">
          <HealthStatusBadge :status="health.status" />
          <div>
            <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {{ health.app_name }} v{{ health.version }} ({{ health.environment }})
            </p>
            <p class="text-xs text-slate-500 dark:text-slate-400">
              Checked {{ formatDateTime(health.timestamp, health.timezone) }} · Display timezone: {{ health.timezone }}
            </p>
          </div>
        </div>
        <UButton
          to="/settings"
          color="neutral"
          variant="outline"
          size="xs"
        >
          Configure Thresholds
        </UButton>
      </div>

      <UAlert
        v-if="health.database.uses_root_user"
        color="warning"
        variant="soft"
        title="Runtime MySQL user is configured as 'root'"
        description="Switch DB_USER in .env to a least-privilege application account such as contenthub_user."
      />

      <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <!-- MySQL Diagnostics -->
        <section class="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <Database class="h-4 w-4 text-teal-600 dark:text-teal-400" />
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
                MySQL Database Connectivity
              </h2>
            </div>
            <HealthStatusBadge :status="health.database.connected ? 'connected' : 'unavailable'" />
          </div>

          <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
            <div>
              <dt class="text-slate-500 dark:text-slate-400">Target</dt>
              <dd class="mt-0.5 font-mono text-slate-900 dark:text-slate-100">
                {{ health.database.host }}:{{ health.database.port }}/{{ health.database.database_name }}
              </dd>
            </div>
            <div>
              <dt class="text-slate-500 dark:text-slate-400">Runtime User</dt>
              <dd class="mt-0.5 font-mono text-slate-900 dark:text-slate-100">
                {{ health.database.user }}
              </dd>
            </div>
            <div>
              <dt class="text-slate-500 dark:text-slate-400">Server Version</dt>
              <dd class="mt-0.5 font-medium text-slate-900 dark:text-slate-100">
                {{ health.database.server_version || 'Unavailable' }}
              </dd>
            </div>
            <div>
              <dt class="text-slate-500 dark:text-slate-400">Charset / Engine</dt>
              <dd class="mt-0.5 font-medium text-slate-900 dark:text-slate-100">
                {{ health.database.character_set || 'Unknown' }} ·
                InnoDB {{ health.database.innodb_available === true ? 'Enabled' : health.database.innodb_available === false ? 'Disabled' : 'Unknown' }}
              </dd>
            </div>
            <div>
              <dt class="text-slate-500 dark:text-slate-400">Round-Trip Latency</dt>
              <dd class="mt-0.5 font-medium text-slate-900 dark:text-slate-100">
                {{ health.database.latency_ms !== null ? `${health.database.latency_ms} ms` : 'N/A' }}
              </dd>
            </div>
            <div>
              <dt class="text-slate-500 dark:text-slate-400">Connection Pool</dt>
              <dd class="mt-0.5 font-medium text-slate-900 dark:text-slate-100">
                size={{ health.database.pool_size }}, overflow={{ health.database.max_overflow }}, recycle={{ health.database.pool_recycle }}s
              </dd>
            </div>
          </dl>

          <UAlert
            v-if="health.database.error"
            color="error"
            variant="soft"
            title="Database Connection Error"
            :description="health.database.error"
            class="mt-4"
          />
        </section>

        <!-- Resource Guardian -->
        <section class="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <ShieldAlert class="h-4 w-4 text-teal-600 dark:text-teal-400" />
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Resource Guardian (psutil)
              </h2>
            </div>
            <HealthStatusBadge :status="health.resources.guardian_status" />
          </div>

          <div class="mt-4 space-y-4 text-xs">
            <div>
              <div class="flex justify-between">
                <span class="font-medium text-slate-700 dark:text-slate-300">
                  CPU Usage ({{ health.resources.cpu_cores }} cores)
                </span>
                <span class="font-mono">{{ health.resources.cpu_percent }}%</span>
              </div>
              <div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  :class="['h-full rounded-full transition-all', progressBarClass(health.resources.cpu_percent, health.resources.thresholds.cpu_warning_percent, health.resources.thresholds.cpu_critical_percent)]"
                  :style="{ width: `${Math.min(100, health.resources.cpu_percent)}%` }"
                />
              </div>
              <p class="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                Warning {{ health.resources.thresholds.cpu_warning_percent }}% · Critical {{ health.resources.thresholds.cpu_critical_percent }}%
              </p>
            </div>

            <div>
              <div class="flex justify-between">
                <span class="font-medium text-slate-700 dark:text-slate-300">
                  RAM Usage ({{ formatMegabytes(health.resources.ram_used_mb) }} / {{ formatMegabytes(health.resources.ram_total_mb) }})
                </span>
                <span class="font-mono">{{ health.resources.ram_percent }}%</span>
              </div>
              <div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  :class="['h-full rounded-full transition-all', progressBarClass(health.resources.ram_percent, health.resources.thresholds.ram_warning_percent)]"
                  :style="{ width: `${Math.min(100, health.resources.ram_percent)}%` }"
                />
              </div>
              <p class="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                Warning threshold: {{ health.resources.thresholds.ram_warning_percent }}%
              </p>
            </div>

            <div class="grid grid-cols-2 gap-3 rounded-md bg-slate-50 p-3 dark:bg-slate-950/60">
              <div>
                <p class="text-slate-500 dark:text-slate-400">Load Average (1m / 5m / 15m)</p>
                <p class="mt-0.5 font-mono font-medium text-slate-900 dark:text-slate-100">
                  {{ health.resources.load_avg_1m ?? '-' }} / {{ health.resources.load_avg_5m ?? '-' }} / {{ health.resources.load_avg_15m ?? '-' }}
                </p>
              </div>
              <div>
                <p class="text-slate-500 dark:text-slate-400">Worker Concurrency Caps</p>
                <p class="mt-0.5 font-medium text-slate-900 dark:text-slate-100">
                  Gen: {{ health.resources.thresholds.max_concurrent_generation }} · Browser: {{ health.resources.thresholds.max_concurrent_browsers }}
                </p>
              </div>
            </div>

            <div
              v-if="health.resources.guardian_reasons.length > 0"
              class="rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
            >
              <p class="font-semibold">Active Guardian Alerts</p>
              <ul class="mt-1 list-disc space-y-0.5 pl-4">
                <li
                  v-for="(reason, idx) in health.resources.guardian_reasons"
                  :key="idx"
                >
                  {{ reason }}
                </li>
              </ul>
            </div>
          </div>
        </section>
      </div>

      <!-- Persistent Storage Verification -->
      <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
          <div class="flex items-center gap-2">
            <HardDrive class="h-4 w-4 text-teal-600 dark:text-teal-400" />
            <div>
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Persistent Storage Paths
              </h2>
              <p class="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                STORAGE_ROOT: {{ health.storage_root }} ({{ health.resources.disk_free_gb }} GB free)
              </p>
            </div>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-5 py-2.5 font-medium">Directory</th>
                <th class="px-5 py-2.5 font-medium">Resolved Path</th>
                <th class="px-5 py-2.5 font-medium">Exists</th>
                <th class="px-5 py-2.5 font-medium">Writable</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="item in health.storage_paths"
                :key="item.name"
              >
                <td class="px-5 py-2.5 font-medium text-slate-900 dark:text-slate-100">
                  {{ item.name }}
                </td>
                <td class="px-5 py-2.5 font-mono text-[11px] text-slate-600 dark:text-slate-300">
                  {{ item.path }}
                </td>
                <td class="px-5 py-2.5">
                  <HealthStatusBadge
                    :status="item.exists ? 'ok' : 'error'"
                    :label="item.exists ? 'Yes' : 'Missing'"
                  />
                </td>
                <td class="px-5 py-2.5">
                  <HealthStatusBadge
                    :status="item.writable ? 'ok' : 'error'"
                    :label="item.writable ? 'Writable' : 'Read-only'"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
