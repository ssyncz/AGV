<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'
import StatCard from '../components/StatCard.vue'
import StatusBadge from '../components/StatusBadge.vue'

const emit = defineEmits(['notify'])
const data = ref({ kpis: {}, alerts: [], work_orders: [], events: [], recent_dispatches: [] })
const loading = ref(true)
const busyAlert = ref(null)
let timer = null

const kpis = computed(() => data.value.kpis || {})

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    data.value = await api.commandCenter()
  } catch (error) {
    if (!silent) emit('notify', { message: `驾驶舱加载失败：${error.message}`, type: 'error' })
  } finally {
    loading.value = false
  }
}

async function handleAlert(alert, action) {
  busyAlert.value = `${alert.id}-${action}`
  try {
    await api.alertAction(alert.id, action)
    emit('notify', { message: action === 'resolve' ? '告警已解决' : '告警已确认' })
    await load(true)
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busyAlert.value = null
  }
}

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 15000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <div class="grid stats-grid">
      <StatCard label="活动工单" :value="kpis.active_work_orders || 0" :foot="`${kpis.active_operation_steps || 0} 个工序可执行或执行中`" icon="▤" accent="blue" />
      <StatCard label="阻塞工单" :value="kpis.blocked_work_orders || 0" foot="设备或质量异常导致" icon="!" accent="amber" />
      <StatCard label="开放告警" :value="kpis.open_alerts || 0" foot="待确认与待解决" icon="◉" accent="cyan" />
      <StatCard label="严重告警" :value="kpis.critical_alerts || 0" foot="需要立即处理" icon="▲" accent="red" />
    </div>

    <div class="command-strip panel mb-16">
      <RouterLink class="command-action" to="/work-orders">
        <span>工单主线</span><strong>{{ kpis.work_order_total || 0 }}</strong><small>创建、下达与追溯</small>
      </RouterLink>
      <RouterLink class="command-action" to="/tasks">
        <span>运输任务</span><strong>{{ kpis.active_tasks || 0 }}</strong><small>{{ kpis.pending_tasks || 0 }} 个待调度</small>
      </RouterLink>
      <RouterLink class="command-action" to="/agvs">
        <span>可用 AGV</span><strong>{{ kpis.agv_available || 0 }}/{{ kpis.agv_total || 0 }}</strong><small>空闲车辆 / 车队总数</small>
      </RouterLink>
      <RouterLink class="command-action" to="/equipment">
        <span>设备异常</span><strong>{{ (kpis.equipment_faults || 0) + (kpis.equipment_warnings || 0) }}</strong><small>{{ kpis.equipment_faults || 0 }} 故障 · {{ kpis.equipment_warnings || 0 }} 预警</small>
      </RouterLink>
      <RouterLink class="command-action" to="/work-orders?quality_status=fail">
        <span>质量不合格</span><strong>{{ kpis.quality_failed || 0 }}</strong><small>需要返工或复检</small>
      </RouterLink>
      <RouterLink class="command-action" to="/tasks">
        <span>交期风险</span><strong>{{ kpis.overdue_tasks || 0 }}</strong><small>已超过交期的任务</small>
      </RouterLink>
    </div>

    <div class="grid command-grid">
      <section class="panel">
        <div class="panel-head">
          <div><div class="panel-title">异常处理队列</div><div class="panel-desc">设备、质量和运营异常统一进入这里</div></div>
          <RouterLink class="link-btn" to="/alerts">查看全部</RouterLink>
        </div>
        <div class="panel-body">
          <div v-if="data.alerts.length" class="alert-list">
            <article v-for="alert in data.alerts" :key="alert.id" class="alert-card" :class="`severity-${alert.severity}`">
              <div class="alert-card-main">
                <div class="alert-title-row">
                  <span class="alert-source">{{ alert.source_type_display }}</span>
                  <strong>{{ alert.title }}</strong>
                  <span class="tag">{{ alert.severity_display }}</span>
                </div>
                <p>{{ alert.message }}</p>
                <div class="cell-sub">
                  {{ formatTime(alert.created_at) }}
                  <span v-if="alert.work_order_no"> · 工单 {{ alert.work_order_no }}</span>
                  <span v-if="alert.equipment_code"> · 设备 {{ alert.equipment_code }}</span>
                </div>
              </div>
              <div class="alert-actions">
                <button v-if="alert.status === 'open'" class="btn btn-sm" :disabled="busyAlert === `${alert.id}-acknowledge`" @click="handleAlert(alert, 'acknowledge')">确认</button>
                <button class="btn btn-sm btn-primary" :disabled="busyAlert === `${alert.id}-resolve`" @click="handleAlert(alert, 'resolve')">解决</button>
              </div>
            </article>
          </div>
          <div v-else class="empty">当前没有开放告警</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">最近业务事件</div><div class="panel-desc">跨模块操作形成统一时间线</div></div></div>
        <div class="panel-body">
          <div v-if="data.events.length" class="event-timeline">
            <div v-for="event in data.events" :key="event.id" class="event-row">
              <span class="event-dot"></span>
              <div>
                <div class="strong">{{ event.summary }}</div>
                <div class="cell-sub">{{ event.event_type }} · {{ event.actor }} · {{ formatTime(event.created_at) }}</div>
              </div>
            </div>
          </div>
          <div v-else class="empty">暂无业务事件</div>
        </div>
      </section>
    </div>

    <section class="panel mt-16">
      <div class="panel-head">
        <div><div class="panel-title">工单执行主线</div><div class="panel-desc">从计划、运输、质检到完成统一追踪</div></div>
        <RouterLink class="btn btn-sm btn-primary" to="/work-orders">进入工单中心</RouterLink>
      </div>
      <div class="panel-body">
        <div class="table-wrap">
          <table>
            <thead><tr><th>工单</th><th>产品</th><th>状态</th><th>质检</th><th>任务进度</th><th>开放告警</th><th>交期</th></tr></thead>
            <tbody>
              <tr v-for="order in data.work_orders" :key="order.id">
                <td><RouterLink class="cell-main mono" :to="{ path: '/work-orders', query: { work_order: order.id } }">{{ order.order_no }}</RouterLink><div class="cell-sub">{{ order.title }}</div></td>
                <td>{{ order.product_detail?.name || '--' }}<div class="cell-sub">{{ order.quantity }} {{ order.product_detail?.unit || '件' }}</div></td>
                <td><StatusBadge :status="order.status" :label="order.status_display" /></td>
                <td><span class="tag" :class="`quality-${order.quality_status}`">{{ order.quality_status_display }}</span></td>
                <td>{{ order.completed_task_count || 0 }}/{{ order.task_count || 0 }}</td>
                <td><span :class="{ 'text-danger': order.open_alert_count }">{{ order.open_alert_count || 0 }}</span></td>
                <td class="small">{{ formatTime(order.due_at) }}</td>
              </tr>
              <tr v-if="!data.work_orders.length"><td colspan="7"><div class="empty">暂无工单</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.command-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); overflow: hidden; }
.command-action { min-height: 104px; display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 16px; border-right: 1px solid var(--line); text-decoration: none; transition: background 150ms ease; }
.command-action:last-child { border-right: 0; }
.command-action:hover { background: #f5f9f7; }
.command-action span { color: var(--muted); font-size: 11px; }
.command-action strong { color: #14262e; font-size: 25px; line-height: 1.1; }
.command-action small { color: var(--muted); font-size: 10px; }
.command-grid { grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr); align-items: stretch; }
.command-grid > .panel { height: 560px; min-height: 0; display: flex; flex-direction: column; }
.command-grid > .panel > .panel-body { flex: 1; min-height: 0; overflow-y: auto; }
.alert-list { display: grid; gap: 10px; }
.alert-card { display: flex; justify-content: space-between; gap: 16px; padding: 13px 14px; border: 1px solid var(--line); border-left: 3px solid var(--amber); border-radius: 10px; background: #fbfcfb; }
.alert-card.severity-critical { border-left-color: var(--red); background: #fff9f9; }
.alert-card-main { min-width: 0; }
.alert-title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.alert-source { color: var(--cyan); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.alert-card p { margin: 6px 0 5px; color: var(--text-soft); font-size: 12px; line-height: 1.5; }
.alert-actions { display: flex; align-items: flex-start; gap: 6px; }
.event-timeline { display: grid; gap: 0; padding-right: 6px; }
.event-row { position: relative; display: grid; grid-template-columns: 18px 1fr; gap: 8px; padding: 0 0 16px; }
.event-row::before { content: ""; position: absolute; top: 8px; bottom: 0; left: 4px; width: 1px; background: var(--line); }
.event-row:last-child::before { display: none; }
.event-dot { width: 9px; height: 9px; margin-top: 4px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 0 4px rgba(14,135,146,.1); z-index: 1; }
.quality-fail { color: var(--red); background: #fdeef0; }
.quality-pass { color: var(--green); background: #eaf7f1; }
.text-danger { color: var(--red); font-weight: 700; }
@media (max-width: 1180px) { .command-strip { grid-template-columns: repeat(3, 1fr); } .command-action:nth-child(3n) { border-right: 0; } }
@media (max-width: 900px) {
  .command-grid { grid-template-columns: 1fr; }
  .command-grid > .panel { height: 520px; }
  .command-strip { grid-template-columns: repeat(2, 1fr); }
}
</style>
