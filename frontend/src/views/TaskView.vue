<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  nodes: { type: Array, default: () => [] },
})
const route = useRoute()
const router = useRouter()
const emit = defineEmits(['refresh', 'notify'])
const query = ref('')
const statusFilter = ref('')
const expanded = ref(null)
const busyId = ref(null)
const planFilter = computed(() => String(route.query.plan || ''))
const workOrderFilter = computed(() => String(route.query.work_order || ''))
const isGroupView = computed(() => !planFilter.value && !workOrderFilter.value)
const nodeMap = computed(() => Object.fromEntries(props.nodes.map((node) => [node.id, node])))

function compareTasks(left, right) {
  const leftOrder = left.dispatch_order || Number.MAX_SAFE_INTEGER
  const rightOrder = right.dispatch_order || Number.MAX_SAFE_INTEGER
  if (leftOrder !== rightOrder) return leftOrder - rightOrder
  const leftStart = left.scheduled_start ? new Date(left.scheduled_start).getTime() : Number.MAX_SAFE_INTEGER
  const rightStart = right.scheduled_start ? new Date(right.scheduled_start).getTime() : Number.MAX_SAFE_INTEGER
  if (leftStart !== rightStart) return leftStart - rightStart
  return new Date(left.created_at).getTime() - new Date(right.created_at).getTime() || left.id - right.id
}

function groupKey(task) {
  return task.work_order ? String(task.work_order) : 'unlinked'
}

const workOrderGroups = computed(() => {
  const grouped = new Map()
  for (const task of props.tasks) {
    const key = groupKey(task)
    if (!grouped.has(key)) {
      grouped.set(key, {
        id: key,
        work_order: task.work_order || null,
        work_order_no: task.work_order_no || '未关联工单',
        planNumbers: new Set(),
        tasks: [],
      })
    }
    const group = grouped.get(key)
    if (task.production_plan_no) group.planNumbers.add(task.production_plan_no)
    group.tasks.push(task)
  }
  return [...grouped.values()]
    .map((group) => {
      const tasks = [...group.tasks].sort(compareTasks)
      return {
        ...group,
        planNumbers: [...group.planNumbers],
        tasks,
        pendingCount: tasks.filter((task) => task.status === 'pending').length,
        assignedCount: tasks.filter((task) => task.status === 'assigned').length,
        inProgressCount: tasks.filter((task) => task.status === 'in_progress').length,
        completedCount: tasks.filter((task) => task.status === 'completed').length,
        scheduledCount: tasks.filter((task) => task.dispatch_order > 0).length,
        scheduleRunCount: new Set(tasks.map((task) => task.schedule_run).filter(Boolean)).size,
      }
    })
    .sort((left, right) => left.work_order_no.localeCompare(right.work_order_no, 'zh-CN'))
})

watch(workOrderGroups, (groups) => {
  if (
    !planFilter.value
    && !workOrderFilter.value
    && groups.length
    && window.matchMedia('(min-width: 981px)').matches
  ) {
    router.replace({ path: '/tasks', query: { work_order: groups[0].id } })
  }
}, { immediate: true })

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return props.tasks
    .filter((task) => {
      const matchesText = !keyword || `${task.task_no} ${task.cargo_name} ${task.assigned_agv_detail?.code || ''} ${task.work_order_no || ''}`.toLowerCase().includes(keyword)
      const matchesStatus = !statusFilter.value || task.status === statusFilter.value
      const matchesPlan = !planFilter.value || String(task.production_plan || '') === planFilter.value
      const matchesWorkOrder = !workOrderFilter.value || groupKey(task) === workOrderFilter.value
      return matchesText && matchesStatus && matchesPlan && matchesWorkOrder
    })
    .sort(compareTasks)
})

const currentTaskGroup = computed(
  () => workOrderGroups.value.find((group) => group.id === workOrderFilter.value) || null,
)
const selectedPlanIds = computed(() => {
  if (!planFilter.value) return []
  return [...new Set(filtered.value.map((task) => task.production_plan).filter(Boolean))]
})

const scheduleRunGroups = computed(() => {
  const grouped = new Map()
  for (const task of filtered.value) {
    const key = task.schedule_run ? `run-${task.schedule_run}` : 'pending'
    if (!grouped.has(key)) {
      grouped.set(key, {
        key,
        schedule_run: task.schedule_run || null,
        algorithm: task.schedule_run_algorithm || '',
        created_at: task.schedule_run_created_at || '',
        task_count: task.schedule_run_task_count || 0,
        agv_count: task.schedule_run_agv_count || 0,
        makespan_seconds: task.schedule_run_makespan_seconds || 0,
        on_time_rate: task.schedule_run_on_time_rate ?? null,
        tasks: [],
      })
    }
    grouped.get(key).tasks.push(task)
  }
  return [...grouped.values()]
    .map((group) => {
      const tasks = [...group.tasks].sort(compareTasks)
      return {
        ...group,
        tasks,
        task_count: group.task_count || tasks.length,
        dispatch_order_start: Math.min(...tasks.map((task) => task.dispatch_order || Number.MAX_SAFE_INTEGER)),
        dispatch_order_end: Math.max(...tasks.map((task) => task.dispatch_order || 0)),
      }
    })
    .sort((left, right) => {
      if (!left.schedule_run) return 1
      if (!right.schedule_run) return -1
      return new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
    })
})

function routeText(task) {
  return (task.route?.nodes || []).map((id) => nodeMap.value[id]?.code || id).join(' → ')
}

function formatDateTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function deadlineState(task) {
  if (!task.due_at) return ''
  const expected = task.completed_at || task.scheduled_end
  if (expected && new Date(expected) > new Date(task.due_at)) return '逾期'
  if (task.status === 'in_progress' && new Date() > new Date(task.due_at)) return '逾期'
  return '正常'
}

function taskEntryLink(group) {
  return { path: '/tasks', query: { work_order: group.id } }
}

function backToQueue() {
  router.push({ path: '/tasks' })
}

function orderRangeLabel(run) {
  if (!run.schedule_run) return '尚未生成排期'
  return `全局顺序 ${run.dispatch_order_start}-${run.dispatch_order_end}`
}

function durationLabel(seconds) {
  return `${Number(seconds || 0).toFixed(1)}s`
}

function runLastCompletion(run) {
  const times = (run.tasks || [])
    .map((task) => (task.scheduled_end ? new Date(task.scheduled_end).getTime() : null))
    .filter((value) => value !== null)
  return times.length ? new Date(Math.max(...times)).toISOString() : ''
}

function runWorkingSeconds(run) {
  return (run.tasks || []).reduce(
    (total, task) => total + Number(task.estimated_duration || 0),
    0,
  )
}

async function runAction(task, action) {
  busyId.value = `${task.id}-${action}`
  try {
    await api.taskAction(task.id, action)
    const messages = { start: '任务已开始执行', complete: '任务已完成，AGV 位置和电量已更新', cancel: '任务已取消' }
    emit('notify', { message: messages[action] })
    emit('refresh')
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <div class="task-workspace" :class="{ 'has-selection': !isGroupView }">
    <aside class="panel task-queue-panel">
      <div class="panel-head">
        <div><div class="panel-title">工单任务队列</div><div class="panel-desc">选择工单查看运输任务与排期</div></div>
        <span class="queue-count">{{ workOrderGroups.length }}</span>
      </div>
      <div class="panel-body">
        <div class="task-queue-summary">
          <span>任务 {{ tasks.length }}</span>
          <span>已排程 {{ tasks.filter(task => task.dispatch_order > 0).length }}</span>
          <span>待调度 {{ tasks.filter(task => task.status === 'pending').length }}</span>
        </div>
        <div v-if="workOrderGroups.length" class="task-group-list">
        <RouterLink v-for="group in workOrderGroups" :key="group.id" :to="taskEntryLink(group)" class="workorder-entry" :class="{ active: workOrderFilter === group.id }">
          <div class="workorder-entry-head">
            <div>
              <div class="workorder-entry-no mono">{{ group.work_order_no }}</div>
              <div class="cell-sub">{{ group.planNumbers.length ? `计划 ${group.planNumbers.join(' / ')}` : '未关联生产计划' }}</div>
            </div>
            <span class="workorder-entry-arrow">→</span>
          </div>
          <div class="workorder-entry-stats">
            <div><span>任务</span><strong>{{ group.tasks.length }}</strong></div>
            <div><span>已排程</span><strong>{{ group.scheduledCount }}</strong></div>
            <div><span>待调度</span><strong>{{ group.pendingCount }}</strong></div>
            <div><span>已完成</span><strong>{{ group.completedCount }}</strong></div>
          </div>
          <div class="workorder-entry-foot">
            <span class="badge badge-assigned">{{ group.assignedCount + group.inProgressCount }} 个执行中/已分配</span>
            <span class="link-btn">{{ group.scheduleRunCount }} 个排期 · 查看任务顺序</span>
          </div>
        </RouterLink>
        </div>
        <div v-else class="empty">暂无运输任务。请先生成生产计划或从工单创建运输任务。</div>
      </div>
    </aside>

    <div class="task-detail-column">
  <section v-if="!isGroupView" class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">{{ workOrderFilter ? `工单 ${currentTaskGroup?.work_order_no || workOrderFilter}` : '生产计划运输任务' }}</div>
        <div class="panel-desc">{{ workOrderFilter ? '任务按全局调度顺序排列，并显示对应 AGV 的车内执行顺序' : `计划 ID ${planFilter} 下的任务与执行顺序` }}</div>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-sm task-mobile-back" @click="backToQueue">← 返回队列</button>
        <span v-if="planFilter" class="tag">计划 ID {{ planFilter }}</span>
        <span v-if="workOrderFilter" class="tag">工单 {{ currentTaskGroup?.work_order_no || workOrderFilter }}</span>
        <input v-model="query" class="input filter-input" placeholder="搜索任务、货物或 AGV..." />
        <select v-model="statusFilter" class="select" style="width: 130px">
          <option value="">全部状态</option><option value="pending">待调度</option><option value="assigned">已分配</option><option value="in_progress">执行中</option><option value="completed">已完成</option><option value="cancelled">已取消</option>
        </select>
      </div>
    </div>
    <div class="panel-body">
      <div v-if="currentTaskGroup" class="workorder-context-strip">
        <div><span>工单任务总数</span><strong>{{ currentTaskGroup.tasks.length }}</strong></div>
        <div><span>排期批次</span><strong>{{ currentTaskGroup.scheduleRunCount }}</strong></div>
        <div><span>已生成调度顺序</span><strong>{{ currentTaskGroup.scheduledCount }}</strong></div>
        <div><span>待调度</span><strong>{{ currentTaskGroup.pendingCount }}</strong></div>
        <div><span>已分配/执行中</span><strong>{{ currentTaskGroup.assignedCount + currentTaskGroup.inProgressCount }}</strong></div>
        <div><span>已完成</span><strong>{{ currentTaskGroup.completedCount }}</strong></div>
      </div>
      <div v-if="selectedPlanIds.length" class="section-toolbar mt-12">
        <span class="muted small">当前计划：{{ selectedPlanIds.join(' / ') }}</span>
        <RouterLink class="link-btn" :to="{ path: '/tasks', query: workOrderFilter ? { work_order: workOrderFilter } : {} }">清除计划筛选</RouterLink>
      </div>
      <div v-if="scheduleRunGroups.length" class="schedule-run-stack mt-16">
        <section v-for="(run, runIndex) in scheduleRunGroups" :key="run.key" class="schedule-run-panel">
          <div class="schedule-run-head">
            <div>
              <div class="schedule-run-title">排期批次 {{ runIndex + 1 }}<span v-if="run.schedule_run" class="tag">调度运行 #{{ run.schedule_run }}</span></div>
              <div class="cell-sub">{{ run.schedule_run ? `${run.algorithm} · ${formatDateTime(run.created_at)} · ${orderRangeLabel(run)}` : '这些任务尚未生成排期' }}</div>
            </div>
            <div v-if="run.schedule_run" class="schedule-run-metrics">
              <span>任务 <strong>{{ run.task_count }}</strong></span>
              <span>AGV <strong>{{ run.agv_count }}</strong></span>
              <span>最后完成 <strong>{{ formatDateTime(runLastCompletion(run)) }}</strong></span>
              <span>作业耗时 <strong>{{ durationLabel(runWorkingSeconds(run)) }}</strong></span>
              <span>准点 <strong>{{ run.on_time_rate ?? '--' }}%</strong></span>
            </div>
          </div>
          <div class="table-wrap schedule-run-table">
            <table>
              <thead><tr><th>调度顺序</th><th>任务</th><th>路线</th><th>时间约束</th><th>货物</th><th>AGV / 车内顺序</th><th>里程/耗时</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                <template v-for="task in run.tasks" :key="task.id">
                  <tr>
                    <td><span v-if="task.dispatch_order" class="dispatch-order-badge">#{{ task.dispatch_order }}</span><span v-else class="tag">待排程</span></td>
                    <td><div class="cell-main mono">{{ task.task_no }}</div><div class="cell-sub">{{ task.operation_step_name ? `工序 ${task.operation_step_name} · ` : '' }}<RouterLink v-if="task.work_order" class="link-btn" :to="{ path: '/work-orders', query: { work_order: task.work_order } }">工单 {{ task.work_order_no }}</RouterLink><span v-else>{{ task.production_plan_no ? `计划 ${task.production_plan_no}` : formatDateTime(task.created_at) }}</span></div></td>
                    <td><span class="strong">{{ task.pickup_node_detail?.code }}</span> → <span class="strong">{{ task.dropoff_node_detail?.code }}</span><button v-if="task.route?.nodes?.length" class="link-btn" @click="expanded = expanded === task.id ? null : task.id">路线</button></td>
                    <td><div class="cell-sub">释放 {{ formatDateTime(task.release_at) }}</div><div class="cell-sub">交期 {{ formatDateTime(task.due_at) }}</div><span v-if="deadlineState(task)" class="badge" :class="deadlineState(task) === '逾期' ? 'badge-failed' : 'badge-completed'">{{ deadlineState(task) }}</span></td>
                    <td>{{ task.cargo_name }}<div class="cell-sub">{{ task.cargo_weight }} kg · P{{ task.priority }}</div></td>
                    <td>{{ task.assigned_agv_detail?.code || '--' }}<div class="cell-sub">{{ task.sequence_number ? `车内第 ${task.sequence_number} 项` : '未分配' }}</div></td>
                    <td>{{ task.total_distance || 0 }} m<div class="cell-sub">{{ task.estimated_duration || 0 }} s</div></td>
                    <td><StatusBadge :status="task.status" /></td>
                    <td>
                      <div class="table-actions">
                        <button v-if="task.status === 'assigned'" class="btn btn-sm btn-primary" :disabled="busyId === `${task.id}-start`" @click="runAction(task, 'start')">开始</button>
                        <button v-if="task.status === 'in_progress'" class="btn btn-sm btn-success" :disabled="busyId === `${task.id}-complete`" @click="runAction(task, 'complete')">完成</button>
                        <button v-if="['pending', 'assigned'].includes(task.status)" class="btn btn-sm btn-danger" :disabled="busyId === `${task.id}-cancel`" @click="runAction(task, 'cancel')">取消</button>
                        <span v-if="['completed', 'cancelled'].includes(task.status)" class="muted small">--</span>
                      </div>
                    </td>
                  </tr>
                  <tr v-if="expanded === task.id">
                    <td colspan="9">
                      <div class="route-detail">
                        <div><span class="muted">规划路线：</span><span class="mono">{{ routeText(task) || '暂无路线' }}</span></div>
                        <div class="mt-12"><span class="muted">约束窗口：</span>释放 {{ formatDateTime(task.release_at) }} · 交期 {{ formatDateTime(task.due_at) }} · 预测订单 {{ task.forecast_order_count ?? '--' }}</div>
                        <div class="mt-12"><span class="muted">预计时间：</span>{{ task.scheduled_start ? new Date(task.scheduled_start).toLocaleString('zh-CN', { hour12: false }) : '--' }} - {{ task.scheduled_end ? new Date(task.scheduled_end).toLocaleString('zh-CN', { hour12: false }) : '--' }}</div>
                        <div v-if="task.route?.waits?.length" class="notice warning mt-12"><span>!</span><div>检测到 {{ task.route.waits.length }} 次节点避碰等待，已自动加入时间窗约束。</div></div>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <div v-else class="empty mt-16">该筛选条件下没有运输任务</div>
    </div>
  </section>
      <section v-else class="panel task-detail-empty">
        <div class="task-empty-visual">
          <span>◇</span>
          <strong>选择工单查看运输任务</strong>
          <p>右侧会展示该工单的排期批次、调度顺序、AGV 分配和完整路线。</p>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.task-workspace { display: grid; grid-template-columns: clamp(350px, 27vw, 430px) minmax(0, 1fr); gap: 18px; align-items: stretch; }
.task-queue-panel { position: sticky; top: 18px; display: flex; flex-direction: column; min-height: 580px; max-height: calc(100vh - 36px); overflow: hidden; }
.task-queue-panel .panel-head { min-height: 68px; padding: 14px 15px 12px; }
.task-queue-panel .panel-body { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 14px; }
.queue-count { min-width: 29px; height: 25px; display: grid; place-items: center; border: 1px solid #d4e5df; border-radius: 8px; color: #25776f; background: #f1f8f5; font-size: 9px; font-weight: 800; }
.task-queue-summary { display: flex; align-items: center; gap: 10px; padding: 11px 12px; border: 1px solid #dfe8e4; border-radius: 9px; color: #667871; background: #f8faf9; font-size: 10.5px; }
.task-queue-summary span + span::before { content: "·"; margin-right: 9px; color: #b7c4bf; }
.task-group-list { flex: 1; min-height: 0; display: grid; align-content: start; gap: 8px; margin-top: 9px; overflow-y: auto; padding: 1px 3px 1px 1px; scrollbar-width: thin; scrollbar-color: rgba(92, 143, 136, 0.25) transparent; }
.workorder-entry-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.workorder-entry { position: relative; display: grid; gap: 12px; overflow: hidden; padding: 16px; border: 1px solid #dce6e1; border-radius: 12px; background: linear-gradient(145deg, #ffffff, #f9fbfa); color: inherit; text-decoration: none; transition: border-color 160ms ease, background 160ms ease, transform 160ms ease, box-shadow 160ms ease; }
.workorder-entry::before { content: ""; position: absolute; inset: 8px auto 8px 0; width: 3px; border-radius: 0 3px 3px 0; background: transparent; }
.workorder-entry:hover { border-color: #a9ccc5; background: #fff; box-shadow: 0 7px 18px rgba(20, 45, 54, 0.055); transform: translateY(-1px); }
.workorder-entry.active { border-color: rgba(14, 135, 146, 0.34); background: linear-gradient(90deg, rgba(14, 135, 146, 0.075), rgba(255, 255, 255, 0.82)); box-shadow: 0 7px 18px rgba(14, 94, 95, 0.07); }
.workorder-entry.active::before { background: var(--cyan); }
.workorder-entry-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.workorder-entry .cell-sub { font-size: 10px; line-height: 1.5; }
.workorder-entry-no { color: #17363e; font-size: 13px; font-weight: 800; }
.workorder-entry-arrow { color: var(--cyan); font-size: 22px; line-height: 1; }
.workorder-entry-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; }
.workorder-entry-stats > div { display: grid; gap: 4px; padding: 10px; border-radius: 8px; background: #eef4f1; }
.workorder-entry-stats span { color: var(--muted); font-size: 10px; }
.workorder-entry-stats strong { font-size: 18px; }
.workorder-entry-foot { display: flex; align-items: center; justify-content: space-between; gap: 7px; flex-wrap: wrap; font-size: 10px; }
.workorder-entry-foot :deep(.badge) { padding: 3px 7px; font-size: 8.5px; }
.task-detail-column { min-width: 0; }
.task-detail-empty { min-height: 440px; display: grid; place-items: center; background: radial-gradient(circle at center, rgba(14, 135, 146, 0.055), transparent 38%), #fff; }
.task-empty-visual { max-width: 330px; display: grid; justify-items: center; gap: 9px; padding: 28px; text-align: center; }
.task-empty-visual > span { width: 54px; height: 54px; display: grid; place-items: center; border: 1px solid rgba(14, 135, 146, 0.15); border-radius: 16px; color: var(--cyan); background: #f1f8f6; font-size: 24px; }
.task-empty-visual strong { color: #244049; font-size: 14px; }
.task-empty-visual p { margin: 0; color: var(--muted); font-size: 10px; line-height: 1.65; }
.task-mobile-back { display: none; }
.workorder-context-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; padding: 11px; border: 1px solid var(--line); border-radius: 10px; background: #f8faf9; }
.workorder-context-strip > div { display: grid; gap: 3px; }
.workorder-context-strip span { color: var(--muted); font-size: 9px; }
.workorder-context-strip strong { font-size: 15px; }
.dispatch-order-badge { display: inline-grid; place-items: center; min-width: 34px; padding: 4px 7px; border-radius: 8px; background: #dff1eb; color: #1d755b; font-size: 11px; font-weight: 800; }
.schedule-run-stack { display: grid; gap: 14px; }
.schedule-run-panel { overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: #fff; }
.schedule-run-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 13px 15px; border-bottom: 1px solid var(--line); background: #f8faf9; }
.schedule-run-title { display: flex; align-items: center; gap: 8px; color: var(--text); font-size: 13px; font-weight: 780; }
.schedule-run-metrics { display: flex; align-items: center; gap: 14px; color: var(--muted); font-size: 9px; flex-wrap: wrap; }
.schedule-run-metrics span { display: flex; align-items: baseline; gap: 4px; }
.schedule-run-metrics strong { color: var(--text); font-size: 12px; }
.schedule-run-table { border: 0; }
@media (max-width: 980px) {
  .task-workspace { grid-template-columns: minmax(0, 1fr); }
  .task-queue-panel { position: static; min-height: 0; max-height: none; }
  .task-group-list { max-height: 440px; }
  .task-workspace.has-selection .task-queue-panel { display: none; }
  .task-workspace:not(.has-selection) .task-detail-column { display: none; }
  .task-mobile-back { display: inline-flex; }
  .workorder-entry-grid { grid-template-columns: 1fr; }
  .workorder-context-strip { grid-template-columns: repeat(3, 1fr); }
  .schedule-run-head { align-items: flex-start; flex-direction: column; }
}
</style>
