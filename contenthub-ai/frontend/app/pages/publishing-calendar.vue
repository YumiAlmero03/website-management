<script setup lang="ts">
import type { CalendarOptions, DatesSetArg, EventClickArg, EventDropArg } from '@fullcalendar/core'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import luxonPlugin from '@fullcalendar/luxon3'
import timeGridPlugin from '@fullcalendar/timegrid'
import FullCalendar from '@fullcalendar/vue3'
import { CalendarDays, ExternalLink, RefreshCw, XCircle } from 'lucide-vue-next'
import type {
  CalendarEventItem,
  CalendarResponse,
  SocialProfileItem,
  Website,
} from '~/types/api'
import {
  formatUtcForLocalInput,
  getPublishingStatusMeta,
  localInputToUtcIso,
  PUBLISHING_TZ_OPTIONS,
} from '~/utils/ai'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const loading = ref(true)
const errorMessage = ref<string | null>(null)
const events = ref<CalendarEventItem[]>([])
const websites = ref<Website[]>([])
const profiles = ref<SocialProfileItem[]>([])

const websiteFilter = ref<string>('all')
const profileFilter = ref<string>('all')
const platformFilter = ref<string>('all')
const statusFilter = ref<string>('all')
const displayTimezone = ref<string>('Asia/Manila')

const activeRange = ref<{ start: string | null; end: string | null }>({
  start: null,
  end: null,
})

// Event inspection & quick-actions modal
const selectedEvent = ref<CalendarEventItem | null>(null)
const rescheduleLocal = ref('')
const savingAction = ref(false)
const manualUrlInput = ref('')
const manualOpen = ref(false)

const platformOptions = computed(() => {
  const seen = new Map<string, string>()
  for (const p of profiles.value) {
    if (!seen.has(p.platform_key)) {
      seen.set(p.platform_key, p.platform_display_name)
    }
  }
  return Array.from(seen.entries()).map(([key, label]) => ({ key, label }))
})

const filteredProfiles = computed(() => {
  if (websiteFilter.value === 'all') {
    return profiles.value
  }
  return profiles.value.filter((p) => String(p.website_id) === websiteFilter.value)
})

const calendarEvents = computed(() =>
  events.value.map((ev) => ({
    id: ev.id,
    title: ev.title,
    start: ev.start_utc,
    backgroundColor: ev.color,
    borderColor: ev.color,
    editable: ['scheduled', 'manual_reminder', 'deferred'].includes(ev.publishing_status),
    extendedProps: { raw: ev },
  })),
)

const calendarOptions = computed<CalendarOptions>(() => ({
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin, luxonPlugin],
  initialView: 'dayGridMonth',
  timeZone: displayTimezone.value || 'Asia/Manila',
  headerToolbar: {
    left: 'prev,next today',
    center: 'title',
    right: 'dayGridMonth,timeGridWeek,timeGridDay',
  },
  height: 'auto',
  editable: true,
  eventDurationEditable: false,
  nowIndicator: true,
  dayMaxEvents: 4,
  events: calendarEvents.value,
  datesSet: handleDatesSet,
  eventClick: handleEventClick,
  eventDrop: handleEventDrop,
}))

async function loadSelectors() {
  try {
    const [sitesRes, profsRes] = await Promise.all([
      request<{ items: Website[] }>('/api/v1/websites', {
        query: { page: 1, page_size: 100 },
      }),
      request<SocialProfileItem[]>('/api/v1/social-profiles'),
    ])
    websites.value = sitesRes.items
    profiles.value = profsRes
  }
  catch {
    // Selector error handled during main calendar load
  }
}

async function loadCalendar() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number | boolean | undefined> = {
      website_id: websiteFilter.value !== 'all' ? Number(websiteFilter.value) : undefined,
      social_profile_id: profileFilter.value !== 'all' ? Number(profileFilter.value) : undefined,
      platform_key: platformFilter.value !== 'all' ? platformFilter.value : undefined,
      status: statusFilter.value !== 'all' ? statusFilter.value : undefined,
      start: activeRange.value.start || undefined,
      end: activeRange.value.end || undefined,
    }
    const res = await request<CalendarResponse>('/api/v1/publishing/calendar', { query })
    events.value = res.events
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load publishing calendar events.')
  }
  finally {
    loading.value = false
  }
}

function handleDatesSet(info: DatesSetArg) {
  activeRange.value = {
    start: info.start.toISOString(),
    end: info.end.toISOString(),
  }
  void loadCalendar()
}

function handleEventClick(info: EventClickArg) {
  const raw = info.event.extendedProps?.raw as CalendarEventItem | undefined
  if (!raw) {
    return
  }
  selectedEvent.value = raw
  rescheduleLocal.value = formatUtcForLocalInput(raw.start_utc, displayTimezone.value)
  manualUrlInput.value = raw.published_url || ''
  manualOpen.value = false
}

async function handleEventDrop(info: EventDropArg) {
  const raw = info.event.extendedProps?.raw as CalendarEventItem | undefined
  const droppedStart = info.event.start
  if (!raw || !droppedStart) {
    info.revert()
    return
  }
  if (!['scheduled', 'manual_reminder', 'deferred'].includes(raw.publishing_status)) {
    info.revert()
    return
  }
  try {
    await request(`/api/v1/social-posts/${raw.social_post_id}/schedule`, {
      method: 'POST',
      body: {
        scheduled_at: droppedStart.toISOString(),
        display_timezone: displayTimezone.value,
      },
    })
    toast.add({
      title: 'Rescheduled post',
      description: `Moved "${raw.title}" to ${formatDateTime(droppedStart.toISOString(), displayTimezone.value)}.`,
      color: 'success',
    })
    await loadCalendar()
  }
  catch (err) {
    info.revert()
    toast.add({
      title: 'Reschedule rejected',
      description: extractErrorMessage(err, 'Post could not be moved to that time slot.'),
      color: 'error',
    })
  }
}

async function saveQuickReschedule() {
  if (!selectedEvent.value) {
    return
  }
  const utcIso = localInputToUtcIso(rescheduleLocal.value, displayTimezone.value)
  if (!utcIso) {
    return
  }
  savingAction.value = true
  try {
    await request(`/api/v1/social-posts/${selectedEvent.value.social_post_id}/schedule`, {
      method: 'POST',
      body: {
        scheduled_at: utcIso,
        display_timezone: displayTimezone.value,
      },
    })
    toast.add({ title: 'Schedule updated', color: 'success' })
    selectedEvent.value = null
    await loadCalendar()
  }
  catch (err) {
    toast.add({
      title: 'Reschedule failed',
      description: extractErrorMessage(err, 'Verify future timestamp and preflight approval status.'),
      color: 'error',
    })
  }
  finally {
    savingAction.value = false
  }
}

async function cancelEventSchedule() {
  if (!selectedEvent.value) {
    return
  }
  savingAction.value = true
  try {
    await request(`/api/v1/social-posts/${selectedEvent.value.social_post_id}/cancel-schedule`, {
      method: 'POST',
      body: { reason: 'Cancelled from Publishing Calendar' },
    })
    toast.add({ title: 'Schedule cancelled', color: 'neutral' })
    selectedEvent.value = null
    await loadCalendar()
  }
  catch (err) {
    toast.add({
      title: 'Cancel failed',
      description: extractErrorMessage(err, 'Could not cancel schedule.'),
      color: 'error',
    })
  }
  finally {
    savingAction.value = false
  }
}

async function submitManualRecorded() {
  if (!selectedEvent.value || !manualUrlInput.value.trim()) {
    return
  }
  savingAction.value = true
  try {
    await request(`/api/v1/social-posts/${selectedEvent.value.social_post_id}/mark-published`, {
      method: 'POST',
      body: {
        published_url: manualUrlInput.value.trim(),
        notes: 'Recorded from Publishing Calendar',
      },
    })
    toast.add({ title: 'Manual publication recorded', color: 'success' })
    selectedEvent.value = null
    await loadCalendar()
  }
  catch (err) {
    toast.add({
      title: 'Recording failed',
      description: extractErrorMessage(err, 'Verify live post URL.'),
      color: 'error',
    })
  }
  finally {
    savingAction.value = false
  }
}

watch(
  () => uiStore.selectedWebsiteId,
  (val) => {
    websiteFilter.value = val !== null ? String(val) : 'all'
    profileFilter.value = 'all'
    void loadCalendar()
  },
  { immediate: true },
)

watch([websiteFilter, profileFilter, platformFilter, statusFilter], () => {
  void loadCalendar()
})

onMounted(async () => {
  await loadSelectors()
  await loadCalendar()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="flex items-center gap-2 text-xl font-semibold text-slate-900 dark:text-slate-100">
          <CalendarDays class="h-5 w-5 text-teal-600" />
          Publishing Calendar
        </h1>
        <p class="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
          Scheduled API posts, manual reminders, published history, and verification items rendered in {{ displayTimezone }}. Drag scheduled items to reschedule.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton to="/social-media" color="neutral" variant="outline" size="xs">
          Social Publishing Hub
        </UButton>
        <UButton to="/connected-accounts" color="neutral" variant="outline" size="xs">
          Connected Accounts
        </UButton>
        <UButton color="primary" size="xs" :loading="loading" @click="loadCalendar">
          <RefreshCw class="mr-1 h-3.5 w-3.5" />
          Refresh
        </UButton>
      </div>
    </div>

    <!-- Filters & Timezone Switcher -->
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="websiteFilter" class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900">
          <option value="all">All Websites</option>
          <option v-for="site in websites" :key="site.id" :value="String(site.id)">{{ site.name }}</option>
        </select>
        <select v-model="platformFilter" class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900">
          <option value="all">All Platforms</option>
          <option v-for="opt in platformOptions" :key="opt.key" :value="opt.key">{{ opt.label }}</option>
        </select>
        <select v-model="profileFilter" class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900">
          <option value="all">All Profiles</option>
          <option v-for="prof in filteredProfiles" :key="prof.id" :value="String(prof.id)">
            {{ prof.website_name }} · {{ prof.profile_name }}
          </option>
        </select>
        <select v-model="statusFilter" class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900">
          <option value="all">All Event Statuses</option>
          <option value="scheduled">Scheduled</option>
          <option value="published">Published (API)</option>
          <option value="manually_published">Published (Manual)</option>
          <option value="verification_required">Verification Required</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      <div class="flex items-center gap-2">
        <span class="text-slate-500">Display TZ:</span>
        <select v-model="displayTimezone" class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900">
          <option v-for="tz in PUBLISHING_TZ_OPTIONS" :key="tz.value" :value="tz.value">
            {{ tz.label }}
          </option>
        </select>
      </div>
    </div>

    <!-- Color Legend -->
    <div class="flex flex-wrap gap-3 text-[11px] text-slate-600 dark:text-slate-300">
      <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-teal-600" /> Scheduled API</span>
      <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-violet-600" /> Manual Reminder</span>
      <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-emerald-600" /> Published</span>
      <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-sky-600" /> Manual Recorded</span>
      <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-orange-600" /> Verify Outcome</span>
      <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-red-600" /> Failed</span>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Calendar unavailable"
      :message="errorMessage"
      retryable
      @retry="loadCalendar()"
    />

    <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      <ClientOnly>
        <FullCalendar :options="calendarOptions" />
        <template #fallback>
          <USkeleton class="h-[620px] w-full" />
        </template>
      </ClientOnly>
    </div>

    <!-- Calendar Event Detail Modal -->
    <UModal
      :open="Boolean(selectedEvent)"
      :title="selectedEvent?.title || 'Publication Event'"
      @update:open="(val) => { if (!val) selectedEvent = null }"
    >
      <template #body>
        <div v-if="selectedEvent" class="space-y-3 text-xs">
          <div class="flex flex-wrap items-center gap-2">
            <UBadge :color="getPublishingStatusMeta(selectedEvent.publishing_status).color" variant="subtle" size="xs">
              {{ getPublishingStatusMeta(selectedEvent.publishing_status).label }}
            </UBadge>
            <UBadge color="neutral" variant="outline" size="xs">
              {{ selectedEvent.platform_display_name || selectedEvent.platform_key }}
            </UBadge>
            <UBadge color="neutral" variant="soft" size="xs">
              {{ selectedEvent.publishing_method === 'api' ? 'API' : 'Manual' }}
            </UBadge>
          </div>

          <div class="grid grid-cols-1 gap-2 rounded bg-slate-50 p-2.5 sm:grid-cols-2 dark:bg-slate-950/60">
            <div>
              <span class="text-slate-500">Website:</span>
              <span class="ml-1 font-medium">{{ selectedEvent.website_name }}</span>
            </div>
            <div>
              <span class="text-slate-500">Profile:</span>
              <span class="ml-1 font-medium">{{ selectedEvent.profile_name }}</span>
            </div>
            <div>
              <span class="text-slate-500">Local ({{ displayTimezone }}):</span>
              <span class="ml-1 font-mono">{{ formatDateTime(selectedEvent.start_utc, displayTimezone) }}</span>
            </div>
            <div>
              <span class="text-slate-500">UTC:</span>
              <span class="ml-1 font-mono">{{ formatDateTime(selectedEvent.start_utc, 'UTC') }}</span>
            </div>
          </div>

          <p class="rounded border border-slate-200 p-2.5 text-slate-700 dark:border-slate-700 dark:text-slate-200">
            {{ selectedEvent.caption_preview }}
          </p>

          <p v-if="selectedEvent.last_error" class="rounded border border-rose-200 bg-rose-50 p-2 text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200">
            Error: {{ selectedEvent.last_error }}
          </p>

          <a
            v-if="selectedEvent.published_url"
            :href="selectedEvent.published_url"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 text-teal-600 hover:underline dark:text-teal-400"
          >
            View Live Published URL <ExternalLink class="h-3 w-3" />
          </a>

          <div
            v-if="['scheduled', 'manual_reminder', 'deferred'].includes(selectedEvent.publishing_status)"
            class="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800"
          >
            <label class="block font-medium">Reschedule ({{ displayTimezone }})</label>
            <div class="flex flex-wrap items-center gap-2">
              <input
                v-model="rescheduleLocal"
                type="datetime-local"
                class="h-8 rounded border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
              <UButton color="primary" size="xs" :loading="savingAction" @click="saveQuickReschedule">
                Save New Time
              </UButton>
              <UButton color="warning" variant="outline" size="xs" :loading="savingAction" @click="cancelEventSchedule">
                <XCircle class="mr-1 h-3 w-3" />
                Cancel Schedule
              </UButton>
            </div>
            <div v-if="selectedEvent.publishing_method === 'manual'" class="pt-1">
              <UButton color="info" variant="subtle" size="xs" @click="manualOpen = !manualOpen">
                Record Live URL (Mark Published)
              </UButton>
              <div v-if="manualOpen" class="mt-2 flex gap-2">
                <UInput v-model="manualUrlInput" size="xs" placeholder="https://..." class="flex-1" />
                <UButton color="success" size="xs" :loading="savingAction" @click="submitManualRecorded">
                  Save
                </UButton>
              </div>
            </div>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton to="/social-media" color="neutral" variant="outline" size="xs">
              Open in Social Publishing Hub
            </UButton>
            <UButton color="neutral" variant="ghost" size="xs" @click="selectedEvent = null">
              Close
            </UButton>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
