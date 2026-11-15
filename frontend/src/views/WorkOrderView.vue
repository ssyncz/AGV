<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import ActionMenu from '../components/ActionMenu.vue'

const emit = defineEmits(['notify'])
const route = useRoute()
const router = useRouter()

const orders = ref([])
const master = ref({ sites: [], products: [], equipment: [] })
const nodes = ref([])
const timeline = ref(null)
const loading = ref(false)
const busy = ref('')
const filters = reactive({ q: '', status: '', quality_status: '' })
const createForm = reactive({
  title: '',
  site: '',
  product: '',
  quantity: 1,
  priority: 2,
  planned_start: '',
  due_at: '',
  notes: '',
})
const taskForm = reactive({
  pickup_node_id: '',
  dropoff_node_id: '',
  cargo_name: '',
  cargo_weight: 10,
  priority: 2,
})

const selectedId = computed(() => Number(route.query.work_order) || null)
const selectedOrder = computed(() => orders.value.find((item) => item.id === selectedId.value) || timeline.value?.work_order || null)
const pageMode = computed(() => (route.query.view === 'create' ? 'create' : 'center'))
const pickupNodes = computed(() => nodes.value.filter((item) => ['pickup', 'intersection'].includes(item.node_type)))
const dropoffNodes = computed(() => nodes.value.filter((item) => ['dropoff', 'intersection'].includes(item.node_type)))

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
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

function queryString() {
  const params = new URLSearchParams()
  if (filters.q.trim()) params.set('q', filters.q.trim())
  if (filters.status) params.set('status', filters.status)
  if (filters.quality_status) params.set('quality_status', filters.quality_status)
  const text = params.toString()
  return text ? `?${text}` : ''
}

function switchWorkOrderMode(mode) {
  router.push({
    path: '/work-orders',
    query: mode === 'create' ? { view: 'create' } : {},
  })
}

async function loadOrders() {
  loading.value = true
  try {
    orders.value = await api.workOrders(queryString())
  } catch (error) {
    emit('notify', { message: `工单加载失败：${error.message}`, type: 'error' })
  } finally {
    loading.value = false
  }
}

async function loadMaster() {
  try {
    master.value = await api.masterData()
    nodes.value = await api.nodes()
    if (!createForm.site && master.value.sites?.length) createForm.site = master.value.sites[0].id
    if (!createForm.product && master.value.products?.length) createForm.product = master.value.products[0].id
    if (!taskForm.pickup_node_id && pickupNodes.value.length) taskForm.pickup_node_id = pickupNodes.value[0].id
    if (!taskForm.dropoff_node_id && dropoffNodes.value.length) taskForm.dropoff_node_id = dropoffNodes.value[0].id
  } catch (error) {
    emit('notify', { message: `主数据加载失败：${error.message}`, type: 'error' })
  }
}

async function loadTimeline() {
  if (!selectedId.value) {
    timeline.value = null
    return
  }
  try {
    timeline.value = await api.workOrderTimeline(selectedId.value)
    if (!taskForm.cargo_name) {
      taskForm.cargo_name = timeline.value.work_order.title
      taskForm.priority = timeline.value.work_order.priority
    }
  } catch (error) {
    emit('notify', { message: `工单时间线加载失败：${error.message}`, type: 'error' })
  }
}

async function createOrder() {
  if (!createForm.title.trim()) return emit('notify', { message: '请填写工单名称', type: 'error' })
  busy.value = 'create'
  try {
    const payload = {
      ...createForm,
      site: createForm.site || null,
      product: createForm.product || null,
      due_at: createForm.due_at ? new Date(createForm.due_at).toISOString() : null,
    }
    const created = await api.createWorkOrder(payload)
    createForm.title = ''
    createForm.notes = ''
    emit('notify', { message: `工单 ${created.order_no} 已创建` })
    await loadOrders()
    await router.push({ path: '/work-orders', query: { work_order: created.id } })
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

// 动作区规范化：每个状态只暴露一个主按钮，其余收进「更多」
const PRIMARY_BY_STATUS = {
  draft: { key: 'release', label: '下达工单' },
  released: { key: 'start', label: '开始执行' },
  in_progress: { key: 'quality-check', label: '提交质检' },
  quality_check: { key: 'complete', label: '完成工单' },
  blocked: { key: 'resume', label: '恢复工单' },
}
const primaryAction = computed(() => {
  const status = selectedOrder.value?.status
  return PRIMARY_BY_STATUS[status] || null
})
const moreActions = computed(() => {
  const order = selectedOrder.value
  if (!order) return []
  const status = order.status
  const items = []
  if (!['completed', 'cancelled', 'blocked'].includes(status)) {
    items.push({ key: 'block', label: '阻塞工单', hint: '异常时中止' })
  }
  if (order.quality_status === 'fail' && status !== 'completed') {
    items.push({ key: 'quality-check', label: '重新提交质检' })
  }
  if (!['completed', 'cancelled'].includes(status)) {
    items.push({ key: 'cancel', label: '取消工单', danger: true })
  }
  return items
})
function onPrimary() {
  if (primaryAction.value) runAction(primaryAction.value.key)
}
function onMore(key) {
  if (key === 'block') blockOrder()
  else runAction(key)
}

async function runAction(action, payload = {}) {
  if (!selectedOrder.value) return
  busy.value = action
  try {
    await api.workOrderAction(selectedOrder.value.id, action, payload)
    emit('notify', { message: '工单状态已更新' })
    await Promise.all([loadOrders(), loadTimeline()])
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

function blockOrder() {
  const reason = window.prompt('请输入阻塞原因')
  if (reason?.trim()) runAction('block', { reason })
}

async function addTask() {
  if (!selectedOrder.value) return
  busy.value = 'task'
  try {
    await api.addWorkOrderTask(selectedOrder.value.id, {
      pickup_node_id: Number(taskForm.pickup_node_id),
      dropoff_node_id: Number(taskForm.dropoff_node_id),
      cargo_name: taskForm.cargo_name || selectedOrder.value.title,
      cargo_weight: Number(taskForm.cargo_weight),
      priority: Number(taskForm.priority),
    })
    emit('notify', { message: '运输任务已创建' })
    await Promise.all([loadOrders(), loadTimeline()])
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

async function runOperation(step, action) {
  busy.value = `operation-${step.id}-${action}`
  try {
    await api.operationStepAction(step.id, action)
    emit('notify', { message: action === 'start' ? `工序 ${step.name} 已开始` : `工序 ${step.name} 已完成` })
    await Promise.all([loadOrders(), loadTimeline()])
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

watch(() => route.query.work_order, loadTimeline, { immediate: false })

onMounted(async () => {
  if (route.query.status) filters.status = String(route.query.status)
  if (route.query.quality_status) filters.quality_status = String(route.query.quality_status)
  await Promise.all([loadMaster(), loadOrders()])
  await loadTimeline()
})
</script>

<template>
  <div class="workorder-page">
    <section class="workorder-entry-menu">
      <button type="button" class="workorder-mode-card" :class="{ active: pageMode === 'create' }" @click="switchWorkOrderMode('create')">
        <span class="workorder-mode-icon">＋</span>
        <span><strong>新建生产工单</strong><small>建立新的生产任务和工序执行主线</small></span>
      </button>
      <button type="button" class="workorder-mode-card" :class="{ active: pageMode === 'center' }" @click="switchWorkOrderMode('center')">
        <span class="workorder-mode-icon">▤</span>
        <span><strong>生产工单中心</strong><small>查询工单、推进工序并查看执行记录</small></span>
      </button>
    </section>

    <div v-if="pageMode === 'create'" class="workorder-create-layout">
    <aside class="panel create-panel">
      <div class="panel-head"><div><div class="panel-title">新建生产工单</div><div class="panel-desc">工单是运输、质检与设备异常的业务主线</div></div></div>
      <div class="panel-body">
        <div class="form-grid single">
          <div class="field"><label>工单名称</label><input v-model="createForm.title" class="input" placeholder="例如：A 型电机装配工单" /></div>
          <div class="field"><label>所属站点</label><select v-model="createForm.site" class="select"><option v-for="site in master.sites" :key="site.id" :value="site.id">{{ site.code }} · {{ site.name }}</option></select></div>
          <div class="field"><label>产品</label><select v-model="createForm.product" class="select"><option v-for="product in master.products" :key="product.id" :value="product.id">{{ product.code }} · {{ product.name }}</option></select></div>
          <div class="field"><label>计划数量</label><input v-model.number="createForm.quantity" class="input" type="number" min="0" step="1" /></div>
          <div class="field"><label>优先级</label><select v-model.number="createForm.priority" class="select"><option :value="1">低</option><option :value="2">普通</option><option :value="3">高</option><option :value="4">紧急</option></select></div>
          <div class="field"><label>计划开始</label><input v-model="createForm.planned_start" class="input" type="date" /></div>
          <div class="field"><label>要求完成</label><input v-model="createForm.due_at" class="input" type="datetime-local" /></div>
          <div class="field"><label>备注</label><textarea v-model="createForm.notes" class="input" rows="3"></textarea></div>
        </div>
        <button class="btn btn-primary btn-block mt-16" :disabled="busy === 'create'" @click="createOrder">{{ busy === 'create' ? '正在创建...' : '创建工单' }}</button>
        <div class="notice info mt-16">通用操作链路：草稿 → 下达 → 执行 → 待质检 → 完成；异常会统一生成告警。</div>
      </div>
    </aside>
    </div>

    <main v-else>
      <section class="panel">
        <div class="panel-head">
          <div><div class="panel-title">生产工单中心</div><div class="panel-desc">按业务状态和质量状态追踪工单</div></div>
          <div class="toolbar-right">
            <input v-model="filters.q" class="input filter-input" placeholder="搜索工单或产品..." @keyup.enter="loadOrders" />
            <select v-model="filters.status" class="select" @change="loadOrders"><option value="">全部状态</option><option value="draft">草稿</option><option value="released">已下达</option><option value="in_progress">执行中</option><option value="quality_check">待质检</option><option value="blocked">已阻塞</option><option value="completed">已完成</option><option value="cancelled">已取消</option></select>
            <select v-model="filters.quality_status" class="select" @change="loadOrders"><option value="">全部质检</option><option value="pending">待检</option><option value="pass">合格</option><option value="fail">不合格</option><option value="waived">让步放行</option></select>
            <button class="btn btn-sm" :disabled="loading" @click="loadOrders">刷新</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="table-wrap">
            <table>
              <thead><tr><th>工单</th><th>站点 / 产品</th><th>状态</th><th>质检</th><th>任务进度</th><th>告警</th><th>交期</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="order in orders" :key="order.id" :class="{ selected: selectedId === order.id }">
                  <td><div class="cell-main mono">{{ order.order_no }}</div><div class="cell-sub">{{ order.title }}</div></td>
                  <td>{{ order.site_detail?.name || '--' }}<div class="cell-sub">{{ order.product_detail?.name || '--' }} · {{ order.quantity }}</div></td>
                  <td><StatusBadge :status="order.status" :label="order.status_display" /></td>
                  <td><span class="quality-pill" :class="`quality-${order.quality_status}`">{{ order.quality_status_display }}</span></td>
                  <td>{{ order.completed_task_count || 0 }}/{{ order.task_count || 0 }}</td>
                  <td><span :class="{ 'text-danger': order.open_alert_count }">{{ order.open_alert_count || 0 }}</span></td>
                  <td class="small">{{ formatTime(order.due_at) }}</td>
                  <td><RouterLink class="link-btn" :to="{ path: '/work-orders', query: { work_order: order.id } }">查看</RouterLink></td>
                </tr>
                <tr v-if="!orders.length"><td colspan="8"><div class="empty">暂无工单</div></td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section v-if="selectedOrder" class="panel mt-16">
        <div class="panel-head">
          <div><div class="panel-title">{{ selectedOrder.order_no }} · {{ selectedOrder.title }}</div><div class="panel-desc">{{ selectedOrder.site_detail?.name }} · {{ selectedOrder.product_detail?.name }} · {{ selectedOrder.quantity }} {{ selectedOrder.product_detail?.unit || '件' }}</div></div>
          <div class="action-bar">
            <StatusBadge :status="selectedOrder.status" :label="selectedOrder.status_display" />
            <button
              v-if="primaryAction"
              class="btn btn-sm btn-primary"
              :disabled="Boolean(busy)"
              @click="onPrimary"
            >{{ busy === primaryAction.key ? '处理中...' : primaryAction.label }}</button>
            <span v-else class="tag">流程已结束</span>
            <ActionMenu :items="moreActions" @select="onMore" />
          </div>
        </div>
        <div class="panel-body">
          <div v-if="selectedOrder.block_reason" class="notice warning mb-16"><strong>当前阻塞：</strong>{{ selectedOrder.block_reason }}</div>
          <div class="grid order-metrics">
            <div><span>工单状态</span><strong>{{ selectedOrder.status_display }}</strong></div>
            <div><span>质检状态</span><strong>{{ selectedOrder.quality_status_display }}</strong></div>
            <div><span>运输进度</span><strong>{{ selectedOrder.completed_task_count || 0 }}/{{ selectedOrder.task_count || 0 }}</strong></div>
            <div><span>开放告警</span><strong>{{ selectedOrder.open_alert_count || 0 }}</strong></div>
            <div><span>计划开始</span><strong>{{ selectedOrder.planned_start || '--' }}</strong></div>
            <div><span>要求完成</span><strong>{{ formatTime(selectedOrder.due_at) }}</strong></div>
          </div>

          <section v-if="timeline?.operation_steps?.length" class="operation-board mt-16">
            <div class="operation-board-head">
              <div><div class="subpanel-title">生产工序执行</div><div class="cell-sub">运输配送、生产加工、质量检验和完工入库按工序顺序推进</div></div>
              <span class="tag">{{ timeline.operation_steps.filter(step => step.status === 'completed').length }} / {{ timeline.operation_steps.length }} 已完成</span>
            </div>
            <div class="operation-flow">
              <article v-for="step in timeline.operation_steps" :key="step.id" class="operation-card" :class="`operation-${step.status}`">
                <div class="operation-card-top">
                  <span class="operation-index">{{ step.sequence_number }}</span>
                  <div class="operation-title"><strong>{{ step.name }}</strong><span>{{ step.step_type_display }}{{ step.quality_gate ? ' · 质量门禁' : '' }}</span></div>
                  <span class="operation-status">{{ step.status_display }}</span>
                </div>
                <div class="operation-meta">
                  <span>标准工时 {{ step.standard_duration_minutes }} 分钟</span>
                  <span>计划 {{ formatTime(step.planned_start) }} → {{ formatTime(step.planned_end) }}</span>
                  <span v-if="step.actual_start">实际开始 {{ formatTime(step.actual_start) }}</span>
                  <span v-if="step.actual_end">实际完成 {{ formatTime(step.actual_end) }}</span>
                </div>
                <div class="operation-actions">
                  <button v-if="step.status === 'ready'" class="btn btn-sm btn-primary" :disabled="busy === `operation-${step.id}-start`" @click="runOperation(step, 'start')">开始工序</button>
                  <button v-if="step.status === 'in_progress'" class="btn btn-sm btn-success" :disabled="busy === `operation-${step.id}-complete`" @click="runOperation(step, 'complete')">完成工序</button>
                  <RouterLink v-if="step.step_type === 'quality'" class="btn btn-sm" :to="{ path: '/vision', query: { work_order: selectedOrder.id } }">进入视觉质检</RouterLink>
                </div>
              </article>
            </div>
          </section>

          <div class="detail-grid mt-16">
            <section class="subpanel timeline-panel">
              <div class="subpanel-title">业务时间线</div>
              <div class="event-timeline mt-12">
                <div v-for="event in timeline?.events || []" :key="event.id" class="event-row">
                  <span class="event-dot"></span>
                  <div><div class="strong">{{ event.summary }}</div><div class="cell-sub">{{ event.event_type }} · {{ event.actor }} · {{ formatTime(event.created_at) }}</div></div>
                </div>
                <div v-if="!timeline?.events?.length" class="empty">暂无事件</div>
              </div>
            </section>

            <section class="subpanel task-create-subpanel">
              <div class="subpanel-title">新增运输任务</div>
              <div class="form-grid single mt-12">
                <div class="field"><label>取货点</label><select v-model="taskForm.pickup_node_id" class="select"><option v-for="node in pickupNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
                <div class="field"><label>放货点</label><select v-model="taskForm.dropoff_node_id" class="select"><option v-for="node in dropoffNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
                <div class="field"><label>货物名称</label><input v-model="taskForm.cargo_name" class="input" /></div>
                <div class="field"><label>重量 (kg)</label><input v-model.number="taskForm.cargo_weight" class="input" type="number" min="0.1" step="0.1" /></div>
              </div>
              <button class="btn btn-primary btn-block mt-12" :disabled="busy === 'task'" @click="addTask">{{ busy === 'task' ? '正在创建...' : '加入运输队列' }}</button>
              <RouterLink class="btn btn-block mt-8" to="/dispatch">前往调度中心</RouterLink>
            </section>
          </div>

          <div v-if="timeline?.schedule_runs?.length" class="schedule-run-stack mt-16">
            <section v-for="(run, runIndex) in timeline.schedule_runs" :key="run.id" class="schedule-run-summary">
              <div class="schedule-run-summary-head">
                <div>
                  <div class="subpanel-title">排期批次 {{ runIndex + 1 }} <span class="tag">调度运行 #{{ run.id }}</span></div>
                  <div class="cell-sub">{{ run.algorithm_display }} · {{ formatTime(run.created_at) }} · 全局顺序 {{ run.dispatch_order_start }}-{{ run.dispatch_order_end }}</div>
                </div>
                <div class="schedule-run-summary-metrics">
                  <span>任务 <strong>{{ run.tasks.length }}</strong></span>
                  <span>AGV <strong>{{ run.agv_count }}</strong></span>
                  <span>最后完成 <strong>{{ formatTime(runLastCompletion(run)) }}</strong></span>
                  <span>作业耗时 <strong>{{ Number(runWorkingSeconds(run)).toFixed(1) }}s</strong></span>
                  <span>准点 <strong>{{ run.on_time_rate }}%</strong></span>
                </div>
              </div>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>全局顺序</th><th>运输任务</th><th>工序</th><th>路线</th><th>AGV / 车内顺序</th><th>状态</th></tr></thead>
                  <tbody>
                    <tr v-for="task in run.tasks" :key="task.id">
                      <td><span class="tag">#{{ task.dispatch_order }}</span></td>
                      <td class="mono">{{ task.task_no }}</td>
                      <td>{{ task.operation_step_name || '--' }}</td>
                      <td>{{ task.pickup_node_detail?.code }} → {{ task.dropoff_node_detail?.code }}</td>
                      <td>{{ task.assigned_agv_detail?.code || '--' }}<div class="cell-sub">{{ task.sequence_number ? `车内 #${task.sequence_number}` : '' }}</div></td>
                      <td><StatusBadge :status="task.status" :label="task.status_display" /></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
          <div v-if="timeline?.unscheduled_tasks?.length" class="schedule-run-summary mt-16">
            <div class="schedule-run-summary-head"><div><div class="subpanel-title">尚未排程任务</div><div class="cell-sub">这些任务尚未分配 AGV 和调度顺序</div></div><span class="tag">{{ timeline.unscheduled_tasks.length }} 个</span></div>
            <div class="table-wrap"><table><thead><tr><th>任务</th><th>工序</th><th>路线</th><th>状态</th></tr></thead><tbody><tr v-for="task in timeline.unscheduled_tasks" :key="task.id"><td class="mono">{{ task.task_no }}</td><td>{{ task.operation_step_name || '--' }}</td><td>{{ task.pickup_node_detail?.code }} → {{ task.dropoff_node_detail?.code }}</td><td><StatusBadge :status="task.status" :label="task.status_display" /></td></tr></tbody></table></div>
          </div>
          <div v-if="!timeline?.schedule_runs?.length && !timeline?.unscheduled_tasks?.length" class="empty mt-16">暂无运输任务</div>

          <div class="detail-grid mt-16">
            <section class="subpanel">
              <div class="subpanel-title">质量检测记录</div>
              <div v-for="record in timeline?.vision_records || []" :key="record.id" class="linked-row">
                <span>#{{ record.id }} · {{ record.task_type_display }}</span>
                <span class="quality-pill" :class="`quality-${record.quality_result}`">{{ record.quality_result_display }}</span>
                <span class="cell-sub">{{ formatTime(record.created_at) }}</span>
              </div>
              <div v-if="!timeline?.vision_records?.length" class="empty">暂无质量检测记录</div>
              <RouterLink class="link-btn mt-12" to="/vision">前往视觉质检</RouterLink>
            </section>
            <section class="subpanel">
              <div class="subpanel-title">设备诊断记录</div>
              <div v-for="record in timeline?.equipment_diagnoses || []" :key="record.id" class="linked-row">
                <span>{{ record.equipment_code }} · {{ record.state_display }}</span>
                <span class="cell-sub">{{ formatTime(record.created_at) }}</span>
              </div>
              <div v-if="!timeline?.equipment_diagnoses?.length" class="empty">暂无设备诊断记录</div>
              <RouterLink class="link-btn mt-12" to="/equipment">前往设备监测</RouterLink>
            </section>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.workorder-layout { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 16px; align-items: start; }
.workorder-page { display: grid; gap: 16px; }
.workorder-entry-menu { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.workorder-mode-card { display: flex; align-items: center; gap: 13px; padding: 15px 17px; border: 1px solid var(--line); border-radius: 13px; background: var(--glass); color: inherit; text-align: left; box-shadow: var(--shadow); backdrop-filter: blur(14px); transition: border-color 160ms ease, background 160ms ease, transform 160ms ease; }
.workorder-mode-card:hover { border-color: var(--accent-line); background: var(--card-bg); transform: translateY(-1px); }
.workorder-mode-card.active { border-color: rgba(47,214,195,.55); background: linear-gradient(180deg, rgba(47,214,195,.2), rgba(47,214,195,.07)); box-shadow: inset 0 1px 0 rgba(255,255,255,.1), 0 0 0 1px rgba(47,214,195,.18), var(--shadow); }
.workorder-mode-icon { width: 36px; height: 36px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 10px; background: rgba(47,214,195,.16); border: 1px solid rgba(47,214,195,.28); color: var(--cyan); font-size: 19px; font-weight: 800; }
.workorder-mode-card > span:last-child { display: grid; gap: 4px; }
.workorder-mode-card strong { color: var(--text); font-size: 13.5px; }
.workorder-mode-card small { color: var(--muted); font-size: 10px; line-height: 1.45; }
.workorder-create-layout { display: grid; grid-template-columns: minmax(0, 620px); align-items: start; }
.workorder-create-layout .create-panel { position: static; }
.create-panel { position: sticky; top: 112px; }
.form-grid.single { grid-template-columns: minmax(0, 1fr); }
.toolbar-right { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.selected { background: var(--accent-tint-weak); }
.quality-pill { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 10px; background: var(--fill-2); border: 1px solid var(--line); color: var(--muted); }
.quality-pass { color: var(--ok-fg); background: var(--tint-green); border-color: var(--tint-green-line); }
.quality-fail { color: var(--danger-fg); background: var(--tint-red); border-color: var(--tint-red-line); }
.quality-pending { color: var(--warn-fg); background: var(--tint-amber); border-color: var(--tint-amber-line); }
.quality-waived { color: var(--violet-fg); background: var(--tint-purple); border-color: var(--tint-purple-line); }
.order-metrics { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.order-metrics > div { padding: 11px; border: 1px solid var(--line); border-radius: 10px; background: var(--fill-1); display: grid; gap: 4px; }
.order-metrics span { color: var(--muted); font-size: 10px; }
.order-metrics strong { color: var(--text); font-size: 12.5px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.subpanel { padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--fill-1); }
.subpanel-title { font-size: 12px; font-weight: 650; color: var(--text); }
.event-timeline { display: grid; gap: 0; }
.timeline-panel, .task-create-subpanel { height: 430px; min-height: 0; }
.timeline-panel { display: flex; flex-direction: column; overflow: hidden; }
.timeline-panel .event-timeline { flex: 1; min-height: 0; overflow-y: auto; padding-right: 7px; }
.task-create-subpanel { overflow-y: auto; }
.event-row { position: relative; display: grid; grid-template-columns: 18px 1fr; gap: 8px; padding: 0 0 14px; }
.event-row::before { content: ""; position: absolute; top: 8px; bottom: 0; left: 4px; width: 1px; background: var(--line); }
.event-row:last-child::before { display: none; }
.event-dot { width: 9px; height: 9px; margin-top: 4px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 0 4px rgba(47,214,195,.14), 0 0 10px rgba(47,214,195,.5); }
.linked-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--row-line); font-size: 11px; }
.linked-row:last-child { border-bottom: 0; }
.text-danger { color: var(--red); font-weight: 650; }
.operation-board { padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--fill-1); }
.operation-board-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.operation-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.operation-card { display: grid; gap: 10px; padding: 12px; border: 1px solid var(--line); border-top: 3px solid var(--line-strong); border-radius: 10px; background: var(--glass); }
.operation-card.operation-ready { border-top-color: var(--amber); }
.operation-card.operation-in_progress { border-top-color: var(--blue); box-shadow: 0 0 0 1px color-mix(in srgb, var(--blue) 22%, transparent); }
.operation-card.operation-completed { border-top-color: var(--green); background: color-mix(in srgb, var(--green) 8%, transparent); }
.operation-card.operation-blocked { border-top-color: var(--red); background: color-mix(in srgb, var(--red) 8%, transparent); }
.operation-card-top { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 8px; align-items: start; }
.operation-index { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 8px; background: var(--fill-3); color: var(--text-soft); font-size: 10px; font-weight: 800; }
.operation-title { min-width: 0; display: grid; gap: 3px; }
.operation-title strong { font-size: 12px; }
.operation-title span { color: var(--muted); font-size: 9px; }
.operation-status { padding: 3px 7px; border-radius: 999px; background: var(--fill-2); color: var(--muted); font-size: 9px; white-space: nowrap; }
.operation-in_progress .operation-status { color: var(--info-fg); background: var(--tint-blue); }
.operation-completed .operation-status { color: var(--ok-fg); background: var(--tint-green); }
.operation-blocked .operation-status { color: var(--danger-fg); background: var(--tint-red); }
.operation-ready .operation-status { color: var(--warn-fg); background: var(--tint-amber); }
.operation-meta { display: grid; gap: 3px; color: var(--muted); font-size: 9px; line-height: 1.45; }
.operation-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.schedule-run-stack { display: grid; gap: 14px; }
.schedule-run-summary { overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: var(--fill-1); }
.schedule-run-summary-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 14px; border-bottom: 1px solid var(--line); background: var(--fill-1); }
.schedule-run-summary-metrics { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 9px; }
.schedule-run-summary-metrics span { display: flex; align-items: baseline; gap: 4px; }
.schedule-run-summary-metrics strong { color: var(--text); font-size: 12px; }
@media (max-width: 1200px) { .workorder-layout { grid-template-columns: 1fr; } .create-panel { position: static; } .order-metrics { grid-template-columns: repeat(3, 1fr); } .operation-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .workorder-entry-menu { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .detail-grid, .order-metrics { grid-template-columns: 1fr; } .schedule-run-summary-head { align-items: flex-start; flex-direction: column; } }
</style>
