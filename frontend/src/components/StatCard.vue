<script setup>
defineProps({
  label: String,
  value: [String, Number],
  foot: String,
  icon: { type: String, default: '●' },
  accent: { type: String, default: 'cyan' },
})
</script>

<template>
  <article class="panel stat-card" :class="`accent-${accent}`">
    <span class="stat-accent" aria-hidden="true"></span>
    <div class="stat-head">
      <span class="stat-mark">{{ icon }}</span>
      <span class="stat-label">{{ label }}</span>
      <span class="stat-signal"><i></i>LIVE</span>
    </div>
    <div class="stat-value">{{ value }}</div>
    <div class="stat-foot">{{ foot }}</div>
  </article>
</template>
