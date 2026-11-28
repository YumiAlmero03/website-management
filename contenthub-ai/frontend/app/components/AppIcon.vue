<script setup lang="ts">
import type { Component } from 'vue'
import {
  Activity,
  BarChart3,
  CalendarDays,
  CheckSquare,
  Compass,
  FileText,
  Globe,
  LayoutDashboard,
  Library,
  Plug,
  ScrollText,
  Settings,
  Share2,
  Sparkles,
  Tags,
  Workflow,
} from 'lucide-vue-next'

const props = defineProps<{
  name: string
}>()

const ICON_MAP: Record<string, Component> = {
  LayoutDashboard,
  CheckSquare,
  Tags,
  Globe,
  Library,
  Share2,
  Compass,
  FileText,
  CalendarDays,
  Plug,
  Sparkles,
  Workflow,
  BarChart3,
  Activity,
  ScrollText,
  Settings,
}

const resolvedIcon = computed<Component>(() => ICON_MAP[props.name] || LayoutDashboard)
</script>

<template>
  <component
    :is="resolvedIcon"
    class="h-4 w-4 shrink-0"
    aria-hidden="true"
  />
</template>
