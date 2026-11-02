<script setup>
defineProps({
  status: { type: String, default: 'idle' },
  label: { type: String, default: '' },
})

const names = {
  idle: '空闲', busy: '执行任务', charging: '充电中', offline: '离线', error: '故障',
  pending: '待调度', assigned: '已分配', in_progress: '执行中', completed: '已完成',
  failed: '失败', cancelled: '已取消',
  draft: '草稿', released: '已下达', quality_check: '待质检', blocked: '已阻塞',
  normal: '正常', warning: '预警', fault: '故障', maintenance: '维护中',
  open: '待处理', acknowledged: '已确认', resolved: '已解决',
}
</script>

<template>
  <span class="badge" :class="`badge-${status}`">{{ label || names[status] || status }}</span>
</template>
