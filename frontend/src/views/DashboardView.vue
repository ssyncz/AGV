<script setup>
import { computed } from 'vue'
import StatCard from '../components/StatCard.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({
  overview: { type: Object, default: () => ({}) },
  agvs: { type: Array, default: () => [] },
  tasks: { type: Array, default: () => [] },
  dispatches: { type: Array, default: () => [] },
})

const utilization = computed(() => props.overview.fleet_utilization || 0)
const recentTasks = computed(() => props.tasks.slice(0, 6))
const statusGroups = computed(() => [
  { key: 'idle', label: '空闲', color: '#29976a' },
  { key: 'busy', label: '执行中', color: '#2f6fda' },
  { key: 'charging', label: '充电中', color: '#c58a1b' },
  { key: 'offline', label: '离线/故障', color: '#cf5260' },
])

function groupCount(key) {
  const counts = props.overview.agv_status_counts || {}
  if (key === 'offline') return (counts.offline || 0) + (counts.error || 0)
  return counts[key] || 0
}

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div>
    <div class="grid stats-grid">
      <StatCard label="AGV 总数" :value="overview.agv_total || 0" foot="已接入调度平台的车辆" icon="▣" accent="cyan" />
      <StatCard label="待调度任务" :value="overview.pending_tasks || 0" foot="等待自动分配任务" icon="◇" accent="amber" />
      <StatCard label="执行中任务" :value="overview.active_tasks || 0" foot="已分配或正在运输" icon="▶" accent="blue" />
      <StatCard label="已完成任务" :value="overview.completed_tasks || 0" foot="累计完成运输任务" icon="✓" accent="green" />
    </div>

    <div v-if="overview.overdue_tasks" class="notice warning mb-16">
      <strong>交期告警：</strong>{{ overview.overdue_tasks }} 个未完成任务已经超过要求完成时间，请优先处理或重新排程。
    </div>
    <div v-else-if="overview.due_soon_tasks" class="notice info mb-16">
      <strong>未来 24 小时：</strong>{{ overview.due_soon_tasks }} 个任务即将到期；当前有 {{ overview.active_production_plans || 0 }} 个生产计划处于活动状态。
    </div>

    <div class="grid dashboard-grid">
      <section class="panel">
        <div class="panel-head">
          <div><div class="panel-title">车队负载与运行状态</div><div class="panel-desc">实时统计 AGV 状态与平均电量</div></div>
          <StatusBadge status="idle" label="系统在线" />
        </div>
        <div class="panel-body">
          <div class="utilization-wrap">
            <div class="utilization-ring" :style="{ '--value': utilization }">
              <div class="utilization-ring-inner">
                <div class="utilization-value">{{ utilization }}%</div>
                <div class="utilization-label">车队利用率</div>
              </div>
            </div>
            <div class="legend-list">
              <div v-for="item in statusGroups" :key="item.key" class="legend-row">
                <div class="legend-name"><span class="legend-dot" :style="{ '--dot': item.color }"></span>{{ item.label }}</div>
                <div class="legend-number">{{ groupCount(item.key) }} 台</div>
              </div>
              <div class="legend-row">
                <div class="legend-name"><span class="legend-dot" style="--dot: #7858ce"></span>平均电量</div>
                <div class="legend-number">{{ overview.average_battery || 0 }}%</div>
              </div>
            </div>
          </div>
          <div class="agv-status-list mt-16">
            <div v-for="agv in agvs" :key="agv.id" class="agv-status-row">
              <div class="agv-code">{{ agv.code }}</div>
              <div class="agv-node">{{ agv.current_node_detail?.name || '--' }}</div>
              <StatusBadge :status="agv.status" />
              <div class="battery">{{ agv.battery_percent }}%<div class="progress-track"><div class="progress-bar" :class="{ warn: agv.battery_percent < 30 }" :style="{ width: `${agv.battery_percent}%` }"></div></div></div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">最近调度记录</div><div class="panel-desc">单台与多台调度分配结果</div></div></div>
        <div class="panel-body">
          <div v-if="dispatches.length" class="route-list">
            <div v-for="item in dispatches.slice(0, 7)" :key="item.id" class="route-card">
              <div class="route-card-top">
                <div><span class="strong mono">{{ item.task_no }}</span><span class="tag" style="margin-left: 7px">{{ item.algorithm_display }}</span></div>
                <StatusBadge :status="item.success ? 'completed' : 'failed'" :label="item.success ? '成功' : '失败'" />
              </div>
              <div class="route-path">{{ item.agv_code || '未分配' }} · {{ item.distance }} m · {{ item.estimated_duration }} s<br>{{ formatTime(item.created_at) }}</div>
            </div>
          </div>
          <div v-else class="empty">暂无调度记录</div>
        </div>
      </section>
    </div>

    <section class="panel mt-16">
      <div class="panel-head"><div><div class="panel-title">最近运输任务</div><div class="panel-desc">按创建时间倒序展示</div></div></div>
      <div class="panel-body">
        <div class="table-wrap">
          <table>
            <thead><tr><th>任务编号</th><th>货物</th><th>取货点</th><th>放货点</th><th>执行 AGV</th><th>优先级</th><th>状态</th><th>创建时间</th></tr></thead>
            <tbody>
              <tr v-for="task in recentTasks" :key="task.id">
                <td class="mono cell-main">{{ task.task_no }}</td>
                <td>{{ task.cargo_name }}<div class="cell-sub">{{ task.cargo_weight }} kg</div></td>
                <td>{{ task.pickup_node_detail?.code }}</td>
                <td>{{ task.dropoff_node_detail?.code }}</td>
                <td>{{ task.assigned_agv_detail?.code || '--' }}</td>
                <td :class="`priority-${task.priority}`">{{ task.priority_display }}</td>
                <td><StatusBadge :status="task.status" /></td>
                <td class="muted">{{ formatTime(task.created_at) }}</td>
              </tr>
              <tr v-if="!recentTasks.length"><td colspan="8"><div class="empty">暂无任务</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>
