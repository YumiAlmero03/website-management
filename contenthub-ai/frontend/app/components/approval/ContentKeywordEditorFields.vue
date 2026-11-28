<script setup lang="ts">
import { AlertTriangle, Plus, Sparkles, Trash2 } from 'lucide-vue-next'
import type {
  CannibalizationMatch,
  ImageAltSuggestionItem,
} from '~/types/api'
import { CONTENT_TYPE_OPTIONS } from '~/utils/format'
import {
  areAnchorsSyncedWithKeywords,
  buildSyncedAnchors,
} from '~/utils/keywordSuggestions'

const props = withDefaults(
  defineProps<{
    focusKeyphrase: string
    secondaryKeywords: string[]
    anchorTextVariations: string[]
    imageAltSuggestions: ImageAltSuggestionItem[]
    contentType?: string
    showContentType?: boolean
    cannibalizationWarnings?: CannibalizationMatch[]
    aiRefining?: boolean
    disabled?: boolean
  }>(),
  {
    contentType: 'blog_post',
    showContentType: true,
    cannibalizationWarnings: () => [],
    aiRefining: false,
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:focusKeyphrase': [value: string]
  'update:secondaryKeywords': [value: string[]]
  'update:anchorTextVariations': [value: string[]]
  'update:imageAltSuggestions': [value: ImageAltSuggestionItem[]]
  'update:contentType': [value: string]
  'requestAiRefine': []
}>()

const newSecondaryInput = ref('')

const anchorsSyncedWithKeywords = computed(() =>
  areAnchorsSyncedWithKeywords(
    props.focusKeyphrase,
    props.secondaryKeywords,
    props.anchorTextVariations,
  ),
)

function emitFocusKeyphrase(nextFocus: string) {
  const shouldSync = anchorsSyncedWithKeywords.value
  emit('update:focusKeyphrase', nextFocus)
  if (shouldSync) {
    emit('update:anchorTextVariations', buildSyncedAnchors(nextFocus, props.secondaryKeywords))
  }
}

function addSecondaryKeyword() {
  const parts = newSecondaryInput.value
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (parts.length === 0) {
    return
  }
  const shouldSync = anchorsSyncedWithKeywords.value
  const existing = new Set(props.secondaryKeywords.map((k) => k.toLowerCase()))
  const merged = [...props.secondaryKeywords]
  for (const part of parts) {
    if (!existing.has(part.toLowerCase()) && part.toLowerCase() !== props.focusKeyphrase.trim().toLowerCase()) {
      existing.add(part.toLowerCase())
      merged.push(part)
    }
  }
  emit('update:secondaryKeywords', merged)
  if (shouldSync) {
    emit('update:anchorTextVariations', buildSyncedAnchors(props.focusKeyphrase, merged))
  }
  newSecondaryInput.value = ''
}

function removeSecondaryKeyword(idx: number) {
  const shouldSync = anchorsSyncedWithKeywords.value
  const next = props.secondaryKeywords.filter((_, i) => i !== idx)
  emit('update:secondaryKeywords', next)
  if (shouldSync) {
    emit('update:anchorTextVariations', buildSyncedAnchors(props.focusKeyphrase, next))
  }
}

function resyncAnchorsFromKeywords() {
  emit(
    'update:anchorTextVariations',
    buildSyncedAnchors(props.focusKeyphrase, props.secondaryKeywords),
  )
}

function updateAltText(idx: number, value: string) {
  const next = props.imageAltSuggestions.map((item, i) =>
    i === idx ? { ...item, suggested_alt: value } : item,
  )
  emit('update:imageAltSuggestions', next)
}

function removeAltSuggestion(idx: number) {
  emit('update:imageAltSuggestions', props.imageAltSuggestions.filter((_, i) => i !== idx))
}
</script>

<template>
  <div class="space-y-4">
    <!-- Cannibalization non-blocking warning -->
    <div
      v-if="cannibalizationWarnings.length > 0"
      class="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-800/70 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <div class="flex items-start gap-2">
        <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <div class="space-y-1">
          <p class="font-semibold">
            Keyword overlap warnings ({{ cannibalizationWarnings.length }})
          </p>
          <p class="text-[11px] opacity-90">
            Another URL uses an identical or related focus keyphrase. Review whether the pages target the same intent:
          </p>
          <ul class="space-y-1 pt-1">
            <li
              v-for="match in cannibalizationWarnings"
              :key="match.content_id"
              class="flex flex-wrap items-center gap-1.5 text-[11px]"
            >
              <UBadge
                :color="match.severity === 'high' ? 'error' : 'warning'"
                variant="subtle"
                size="xs"
              >
                {{ match.similarity_score }}%
              </UBadge>
              <span>{{ match.severity === 'high' ? 'Exact keyword overlap' : 'Possible cannibalization' }}</span>
              <NuxtLink
                :to="`/content-library/${match.content_id}`"
                class="font-medium underline"
              >
                {{ match.title }}
              </NuxtLink>
              <span class="font-mono text-[10px] opacity-80">({{ match.focus_keyphrase }})</span>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Classification + Focus Keyphrase -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div v-if="showContentType">
        <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300">
          Content Classification
        </label>
        <select
          :value="contentType"
          :disabled="disabled"
          class="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-800 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          @change="emit('update:contentType', ($event.target as HTMLSelectElement).value)"
        >
          <option
            v-for="opt in CONTENT_TYPE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </option>
        </select>
      </div>

      <div :class="showContentType ? 'sm:col-span-2' : 'sm:col-span-3'">
        <div class="flex items-center justify-between">
          <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300">
            Primary Focus Keyphrase *
          </label>
          <UButton
            type="button"
            size="xs"
            color="neutral"
            variant="ghost"
            :loading="aiRefining"
            :disabled="disabled"
            @click="emit('requestAiRefine')"
          >
            <Sparkles class="mr-1 h-3 w-3 text-teal-600" />
            AI Refine Suggestions
          </UButton>
        </div>
        <input
          :value="focusKeyphrase"
          type="text"
          :disabled="disabled"
          placeholder="e.g. Fixed Odds vs Dynamic Odds"
          class="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-xs font-medium text-slate-900 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          :class="cannibalizationWarnings.length > 0 ? '!border-yellow-400 !bg-yellow-100 dark:!border-yellow-600 dark:!bg-yellow-950' : ''"
          @input="emitFocusKeyphrase(($event.target as HTMLInputElement).value)"
        >
      </div>
    </div>

    <!-- Secondary Keywords -->
    <div>
      <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300">
        Secondary Keywords
      </label>
      <div class="mt-1.5 flex flex-wrap gap-1.5">
        <span
          v-for="(kw, idx) in secondaryKeywords"
          :key="`${kw}-${idx}`"
          class="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[11px] text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          {{ kw }}
          <button
            v-if="!disabled"
            type="button"
            class="text-slate-400 hover:text-rose-600"
            aria-label="Remove secondary keyword"
            @click="removeSecondaryKeyword(idx)"
          >
            ×
          </button>
        </span>
        <span
          v-if="secondaryKeywords.length === 0"
          class="text-[11px] text-slate-400"
        >
          No secondary keywords added yet.
        </span>
      </div>
      <div class="mt-2 flex gap-2">
        <input
          v-model="newSecondaryInput"
          type="text"
          :disabled="disabled"
          placeholder="Add secondary keyword (comma or Enter separated)"
          class="h-8 flex-1 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-800 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          @keydown.enter.prevent="addSecondaryKeyword"
        >
        <UButton
          type="button"
          size="xs"
          color="neutral"
          variant="outline"
          :disabled="disabled || !newSecondaryInput.trim()"
          @click="addSecondaryKeyword"
        >
          <Plus class="mr-1 h-3 w-3" />
          Add
        </UButton>
      </div>
    </div>

    <!-- Anchor Text Variations (Clickable Link Copy) -->
    <div>
      <div class="flex items-center justify-between gap-2">
        <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300">
          Suggested Anchor Text Variations (for clickable links)
        </label>
        <button
          v-if="!disabled && !anchorsSyncedWithKeywords"
          type="button"
          class="text-[11px] font-medium text-teal-600 hover:underline dark:text-teal-400"
          @click="resyncAnchorsFromKeywords"
        >
          Sync with Focus + Secondary
        </button>
      </div>
      <div class="mt-1.5 flex flex-wrap gap-1.5">
        <span
          v-for="(anc, idx) in anchorTextVariations"
          :key="`${anc}-${idx}`"
          class="inline-flex items-center gap-1 rounded-full border border-teal-200 bg-teal-50 px-2.5 py-0.5 text-[11px] text-teal-800 dark:border-teal-900/60 dark:bg-teal-950/40 dark:text-teal-200"
        >
          {{ anc }}
        </span>
      </div>
    </div>

    <!-- Image-specific Alt Text Suggestions -->
    <div v-if="imageAltSuggestions.length > 0">
      <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300">
        Image Alt Text Suggestions (descriptive accessibility text, distinct from link anchors)
      </label>
      <div class="mt-1.5 space-y-2">
        <div
          v-for="(altItem, idx) in imageAltSuggestions"
          :key="idx"
          class="rounded-md border border-slate-200 bg-slate-50/70 p-2.5 dark:border-slate-800 dark:bg-slate-950/50"
        >
          <div class="flex items-center justify-between gap-2 text-[11px] text-slate-500">
            <span class="truncate font-mono">
              {{ altItem.image_url || altItem.context || `Image #${idx + 1}` }}
            </span>
            <button
              v-if="!disabled"
              type="button"
              class="text-slate-400 hover:text-rose-600"
              aria-label="Remove image alt suggestion"
              @click="removeAltSuggestion(idx)"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
          <input
            :value="altItem.suggested_alt"
            type="text"
            :disabled="disabled"
            placeholder="Describe what appears in the image clearly"
            class="mt-1.5 h-8 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-800 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            @input="updateAltText(idx, ($event.target as HTMLInputElement).value)"
          >
        </div>
      </div>
    </div>
  </div>
</template>
