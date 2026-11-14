<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'

const emit = defineEmits(['notify'])
const alerts = ref([])
const loading = ref(false)
const busy = ref('')
const filters = reactive({ status: '', severity: '', source_type: '' })
const openCount = computed(() => alerts.value.filter((item) => item.status !== 'resolved').length)

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

function queryString() {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  const text = params.toString()
  return text ? `?${text}` : ''
}

async function load() {
  loading.value = true
  try {
    alerts.value = await api.alerts(queryString())
  } catch (error) {
    emit('notify', { message: `告警加载失败：${error.message}`, type: 'error' })
  } finally {
    loading.value = false
  }
}

async function handle(alert, action) {
  busy.value = `${alert.id}-${action}`
  try {
    await api.alertAction(alert.id, action)
    emit('notify', { message: action === 'resolve' ? '告警已解决' : '告警已确认' })
    await load()
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div><div class="panel-title">运营告警中心</div><div class="panel-desc">设备故障、质量不合格与交期风险统一处理；当前 {{ openCount }} 条未解决</div></div>
      <div class="toolbar-right">
        <select v-model="filters.status" class="select" @change="load"><option value="">全部状态</option><option value="open">待处理</option><option value="acknowledged">已确认</option><option value="resolved">已解决</option></select>
        <select v-model="filters.severity" class="select" @change="load"><option value="">全部级别</option><option value="critical">严重</option><option value="warning">警告</option><option value="info">提示</option></select>
        <select v-model="filters.source_type" class="select" @change="load"><option value="">全部来源</option><option value="equipment">设备</option><option value="quality">质量</option><option value="agv">AGV</option><option value="deadline">交期</option><option value="system">系统</option></select>
        <button class="btn btn-sm" :disabled="loading" @click="load">{{ loading ? '加载中...' : '刷新' }}</button>
      </div>
    </div>
    <div class="panel-body">
      <div class="table-wrap">
        <table>
          <thead><tr><th>级别</th><th>来源</th><th>告警</th><th>关联对象</th><th>状态</th><th>时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="alert in alerts" :key="alert.id">
              <td><span class="severity-pill" :class="`severity-${alert.severity}`">{{ alert.severity_display }}</span></td>
              <td>{{ alert.source_type_display }}</td>
              <td><div class="cell-main">{{ alert.title }}</div><div class="cell-sub">{{ alert.message }}</div></td>
              <td>
                <RouterLink v-if="alert.work_order" class="link-btn" :to="{ path: '/work-orders', query: { work_order: alert.work_order } }">{{ alert.work_order_no }}</RouterLink>
                <div v-if="alert.equipment_code" class="cell-sub">设备 {{ alert.equipment_code }}</div>
              </td>
              <td>{{ alert.status_display }}<div v-if="alert.resolved_by" class="cell-sub">{{ alert.resolved_by }}</div></td>
              <td class="small">{{ formatTime(alert.created_at) }}</td>
              <td>
                <div class="table-actions">
                  <button v-if="alert.status === 'open'" class="btn btn-sm" :disabled="busy === `${alert.id}-acknowledge`" @click="handle(alert, 'acknowledge')">确认</button>
                  <button v-if="alert.status !== 'resolved'" class="btn btn-sm btn-primary" :disabled="busy === `${alert.id}-resolve`" @click="handle(alert, 'resolve')">解决</button>
                  <span v-else class="muted small">已关闭</span>
                </div>
              </td>
            </tr>
            <tr v-if="!alerts.length"><td colspan="7"><div class="empty">没有匹配的告警</div></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.toolbar-right { display: flex; gap: 8px; flex-wrap: wrap; }
.severity-pill { display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px; border-radius: 999px; font-size: 10px; background: var(--fill-2); border: 1px solid var(--line); color: var(--muted); }
.severity-critical { color: var(--danger-fg); background: var(--tint-red); border-color: var(--tint-red-line); }
.severity-warning { color: var(--warn-fg); background: var(--tint-amber); border-color: var(--tint-amber-line); }
.severity-info { color: var(--info-fg); background: var(--tint-blue); border-color: var(--tint-blue-line); }
</style>
