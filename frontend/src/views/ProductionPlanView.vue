<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'

const emit = defineEmits(['notify'])
const plans = ref([])
const loading = ref(false)
const busy = ref('')
const scheduleNotice = ref('')

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

async function load() {
  loading.value = true
  try {
    plans.value = await api.productionPlans()
  } catch (error) {
    emit('notify', { message: `生产计划加载失败：${error.message}`, type: 'error' })
  } finally {
    loading.value = false
  }
}

async function schedule(plan) {
  busy.value = `${plan.id}-schedule`
  try {
    const result = await api.scheduleProductionPlan(plan.id, { strict_deadlines: false })
    scheduleNotice.value = result.message
    emit('notify', { message: result.message })
    await load()
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

async function cancel(plan) {
  if (!window.confirm(`确认取消计划 ${plan.plan_no}？`)) return
  busy.value = `${plan.id}-cancel`
  try {
    await api.cancelProductionPlan(plan.id)
    emit('notify', { message: '生产计划已取消' })
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
      <div><div class="panel-title">生产计划中心</div><div class="panel-desc">预测结果生成的计划、运输任务与执行工单统一查看</div></div>
      <div class="toolbar-right"><RouterLink class="btn btn-sm btn-primary" to="/forecast">从预测生成计划</RouterLink><button class="btn btn-sm" :disabled="loading" @click="load">刷新</button></div>
    </div>
    <div class="panel-body">
      <div v-if="scheduleNotice" class="notice success mb-16">{{ scheduleNotice }}</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>计划</th><th>计划期</th><th>预测订单</th><th>任务进度</th><th>执行工单</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="plan in plans" :key="plan.id">
              <td><div class="cell-main mono">{{ plan.plan_no }}</div><div class="cell-sub">{{ plan.name }}</div></td>
              <td>{{ plan.planning_start }} → {{ plan.planning_end }}</td>
              <td>{{ Math.round(plan.forecast_order_total) }}</td>
              <td>{{ plan.completed_task_count || 0 }}/{{ plan.task_count }}<div class="cell-sub">{{ plan.pending_task_count || 0 }} 个待排程 · {{ plan.planned_task_count || 0 }} 个活动任务</div></td>
              <td><RouterLink v-if="plan.work_order" class="link-btn" :to="{ path: '/work-orders', query: { work_order: plan.work_order } }">{{ plan.work_order_no }}</RouterLink><span v-else class="muted">--</span></td>
              <td><span class="tag">{{ plan.status_display }}</span></td>
              <td class="small">{{ formatTime(plan.created_at) }}</td>
              <td><div class="table-actions"><button v-if="plan.pending_task_count > 0 && !['completed', 'cancelled'].includes(plan.status)" class="btn btn-sm btn-primary" :disabled="busy === `${plan.id}-schedule`" @click="schedule(plan)">{{ plan.status === 'planned' ? '联合排程' : '继续排程待处理任务' }}</button><button v-if="!['completed', 'cancelled'].includes(plan.status)" class="btn btn-sm btn-danger" :disabled="busy === `${plan.id}-cancel`" @click="cancel(plan)">取消</button></div></td>
            </tr>
            <tr v-if="!plans.length"><td colspan="8"><div class="empty">暂无生产计划</div></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.toolbar-right { display: flex; gap: 8px; }
</style>
