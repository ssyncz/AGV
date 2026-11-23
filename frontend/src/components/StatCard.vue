<script setup>
defineProps({
  label: String,
  value: [String, Number],
  icon: { type: String, default: '●' },
  accent: { type: String, default: 'cyan' },
})
</script>

<template>
  <div class="panel stat-card" :class="`accent-${accent}`">
    <div class="stat-label"><span class="stat-mark">{{ icon }}</span>{{ label }}</div>
    <div class="stat-value">{{ value }}</div>
  </div>
</template>
