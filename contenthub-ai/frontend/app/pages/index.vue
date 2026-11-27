<script setup lang="ts">
import { ArrowRight, RefreshCw } from 'lucide-vue-next'
import type { DashboardSummary } from '~/types/api'
import { extractErrorMessage, formatDateTime, formatMegabytes } from '~/utils/format'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const summary = ref<DashboardSummary | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const errorMessage = ref<string | null>(null)

const futureModules = computed(() =>
  (summary.value?.modules || []).filter((m) => m.status !== 'active'),
)

async function loadDashboard(showToast = false) {
  if (summary.value) {
    refreshing.value = true
  }
  else {
    loading.value = true
  }
  errorMessage.value = null

  try {
    const query: Record<string, number> = {}
    if (uiStore.selectedBrandId !== null) {
      query.brand_id = uiStore.selectedBrandId
    }
    if (uiStore.selectedWebsiteId !== null) {
      query.website_id = uiStore.selectedWebsiteId
    }
    summary.value = await request<DashboardSummary>('/api/v1/dashboard/summary', { query })
    if (showToast) {
      toast.add({
        title: 'Dashboard refreshed',
        description: 'Live MySQL website monitoring and server metrics updated.',
        color: 'success',
      })
    }
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to fetch dashboard summary.')
  }
  finally {
    loading.value = false
    refreshing.value = false
  }
}

watch(
  () => [uiStore.selectedBrandId, uiStore.selectedWebsiteId],
  () => {
    void loadDashboard(false)
  },
)

onMounted(() => {
  void loadDashboard(false)
  void uiStore.refreshGlobalSelectors()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Operations Dashboard
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Real MySQL website monitoring metrics, recent scan results, and live server health.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span
          v-if="summary"
          class="text-xs text-slate-500 dark:text-slate-400"
        >
          Updated {{ formatDateTime(summary.generated_at, summary.timezone) }} ({{ summary.timezone }})
        </span>
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          :loading="refreshing"
          @click="loadDashboard(true)"
        >
          <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
          Refresh
        </UButton>
      </div>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Dashboard data unavailable"
      :message="errorMessage"
      retryable
      @retry="loadDashboard(false)"
    />

    <div
      v-if="loading"
      class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      <div
        v-for="idx in 8"
        :key="idx"
        class="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
      >
        <USkeleton class="h-3 w-24" />
        <USkeleton class="mt-3 h-7 w-20" />
        <USkeleton class="mt-3 h-3 w-36" />
      </div>
    </div>

    <template v-else-if="summary">
      <!-- Real Phase 2 Website Monitoring Metrics -->
      <section aria-label="Website monitoring statistics">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Website Monitoring & Content Library
          </h2>
          <div class="flex items-center gap-2">
            <UButton
              to="/brands"
              color="neutral"
              variant="outline"
              size="xs"
            >
              Manage Brands
            </UButton>
            <UButton
              to="/websites"
              color="primary"
              size="xs"
            >
              Manage Websites
            </UButton>
          </div>
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            title="Total Brands"
            :value="summary.phase2_metrics.total_brands"
            subtitle="Configured brand profiles in MySQL"
            icon="Tags"
          />
          <MetricCard
            title="Active Websites"
            :value="summary.phase2_metrics.active_websites"
            :subtitle="`${summary.phase2_metrics.websites_due_for_scan} due for scheduled scan`"
            icon="Globe"
          />
          <MetricCard
            title="Discovered Articles"
            :value="summary.phase2_metrics.total_articles"
            :subtitle="`${summary.phase2_metrics.articles_discovered_today} discovered today · ${summary.phase2_metrics.updated_articles} updated`"
            icon="Library"
          />
          <MetricCard
            title="Completed / Failed Scans"
            :value="`${summary.phase2_metrics.completed_scans} / ${summary.phase2_metrics.failed_scans}`"
            subtitle="Historical MySQL website_scan_logs totals"
            icon="Activity"
            :status="summary.phase2_metrics.failed_scans > 0 ? 'warning' : 'ok'"
          />
        </div>
      </section>

      <!-- Live Server & Database Health -->
      <section aria-label="Live infrastructure metrics">
        <h2 class="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
          Server & MySQL Health
        </h2>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            title="MySQL Database"
            :value="summary.database.connected ? (summary.database.server_version || 'Connected') : 'Unavailable'"
            :subtitle="summary.database.connected
              ? `${summary.database.database_name} · ${summary.database.character_set || 'utf8mb4'} · ${summary.database.latency_ms ?? '-'} ms`
              : (summary.database.error || 'Check .env database credentials')"
            icon="Activity"
            :status="summary.database.connected ? 'connected' : 'unavailable'"
          />
          <MetricCard
            title="Server CPU"
            :value="`${summary.resources.cpu_percent}%`"
            :subtitle="`${summary.resources.cpu_cores} cores · warn ${summary.resources.thresholds.cpu_warning_percent}% / crit ${summary.resources.thresholds.cpu_critical_percent}%`"
            icon="Activity"
            :status="summary.resources.guardian_status"
          />
          <MetricCard
            title="Server Memory"
            :value="`${summary.resources.ram_percent}%`"
            :subtitle="`${formatMegabytes(summary.resources.ram_used_mb)} / ${formatMegabytes(summary.resources.ram_total_mb)}`"
            icon="Activity"
            :status="summary.resources.ram_percent >= summary.resources.thresholds.ram_warning_percent ? 'warning' : 'normal'"
          />
          <MetricCard
            title="Resource Guardian"
            :value="summary.resources.load_avg_1m !== null ? `Load ${summary.resources.load_avg_1m}` : 'Active'"
            :subtitle="`Disk ${summary.resources.disk_percent}% (${summary.resources.disk_free_gb} GB free)`"
            icon="Workflow"
            :status="summary.resources.guardian_status"
          />
        </div>
      </section>

      <!-- Most Recent Scan Results -->
      <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <div>
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Recent Website Scans
            </h2>
            <p class="text-xs text-slate-500 dark:text-slate-400">
              Latest discovery and content extraction executions recorded in MySQL.
            </p>
          </div>
          <UButton
            to="/websites"
            color="neutral"
            variant="ghost"
            size="xs"
          >
            All Websites
            <ArrowRight class="ml-1 h-3.5 w-3.5" />
          </UButton>
        </div>

        <div
          v-if="summary.recent_scans.length === 0"
          class="p-4"
        >
          <AppEmptyState
            title="No website scans executed yet"
            description="Register a brand and website, then trigger a manual scan to populate your Content Library."
          />
        </div>

        <div
          v-else
          class="overflow-x-auto"
        >
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">Website</th>
                <th class="px-4 py-2.5 font-medium">Method</th>
                <th class="px-4 py-2.5 font-medium">Trigger</th>
                <th class="px-4 py-2.5 font-medium">Status</th>
                <th class="px-4 py-2.5 font-medium">URLs / New / Updated / Failed</th>
                <th class="px-4 py-2.5 font-medium">Duration</th>
                <th class="px-4 py-2.5 font-medium">Created</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="scan in summary.recent_scans"
                :key="scan.id"
                class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
              >
                <td class="px-4 py-2.5 font-medium text-teal-700 dark:text-teal-300">
                  <NuxtLink
                    :to="`/websites/${scan.website_id}`"
                    class="hover:underline"
                  >
                    {{ scan.website_name || `Website #${scan.website_id}` }}
                  </NuxtLink>
                </td>
                <td class="px-4 py-2.5 font-mono text-[11px]">{{ scan.scan_method }}</td>
                <td class="px-4 py-2.5">{{ scan.trigger_type }}</td>
                <td class="px-4 py-2.5">
                  <HealthStatusBadge :status="scan.status === 'completed' ? 'ok' : scan.status === 'partially_completed' ? 'warning' : scan.status" :label="scan.status" />
                </td>
                <td class="px-4 py-2.5 font-mono text-[11px]">
                  {{ scan.urls_found }} / +{{ scan.new_articles }} / ~{{ scan.updated_articles }} / !{{ scan.failed_articles }}
                </td>
                <td class="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                  {{ scan.duration_ms !== null ? `${(scan.duration_ms / 1000).toFixed(1)}s` : '-' }}
                </td>
                <td class="px-4 py-2.5 whitespace-nowrap text-slate-500 dark:text-slate-400">
                  {{ formatDateTime(scan.created_at, summary.timezone) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Recent Activity Logs -->
      <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <div>
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Recent Activity
            </h2>
            <p class="text-xs text-slate-500 dark:text-slate-400">
              Audit trail of authentication, brand, website, scanner, and settings events.
            </p>
          </div>
          <UButton
            to="/logs"
            color="neutral"
            variant="ghost"
            size="xs"
          >
            View All Logs
            <ArrowRight class="ml-1 h-3.5 w-3.5" />
          </UButton>
        </div>

        <div
          v-if="summary.recent_activities.length === 0"
          class="p-4"
        >
          <AppEmptyState
            title="No activity recorded yet"
            description="Administrative events and scan completions will appear here automatically."
          />
        </div>

        <div
          v-else
          class="overflow-x-auto"
        >
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">Timestamp</th>
                <th class="px-4 py-2.5 font-medium">Category</th>
                <th class="px-4 py-2.5 font-medium">Level</th>
                <th class="px-4 py-2.5 font-medium">Action</th>
                <th class="px-4 py-2.5 font-medium">Message</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="item in summary.recent_activities"
                :key="item.id"
                class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
              >
                <td class="px-4 py-2.5 whitespace-nowrap text-slate-500 dark:text-slate-400">
                  {{ formatDateTime(item.created_at, summary.timezone) }}
                </td>
                <td class="px-4 py-2.5 whitespace-nowrap">
                  <UBadge
                    color="neutral"
                    variant="subtle"
                    size="sm"
                  >
                    {{ item.category }}
                  </UBadge>
                </td>
                <td class="px-4 py-2.5 whitespace-nowrap">
                  <HealthStatusBadge :status="item.level === 'info' ? 'ok' : item.level" :label="item.level" />
                </td>
                <td class="px-4 py-2.5 font-mono text-[11px] whitespace-nowrap text-slate-700 dark:text-slate-300">
                  {{ item.action }}
                </td>
                <td class="px-4 py-2.5 text-slate-700 dark:text-slate-200">
                  {{ item.message }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Honest Future-Phase Modules Grid (Phases 3–6) -->
      <section aria-label="Upcoming roadmap modules">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Upcoming Modules (Phases 3–6 — Not Yet Implemented)
            </h2>
            <p class="text-xs text-slate-500 dark:text-slate-400">
              Gemini AI, social publishing, editorial drafting, and automation metrics remain honestly withheld until their scheduled phases.
            </p>
          </div>
          <UBadge
            color="primary"
            variant="subtle"
          >
            Active: Phase 2 Website Monitoring
          </UBadge>
        </div>

        <div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          <NuxtLink
            v-for="mod in futureModules"
            :key="mod.key"
            :to="mod.route"
            class="group rounded-lg border border-slate-200 bg-white p-4 transition-colors hover:border-teal-400 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-teal-700"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-semibold text-slate-900 group-hover:text-teal-700 dark:text-slate-100 dark:group-hover:text-teal-300">
                {{ mod.label }}
              </span>
              <UBadge
                color="neutral"
                variant="subtle"
                size="sm"
              >
                Phase {{ mod.phase }} · Unavailable
              </UBadge>
            </div>
            <p class="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
              {{ mod.summary }}
            </p>
          </NuxtLink>
        </div>
      </section>
    </template>
  </div>
</template>
