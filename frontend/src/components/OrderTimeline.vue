<script setup>
defineProps({
  events: { type: Array, default: () => [] },
})

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div v-if="events.length" class="order-timeline">
    <article v-for="event in events" :key="event.id || `${event.event_type}-${event.occurred_at}`" class="timeline-item">
      <span class="timeline-dot" :class="`event-${event.event_type}`"></span>
      <div class="timeline-card">
        <div class="timeline-head">
          <strong>{{ event.title }}</strong>
          <span>{{ event.event_type_display }}</span>
        </div>
        <p v-if="event.description">{{ event.description }}</p>
        <time>{{ formatTime(event.occurred_at) }}</time>
      </div>
    </article>
  </div>
  <div v-else class="empty">暂无订单事件</div>
</template>

<style scoped>
.order-timeline {
  display: grid;
  gap: 0;
  padding: 2px 0;
}
.timeline-item {
  position: relative;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 12px;
  padding-bottom: 18px;
}
.timeline-item:not(:last-child)::before {
  content: "";
  position: absolute;
  left: 5px;
  top: 13px;
  bottom: -1px;
  width: 1px;
  background: #d8e3df;
}
.timeline-dot {
  position: relative;
  z-index: 1;
  width: 11px;
  height: 11px;
  margin-top: 4px;
  border: 3px solid #eef5f2;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 0 1px #8dc4c1;
}
.timeline-dot.event-scheduled { background: var(--blue); box-shadow: 0 0 0 1px #a8c0ec; }
.timeline-dot.event-started { background: var(--purple); box-shadow: 0 0 0 1px #c7b8ed; }
.timeline-dot.event-completed { background: var(--green); box-shadow: 0 0 0 1px #9dd1ba; }
.timeline-dot.event-failed { background: var(--red); box-shadow: 0 0 0 1px #e2aab1; }
.timeline-dot.event-cancelled { background: #7f8d92; box-shadow: 0 0 0 1px #c8d1ce; }
.timeline-card {
  padding: 11px 13px;
  border: 1px solid #e0e8e4;
  border-radius: 10px;
  background: #f8fbfa;
}
.timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.timeline-head strong { color: #1c343c; font-size: 12px; }
.timeline-head span { color: #7a898f; font-size: 10px; }
.timeline-card p {
  margin: 7px 0 5px;
  color: #5e7178;
  font-size: 11px;
  line-height: 1.6;
}
.timeline-card time { color: #8a979b; font-size: 10px; }
</style>
