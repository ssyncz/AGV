<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge.vue'

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

function priorityText(value) {
  return { 1: '低优先级', 2: '普通优先级', 3: '高优先级', 4: '紧急工单' }[value] || '普通优先级'
}

function selectedSiteName() {
  return master.value.sites?.find((item) => item.id === createForm.site)?.name || '未选择站点'
}

function selectedProductName() {
  return master.value.products?.find((item) => item.id === createForm.product)?.name || '未选择产品'
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

function backToQueue() {
  router.push({ path: '/work-orders' })
}

async function loadOrders() {
  loading.value = true
  try {
    orders.value = await api.workOrders(queryString())
    if (
      pageMode.value === 'center'
      && !selectedId.value
      && orders.value.length
      && window.matchMedia('(min-width: 981px)').matches
    ) {
      await router.replace({
        path: '/work-orders',
        query: { ...route.query, work_order: orders.value[0].id },
      })
    }
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
    <section class="workorder-command-bar">
      <div class="workorder-command-copy">
        <span class="workorder-command-mark">▤</span>
        <div><strong>生产工单工作台</strong><small>从队列选择工单，在同一工作区完成下达、执行、质检与追溯</small></div>
      </div>
      <div class="workorder-mode-tabs">
        <button type="button" :class="{ active: pageMode === 'center' }" @click="switchWorkOrderMode('center')">工单中心</button>
        <button type="button" :class="{ active: pageMode === 'create' }" @click="switchWorkOrderMode('create')">＋ 新建工单</button>
      </div>
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
    <aside class="panel create-preview-panel">
      <div class="panel-head"><div><div class="panel-title">工单预览</div><div class="panel-desc">创建前核对工单信息与后续业务链路</div></div><span class="tag">草稿</span></div>
      <div class="panel-body">
        <article class="create-preview-card">
          <div class="preview-card-head"><span class="mono">NEW WORK ORDER</span><span class="preview-priority">{{ priorityText(createForm.priority) }}</span></div>
          <h3>{{ createForm.title || '未命名生产工单' }}</h3>
          <div class="preview-context">{{ selectedSiteName() }} · {{ selectedProductName() }}</div>
          <div class="preview-numbers">
            <div><span>计划数量</span><strong>{{ createForm.quantity || 0 }}</strong><small>件</small></div>
            <div><span>计划开始</span><strong>{{ createForm.planned_start || '待设置' }}</strong></div>
            <div><span>要求完成</span><strong>{{ createForm.due_at ? formatTime(createForm.due_at) : '待设置' }}</strong></div>
          </div>
        </article>

        <section class="create-flow-panel">
          <div class="create-section-title">工单生命周期</div>
          <div class="create-flow">
            <div class="active"><span>01</span><div><strong>草稿</strong><small>当前创建阶段</small></div></div>
            <div><span>02</span><div><strong>下达</strong><small>分配执行资源</small></div></div>
            <div><span>03</span><div><strong>执行</strong><small>推进生产工序</small></div></div>
            <div><span>04</span><div><strong>质检</strong><small>质量门禁确认</small></div></div>
            <div><span>05</span><div><strong>完成</strong><small>进入归档追溯</small></div></div>
          </div>
        </section>

        <section class="create-impact-panel">
          <div class="create-section-title">创建后将进入</div>
          <div class="create-impact-grid">
            <div><span>▤</span><strong>工单主线</strong><small>下达、工序执行与状态追踪</small></div>
            <div><span>◇</span><strong>运输任务</strong><small>生产配送与 AGV 调度</small></div>
            <div><span>◈</span><strong>质量追溯</strong><small>视觉质检与设备诊断记录</small></div>
          </div>
        </section>

        <div v-if="createForm.notes" class="create-preview-note"><strong>备注</strong><span>{{ createForm.notes }}</span></div>
      </div>
    </aside>
    </div>

    <main v-else class="workorder-workspace" :class="{ 'has-selection': selectedOrder }">
      <aside class="panel workorder-queue-panel">
        <div class="panel-head">
          <div><div class="panel-title">工单队列</div><div class="panel-desc">选择工单后在右侧查看完整执行链路</div></div>
          <button class="btn btn-sm queue-refresh" :disabled="loading" @click="loadOrders">{{ loading ? '加载中' : '刷新' }}</button>
        </div>
        <div class="panel-body">
          <div class="queue-filters">
            <input v-model="filters.q" class="input" placeholder="搜索工单、产品..." @keyup.enter="loadOrders" />
            <div class="queue-filter-row">
              <select v-model="filters.status" class="select" @change="loadOrders"><option value="">全部状态</option><option value="draft">草稿</option><option value="released">已下达</option><option value="in_progress">执行中</option><option value="quality_check">待质检</option><option value="blocked">已阻塞</option><option value="completed">已完成</option><option value="cancelled">已取消</option></select>
              <select v-model="filters.quality_status" class="select" @change="loadOrders"><option value="">全部质检</option><option value="pending">待检</option><option value="pass">合格</option><option value="fail">不合格</option><option value="waived">让步放行</option></select>
            </div>
          </div>
          <div class="queue-summary"><span>共 {{ orders.length }} 张工单</span><span>{{ orders.filter(order => order.open_alert_count).length }} 张含告警</span></div>
          <div class="workorder-queue">
            <RouterLink
              v-for="order in orders"
              :key="order.id"
              class="workorder-queue-item"
              :class="{ active: selectedId === order.id }"
              :to="{ path: '/work-orders', query: { work_order: order.id } }"
            >
              <div class="queue-item-head">
                <span class="queue-order-no mono">{{ order.order_no }}</span>
                <StatusBadge :status="order.status" :label="order.status_display" />
              </div>
              <strong class="queue-order-title">{{ order.title }}</strong>
              <div class="queue-item-meta">{{ order.product_detail?.name || '--' }} · {{ order.quantity }} {{ order.product_detail?.unit || '件' }}</div>
              <div class="queue-item-foot">
                <span>运输 {{ order.completed_task_count || 0 }}/{{ order.task_count || 0 }}</span>
                <span class="quality-pill" :class="`quality-${order.quality_status}`">{{ order.quality_status_display }}</span>
                <span :class="{ 'text-danger': order.open_alert_count }">{{ order.open_alert_count || 0 }} 告警</span>
              </div>
              <div class="queue-item-due">交期 {{ formatTime(order.due_at) }}</div>
            </RouterLink>
            <div v-if="!orders.length" class="empty">没有符合筛选条件的工单</div>
          </div>
        </div>
      </aside>

      <section v-if="selectedOrder" class="panel workorder-detail-panel">
        <div class="panel-head">
          <div><div class="panel-title">{{ selectedOrder.order_no }} · {{ selectedOrder.title }}</div><div class="panel-desc">{{ selectedOrder.site_detail?.name }} · {{ selectedOrder.product_detail?.name }} · {{ selectedOrder.quantity }} {{ selectedOrder.product_detail?.unit || '件' }}</div></div>
          <div class="toolbar-right">
            <button class="btn btn-sm workorder-mobile-back" @click="backToQueue">← 返回队列</button>
            <button v-if="selectedOrder.status === 'draft'" class="btn btn-sm btn-primary" :disabled="busy === 'release'" @click="runAction('release')">下达工单</button>
            <button v-if="selectedOrder.status === 'released'" class="btn btn-sm btn-primary" :disabled="busy === 'start'" @click="runAction('start')">开始执行</button>
            <button v-if="['in_progress', 'quality_check'].includes(selectedOrder.status)" class="btn btn-sm" :disabled="busy === 'quality-check'" @click="runAction('quality-check')">提交质检</button>
            <button v-if="selectedOrder.status === 'quality_check'" class="btn btn-sm btn-success" :disabled="busy === 'complete'" @click="runAction('complete')">完成工单</button>
            <button v-if="!['completed', 'cancelled', 'blocked'].includes(selectedOrder.status)" class="btn btn-sm btn-danger" :disabled="busy === 'block'" @click="blockOrder">阻塞</button>
            <button v-if="selectedOrder.status === 'blocked'" class="btn btn-sm btn-primary" :disabled="busy === 'resume'" @click="runAction('resume')">恢复</button>
            <button v-if="!['completed', 'cancelled'].includes(selectedOrder.status)" class="btn btn-sm btn-danger" :disabled="busy === 'cancel'" @click="runAction('cancel')">取消</button>
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
              <div class="subpanel-title-row">
                <div class="subpanel-title">新增运输任务</div>
                <RouterLink class="subpanel-link" to="/dispatch">查看调度中心 →</RouterLink>
              </div>
              <div class="form-grid single mt-12">
                <div class="field"><label>取货点</label><select v-model="taskForm.pickup_node_id" class="select"><option v-for="node in pickupNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
                <div class="field"><label>放货点</label><select v-model="taskForm.dropoff_node_id" class="select"><option v-for="node in dropoffNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
                <div class="field"><label>货物名称</label><input v-model="taskForm.cargo_name" class="input" /></div>
                <div class="field"><label>重量 (kg)</label><input v-model.number="taskForm.cargo_weight" class="input" type="number" min="0.1" step="0.1" /></div>
              </div>
              <button class="btn btn-primary btn-block mt-12" :disabled="busy === 'task'" @click="addTask">{{ busy === 'task' ? '正在创建...' : '加入运输队列' }}</button>
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
      <section v-else class="panel workorder-detail-empty">
        <div class="workorder-empty-visual">
          <span class="workorder-empty-icon">▤</span>
          <strong>从工单队列开始</strong>
          <p>选择左侧工单后，这里会显示工序执行、运输任务、质量记录和业务时间线。</p>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.workorder-layout { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 16px; align-items: start; }
.workorder-page { display: grid; gap: 16px; }
.workorder-entry-menu { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.workorder-mode-card { display: flex; align-items: center; gap: 13px; padding: 16px 18px; border: 1px solid var(--line); border-radius: 13px; background: #fff; color: inherit; text-align: left; box-shadow: var(--shadow); transition: border-color 160ms ease, background 160ms ease, transform 160ms ease; }
.workorder-mode-card:hover { border-color: #a9ccc5; transform: translateY(-1px); }
.workorder-mode-card.active { border-color: var(--cyan); background: #f2faf8; box-shadow: 0 0 0 2px rgba(14,135,146,.08), var(--shadow); }
.workorder-mode-icon { width: 38px; height: 38px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 10px; background: #e4f2ee; color: var(--cyan); font-size: 20px; font-weight: 800; }
.workorder-mode-card > span:last-child { display: grid; gap: 4px; }
.workorder-mode-card strong { color: var(--text); font-size: 14px; }
.workorder-mode-card small { color: var(--muted); font-size: 10px; line-height: 1.45; }
.workorder-create-layout { display: grid; grid-template-columns: minmax(0, 1.12fr) minmax(320px, 0.88fr); gap: 16px; align-items: start; }
.workorder-create-layout .create-panel { position: static; }
.create-panel { position: sticky; top: 112px; }
.create-preview-panel { position: sticky; top: 18px; overflow: hidden; }
.create-preview-panel > .panel-body { display: grid; gap: 12px; padding: 16px; }
.create-preview-card {
  display: grid;
  gap: 8px;
  padding: 17px;
  border: 1px solid #d9e7e1;
  border-radius: 14px;
  background:
    linear-gradient(rgba(48, 104, 96, 0.022) 1px, transparent 1px),
    linear-gradient(90deg, rgba(48, 104, 96, 0.022) 1px, transparent 1px),
    radial-gradient(circle at 92% 10%, rgba(14, 135, 146, 0.09), transparent 30%),
    #fbfdfc;
  background-size: 22px 22px, 22px 22px, auto, auto;
}
.preview-card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.preview-card-head > span:first-child { color: #7c8f89; font-size: 8px; letter-spacing: 0.08em; }
.preview-priority { padding: 3px 7px; border-radius: 999px; color: #85651e; background: #fff8e8; font-size: 8.5px; font-weight: 720; }
.create-preview-card h3 { margin: 2px 0 0; color: #1c3940; font-size: 17px; line-height: 1.4; }
.preview-context { color: #71817c; font-size: 9.5px; }
.preview-numbers { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin-top: 5px; }
.preview-numbers > div { min-width: 0; display: grid; gap: 2px; padding: 9px; border: 1px solid #e0e9e5; border-radius: 8px; background: rgba(255, 255, 255, 0.7); }
.preview-numbers span { color: #88968f; font-size: 7.5px; }
.preview-numbers strong { overflow: hidden; color: #2a474d; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.preview-numbers small { color: #96a19d; font-size: 7px; }
.create-flow-panel,
.create-impact-panel { padding: 13px; border: 1px solid #dfe8e4; border-radius: 11px; background: #fbfcfb; }
.create-section-title { margin-bottom: 9px; color: #344e54; font-size: 10.5px; font-weight: 780; }
.create-flow { display: grid; gap: 4px; }
.create-flow > div { display: grid; grid-template-columns: 25px minmax(0, 1fr); gap: 8px; align-items: center; padding: 7px 8px; border-radius: 8px; color: #81908b; background: #f5f8f6; }
.create-flow > div.active { color: #17665f; background: #eaf7f2; box-shadow: inset 3px 0 0 var(--cyan); }
.create-flow span { width: 24px; height: 24px; display: grid; place-items: center; border-radius: 7px; background: rgba(255, 255, 255, 0.76); font-family: "Cascadia Mono", Consolas, monospace; font-size: 7.5px; font-weight: 800; }
.create-flow > div > div { display: grid; gap: 1px; }
.create-flow strong { color: inherit; font-size: 9.5px; }
.create-flow small { color: #93a09b; font-size: 7.5px; }
.create-impact-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; }
.create-impact-grid > div { display: grid; gap: 4px; padding: 10px; border: 1px solid #e1e9e5; border-radius: 8px; background: #fff; }
.create-impact-grid > div > span { color: var(--cyan); font-size: 14px; }
.create-impact-grid strong { color: #304a50; font-size: 9px; }
.create-impact-grid small { color: #8b9893; font-size: 7.5px; line-height: 1.4; }
.create-preview-note { display: grid; gap: 4px; padding: 10px 11px; border: 1px solid #dde8e3; border-radius: 9px; background: #f8faf9; }
.create-preview-note strong { color: #566b65; font-size: 8.5px; }
.create-preview-note span { color: #7d8c87; font-size: 9px; line-height: 1.5; white-space: pre-wrap; }
.form-grid.single { grid-template-columns: minmax(0, 1fr); }
.toolbar-right { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.selected { background: #f1f8f6; }
.quality-pill { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 10px; background: #edf1ef; color: var(--muted); }
.quality-pass { color: var(--green); background: #eaf7f1; }
.quality-fail { color: var(--red); background: #fdeef0; }
.quality-pending { color: var(--amber); background: #fdf5e6; }
.quality-waived { color: var(--purple); background: #f1edfb; }
.order-metrics { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.order-metrics > div { padding: 12px; border: 1px solid var(--line); border-radius: 10px; background: #f8faf9; display: grid; gap: 4px; }
.order-metrics span { color: var(--muted); font-size: 10px; }
.order-metrics strong { color: var(--text); font-size: 13px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.subpanel { padding: 15px; border: 1px solid var(--line); border-radius: 12px; background: #fbfcfb; }
.subpanel-title { font-size: 12px; font-weight: 750; color: var(--text); }
.subpanel-title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.subpanel-link {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 10px;
  border: 1px solid #cbded8;
  border-radius: 8px;
  color: var(--cyan);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 2px 7px rgba(20, 45, 54, 0.04);
  font-size: 10.5px;
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
  transition: color 150ms ease, border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
}
.subpanel-link:hover {
  color: #0b6971;
  border-color: #9fc7bf;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(20, 45, 54, 0.07);
  text-decoration: none;
}
.event-timeline { display: grid; gap: 0; }
.timeline-panel, .task-create-subpanel { height: 430px; min-height: 0; }
.timeline-panel { display: flex; flex-direction: column; overflow: hidden; }
.timeline-panel .event-timeline { flex: 1; min-height: 0; overflow-y: auto; padding-right: 7px; }
.task-create-subpanel { overflow-y: auto; }
.event-row { position: relative; display: grid; grid-template-columns: 18px 1fr; gap: 8px; padding: 0 0 14px; }
.event-row::before { content: ""; position: absolute; top: 8px; bottom: 0; left: 4px; width: 1px; background: var(--line); }
.event-row:last-child::before { display: none; }
.event-dot { width: 9px; height: 9px; margin-top: 4px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 0 4px rgba(14,135,146,.1); }
.linked-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid #edf1ef; font-size: 11px; }
.linked-row:last-child { border-bottom: 0; }
.text-danger { color: var(--red); font-weight: 700; }
.operation-board { padding: 15px; border: 1px solid var(--line); border-radius: 12px; background: #f8faf9; }
.operation-board-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
.operation-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.operation-card { display: grid; gap: 10px; padding: 13px; border: 1px solid var(--line); border-top: 3px solid #aebbb6; border-radius: 10px; background: #fff; }
.operation-card.operation-ready { border-top-color: var(--amber); }
.operation-card.operation-in_progress { border-top-color: var(--blue); box-shadow: 0 0 0 2px rgba(47,111,218,.06); }
.operation-card.operation-completed { border-top-color: var(--green); background: #f8fdfb; }
.operation-card.operation-blocked { border-top-color: var(--red); background: #fffafa; }
.operation-card-top { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 8px; align-items: start; }
.operation-index { width: 27px; height: 27px; display: grid; place-items: center; border-radius: 8px; background: #e8efec; color: #49625c; font-size: 10px; font-weight: 800; }
.operation-title { min-width: 0; display: grid; gap: 3px; }
.operation-title strong { font-size: 12px; }
.operation-title span { color: var(--muted); font-size: 9px; }
.operation-status { padding: 3px 7px; border-radius: 999px; background: #eef2f0; color: var(--muted); font-size: 9px; white-space: nowrap; }
.operation-in_progress .operation-status { color: var(--blue); background: #edf3ff; }
.operation-completed .operation-status { color: var(--green); background: #eaf7f1; }
.operation-blocked .operation-status { color: var(--red); background: #fdeef0; }
.operation-ready .operation-status { color: var(--amber); background: #fdf5e6; }
.operation-meta { display: grid; gap: 3px; color: var(--muted); font-size: 9px; line-height: 1.45; }
.operation-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.schedule-run-stack { display: grid; gap: 14px; }
.schedule-run-summary { overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: #fff; }
.schedule-run-summary-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 13px 15px; border-bottom: 1px solid var(--line); background: #f8faf9; }
.schedule-run-summary-metrics { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 9px; }
.schedule-run-summary-metrics span { display: flex; align-items: baseline; gap: 4px; }
.schedule-run-summary-metrics strong { color: var(--text); font-size: 12px; }
.workorder-command-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 13px 16px;
  border: 1px solid var(--line);
  border-radius: 15px;
  background:
    radial-gradient(circle at 88% 20%, rgba(14, 135, 146, 0.07), transparent 28%),
    linear-gradient(135deg, #ffffff, #f8fbf9);
  box-shadow: 0 8px 24px rgba(20, 45, 54, 0.04);
}
.workorder-command-copy { display: flex; align-items: center; gap: 12px; min-width: 0; }
.workorder-command-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border: 1px solid rgba(14, 135, 146, 0.16);
  border-radius: 11px;
  color: var(--cyan);
  background: rgba(233, 247, 243, 0.8);
  font-size: 17px;
}
.workorder-command-copy > div { display: grid; gap: 3px; min-width: 0; }
.workorder-command-copy strong { color: #173039; font-size: 13px; font-weight: 800; }
.workorder-command-copy small { color: var(--muted); font-size: 9.5px; line-height: 1.4; }
.workorder-mode-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid #dbe5e0;
  border-radius: 11px;
  background: #eef4f1;
}
.workorder-mode-tabs button {
  min-height: 32px;
  padding: 6px 12px;
  border: 0;
  border-radius: 8px;
  color: #677a73;
  background: transparent;
  font-size: 10.5px;
  font-weight: 680;
  white-space: nowrap;
}
.workorder-mode-tabs button:hover { color: #1c4a48; background: rgba(255, 255, 255, 0.62); }
.workorder-mode-tabs button.active {
  color: #123d3e;
  background: #ffffff;
  box-shadow: 0 2px 7px rgba(20, 45, 54, 0.08), inset 0 -1px 0 rgba(14, 135, 146, 0.12);
}
.workorder-workspace {
  display: grid;
  grid-template-columns: clamp(260px, 18vw, 300px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.workorder-queue-panel {
  position: sticky;
  top: 18px;
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 36px);
  overflow: hidden;
}
.workorder-queue-panel .panel-head { min-height: 68px; padding: 14px 15px 12px; }
.workorder-queue-panel .panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.queue-refresh { min-width: 58px; }
.queue-filters { display: grid; gap: 8px; }
.queue-filter-row { display: grid; grid-template-columns: minmax(0, 1fr) 92px; gap: 7px; }
.queue-filters .input,
.queue-filters .select { min-height: 36px; font-size: 10.5px; }
.queue-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 2px 8px;
  color: #84928d;
  font-size: 9px;
}
.workorder-queue {
  flex: 1;
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 7px;
  overflow-y: auto;
  padding: 1px 3px 1px 1px;
  scrollbar-width: thin;
  scrollbar-color: rgba(92, 143, 136, 0.25) transparent;
}
.workorder-queue-item {
  position: relative;
  display: grid;
  gap: 5px;
  overflow: hidden;
  padding: 11px 11px 10px;
  border: 1px solid #dce6e1;
  border-radius: 11px;
  color: inherit;
  background: linear-gradient(145deg, #ffffff, #f9fbfa);
  text-decoration: none;
  transition: border-color 150ms ease, background 150ms ease, transform 150ms ease, box-shadow 150ms ease;
}
.workorder-queue-item::before {
  content: "";
  position: absolute;
  inset: 8px auto 8px 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: transparent;
}
.workorder-queue-item:hover {
  border-color: #b9cec7;
  background: #ffffff;
  box-shadow: 0 7px 18px rgba(20, 45, 54, 0.055);
  transform: translateY(-1px);
}
.workorder-queue-item.active {
  border-color: rgba(14, 135, 146, 0.35);
  background: linear-gradient(90deg, rgba(14, 135, 146, 0.075), rgba(255, 255, 255, 0.8));
  box-shadow: 0 7px 18px rgba(14, 94, 95, 0.07);
}
.workorder-queue-item.active::before { background: var(--cyan); box-shadow: 0 0 10px rgba(14, 135, 146, 0.32); }
.queue-item-head,
.queue-item-foot { display: flex; align-items: center; justify-content: space-between; gap: 7px; }
.queue-order-no { color: #155b62; font-size: 9.5px; font-weight: 760; }
.queue-item-head :deep(.badge) { padding: 3px 6px; font-size: 8px; }
.queue-order-title {
  overflow: hidden;
  color: #20363e;
  font-size: 11.5px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-item-meta { overflow: hidden; color: #7b8984; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.queue-item-foot { color: #71827b; font-size: 8.5px; }
.queue-item-foot .quality-pill { padding: 2px 6px; font-size: 8px; }
.queue-item-due { color: #96a19d; font-size: 8.5px; }
.workorder-queue-panel .empty { padding: 32px 12px; }
.workorder-detail-panel { min-width: 0; }
.workorder-detail-empty {
  min-height: 420px;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at center, rgba(14, 135, 146, 0.055), transparent 36%),
    #ffffff;
}
.workorder-empty-visual { max-width: 330px; display: grid; justify-items: center; gap: 9px; padding: 30px; text-align: center; }
.workorder-empty-icon {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(14, 135, 146, 0.15);
  border-radius: 16px;
  color: var(--cyan);
  background: #f1f8f6;
  font-size: 23px;
}
.workorder-empty-visual strong { color: #244049; font-size: 14px; }
.workorder-empty-visual p { margin: 0; color: var(--muted); font-size: 10px; line-height: 1.65; }
.workorder-mobile-back { display: none; }
@media (max-width: 980px) {
  .workorder-workspace { grid-template-columns: minmax(0, 1fr); }
  .workorder-create-layout { grid-template-columns: minmax(0, 1fr); }
  .create-preview-panel { position: static; }
  .workorder-queue-panel { position: static; max-height: none; }
  .workorder-queue { max-height: 430px; }
  .workorder-workspace.has-selection .workorder-queue-panel { display: none; }
  .workorder-mobile-back { display: inline-flex; }
}
@media (max-width: 760px) {
  .workorder-command-bar { align-items: stretch; flex-direction: column; gap: 11px; }
  .workorder-mode-tabs { align-self: stretch; }
  .workorder-mode-tabs button { flex: 1; }
  .workorder-detail-panel > .panel-head { gap: 10px; }
  .workorder-detail-panel > .panel-head .toolbar-right { width: 100%; justify-content: flex-start; }
  .preview-numbers,
  .create-impact-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 1200px) { .workorder-layout { grid-template-columns: 1fr; } .create-panel { position: static; } .order-metrics { grid-template-columns: repeat(3, 1fr); } .operation-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .workorder-entry-menu { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .detail-grid, .order-metrics { grid-template-columns: 1fr; } .schedule-run-summary-head { align-items: flex-start; flex-direction: column; } }
</style>
