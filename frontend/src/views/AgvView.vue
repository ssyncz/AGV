<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ agvs: { type: Array, default: () => [] } })
const emit = defineEmits(['refresh', 'notify'])
const query = ref('')

const filtered = computed(() => {
  const text = query.value.trim().toLowerCase()
  if (!text) return props.agvs
  return props.agvs.filter((item) => `${item.code} ${item.name} ${item.current_node_detail?.name}`.toLowerCase().includes(text))
})

async function changeStatus(agv, event) {
  try {
    await api.updateAgv(agv.id, { status: event.target.value })
    emit('notify', { message: `${agv.code} 状态已更新` })
    emit('refresh')
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
    emit('refresh')
  }
}
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div><div class="panel-title">AGV 车队管理</div></div>
      <input v-model="query" class="input filter-input" placeholder="搜索编号、名称或位置..." />
    </div>
    <div class="panel-body">
      <div class="grid stats-grid fleet-stats">
        <div class="mini-stat panel"><span>空闲车辆</span><strong>{{ agvs.filter(v => v.status === 'idle').length }}</strong></div>
        <div class="mini-stat panel"><span>执行任务</span><strong>{{ agvs.filter(v => v.status === 'busy').length }}</strong></div>
        <div class="mini-stat panel"><span>充电车辆</span><strong>{{ agvs.filter(v => v.status === 'charging').length }}</strong></div>
        <div class="mini-stat panel"><span>异常/离线</span><strong>{{ agvs.filter(v => ['error', 'offline'].includes(v.status)).length }}</strong></div>
      </div>
      <div class="table-wrap mt-16">
        <table>
          <thead><tr><th>AGV</th><th>型号</th><th>当前位置</th><th>状态</th><th>电量</th><th>额定载重</th><th>运行速度</th><th>任务数</th><th>状态控制</th></tr></thead>
          <tbody>
            <tr v-for="agv in filtered" :key="agv.id">
              <td><div class="cell-main mono">{{ agv.code }}</div><div class="cell-sub">{{ agv.name }}</div></td>
              <td>{{ agv.model_name || '--' }}</td>
              <td>{{ agv.current_node_detail?.code }} · {{ agv.current_node_detail?.name }}</td>
              <td><StatusBadge :status="agv.status" /></td>
              <td>
                <div class="battery">{{ agv.battery_percent }}%<div class="progress-track"><div class="progress-bar" :class="{ warn: agv.battery_percent < 30 }" :style="{ width: `${agv.battery_percent}%` }"></div></div></div>
              </td>
              <td>{{ agv.payload_capacity }} kg</td>
              <td>{{ agv.speed }} m/s</td>
              <td>{{ agv.active_task_count || 0 }}</td>
              <td>
                <select class="select btn-sm" :value="agv.status" @change="changeStatus(agv, $event)">
                  <option value="idle">空闲</option><option value="busy">执行任务</option><option value="charging">充电中</option><option value="offline">离线</option><option value="error">故障</option>
                </select>
              </td>
            </tr>
            <tr v-if="!filtered.length"><td colspan="9"><div class="empty">没有匹配的 AGV</div></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
