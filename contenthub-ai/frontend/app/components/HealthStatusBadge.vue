<script setup lang="ts">
const props = defineProps<{
  status: string
  label?: string
}>()

type BadgeColor = 'success' | 'warning' | 'error' | 'neutral' | 'primary' | 'info'

const normalizedStatus = computed(() => props.status.trim().toLowerCase())

const badgeColor = computed<BadgeColor>(() => {
  switch (normalizedStatus.value) {
    case 'ok':
    case 'normal':
    case 'connected':
    case 'active':
    case 'healthy':
      return 'success'
    case 'warning':
      return 'warning'
    case 'critical':
    case 'degraded':
    case 'unavailable':
    case 'error':
    case 'failed':
      return 'error'
    default:
      return 'neutral'
  }
})

const displayLabel = computed(() => {
  if (props.label) {
    return props.label
  }
  return normalizedStatus.value
    .split('_')
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ')
})
</script>

<template>
  <UBadge
    :color="badgeColor"
    variant="subtle"
    size="sm"
  >
    {{ displayLabel }}
  </UBadge>
</template>
